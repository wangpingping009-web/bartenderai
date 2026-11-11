# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from app.core.config import settings
from app.core import llm as llm_module


@pytest.fixture(autouse=True)
def reset_provider_health():
    llm_module._runtime_health.clear()
    yield
    llm_module._runtime_health.clear()


class _GenerateModel:
    def __init__(self, name: str, calls: list, error: Exception | None = None):
        self.name = name
        self.calls = calls
        self.error = error

    def _generate(self, messages, **kwargs):
        self.calls.append((self.name, [message.content for message in messages]))
        if self.error:
            raise self.error
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="备用回答"))])


class _StreamModel:
    def __init__(self, chunks: list[str], error: Exception | None = None):
        self.chunks = chunks
        self.error = error

    def _stream(self, messages, **kwargs):
        for text in self.chunks:
            yield ChatGenerationChunk(message=AIMessageChunk(content=text))
        if self.error:
            raise self.error


def test_same_real_task_fails_over_without_ping(monkeypatch):
    calls = []
    primary = _GenerateModel("primary", calls, ConnectionError("provider down"))
    backup = _GenerateModel("backup", calls)
    monkeypatch.setattr(llm_module.FailoverChatModel, "_models",
                        lambda self: [primary, backup])

    result = llm_module.FailoverChatModel().invoke("请理解这条真实需求")

    assert result.content == "备用回答"
    assert calls == [
        ("primary", ["请理解这条真实需求"]),
        ("backup", ["请理解这条真实需求"]),
    ]


def test_stream_fails_over_only_before_any_text(monkeypatch):
    primary = _StreamModel([], ConnectionError("provider down"))
    backup = _StreamModel(["真实", "流式"])
    monkeypatch.setattr(llm_module.FailoverChatModel, "_models",
                        lambda self: [primary, backup])

    chunks = list(llm_module.FailoverChatModel().stream("开始"))

    assert "".join(chunk.content for chunk in chunks) == "真实流式"


def test_stream_never_splices_two_provider_answers(monkeypatch):
    primary = _StreamModel(["主模型半句"], ConnectionError("provider down"))
    backup = _StreamModel(["备用完整回答"])
    monkeypatch.setattr(llm_module.FailoverChatModel, "_models",
                        lambda self: [primary, backup])

    with pytest.raises(ConnectionError):
        list(llm_module.FailoverChatModel().stream("开始"))


def test_circuit_breaker_skips_known_failed_provider(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_LLM_BASE_URL", "")
    monkeypatch.setattr(settings, "LOCAL_LLM_MODEL", "")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "ds-real-key")
    monkeypatch.setattr(settings, "QWEN_API_KEY", "qw-real-key")
    monkeypatch.setattr(settings, "LLM_PROVIDER_PRIORITY", "deepseek,qwen")
    monkeypatch.setattr(settings, "LLM_CIRCUIT_BREAKER_SECONDS", 60)

    llm_module.record_llm_failure(ConnectionError("connection failed"), "deepseek")

    assert [provider.name for provider in llm_module._available_providers()] == ["qwen"]
    provider_state = {row["name"]: row for row in llm_module.llm_provider_health()}
    assert provider_state["deepseek"]["status"] == "cooldown"
    assert provider_state["deepseek"]["reason"] == "connection_failed"


def test_local_openai_compatible_provider_needs_url_and_model(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(settings, "LOCAL_LLM_MODEL", "qwen3:8b")
    monkeypatch.setattr(settings, "LOCAL_LLM_API_KEY", "")
    monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "")
    monkeypatch.setattr(settings, "QWEN_API_KEY", "")

    providers = llm_module._providers()

    assert [(provider.name, provider.model) for provider in providers] == [
        ("local", "qwen3:8b"),
    ]
    assert providers[0].api_key == "local-not-secret"
