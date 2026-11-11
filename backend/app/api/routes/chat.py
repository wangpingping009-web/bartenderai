# -*- coding: utf-8 -*-
"""聊天 SSE 流式接口：把多 Agent 执行过程实时推给前端。

一条流：思考中 → 总控判断 → 专业 Agent 执行中 → 审校 → done(完整答案+引用)。

M6 在此叠加三层防护（安全优先，不拖垮体验）：
1. 输入净化 + Prompt 注入检测（core/security）—— 改过的文本才进图
2. 限流（core/ratelimit）—— 按 user_id 滑动窗口，超限 429
3. 审计日志（core/audit）—— 每轮记一条（含注入告警标记，明文只存哈希）
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.schemas import ChatRequest
from app.core.audit import audit_log, summarize
from app.core.ratelimit import check_chat_quota
from app.core.security import defend_prompt
from app.db import repositories as repo
from app.services.gamification import bump
from app.services.streaming import stream_agent_response

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _persist_turn(gen, username: str, user_msg: str):
    """边转发边捕获 done 答案，流结束后落库（问+答）+ 记成长动作。"""
    answer = None
    for chunk in gen:
        yield chunk
        if chunk.startswith("data: "):
            try:
                evt = json.loads(chunk[6:])
            except json.JSONDecodeError:
                continue
            if evt.get("type") == "done" and evt.get("answer"):
                answer = evt["answer"]
    if answer:
        repo.append_chat(username, "user", user_msg)
        repo.append_chat(username, "assistant", answer)
        bump(username, "chat")   # M7：聊成一次，攒 XP + 徽章


@router.post("/stream")
def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE 流式对话。POST JSON {message, user_id?, session_id?}。"""
    # ---- 限流（先于一切，防刷接口）----
    check_chat_quota(req.user_id)

    # ---- 输入防护：净化 + 注入检测（注入不硬拦，但打审计标）----
    defense = defend_prompt(req.message)
    audit_log(action="chat", user=req.user_id,
              detail=f"injection={','.join(defense['injection_flags']) or 'none'}",
              meta_hash=summarize(req.message))

    repo.get_or_create_user(req.user_id)
    stock = repo.list_inventory(req.user_id)
    profile = repo.get_profile(req.user_id)
    history = repo.list_chat_history(req.user_id, limit=20)

    gen = stream_agent_response(
        defense["sanitized"],
        history=history,
        user_id=req.user_id,
        session_id=req.session_id,
        stock=stock or None,      # 空库存显式传 None，让 Agent 知道"没库存"
        profile=profile or None,
    )
    wrapped = _persist_turn(gen, req.user_id, defense["sanitized"])
    return StreamingResponse(
        wrapped,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
