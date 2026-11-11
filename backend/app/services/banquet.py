# -*- coding: utf-8 -*-
"""晚宴规划器（M7）：为多杯酒 × N 人 批量计算备料量。

确定性算法：
- 每杯按人数换算总量（配料数量 × 份数）
- 每杯算出"总烈酒毫升数"，供单杯/整桌酒精预算参考
- 给出批次提示（先做哪杯、哪些可预调、每份多少毫升）
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.services.zero_alcohol import get_cocktail, mocktailize

_COCKTAILS_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "cocktails.json"

# 常见容量单位 → 每份基础毫升（ml），用于换算"份数 × 人"
_UNIT_ML = {
    "oz": 30, "cl": 10, "ml": 1,
    "tsp": 5, "tbsp": 15, "dash": 1, "drop": 1, "bar spoon": 5,
    "cup": 240, "part": 30, "slice": 1, "wedge": 1, "twist": 1,
    "splash": 5, "shot": 45,
}


def _parse_amount(text: str) -> float:
    """把 '2-3 oz' / '1/2 oz' / '45 ml' 解析成纯数值（取上限，稳妥）。"""
    if not text:
        return 1.0
    m = re.search(r"([\d]+(?:[/\.]\d+)?)\s*(?:-|to)?\s*([\d]+(?:[/\.]\d+)?)?", text)
    if not m:
        return 1.0
    try:
        if "/" in m.group(1):
            n, d = m.group(1).split("/")
            base = int(n) / int(d)
        else:
            base = float(m.group(1))
        if m.group(2):
            if "/" in m.group(2):
                n, d = m.group(2).split("/")
                base = max(base, int(n) / int(d))
            else:
                base = max(base, float(m.group(2)))
        return base
    except (ValueError, ZeroDivisionError):
        return 1.0


def _amount_to_ml(text: str) -> float:
    val = _parse_amount(text)
    low = text.lower()
    for unit, ml in _UNIT_ML.items():
        if unit in low:
            return val * ml
    return val * 30  # 无单位默认当 1 份 ≈ 30ml


def plan_banquet(recipe_names: list[str], headcount: int, mocktail: bool = False) -> dict:
    """规划一场晚宴。recipe_names: 选中的配方名；headcount: 宾客人数。

    返回每杯的备料量、烈酒预算、批次提示。
    """
    if headcount < 1:
        headcount = 1
    plans = []
    for name in recipe_names:
        recipe = get_cocktail(name)
        if recipe is None:
            plans.append({"name": name, "error": "未找到该配方"})
            continue
        if mocktail:
            recipe = mocktailize(recipe)
        total_spirit_ml = 0.0
        items = []
        for ing in recipe.get("ingredients", []):
            amount_ml = _amount_to_ml(ing.get("amount", ""))
            total = amount_ml * headcount
            total_spirit_ml += total if _is_spirit(ing.get("name", "")) else 0
            items.append({"name": ing["name"], "per_person": round(amount_ml, 1),
                          "for_n": round(total, 1), "unit": "ml"})
        plans.append({
            "name": recipe.get("mocktail_name", recipe["name"]),
            "alcohol_free": recipe.get("alcohol_free", False),
            "ingredients": items,
            "total_spirit_ml": round(total_spirit_ml, 1),
            "per_person_spirit_ml": round(total_spirit_ml / headcount, 1),
            "method_hint": _prep_hint(recipe.get("category", "")),
        })

    return {
        "headcount": headcount,
        "cocktails": plans,
        "batch_tips": [
            f"共 {len(plans)} 杯 × {headcount} 人。先做不加冰的、可预调的（如大都会、曼哈顿），"
            "上桌前 5 分钟再摇/搅加冰",
            "备料按 'for_n' 列；宁多勿少，冰块按每人 2 杯的量提前冻",
            "烈酒预算：整桌约 " + str(round(sum(p.get("total_spirit_ml", 0) for p in plans), 1))
            + " ml 纯酒精（标准酒），单杯约 "
            + str(round(sum(p.get("per_person_spirit_ml", 0) for p in plans), 1)) + " ml。",
        ],
    }


def _is_spirit(name: str) -> bool:
    """粗判是否含酒精基酒（用于酒精预算）。"""
    low = name.lower()
    spirits = ["gin", "rum", "vodka", "tequila", "mezcal", "whis", "brandy", "cognac",
               "amaretto", "baileys", "vermouth", "triple sec", "cointreau",
               "grand marnier", "campari", "sherry", "champagne", "prosecco",
               "liqueur", "port", "beer", "stout", "wine"]
    return any(s in low for s in spirits)


def _prep_hint(category: str) -> str:
    if not category:
        return "摇和或搅拌，看配方标注"
    cat = category.lower()
    if "shot" in cat:
        return "直接倒杯，适合轮桌快速供应"
    if "punch" in cat or "bowl" in cat:
        return "整桶预调，上桌前加冰块"
    return "按配方执行：含果汁/奶的摇和，纯烈酒的搅拌"
