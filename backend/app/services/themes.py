# -*- coding: utf-8 -*-
"""主题酒单服务：从策展数据（themes.json）读取主题菜单。

对应 REQUIREMENTS §6「主题派对酒单（新年/夏夜晚风/约会之夜）」。
纯策展数据、确定性输出，不依赖 LLM / Milvus —— 数据驱动特色的一个例子。
"""
from __future__ import annotations

import json
from pathlib import Path

_THEMES_PATH = Path(__file__).resolve().parents[2] / "data" / "knowledge" / "themes.json"

_cache: dict | None = None


def _load() -> dict:
    """加载主题数据（首次读取后缓存）。"""
    global _cache
    if _cache is None:
        _cache = json.loads(_THEMES_PATH.read_text(encoding="utf-8"))
    return _cache


def list_themes() -> list[dict]:
    """所有主题的摘要（不含推荐详情）。"""
    data = _load()
    return [
        {"key": k, "name": v["name"], "emoji": v["emoji"], "vibe": v["vibe"],
         "count": len(v.get("recommendations", []))}
        for k, v in data.items()
    ]


def get_theme(key: str) -> dict | None:
    """按 key 取完整主题（含推荐清单）。"""
    return _load().get(key)
