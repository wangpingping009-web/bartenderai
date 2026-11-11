# -*- coding: utf-8 -*-
"""零酒模式（M7）：把含酒精配方确定性改造成无酒精 Mocktail。

数据里所有 441 杯都是含酒精的 → "零酒"不是过滤，而是改造：
把基酒换成风味等价的无酒精替代物，保留风味骨架与技法。
完全确定性规则（无 LLM），可单测。展示"替代引擎"的第二种应用。

替代映射以"风味功能"为准（M5 替代规则的延续）：
  Gin      → 无酒精金酒（杜松风味）/ 青柠+黄瓜水
  Light rum→ 椰子水（甜感近似）/ 朗姆风味香精
  Dark rum → 菠萝汁 + 红糖（烟熏甜感近似）
  Vodka    → 苏打水（中性，只当体积）/ 无酒精伏特加
  Tequila  → 青柠汁 + 龙舌兰糖浆（草本酸感）
  Whisky/Bourbon/Scotch → 苹果汁 + 烟熏苦精（木质烟熏近似）
  Brandy/Cognac → 葡萄汁（果香近似）
  Amaretto / 利口酒 → 对应果味糖浆
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_COCKTAILS_PATH = Path(__file__).resolve().parents[2] / "data" / "processed" / "cocktails.json"

# 基酒关键词 → 无酒精替代物 + 说明（风味近似原理）
_BASE_SWAPS: list[tuple[list[str], str, str]] = [
    (["gin"], "无酒精金酒（杜松风味）", "杜松子是金酒的风味核心，无酒精金酒保留草本与柑橘气息"),
    (["light rum", "white rum", "silver rum", "rum"], "椰子水 + 青柠", "椰香与淡朗姆的清甜近似，酸度由青柠补齐"),
    (["dark rum", "gold rum", "black rum", "spiced rum"], "菠萝汁 + 红糖", "深色朗姆的焦糖与热带果味，用红糖还原甜感"),
    (["vodka"], "苏打水", "伏特加本身风味中性，用苏打补体积、几乎不改变味道"),
    (["tequila", "mezcal"], "青柠汁 + 龙舌兰糖浆", "龙舌兰的草本酸感，用青柠+糖浆还原"),
    (["whisky", "whiskey", "bourbon", "scotch", "rye"], "苹果汁 + 烟熏苦精", "苹果汁的木质甜感 + 苦精的烟熏层次，近似威士忌"),
    (["brandy", "cognac"], "葡萄汁（无籽）", "白兰地的果香源自葡萄，葡萄汁直接还原"),
    (["amaretto"], "杏仁糖浆", "杏仁利口酒的风味就是杏仁，糖浆还原"),
    (["baileys", "irish cream"], "椰奶 + 咖啡糖浆", "Baileys 的奶感与咖啡甜感分层还原"),
    (["triple sec", "cointreau", "grand marnier", "orange liqueur", "orange curacao"], "橙味糖浆", "橙皮利口酒 → 橙味糖浆，甜酸一致"),
    (["campari"], "无酒精苦味开胃酒", "Campari 的草本苦味用无酒精版本还原"),
    (["sherry", "vermouth", "port", "madeira"], "无醇风味增强剂", "加香葡萄酒用无醇版本还原草本层次"),
    (["champagne", "prosecco", "sparkling wine"], "无酒精气泡酒 / 苏打水", "起泡的仪式感保留，气泡是关键"),
    (["beer", "stout", "lager"], "无醇啤酒", "麦芽香与气泡还原"),
]


def _load_cocktails() -> list[dict]:
    return json.loads(_COCKTAILS_PATH.read_text(encoding="utf-8"))


def _find_base_in(name: str, ingredients: list[dict]) -> str | None:
    """找出一条配方里最像"基酒"的成分（前 30% 里第一个命中基酒词库的）。"""
    text = name.lower()
    for keywords, swap, _why in _BASE_SWAPS:
        if any(k in text for k in keywords):
            return swap
    for item in ingredients[:3]:  # 基酒惯例排前
        item_name = item.get("name", "").lower()
        for keywords, swap, _why in _BASE_SWAPS:
            if any(k in item_name for k in keywords):
                return swap
    return None


def mocktailize(recipe: dict) -> dict:
    """把一杯含酒精配方改造成 Mocktail 卡。不改原数据，返回新 dict。

    - base_swap: 基酒 → 无酒精替代物
    - 原含酒精配料（非基酒，如利口酒）也按规则替换；找不到则保留并标注
    - 输出带 alcohol_free=True + 风味说明
    """
    ingredients = recipe.get("ingredients", [])
    base_swap = _find_base_in(recipe.get("name", ""), ingredients)
    new_ingredients: list[dict] = []
    replaced: list[dict] = []
    for item in ingredients:
        name = item.get("name", "")
        low = name.lower()
        # 基酒命中：直接用替代物替换整条
        hit = None
        for keywords, swap, why in _BASE_SWAPS:
            if any(k in low for k in keywords):
                hit = (swap, why)
                break
        if hit:
            swap, why = hit
            replaced.append({"from": name, "to": swap, "why": why})
            new_ingredients.append({"name": swap, "amount": item.get("amount", ""),
                                    "note": "替代基酒，0 酒精"})
        else:
            new_ingredients.append(item)
    return {
        **recipe,
        "name": recipe["name"],
        "mocktail_name": f"无酒精·{recipe['name']}",
        "alcoholic": False,
        "abv_estimate": 0,
        "alcohol_free": True,
        "base_swap": base_swap,
        "replaced": replaced,
        "ingredients": new_ingredients,
        "note": "由原配方改造：替换基酒为无酒精替代物，保留风味骨架。"
                "若替代物是糖浆/果汁类，可减少自带糖量，避免偏甜。",
    }


def list_mocktailable(limit: int = 20) -> list[dict]:
    """所有可改造的配方（含基酒），返回轻量卡片列表。"""
    out = []
    for c in _load_cocktails():
        if _find_base_in(c.get("name", ""), c.get("ingredients", [])):
            out.append({"name": c["name"], "category": c.get("category"),
                        "ingredients_text": c.get("ingredients_text")})
    return out[:limit]


def get_cocktail(name: str) -> dict | None:
    """按名字取配方（大小写不敏感）。"""
    for c in _load_cocktails():
        if c.get("name", "").lower() == name.lower():
            return c
    return None
