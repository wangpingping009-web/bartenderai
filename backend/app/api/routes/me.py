# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.core.auth import current_user, hash_password, verify_password
from app.db import repositories as repo
from app.db.database import db
from app.services import gamification
from app.services.recipe_catalog import inventory_matches

router = APIRouter(prefix="/api/me", tags=["me"])


class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    profile: dict | None = None


class InventoryIn(BaseModel):
    items: list[str] = Field(default_factory=list, max_length=100)


class FavoriteIn(BaseModel):
    recipe: dict


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


@router.get("")
def get_me(user: dict = Depends(current_user)) -> dict:
    return {**{k: v for k, v in user.items() if k != "username"},
            "profile": repo.get_profile(user["username"]),
            "progress": gamification.get_progress(user["id"])}


@router.patch("")
def update_me(payload: ProfileIn, user: dict = Depends(current_user)) -> dict:
    if payload.display_name is not None:
        with db() as conn:
            conn.execute("UPDATE users SET display_name=? WHERE id=?",
                         (payload.display_name.strip(), user["id"]))
    if payload.profile is not None:
        repo.merge_profile(user["username"], payload.profile)
    return get_me(user)


@router.get("/inventory")
def inventory(user: dict = Depends(current_user)) -> dict:
    return {"items": repo.list_inventory(user["username"])}


@router.put("/inventory")
def set_inventory(payload: InventoryIn, user: dict = Depends(current_user)) -> dict:
    clean = list(dict.fromkeys(x.strip()[:64] for x in payload.items if x.strip()))
    repo.set_inventory(user["username"], clean)
    return {"items": repo.list_inventory(user["username"])}


@router.get("/inventory/matches")
def matches(user: dict = Depends(current_user)) -> dict:
    return inventory_matches(repo.list_inventory(user["username"]))


@router.get("/favorites")
def favorites(user: dict = Depends(current_user)) -> dict:
    items = repo.list_favorites(user["username"])
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}


@router.post("/favorites", status_code=201)
def add_favorite(payload: FavoriteIn, user: dict = Depends(current_user)) -> dict:
    repo.add_favorite(user["username"], payload.recipe)
    gamification.record_action(user["id"], "favorite")
    return {"ok": True}


@router.delete("/favorites/{recipe_name}", status_code=204)
def remove_favorite(recipe_name: str, user: dict = Depends(current_user)):
    if not repo.remove_favorite(user["username"], recipe_name):
        raise HTTPException(404, detail="收藏不存在")


@router.post("/change-password")
def change_password(payload: ChangePasswordIn, user: dict = Depends(current_user)) -> dict:
    from app.core.auth import get_user_by_id
    row = get_user_by_id(user["id"])
    if not verify_password(payload.current_password, row["password_hash"]):
        raise HTTPException(400, detail="当前密码错误")
    encoded = hash_password(payload.new_password)
    with db() as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (encoded, user["id"]))
        conn.execute("UPDATE refresh_tokens SET revoked_at=datetime('now') WHERE user_id=? AND revoked_at IS NULL",
                     (user["id"],))
    return {"message": "密码已修改，请重新登录"}


@router.get("/export")
def export_data(user: dict = Depends(current_user)) -> dict:
    with db() as conn:
        conversations = [dict(r) for r in conn.execute(
            "SELECT id,title,created_at,updated_at FROM conversations WHERE user_id=?", (user["id"],)).fetchall()]
        feedback = [dict(r) for r in conn.execute(
            "SELECT recipe_id,recipe_name,rating,tags_json,note,created_at FROM feedback WHERE user_id=?",
            (user["id"],)).fetchall()]
    return {"account": {k: v for k, v in user.items() if k != "username"},
            "profile": repo.get_profile(user["username"]), "inventory": repo.list_inventory(user["username"]),
            "favorites": repo.list_favorites(user["username"]), "conversations": conversations,
            "feedback": feedback}


@router.delete("", status_code=204)
def delete_account(user: dict = Depends(current_user)):
    with db() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (user["id"],))
