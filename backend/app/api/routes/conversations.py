# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.auth import current_user
from app.core.crypto import decrypt_text, encrypt_text
from app.core.security import defend_prompt
from app.db import repositories as repo
from app.db.database import db
from app.services.gamification import record_action
from app.services.streaming import stream_agent_response

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationIn(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=120)


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def _owned(conversation_id: str, user_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM conversations WHERE id=? AND user_id=?",
                           (conversation_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, detail="会话不存在")
    return row


@router.get("")
def list_conversations(user: dict = Depends(current_user)) -> dict:
    with db() as conn:
        rows = conn.execute(
            "SELECT id,title,created_at,updated_at FROM conversations WHERE user_id=? ORDER BY updated_at DESC",
            (user["id"],)).fetchall()
    items = [dict(r) for r in rows]
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}


@router.post("", status_code=201)
def create_conversation(payload: ConversationIn, user: dict = Depends(current_user)) -> dict:
    conversation_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute("INSERT INTO conversations(id,user_id,title) VALUES(?,?,?)",
                     (conversation_id, user["id"], payload.title.strip()))
    return {"id": conversation_id, "title": payload.title.strip()}


@router.patch("/{conversation_id}")
def rename_conversation(conversation_id: str, payload: ConversationIn,
                        user: dict = Depends(current_user)) -> dict:
    _owned(conversation_id, user["id"])
    with db() as conn:
        conn.execute("UPDATE conversations SET title=?,updated_at=datetime('now','localtime') WHERE id=?",
                     (payload.title.strip(), conversation_id))
    return {"id": conversation_id, "title": payload.title.strip()}


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, user: dict = Depends(current_user)):
    _owned(conversation_id, user["id"])
    with db() as conn:
        conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))


@router.get("/{conversation_id}/messages")
def list_messages(conversation_id: str, user: dict = Depends(current_user)) -> dict:
    _owned(conversation_id, user["id"])
    with db() as conn:
        rows = conn.execute(
            "SELECT id,role,content,metadata_json,created_at FROM messages WHERE conversation_id=? ORDER BY id",
            (conversation_id,)).fetchall()
    items = []
    for row in rows:
        try:
            meta = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        items.append({"id": row["id"], "role": row["role"], "content": decrypt_text(row["content"]),
                      "metadata": meta, "created_at": row["created_at"]})
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}


def _history(conversation_id: str, limit: int = 20) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT role,content,metadata_json FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit)).fetchall()
    history = []
    for row in reversed(rows):
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            metadata = {}
        history.append({"role": row["role"], "content": decrypt_text(row["content"]),
                        "metadata": metadata})
    return history


@router.post("/{conversation_id}/messages/stream")
def stream_message(conversation_id: str, payload: MessageIn,
                   user: dict = Depends(current_user)) -> StreamingResponse:
    conversation = _owned(conversation_id, user["id"])
    defense = defend_prompt(payload.message)
    message = defense["sanitized"]
    history = _history(conversation_id)
    stock = repo.list_inventory(user["username"])
    profile = repo.get_profile(user["username"])
    with db() as conn:
        conn.execute("INSERT INTO messages(conversation_id,role,content) VALUES(?,?,?)",
                     (conversation_id, "user", encrypt_text(message)))
        if conversation["title"] == "新对话":
            conn.execute("UPDATE conversations SET title=?,updated_at=datetime('now','localtime') WHERE id=?",
                         (message[:32], conversation_id))

    def generate():
        answer = ""
        metadata: dict = {}
        for chunk in stream_agent_response(message, history=history, user_id=user["username"],
                                           session_id=conversation_id, stock=stock or None,
                                           profile=profile or None):
            yield chunk
            if chunk.startswith("data: "):
                try:
                    event = json.loads(chunk[6:])
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "done":
                    answer = event.get("answer") or ""
                    metadata = {"references": event.get("references") or [],
                                 "recipe": event.get("recipe"),
                                 "recipes": event.get("recipes") or [],
                                  "creative_brief": event.get("creative_brief") or {},
                                  "trace": event.get("agent_trace") or [],
                                  "capability_mode": event.get("capability_mode") or "unavailable",
                                 "retrieval": event.get("retrieval") or {},
                                 "trace_id": event.get("trace_id")}
        if answer:
            with db() as conn:
                conn.execute(
                    "INSERT INTO messages(conversation_id,role,content,metadata_json) VALUES(?,?,?,?)",
                    (conversation_id, "assistant", encrypt_text(answer), json.dumps(metadata, ensure_ascii=False)))
                conn.execute("UPDATE conversations SET updated_at=datetime('now','localtime') WHERE id=?",
                             (conversation_id,))
            record_action(user["id"], "chat")
            from app.services.profile import deterministic_profile_delta
            delta = deterministic_profile_delta(message)
            if delta:
                repo.merge_profile(user["username"], delta)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
