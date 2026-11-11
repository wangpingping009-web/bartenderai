# -*- coding: utf-8 -*-
"""LLM 客户端封装：多供应商路由 + 用量打点 + 降级容灾（M6）。

为什么单独封装一层:
- 业务代码（Agent / 检索 / 审校）只认 `get_llm()`，不直接碰供应商细节
- 换模型 / 换供应商 / 加路由策略，只改这里，全局生效

M6 三层能力：
1. 任务分级路由：默认 DeepSeek（主力），Qwen 作备用；
   重任务可用 get_llm_with_failover() 主动降级
2. 用量打点：返回 TrackedChatOpenAI，每次调用自动记 usage_log
   （token/成本，成本看板数据源，见 core/usage）
3. 降级容灾：主模型失败（限流/超时/网络）→ 自动切备用供应商
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import time
from typing import Any, Iterator, Optional, Sequence

from langchain_core.messages import BaseMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.core.usage import current_usage_ctx, estimate_tokens, record_usage


_runtime_health: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class LLMProvider:
    name: str
    base_url: str
    api_key: str
    model: str


def llm_error_reason(error: Exception) -> str:
    """Map provider failures to stable capability codes without leaking details."""
    status = getattr(error, "status_code", None)
    text = str(error).lower()
    if status == 402 or "insufficient balance" in text or "insufficient_balance" in text:
        return "insufficient_balance"
    if status in (401, 403) or "authentication" in text or "invalid api key" in text:
        return "authentication_failed"
    if status == 429 or "rate limit" in text:
        return "rate_limited"
    if "connection" in text or "connecterror" in text or "timeout" in text:
        return "connection_failed"
    return "request_failed"


def is_non_retryable_llm_error(error: Exception) -> bool:
    return llm_error_reason(error) in {"insufficient_balance", "authentication_failed"}


def _provider_name_from_url(base_url: str | None) -> str:
    value = (base_url or "").lower()
    if "deepseek" in value:
        return "deepseek"
    if "dashscope" in value or "aliyuncs" in value:
        return "qwen"
    return "local"


def _health_entry(provider: str) -> dict[str, Any]:
    return _runtime_health.setdefault(provider, {
        "available": None,
        "reason": None,
        "checked_at": 0.0,
        "last_success_at": None,
        "last_failure_at": None,
        "cooldown_until": 0.0,
        "consecutive_failures": 0,
    })


def record_llm_success(provider: str | None = None) -> None:
    configured = _providers() if provider is None else []
    name = provider or (configured[0].name if configured else "unknown")
    now = time.time()
    _health_entry(name).update(
        available=True, reason=None, checked_at=now, last_success_at=now,
        cooldown_until=0.0, consecutive_failures=0,
    )


def record_llm_failure(error: Exception, provider: str | None = None) -> None:
    configured = _providers() if provider is None else []
    name = provider or (configured[0].name if configured else "unknown")
    now = time.time()
    entry = _health_entry(name)
    failures = int(entry.get("consecutive_failures") or 0) + 1
    entry.update(
        available=False,
        reason=llm_error_reason(error),
        checked_at=now,
        last_failure_at=now,
        cooldown_until=now + max(1, settings.LLM_CIRCUIT_BREAKER_SECONDS),
        consecutive_failures=failures,
    )


def llm_runtime_health() -> dict[str, Any]:
    """Aggregate health kept for compatibility with existing health consumers."""
    configured = [provider.name for provider in _providers()]
    entries = [_runtime_health.get(name) for name in configured]
    if any(entry and entry.get("available") is True for entry in entries):
        latest = max(
            (entry for entry in entries if entry and entry.get("available") is True),
            key=lambda item: item.get("checked_at", 0.0),
        )
        return {"available": True, "reason": None,
                "checked_at": latest.get("checked_at", 0.0)}
    if any(entry is None or entry.get("available") is None for entry in entries):
        return {"available": None, "reason": None, "checked_at": 0.0}
    known = [entry for entry in entries if entry and entry.get("available") is False]
    if known:
        latest = max(known, key=lambda item: item.get("checked_at", 0.0))
        return {"available": False, "reason": latest.get("reason"),
                "checked_at": latest.get("checked_at", 0.0)}
    return {"available": None, "reason": None, "checked_at": 0.0}


def llm_provider_health() -> list[dict[str, Any]]:
    """Return non-secret provider state for the capability endpoint."""
    now = time.time()
    rows = []
    for provider in _providers():
        entry = dict(_health_entry(provider.name))
        cooldown_until = float(entry.get("cooldown_until") or 0.0)
        available = entry.get("available")
        status = "available" if available is True else (
            "unverified" if available is None else
            "cooldown" if cooldown_until > now else "unavailable"
        )
        rows.append({
            "name": provider.name,
            "model": provider.model,
            "status": status,
            "available": available is True,
            "reason": entry.get("reason"),
            "checked_at": entry.get("checked_at", 0.0),
            "retry_after_seconds": max(0, round(cooldown_until - now)),
        })
    return rows


class TrackedChatOpenAI(ChatOpenAI):
    """自动记录每次调用的用量/成本（无侵入打点）。

    业务代码无感知：只要走 get_llm() 拿到的就是这个类，
    invoke 结果自动写 usage_log。成本看板因此零改造可用。
    """

    def _generate(self, messages: list[BaseMessage], stop: Optional[list[str]] = None,
                  run_manager: Any = None, **kwargs: Any) -> ChatResult:
        provider = _provider_name_from_url(str(self.openai_api_base or ""))
        try:
            result = super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        except Exception as error:
            record_llm_failure(error, provider)
            raise
        record_llm_success(provider)
        message = result.generations[0].message if result.generations else None
        self._record_usage(messages, message)
        return result

    def _stream(self, messages: list[BaseMessage], stop: Optional[list[str]] = None,
                run_manager: Any = None, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        provider = _provider_name_from_url(str(self.openai_api_base or ""))
        chunks: list[str] = []
        try:
            for chunk in super()._stream(
                    messages, stop=stop, run_manager=run_manager, **kwargs):
                content = getattr(chunk.message, "content", "") or ""
                if isinstance(content, str):
                    chunks.append(content)
                yield chunk
        except Exception as error:
            record_llm_failure(error, provider)
            raise
        record_llm_success(provider)
        self._record_usage(messages, type("StreamResult", (), {"content": "".join(chunks)})())

    def _record_usage(self, input: Any, result: Any) -> None:
        try:
            usage = getattr(result, "usage_metadata", None)
            in_tok = usage.get("input_tokens") if usage else None
            out_tok = usage.get("output_tokens") if usage else None
            if in_tok is None:            # 供应商没给 token 数 → 估算
                in_tok = estimate_tokens(self._input_text(input))
            if out_tok is None:
                out_tok = estimate_tokens(getattr(result, "content", "") or "")
            ctx = current_usage_ctx()
            record_usage(
                model=self.model_name,
                provider=(self.openai_api_base or "local")[:60],
                in_tokens=int(in_tok), out_tokens=int(out_tok),
                task=ctx["task"], user=ctx["user"],
            )
        except Exception:
            pass  # 打点失败不影响主流程

    @staticmethod
    def _input_text(input: Any) -> str:
        if isinstance(input, list):
            parts = []
            for m in input:
                if isinstance(m, BaseMessage):
                    c = m.content
                    parts.append(c if isinstance(c, str) else str(c))
            return " ".join(parts)
        if isinstance(input, dict):
            return str(input)
        return str(input)


@lru_cache(maxsize=8)
def _llm_for(base_url: str, api_key: str, model: str, temperature: float, max_tokens: int) -> TrackedChatOpenAI:
    """构造并缓存一个 LLM 实例（同参数复用）。"""
    return TrackedChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=settings.LLM_TIMEOUT_SECONDS,
        max_retries=settings.LLM_MAX_RETRIES,
    )


def _is_placeholder(key: str | None) -> bool:
    """占位符 key 视为未配置：复制模板没改、或留空的都不算。

    否则 `QWEN_API_KEY=your-dashscope-api-key` 会被当成有效 key，
    get_llm() 路由到 Qwen 后真实调用必 401。
    """
    if not key:
        return True
    k = key.strip().lower()
    return k.startswith(("your-", "your_", "sk-your")) or k in ("change-me", "changeme", "xxx")


def _providers() -> list[LLMProvider]:
    """按优先级列出已配置的供应商（base_url, api_key, model）。

    DeepSeek 优先（默认主力）；Qwen 备用。占位符 / 空的 key 直接跳过，
    避免路由到无效供应商。
    """
    configured: dict[str, LLMProvider] = {}
    if settings.LOCAL_LLM_BASE_URL.strip() and settings.LOCAL_LLM_MODEL.strip():
        configured["local"] = LLMProvider(
            "local", settings.LOCAL_LLM_BASE_URL.strip(),
            settings.LOCAL_LLM_API_KEY.strip() or "local-not-secret",
            settings.LOCAL_LLM_MODEL.strip(),
        )
    if settings.DEEPSEEK_API_KEY and not _is_placeholder(settings.DEEPSEEK_API_KEY):
        configured["deepseek"] = LLMProvider(
            "deepseek", settings.DEEPSEEK_BASE_URL,
            settings.DEEPSEEK_API_KEY, settings.DEEPSEEK_MODEL,
        )
    if settings.QWEN_API_KEY and not _is_placeholder(settings.QWEN_API_KEY):
        configured["qwen"] = LLMProvider(
            "qwen", settings.QWEN_BASE_URL, settings.QWEN_API_KEY, settings.QWEN_MODEL,
        )
    priority = [item.strip().lower() for item in settings.LLM_PROVIDER_PRIORITY.split(",")]
    ordered = [configured.pop(name) for name in priority if name in configured]
    ordered.extend(configured.values())
    return ordered


def _available_providers() -> list[LLMProvider]:
    providers = _providers()
    if not providers:
        return []
    now = time.time()
    active = [provider for provider in providers
              if float(_health_entry(provider.name).get("cooldown_until") or 0.0) <= now]
    return active


class FailoverChatModel(BaseChatModel):
    """One logical chat model that retries the same task across real providers."""

    temperature: float = 0.3
    max_tokens: int = 2048

    @property
    def _llm_type(self) -> str:
        return "bartenderai-openai-compatible-failover"

    def _models(self) -> list[TrackedChatOpenAI]:
        providers = _available_providers()
        if not providers:
            configured = _providers()
            if configured:
                reasons = ", ".join(
                    f"{provider.name}:{_health_entry(provider.name).get('reason') or 'cooldown'}"
                    for provider in configured
                )
                raise RuntimeError(f"所有已配置模型暂处于冷却期（{reasons}）")
            raise RuntimeError(
                "未配置任何可用模型。请配置本地 OpenAI-compatible 服务、"
                "QWEN_API_KEY 或 DEEPSEEK_API_KEY。"
            )
        return [
            _llm_for(provider.base_url, provider.api_key, provider.model,
                     self.temperature, self.max_tokens)
            for provider in providers
        ]

    def _generate(self, messages: list[BaseMessage], stop: Optional[list[str]] = None,
                  run_manager: Any = None, **kwargs: Any) -> ChatResult:
        last_error: Exception | None = None
        for model in self._models():
            try:
                return model._generate(
                    messages, stop=stop, run_manager=run_manager, **kwargs,
                )
            except Exception as error:
                last_error = error
        raise last_error or RuntimeError("没有可用的模型供应商")

    def _stream(self, messages: list[BaseMessage], stop: Optional[list[str]] = None,
                run_manager: Any = None, **kwargs: Any) -> Iterator[ChatGenerationChunk]:
        last_error: Exception | None = None
        for model in self._models():
            emitted = False
            try:
                for chunk in model._stream(
                        messages, stop=stop, run_manager=run_manager, **kwargs):
                    emitted = True
                    yield chunk
                return
            except Exception as error:
                last_error = error
                # Switching after output started would splice two answers together.
                if emitted:
                    raise
        raise last_error or RuntimeError("没有可用的模型供应商")

    @staticmethod
    def _fallback_runnable(runnables: Sequence[Runnable]) -> Runnable:
        if not runnables:
            raise RuntimeError("没有可用的模型供应商")
        return runnables[0].with_fallbacks(list(runnables[1:]))

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: str | None = None,
                   **kwargs: Any) -> Runnable:
        return self._fallback_runnable([
            model.bind_tools(tools, tool_choice=tool_choice, **kwargs)
            for model in self._models()
        ])

    def with_structured_output(self, schema: dict[str, Any] | type, *,
                               include_raw: bool = False, **kwargs: Any) -> Runnable:
        return self._fallback_runnable([
            model.with_structured_output(
                schema, include_raw=include_raw, **kwargs,
            )
            for model in self._models()
        ])


def get_llm(temperature: float = 0.3, max_tokens: int = 2048) -> FailoverChatModel:
    """获取默认 LLM（按配置自动选择可用供应商）。

    Args:
        temperature: 生成温度。检索/审校用低值(0~0.3)求稳定，
                     创意玩法用高值(0.8+)求发散。
        max_tokens:  单次输出上限。
    """
    if not _providers():
        raise RuntimeError(
            "未配置任何可用模型。请配置本地 OpenAI-compatible 服务、"
            "QWEN_API_KEY 或 DEEPSEEK_API_KEY。"
        )
    return FailoverChatModel(temperature=temperature, max_tokens=max_tokens)


def iter_configured_llms(temperature: float = 0.3,
                         max_tokens: int = 2048) -> list[TrackedChatOpenAI]:
    """Return every configured provider in priority order.

    Callers that need structured output must retry the *real task* on each
    provider. A separate ``ping`` is not enough: it adds latency and can pass
    even when the subsequent JSON request is rejected.
    """
    providers = _providers()
    if not providers:
        raise RuntimeError(
            "未配置任何可用模型。请配置本地 OpenAI-compatible 服务、"
            "QWEN_API_KEY 或 DEEPSEEK_API_KEY。"
        )
    active = _available_providers()
    if not active:
        raise RuntimeError("所有已配置模型暂处于冷却期")
    return [_llm_for(item.base_url, item.api_key, item.model, temperature, max_tokens)
            for item in active]


def get_llm_with_failover(temperature: float = 0.3,
                          max_tokens: int = 2048) -> FailoverChatModel:
    """Compatibility alias; get_llm already performs real-task failover."""
    return get_llm(temperature=temperature, max_tokens=max_tokens)


def get_creative_llm() -> FailoverChatModel:
    """创意型 LLM（新配方生成 / 挑战玩法）：高温发散。"""
    return get_llm(temperature=0.9, max_tokens=2048)
