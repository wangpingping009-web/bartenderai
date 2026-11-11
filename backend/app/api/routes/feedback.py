# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.auth import current_user
from app.db import repositories as repo
from app.db.database import db

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
ALLOWED_TAGS = {"too_sweet", "too_sour", "too_strong", "too_weak", "just_right", "not_my_taste"}


class FeedbackIn(BaseModel):
    recipe_id: str = Field(default="", max_length=80)
    recipe_name: str = Field(default="", max_length=160)
    rating: int = Field(ge=1, le=5)
    tags: list[str] = Field(default_factory=list, max_length=8)
    note: str = Field(default="", max_length=500)


def _profile_delta(tags: set[str], recipe_name: str) -> dict:
    delta: dict = {}
    feedback = []
    if "too_sweet" in tags:
        delta["sweetness"] = 3
        feedback.append(f"{recipe_name or '这杯酒'}太甜")
    if "too_sour" in tags:
        delta["sourness"] = 3
        feedback.append(f"{recipe_name or '这杯酒'}太酸")
    if "too_strong" in tags:
        delta["strong"] = 3
        feedback.append(f"{recipe_name or '这杯酒'}酒精感太强")
    if "too_weak" in tags:
        delta["strong"] = 7
        feedback.append(f"{recipe_name or '这杯酒'}酒精感太弱")
    if feedback:
        delta["feedback"] = feedback
    return delta


@router.post("", status_code=201)
def create_feedback(payload: FeedbackIn, user: dict = Depends(current_user)) -> dict:
    tags = {x for x in payload.tags if x in ALLOWED_TAGS}
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO feedback(user_id,recipe_id,recipe_name,rating,tags_json,note) VALUES(?,?,?,?,?,?)",
            (user["id"], payload.recipe_id, payload.recipe_name, payload.rating,
             json.dumps(sorted(tags), ensure_ascii=False), payload.note.strip()))
    delta = _profile_delta(tags, payload.recipe_name)
    if delta:
        repo.merge_profile(user["username"], delta)
    return {"id": cur.lastrowid, "profile_updated": bool(delta)}
