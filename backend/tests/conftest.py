# -*- coding: utf-8 -*-
"""pytest 共享夹具。

设计（对应 REQUIREMENTS 11 质量层-确定性测试）:
- 用真实 LLM 的测试不可复现、费钱，所以基础测试全部 mock LLM
- fixture `fake_llm` 返回一个假 LLM：按预设返回，模拟"工具已调用、结论已给出"
- 这样能验证：reAct 循环流程 / 状态路由 / 结果合并，而不用真调模型
- E2E 真 LLM 测试单独放 tests/e2e/，默认被 markers 隔离，不随单测跑

用法:
  from tests.conftest import fake_llm
"""
from __future__ import annotations

import pytest

from langchain_core.messages import AIMessage


class FakeChatModel:
    """极简假 LLM：固定返回预设文本。用于测流程而非模型能力。"""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = []

    def invoke(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        text = self._responses[0] if self._responses else "(no response)"
        if len(self._responses) > 1:
            self._responses.pop(0)
        return AIMessage(content=text)


@pytest.fixture
def fake_llm():
    """返回一个预设回复序列的假 LLM。"""
    return FakeChatModel(["这是一条确定性测试回复。"])


@pytest.fixture
def agent_context():
    """一个空的 Agent 上下文，供各 Agent 单测。"""
    from app.agents.base import AgentContext
    return AgentContext(user_query="测试问题", history=[])
