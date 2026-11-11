# -*- coding: utf-8 -*-
"""LLM 用量与成本统计（M6 限流+成本看板）。

不依赖供应商的精确 token 计数（那需要逐家调 tokenizer），
用"字符估算 + 有 usage_metadata 就用真实值"两级方案：
1. 供应商返回 usage_metadata → 用真实 token 数
2. 否则按字符估算（中文≈1 token/字，英文≈4 字符/token）

ContextVars 打点：核心 LLM 调用自动记一笔（见 core/llm 的 TrackedChatOpenAI），
scope 由调用方（graph 执行 / 各服务）用 usage_scope() 圈定任务名与用户。
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager

from app.core.config import settings
from app.db.database import db

# 成本模型：每百万 token 价格（元）。约值，可改可换。
PRICE_PER_1M: dict[str, tuple[float, float]] = {
    "qwen-plus":     (0.40, 1.20),   # (输入, 输出) 元/1M token
    "qwen-max":      (2.40, 9.60),
    "qwen-vl-plus":  (1.50, 8.00),
    "deepseek-chat": (1.00, 2.00),
    "default":       (1.00, 2.00),
}

_USAGE_CTX: "contextvars.ContextVar[dict | None]" = contextvars.ContextVar("usage_ctx", default=None)


@contextmanager
def usage_scope(task: str, user: str = ""):
    """圈定一段代码的 LLM 用量归属（任务名 + 用户）。"""
    token = _USAGE_CTX.set({"task": task, "user": user})
    try:
        yield
    finally:
        _USAGE_CTX.reset(token)


def current_usage_ctx() -> dict:
    return _USAGE_CTX.get() or {"task": "default", "user": ""}


def estimate_tokens(text: str | None) -> int:
    """字符 → token 粗估：中文≈1字/token，英文≈4字符/token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    ascii_n = len(text) - cjk
    ascii_tok = max(1, round(ascii_n / 4)) if ascii_n else 0
    return cjk + ascii_tok


def estimate_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    in_price, out_price = PRICE_PER_1M.get(model, PRICE_PER_1M["default"])
    return (in_tokens / 1e6) * in_price + (out_tokens / 1e6) * out_price


def record_usage(model: str, provider: str, in_tokens: int, out_tokens: int,
                 task: str = "", user: str = "") -> None:
    """记一笔用量（幂等，失败不影响主流程）。"""
    cost = estimate_cost(model, in_tokens, out_tokens)
    try:
        with db() as conn:
            conn.execute(
                "INSERT INTO usage_log (user_id, task, provider, model, input_tokens, output_tokens, cost_cny) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user, task, provider, model, in_tokens, out_tokens, round(cost, 5)),
            )
    except Exception:
        pass


def _clean(row: dict | None) -> dict:
    """SQLite SUM 对空表返回 NULL → 统一成 0，前端好渲染。"""
    return {k: (0 if v is None else v) for k, v in (row or {}).items()}


def query_usage_summary(days: int = 7) -> dict:
    """用量/成本汇总：每日 + 分模型。管理看板 / 测试用。"""
    with db() as conn:
        daily = conn.execute(
            "SELECT substr(created_at,1,10) AS d, COUNT(*) AS calls, "
            "SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok, "
            "SUM(cost_cny) AS cost "
            "FROM usage_log WHERE created_at >= datetime('now','localtime', ?) "
            "GROUP BY d ORDER BY d",
            (f"-{days} days",),
        ).fetchall()
        by_model = conn.execute(
            "SELECT model, COUNT(*) AS calls, SUM(cost_cny) AS cost, "
            "SUM(input_tokens+output_tokens) AS tokens "
            "FROM usage_log GROUP BY model ORDER BY cost DESC",
        ).fetchall()
        totals = conn.execute(
            "SELECT COUNT(*) AS calls, SUM(cost_cny) AS cost, "
            "SUM(input_tokens+output_tokens) AS tokens FROM usage_log",
        ).fetchone()
    return {
        "days": days,
        "daily": [_clean(dict(r)) for r in daily],
        "by_model": [_clean(dict(r)) for r in by_model],
        "totals": _clean(dict(totals)),
    }
