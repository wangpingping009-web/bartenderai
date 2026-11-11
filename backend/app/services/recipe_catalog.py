# -*- coding: utf-8 -*-
"""Normalized recipe catalog built from the 441-record CocktailDB dataset."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "processed" / "cocktails.json"

RECIPE_NAMES = {
    "A1": "柑橘石榴金酒", "ABC": "杏仁奶油干邑", "ACID": "双桶烈焰",
    "AT&T": "杜松伏特汤力", "A. J.": "苹果杰克西柚", "GG": "香草姜汁高球",
    "H.D.": "爱尔兰威士忌咖啡", "B-52": "B-52 轰炸机", "B-53": "B-53 轰炸机",
    "252": "二五二烈焰", "747": "榛果咖啡奶油", "Alexander": "亚历山大",
    "Margarita": "玛格丽特", "Mojito": "莫吉托", "Old Fashioned": "古典鸡尾酒",
    "Negroni": "内格罗尼", "Manhattan": "曼哈顿", "Daiquiri": "得其利",
    "Whiskey Sour": "威士忌酸", "Gin Fizz": "金菲士", "Moscow Mule": "莫斯科骡子",
    "Long Island Iced Tea": "长岛冰茶", "Cosmopolitan": "大都会", "Sidecar": "边车",
    "Bloody Mary": "血腥玛丽", "Pina Colada": "椰林飘香", "Mai Tai": "迈泰",
    "Martini": "马天尼", "Dry Martini": "干马天尼", "French 75": "法国75",
    "Tom Collins": "汤姆柯林斯", "White Russian": "白俄罗斯", "Black Russian": "黑俄罗斯",
    "Tequila Sunrise": "龙舌兰日出", "Singapore Sling": "新加坡司令",
    "Sex on the Beach": "性感海滩", "Cuba Libre": "自由古巴", "Mint Julep": "薄荷朱利普",
    "Irish Coffee": "爱尔兰咖啡", "Americano": "美式鸡尾酒", "Aperol Spritz": "阿佩罗橙光",
}

INGREDIENTS = {
    "gin": "金酒", "vodka": "伏特加", "rum": "朗姆", "white rum": "白朗姆",
    "dark rum": "黑朗姆", "tequila": "龙舌兰", "whiskey": "威士忌", "whisky": "威士忌",
    "bourbon": "波本威士忌", "brandy": "白兰地", "cognac": "干邑",
    "lemon juice": "柠檬汁", "lime juice": "青柠汁", "lemon": "柠檬", "lime": "青柠",
    "sugar syrup": "糖浆", "simple syrup": "糖浆", "sugar": "糖", "honey": "蜂蜜",
    "honey syrup": "蜂蜜糖浆", "mint": "薄荷", "basil": "罗勒",
    "soda water": "苏打水", "tonic water": "汤力水", "orange juice": "橙汁",
    "pineapple juice": "菠萝汁", "cranberry juice": "蔓越莓汁", "egg white": "蛋清",
    "sweet vermouth": "甜味美思", "dry vermouth": "干味美思", "triple sec": "橙味利口酒",
    "cointreau": "君度", "campari": "金巴利", "angostura bitters": "安格斯图拉苦精",
    "coffee liqueur": "咖啡利口酒", "baileys irish cream": "百利甜酒",
    "ginger beer": "姜汁啤酒", "cola": "可乐", "grenadine": "红石榴糖浆",
    "cream": "奶油", "light cream": "淡奶油", "milk": "牛奶", "coconut cream": "椰浆",
    "creme de cacao": "可可利口酒", "cherry brandy": "樱桃白兰地",
    "southern comfort": "南方舒适利口酒", "sweet and sour": "酸甜汁",
    "yukon jack": "育空杰克利口酒", "nutmeg": "肉豆蔻",
}

INGREDIENT_ALIASES = {
    "汤力": "tonic water", "汤力水": "tonic water", "苏打": "soda water",
    "气泡水": "soda water", "糖水": "simple syrup", "蜂蜜糖浆": "honey syrup",
    "琴酒": "gin", "毡酒": "gin", "波本": "bourbon", "橙酒": "triple sec",
    "lemon peel": "lemon", "lime peel": "lime", "orange peel": "orange",
    "柠檬皮": "lemon", "青柠皮": "lime", "橙皮": "orange", "冰块": "ice",
}

BAR_BASICS = {"ice"}

ABV = {
    "gin": 40, "vodka": 40, "rum": 40, "white rum": 40, "dark rum": 40,
    "tequila": 40, "whiskey": 40, "whisky": 40, "bourbon": 40, "brandy": 40,
    "cognac": 40, "vermouth": 16, "campari": 25, "triple sec": 30, "cointreau": 40,
    "liqueur": 20, "wine": 12, "champagne": 12, "beer": 5,
}


def canonical(value: str) -> str:
    value = (value or "").strip().lower()
    if value in INGREDIENT_ALIASES:
        return INGREDIENT_ALIASES[value]
    for en, zh in INGREDIENTS.items():
        if value == en or value == zh.lower():
            return en
    return re.sub(r"\s+", " ", value)


def ingredient_zh(value: str) -> str:
    return INGREDIENTS.get(canonical(value), value)


def _milliliters(amount: str) -> float:
    text = (amount or "").strip().lower().replace("½", "1/2").replace("¼", "1/4").replace("¾", "3/4")
    mixed = re.search(r"(\d+)\s+(\d+)\/(\d+)", text)
    frac = re.search(r"(?<!\d)(\d+)\/(\d+)", text)
    num = re.search(r"\d+(?:\.\d+)?", text)
    if mixed:
        value = float(mixed.group(1)) + float(mixed.group(2)) / float(mixed.group(3))
    elif frac:
        value = float(frac.group(1)) / float(frac.group(2))
    elif num:
        value = float(num.group())
    else:
        return 0
    if "oz" in text or "shot" in text:
        return value * 30
    if "cl" in text:
        return value * 10
    if "ml" in text:
        return value
    if "tsp" in text or "teaspoon" in text:
        return value * 5
    if "tbsp" in text:
        return value * 15
    return 0


def _ingredient_abv(name: str) -> float:
    key = canonical(name)
    for marker, value in ABV.items():
        if marker in key:
            return value
    return 0


def _estimate_abv(ingredients: list[dict], alcoholic: bool) -> float:
    if not alcoholic:
        return 0
    total = 0.0
    alcohol = 0.0
    for item in ingredients:
        ml = _milliliters(item.get("amount", ""))
        total += ml
        alcohol += ml * _ingredient_abv(item.get("name", "")) / 100
    if total <= 0:
        return 18.0
    # Shaken/stirred drinks normally gain roughly 20% dilution.
    return round(min(50.0, alcohol / (total * 1.2) * 100), 1)


def _flavor(ingredients: list[dict], abv: float) -> dict:
    text = " ".join(canonical(i.get("name", "")) for i in ingredients)
    sweet = 6 if any(x in text for x in ("sugar", "syrup", "liqueur", "grenadine", "cream", "creme")) else 3
    sour = 7 if any(x in text for x in ("lemon", "lime", "grapefruit", "sweet and sour", "sour mix")) else 2
    bitter = 6 if any(x in text for x in ("bitters", "campari", "vermouth", "tonic")) else 2
    aroma = 7 if any(x in text for x in ("mint", "gin", "bitters", "vermouth", "orange")) else 4
    body = 7 if any(x in text for x in ("cream", "egg", "milk", "coffee")) else 4
    return {"sweet": sweet, "sour": sour, "bitter": bitter,
            "strong": min(10, round(abv / 4)), "body": body, "aroma": aroma}


def build_recipe_guide(ingredients: list[dict], glass: str,
                       instructions: str = "", instructions_en: str = "") -> dict:
    """Build a complete, executable mixing guide from source recipe facts."""
    source = f"{instructions_en} {instructions}".lower()
    names = " ".join(str(item.get("name") or "").lower() for item in ingredients)
    if "layer" in source:
        method, timer = "分层 Layer", 0
        tools = [glass or "利口杯", "吧匙", "量酒器"]
    elif "blend" in source:
        method, timer = "搅打 Blend", 18
        tools = [glass or "合适杯具", "搅拌机", "量酒器"]
    elif "shake" in source:
        method, timer = "摇和 Shake", 15
        tools = [glass or "合适杯具", "雪克壶", "量酒器", "滤冰器"]
    elif "stir" in source:
        method, timer = "搅拌 Stir", 20
        tools = [glass or "合适杯具", "调酒杯", "吧匙", "量酒器", "滤冰器"]
    else:
        method, timer = "杯中直调 Build", 0
        tools = [glass or "合适杯具", "吧匙", "量酒器"]

    has_ice = "ice" in source or "冰" in instructions
    has_egg = "egg" in names or "蛋" in names
    measured = "；".join(
        f"{item.get('name_zh') or ingredient_zh(item.get('name') or '')} {item.get('amount') or '适量'}"
        for item in ingredients
    )
    prep = f"准备并清洁 {glass or '合适杯具'}，备好" + "、".join(tools[1:])
    if has_ice:
        prep += "和足量新鲜冰块"
    prep += "。需要冰镇的杯具先加冰静置。"
    steps = [prep, f"逐项量取本杯材料：{measured}。"]

    if has_egg and method.startswith("摇和"):
        steps.extend([
            "先不加冰，将含蛋清的材料放入雪克壶，干摇约 15 秒，使蛋白充分起泡。",
            "加入冰块后再次用力摇和约 12 秒，让酒液冷却并达到合适稀释度。",
            f"双重过滤到 {glass or '杯具'}，拦住碎冰并让泡沫更细腻。",
        ])
        timer = 15
    elif method.startswith("摇和"):
        steps.extend([
            f"把材料与冰块加入雪克壶，密封后用力摇和约 {timer} 秒。",
            f"过滤到{('已冰镇的' if 'chill' in source else '')}{glass or '杯具'}，不要把雪克壶中的碎冰带入成品。",
        ])
    elif method.startswith("搅拌"):
        steps.extend([
            f"把材料和大块冰放入调酒杯，用吧匙平稳搅拌约 {timer} 秒。",
            f"过滤到{('已冰镇的' if 'chill' in source else '')}{glass or '杯具'}，保持酒液清澈。",
        ])
    elif method.startswith("搅打"):
        steps.extend([
            f"将材料和配方要求的冰加入搅拌机，搅打约 {timer} 秒至质地均匀。",
            f"倒入 {glass or '杯具'}，轻敲杯底排出过大的气泡。",
        ])
    elif method.startswith("分层"):
        steps.extend([
            "按材料密度从高到低排列顺序，先倒入最重的一层。",
            "将吧匙背贴近液面，其余材料沿吧匙缓慢注入，保持层次边界清晰。",
        ])
    else:
        steps.extend([
            f"按配方顺序把材料加入{('装有冰块的' if has_ice else '')}{glass or '杯具'}。",
            "用吧匙轻柔混合；含气泡的材料最后补入，避免过度搅拌损失气泡。",
        ])

    if "top" in source or "fill" in source:
        steps.append("最后补入配方中的气泡饮料或长饮材料，轻提一次吧匙使其均匀。")
    steps.append("检查温度、液面和杯口；原配方未注明装饰时保持简洁，调好后立即饮用。")
    return {
        "method": method,
        "timer_seconds": timer,
        "timer_label": "干摇计时" if has_egg and method.startswith("摇和") else f"{method.split()[0]}计时",
        "equipment": list(dict.fromkeys(tools)),
        "steps": list(dict.fromkeys(steps)),
    }


def normalize(raw: dict) -> dict:
    ingredients = []
    for item in raw.get("ingredients") or []:
        name = item.get("name", "")
        ingredients.append({"name": name, "name_zh": ingredient_zh(name),
                            "canonical": canonical(name), "amount": (item.get("amount") or "").strip()})
    abv = raw.get("abv_estimate")
    if abv is None:
        abv = _estimate_abv(ingredients, bool(raw.get("alcoholic")))
    name = raw.get("name") or ""
    name_cn = raw.get("name_cn") or RECIPE_NAMES.get(name) or name
    aliases = list(dict.fromkeys([name, name_cn]))
    flavor = raw.get("flavor_profile") or _flavor(ingredients, float(abv or 0))
    instructions = raw.get("instructions_zh") or raw.get("instructions_en") or ""
    instructions_en = raw.get("instructions_en") or ""
    guide = build_recipe_guide(ingredients, raw.get("glass") or "", instructions, instructions_en)
    return {
        "id": str(raw.get("id") or name), "name": name, "name_cn": name_cn, "aliases": aliases,
        "category": raw.get("category") or "Other", "alcoholic": bool(raw.get("alcoholic")),
        "glass": raw.get("glass") or "", "instructions": instructions,
        "instructions_en": instructions_en, "ingredients": ingredients,
        "image": raw.get("image") or "", "abv": abv, "flavor": flavor, "tags": raw.get("tags") or [],
        "source": raw.get("source") or "thecocktaildb", "version": int(raw.get("version") or 1),
        **guide,
    }


@lru_cache(maxsize=1)
def all_recipes() -> list[dict]:
    if not DATA_FILE.exists():
        return []
    with open(DATA_FILE, encoding="utf-8") as handle:
        return [normalize(item) for item in json.load(handle)]


def get_recipe(recipe_id: str) -> dict | None:
    needle = recipe_id.lower()
    return next((r for r in all_recipes() if r["id"].lower() == needle or r["name"].lower() == needle
                 or r["name_cn"].lower() == needle), None)


def search_recipes(q: str = "", category: str = "", alcoholic: bool | None = None,
                   base_spirit: str = "", inventory: list[str] | None = None,
                   available_only: bool = False, flavor: str = "",
                   abv_min: float | None = None, abv_max: float | None = None,
                   sort: str = "") -> list[dict]:
    query = q.strip().lower()
    query_tokens = [token for token in re.split(r"\s+", query) if token]
    inv = {canonical(x) for x in (inventory or [])}
    out = []
    for recipe in all_recipes():
        haystack = " ".join(recipe["aliases"] + [i["name"] + " " + i["name_zh"] for i in recipe["ingredients"]]).lower()
        if query_tokens and not all(token in haystack for token in query_tokens):
            continue
        if category and recipe["category"] != category:
            continue
        if alcoholic is not None and recipe["alcoholic"] != alcoholic:
            continue
        base = canonical(base_spirit)
        if base_spirit and not any(base == i["canonical"] or base in i["canonical"]
                                   for i in recipe["ingredients"]):
            continue
        if flavor and float(recipe["flavor"].get(flavor, 0)) < 5:
            continue
        if abv_min is not None and float(recipe["abv"] or 0) < abv_min:
            continue
        if abv_max is not None and float(recipe["abv"] or 0) > abv_max:
            continue
        required = {i["canonical"] for i in recipe["ingredients"]
                    if i["canonical"] and i["canonical"] not in BAR_BASICS}
        missing = sorted(required - inv) if inventory is not None else []
        if available_only and missing:
            continue
        out.append({**recipe, "missing_ingredients": missing, "available": inventory is not None and not missing})
    if sort == "abv_asc":
        out.sort(key=lambda item: (float(item.get("abv") or 0), item["name"]))
    elif sort == "abv_desc":
        out.sort(key=lambda item: (-float(item.get("abv") or 0), item["name"]))
    elif sort in ("sweet", "sour", "aroma"):
        out.sort(key=lambda item: (-float(item["flavor"].get(sort, 0)), item["name"]))
    elif sort == "name":
        out.sort(key=lambda item: item.get("name_cn") or item["name"])
    return out


def inventory_matches(inventory: list[str], limit: int = 30) -> dict:
    inv = {canonical(x) for x in inventory}
    scored = []
    for recipe in all_recipes():
        required = {i["canonical"] for i in recipe["ingredients"]
                    if i["canonical"] and i["canonical"] not in BAR_BASICS}
        if not required:
            continue
        missing = sorted(required - inv)
        ratio = round((len(required) - len(missing)) / len(required), 3)
        scored.append((len(missing), -ratio, {**recipe, "missing_ingredients": missing,
                                             "substitution_suggestions": _substitution_suggestions(missing, inv),
                                             "match_ratio": ratio, "available": not missing}))
    scored.sort(key=lambda item: (item[0], item[1], item[2]["name"]))
    items = [x[2] for x in scored[:limit]]
    return {"ready": [x for x in items if x["available"]],
            "nearby": [x for x in items if not x["available"]]}


@lru_cache(maxsize=1)
def _substitution_cards() -> list[dict]:
    path = DATA_FILE.parents[1] / "knowledge" / "substitutions.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, list) else []


def _substitution_suggestions(missing: list[str], inventory: set[str]) -> dict[str, list[dict]]:
    """Attach curated substitution evidence to missing inventory items."""
    result: dict[str, list[dict]] = {}
    for ingredient in missing:
        names = {ingredient, ingredient_zh(ingredient)}
        suggestions = []
        for card in _substitution_cards():
            text = " ".join(str(card.get(key) or "") for key in ("title", "title_cn", "content", "content_cn")).lower()
            if not any(name.lower() in text for name in names if name):
                continue
            inventory_match = next((owned for owned in inventory if owned and owned in text), None)
            suggestions.append({
                "id": card.get("id"), "title": card.get("title_cn") or card.get("title"),
                "available_substitute": ingredient_zh(inventory_match) if inventory_match else None,
                "guidance": card.get("content_cn") or card.get("content"),
            })
        if suggestions:
            result[ingredient] = suggestions[:2]
    return result
