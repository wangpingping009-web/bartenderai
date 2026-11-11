# -*- coding: utf-8 -*-
"""SSE 事件流协议（前端实时展示 + 可观测共用）。

前端通过 SSE 订阅 `/api/chat/stream`，收到一串事件。每个事件形如：
  data: {"type": "agent_event", "agent": "retriever", "message": "正在检索...", "ts": 1720000000}

事件类型（type 字段）:
- status:       阶段状态（思考中/检索中/审校中...）
- agent_event:  具体 Agent 的执行细节（正在检索/检索到X条/调用公网...）
- reference:    引用来源（前端可展示"来源"角标）
- partial:      答案流式片段（打字机）
- done:         回答结束（带引用、来源）
- error:        错误

设计动机:
- 统一事件协议，前端只按 type 渲染，不关心内部
- M6 的 Langfuse 埋点直接复用这些事件（无需再改 Agent 代码）
"""
from __future__ import annotations

import json
import re
import time
from typing import Any


def _base(event_type: str, **extra: Any) -> dict:
    return {"type": event_type, "ts": int(time.time()), **extra}


def status_event(message: str, agent: str | None = None) -> str:
    """阶段状态事件，如 {思考中} {检索中}。"""
    return json.dumps(_base("status", message=message, agent=agent), ensure_ascii=False)


def agent_event(agent: str, message: str) -> str:
    """Agent 执行细节事件，如 {正在检索: 玛格丽特}。"""
    return json.dumps(_base("agent_event", agent=agent, message=message), ensure_ascii=False)


def reference_event(references: list[str]) -> str:
    """引用来源事件（前端展示"来源"）。"""
    return json.dumps(_base("reference", references=references), ensure_ascii=False)


def _citation(ref) -> dict:
    if isinstance(ref, dict):
        return ref
    text = str(ref)
    match = re.match(r"\[([^:\]]+):([^\]]+)\]\s*(.*?)(?:\s*\(score=([-\d.]+)\))?$", text)
    if not match:
        return {"source_type": "unknown", "id": "", "title": text,
                "score": None, "version": None, "url": None}
    return {"source_type": match.group(1), "id": match.group(2), "title": match.group(3),
            "score": float(match.group(4)) if match.group(4) else None,
            "version": 1, "url": None}


def done_event(answer: str, references: list | None = None,
               agent_trace: list[dict] | None = None,
               recipe: dict | None = None,
               recipes: list[dict] | None = None,
               creative_brief: dict | None = None,
               capability_mode: str = "unavailable",
               retrieval: dict | None = None) -> str:
    """回答结束事件，附完整答案、引用与结构化配方卡（如有）。"""
    return json.dumps(
        _base("done", answer=answer, references=[_citation(r) for r in (references or [])],
              agent_trace=agent_trace or [], recipe=recipe, recipes=recipes or [],
              creative_brief=creative_brief or {}, capability_mode=capability_mode,
              retrieval=retrieval or {}),
        ensure_ascii=False,
    )


def error_event(message: str) -> str:
    return json.dumps(_base("error", message=message), ensure_ascii=False)


def partial_event(text: str) -> str:
    """答案流式片段事件。"""
    return json.dumps(_base("partial", text=text), ensure_ascii=False)


# SSE 格式：每条事件前加 "data: " 前缀，空行分隔
def sse_format(event_json: str) -> str:
    return f"data: {event_json}\n\n"
