# -*- coding: utf-8 -*-
"""每日一酒（M7）：按日期确定性随机，同一天所有人看到同一杯。"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

_COCKTAILS_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "cocktails.json"

# 趣味挑战：从知识里生成"用 X 做 Y"的玩法（确定性取当天种子）
_CHALLENGE_INGREDIENTS = ["青柠", "薄荷", "蜂蜜", "姜", "黄瓜", "西瓜", "桂花", "茉莉", "可乐", "咖啡"]


def _load_cocktails() -> list[dict]:
    return json.loads(_COCKTAILS_PATH.read_text(encoding="utf-8"))


def _seed_for(day: str) -> int:
    """把日期字符串变成稳定种子。"""
    return int(hashlib.sha256(day.encode()).hexdigest(), 16)


def daily_cocktail(day: str | None = None) -> dict:
    """指定日期（YYYY-MM-DD）的每日一酒。同一天结果一致，无需 LLM。"""
    day = day or date.today().isoformat()
    items = _load_cocktails()
    idx = _seed_for(day) % len(items)
    c = items[idx]
    return {
        "date": day,
        "recipe": {
            "name": c["name"],
            "category": c.get("category"),
            "ingredients_text": c.get("ingredients_text"),
            "glass": c.get("glass"),
            "tags": c.get("tags"),
        },
        "tip": "今日特调：按日期种子选出，适合作为你的入门练习对象。",
    }


def daily_challenge(day: str | None = None) -> dict:
    """趣味挑战：用两种随机材料创作一杯自己的鸡尾酒。"""
    day = day or date.today().isoformat()
    seed = _seed_for("challenge:" + day)
    a = _CHALLENGE_INGREDIENTS[seed % len(_CHALLENGE_INGREDIENTS)]
    b = _CHALLENGE_INGREDIENTS[(seed // 7) % len(_CHALLENGE_INGREDIENTS)]
    while b == a:
        b = _CHALLENGE_INGREDIENTS[(seed // 13 + 1) % len(_CHALLENGE_INGREDIENTS)]
    return {
        "date": day,
        "ingredient_a": a,
        "ingredient_b": b,
        "title": f"挑战：用 {a} × {b} 创作一杯",
        "steps": [
            f"先想：{a} 和 {b} 是什么风味（酸甜/清爽/浓郁）？",
            f"给它们配一个基酒或做成无酒精版本",
            "写下一句配方（材料+比例+摇还是搅）",
            "调出来试一口，好喝就收藏，不好喝记录原因",
        ],
    }
