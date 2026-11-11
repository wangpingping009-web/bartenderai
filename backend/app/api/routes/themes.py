# -*- coding: utf-8 -*-
"""主题酒单 API：策展主题菜单（新年/夏夜/约会）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.services import themes

router = APIRouter(prefix="/api/themes", tags=["themes"])


@router.get("")
def list_themes() -> dict:
    return {"themes": themes.list_themes()}


@router.get("/{key}")
def get_theme(key: str) -> dict:
    t = themes.get_theme(key)
    if t is None:
        raise HTTPException(status_code=404, detail=f"无主题 {key}")
    return {"key": key, **t}
