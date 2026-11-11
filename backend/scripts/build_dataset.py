# -*- coding: utf-8 -*-
"""清洗原始数据 -> 结构化配方库。

输入: data/raw/cocktails_raw.json  (TheCocktailDB 原始字段)
输出: data/processed/cocktails.json (本项目结构化 schema)

做了什么清洗:
1. 抽材料: 把 strIngredient1..15 + strMeasure1..15 配对成 [{name, amount}]
   并过滤空材料、去掉用量里的单位噪音("oz"/"shot"/"cl" 保留原文)
2. 归一化: 布尔字段(alcoholic)、空值(glass/tags)、材料名转小写
3. 拼检索文本: ingredients_text 是向量检索的关键——把"可被搜索到"的信息
   都拼进一句话里(名称+材料+分类+标签), 让"tequila lime salt"能命中玛格丽特
4. 打标来源与版本: 支持知识库版本追溯(M6 治理)

保留原字段与增强字段并存: raw 字段不动, 只新增结构化字段,
方便之后对照调试和增量重清洗。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

RAW_PATH = Path(__file__).resolve().parents[1] / "data" / "raw"
PROC_PATH = Path(__file__).resolve().parents[1] / "data" / "processed"

INGREDIENT_MAX = 15  # TheCocktailDB 最多 15 个材料槽位

# 常见"量词/杯型"噪音词, 用于用量规整(不删数字, 只清理明显无效值)
_MEASURE_NOISE = re.compile(r"^(½|1\/2)?( of )?$|^part$|^$", re.I)


def _extract_ingredients(drink: dict) -> list[dict]:
    """把 strIngredientN/strMeasureN 配对成结构化材料列表。"""
    pairs = []
    for i in range(1, INGREDIENT_MAX + 1):
        name = (drink.get(f"strIngredient{i}") or "").strip()
        if not name:
            continue  # 空槽位直接跳过
        amount = (drink.get(f"strMeasure{i}") or "").strip()
        if _MEASURE_NOISE.match(amount):
            amount = ""
        pairs.append({
            "name": name,
            "amount": amount,
        })
    return pairs


def _extract_tags(drink: dict) -> list[str]:
    """strTags 是逗号分隔标签(如 "IBA,ContemporaryClassic")。"""
    raw = (drink.get("strTags") or "").strip()
    return [t.strip() for t in raw.split(",") if t.strip()]


def _to_recipe(drink: dict) -> dict:
    """单条原始记录 -> 结构化配方。原始字段保留在 raw_ 前缀。"""
    ingredients = _extract_ingredients(drink)
    tags = _extract_tags(drink)
    alcoholic = drink.get("strAlcoholic") == "Alcoholic"

    # 检索文本: 供向量/BM25 检索的"扁平化"文本。
    # 语义上是"用户一句话里有这些词, 就能撞上这款酒"。
    searchable_parts = [
        drink.get("strDrink", ""),
        *(ing["name"] for ing in ingredients),
        drink.get("strCategory", ""),
        drink.get("strGlass", ""),
        *tags,
    ]
    ingredients_text = ", ".join(p for p in searchable_parts if p)

    return {
        "id": drink["idDrink"],
        "name": drink.get("strDrink", ""),
        "category": drink.get("strCategory", ""),
        "alcoholic": alcoholic,
        "glass": drink.get("strGlass", ""),
        "instructions_en": drink.get("strInstructions", ""),
        "instructions_zh": drink.get("strInstructionsZH-HANS", ""),
        "ingredients": ingredients,
        "tags": tags,
        "ingredients_text": ingredients_text,  # 检索用
        "image": drink.get("strDrinkThumb", ""),
        "abv_estimate": None,   # 后续由风味引擎估算(M5)
        "flavor_profile": None,  # 六维雷达图数据(M5)
        "source": "thecocktaildb",
        "version": 1,
    }


def main() -> None:
    PROC_PATH.mkdir(parents=True, exist_ok=True)

    with open(RAW_PATH / "cocktails_raw.json", encoding="utf-8") as f:
        drinks = json.load(f)

    recipes = [_to_recipe(d) for d in drinks]

    # 空材料或空名称的极少数脏数据直接丢弃(保质量)
    clean = [r for r in recipes if r["name"] and r["ingredients"]]

    out = PROC_PATH / "cocktails.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)

    n_zh = sum(1 for r in clean if r["instructions_zh"])
    print(f"清洗完成: {len(clean)} 款 (丢弃 {len(recipes) - len(clean)}) -> {out}")
    print(f"含中文步骤: {n_zh} 款")
    print(f"无酒精/可选酒精: {sum(1 for r in clean if not r['alcoholic'])} 款")


if __name__ == "__main__":
    main()
