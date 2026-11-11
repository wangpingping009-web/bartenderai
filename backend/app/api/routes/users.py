# -*- coding: utf-8 -*-
"""用户/库存/画像 API（M4 简单用户体系 + M6 审计）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.schemas import InventoryBatch, InventoryItem, ProfileUpdate
from app.core.audit import audit_log
from app.db import repositories as repo
from app.services.gamification import bump

router = APIRouter(prefix="/api/users", tags=["users"])


# ---------- 库存 ----------

@router.get("/{username}/inventory")
def get_inventory(username: str) -> dict:
    return {"username": username, "items": repo.list_inventory(username)}


@router.post("/{username}/inventory")
def add_inventory(username: str, item: InventoryItem) -> dict:
    repo.add_inventory_item(username, item.name)
    audit_log(action="inventory_add", user=username, detail=item.name[:100])
    bump(username, "inventory")   # M7：添加库存攒 XP
    return {"ok": True, "items": repo.list_inventory(username)}


@router.delete("/{username}/inventory/{item_name}")
def delete_inventory(username: str, item_name: str) -> dict:
    removed = repo.remove_inventory_item(username, item_name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"库存中无 {item_name}")
    audit_log(action="inventory_remove", user=username, detail=item_name[:100])
    return {"ok": True, "items": repo.list_inventory(username)}


@router.put("/{username}/inventory")
def set_inventory(username: str, batch: InventoryBatch) -> dict:
    """整体替换库存（前端批量勾选导入用）。"""
    repo.set_inventory(username, batch.items)
    audit_log(action="inventory_set", user=username, detail=f"count={len(batch.items)}")
    return {"ok": True, "items": repo.list_inventory(username)}


# ---------- 画像 ----------

@router.get("/{username}/profile")
def get_profile(username: str) -> dict:
    return repo.get_profile(username) or {}


@router.post("/{username}/profile")
def update_profile(username: str, upd: ProfileUpdate) -> dict:
    """增量合并画像（可只传要更新的维度）。"""
    return repo.merge_profile(username, upd.profile)


# ---------- 收藏 ----------

@router.get("/{username}/favorites")
def get_favorites(username: str) -> dict:
    return {"username": username, "favorites": repo.list_favorites(username)}


@router.post("/{username}/favorites")
def add_favorite(username: str, card: dict) -> dict:
    """收藏一张配方卡（完整 recipe dict）。同名覆盖。"""
    repo.add_favorite(username, card)
    bump(username, "favorite")   # M7：收藏攒 XP
    return {"ok": True, "favorites": repo.list_favorites(username)}


@router.delete("/{username}/favorites/{recipe_name}")
def delete_favorite(username: str, recipe_name: str) -> dict:
    if not repo.remove_favorite(username, recipe_name):
        raise HTTPException(status_code=404, detail=f"未收藏 {recipe_name}")
    return {"ok": True, "favorites": repo.list_favorites(username)}
