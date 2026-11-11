# -*- coding: utf-8 -*-
"""Reliable recipe answers built directly from the normalized catalog."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.rag.hybrid import HybridRetriever, RetrievedDoc
from app.services.recipe_catalog import (
    INGREDIENTS, INGREDIENT_ALIASES, RECIPE_NAMES, all_recipes, canonical, get_recipe,
    ingredient_zh, inventory_matches,
)


@dataclass
class DeterministicAnswer:
    answer: str
    recipe: dict | None = None
    doc: RetrievedDoc | None = None
    recipes: list[dict] = field(default_factory=list)
    docs: list[RetrievedDoc] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)


@dataclass
class RecipeConversationContext:
    """Recipe intent recovered from real conversation history, without an LLM."""

    query: str
    followup: bool = False
    exclude_recipe_ids: set[str] = field(default_factory=set)
    inherited_preference: str = ""
    recommendation_count: int = 1
    selected_recipe_id: str | None = None


_SOUR_INGREDIENTS = (
    "lemon", "lime", "grapefruit", "sour", "citrus", "酸甜", "柠檬", "青柠",
    "orange juice", "pineapple juice", "cranberry juice",
)
_SWEET_INGREDIENTS = (
    "sugar", "syrup", "liqueur", "cream", "creme", "chocolate", "coffee liqueur",
    "grenadine", "honey", "糖", "奶油", "利口酒",
)
_POPULAR = {
    "White Russian": 4.0, "Pina Colada": 3.5, "Alexander": 3.0,
    "B-52": 2.5, "Mojito": 2.0, "Margarita": 2.0, "Negroni": 2.0,
}
_FOLLOWUP_RE = re.compile(
    r"\s*(?:还有(?:吗|呢|别的(?:吗|呢)?)?|别的呢|再(?:来|推荐)(?:一杯|一个|一款)?(?:吗|呢)?|"
    r"换(?:一杯|一个|一款)(?:吗|呢)?|下一个)\s*[？?！!。.]*\s*$"
)
_MORE_COUNT_FOLLOWUP_RE = re.compile(
    r"(?:再|另外|更多|多)(?:给我)?(?:来|推荐|找|选)?.*"
    r"[0-9一二三四五六七八九十两]+\s*(?:个|款|杯|种)"
)
_PRIOR_RESULT_RE = re.compile(
    r"这(?:杯|个|款)|那(?:杯|个|款)|上(?:一杯|一个|一款|次)|刚才|之前|"
    r"第\s*[0-9一二三四五六七八九十两]+\s*(?:个|款|杯|种)|换(?:掉|一个|一杯|一款)"
)
_NEW_REQUEST_RE = re.compile(
    r"今天|今晚|现在|这次|此刻|心情|状态|场景|聚会|晚餐|约会|"
    r"我?想喝|想来|给我(?:推荐|找|选)|来一杯"
)
_REVISION_RE = re.compile(
    r"换|改成|改一下|调整|另一个|别的|不喜欢|不合适|太甜|太酸|太苦|太烈|"
    r"甜一点|酸一点|淡一点|烈一点|清爽一点|不要这|不要第|前\s*[一二三四五六七八九十两0-9]+\s*个"
)
_RECOMMEND_RE = re.compile(r"推荐|想喝|来一杯|适合|口味|甜|酸|苦|清爽|浓郁|奶油|果味|低度|低酒精|烈|柔和|晴朗|阳光|天气")
_COUNT_RE = re.compile(
    r"(?:推荐|再来|再给我|给我(?:多)?推荐|多推荐)\s*"
    r"([0-9一二三四五六七八九十两]+)\s*(?:个|款|杯|种)"
)
_ORDINAL_RE = re.compile(r"第\s*([0-9一二三四五六七八九十两]+)\s*(?:个|款|杯|种)")
_CN_NUMBERS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _number(text: str) -> int:
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if text.startswith("十"):
        return 10 + _CN_NUMBERS.get(text[1:], 0)
    if text.endswith("十"):
        return _CN_NUMBERS.get(text[:-1], 0) * 10
    if "十" in text:
        left, right = text.split("十", 1)
        return _CN_NUMBERS.get(left, 1) * 10 + _CN_NUMBERS.get(right, 0)
    return _CN_NUMBERS.get(text, 1)


def requested_recommendation_count(query: str) -> int:
    match = _COUNT_RE.search(query or "")
    return max(1, min(10, _number(match.group(1)))) if match else 1


def _ingredients_text(recipe: dict) -> str:
    return " ".join(str(item.get("name") or "").lower() for item in recipe.get("ingredients") or [])


def _recipe_ingredients(recipe: dict) -> set[str]:
    return {
        canonical(item.get("canonical") or item.get("name") or "")
        for item in recipe.get("ingredients") or []
        if item.get("canonical") or item.get("name")
    }


def _preference_query(query: str) -> bool:
    return bool(re.search(
        r"甜|酸|苦|清爽|浓郁|奶油|果味|低度|低酒精|烈|柔和|口味|推荐|"
        r"晴朗|阳光|艳阳|天气|夏天|炎热|落日",
        query or "",
    ))


def is_preference_query(query: str) -> bool:
    return _preference_query(query)


def extract_inventory_mentions(query: str) -> list[str]:
    """Extract explicit materials from the current turn without mutating saved inventory."""
    text = (query or "").lower()
    matches: list[tuple[int, int, str]] = []

    def add_matches(label: str, target: str, *, english: bool = False) -> None:
        if not label:
            return
        pattern = (rf"(?<![a-z]){re.escape(label)}(?![a-z])"
                   if english else re.escape(label))
        for match in re.finditer(pattern, text):
            matches.append((match.start(), match.end(), canonical(target)))

    for alias, target in INGREDIENT_ALIASES.items():
        add_matches(alias.lower(), target, english=alias.isascii())
    for english, chinese in INGREDIENTS.items():
        add_matches(english.lower(), english, english=True)
        add_matches(chinese.lower(), english)

    # A phrase such as "淡奶油" must not also become "奶油". Select the
    # longest spans first, then restore their order in the user's sentence.
    selected: list[tuple[int, int, str]] = []
    for candidate in sorted(matches, key=lambda item: (-(item[1] - item[0]), item[0])):
        start, end, _ = candidate
        if any(start < chosen_end and end > chosen_start
               for chosen_start, chosen_end, _ in selected):
            continue
        selected.append(candidate)
    found: list[str] = []
    for _, _, target in sorted(selected, key=lambda item: item[0]):
        if target not in found:
            found.append(target)
    return found


_INGREDIENT_FAMILIES = (
    frozenset({"cream", "light cream", "heavy cream", "whipping cream",
               "whipped cream", "half-and-half"}),
)


def _expand_ingredient_families(ingredients: set[str]) -> set[str]:
    expanded = set(ingredients)
    for family in _INGREDIENT_FAMILIES:
        if expanded & family:
            expanded.update(family)
    return expanded


def _inventory_preference_score(recipe: dict, query: str,
                                profile: dict | None = None) -> float:
    text = (query or "").lower()
    flavor = recipe.get("flavor") or {}
    sweet = float(flavor.get("sweet", 0))
    sour = float(flavor.get("sour", 0))
    strong = float(flavor.get("strong", 0))
    body = float(flavor.get("body", 0))
    aroma = float(flavor.get("aroma", 0))
    score = float(recipe.get("match_ratio") or 0) * 30
    score += 100 if recipe.get("available") else -8 * len(recipe.get("missing_ingredients") or [])
    if re.search(r"不太甜|不是很甜|不要太甜|别太甜|少甜|低甜|中低甜|微甜|甜.{0,5}(?:不|别|不要).{0,3}太?甜", text):
        score += 10 - abs(sweet - 4) * 2.2
    elif "甜" in text:
        score += sweet * 1.5
    if re.search(r"不太酸|不是很酸|不要太酸|别太酸|少酸|低酸|中低酸|微酸|酸.{0,5}(?:不|别|不要).{0,3}太?酸", text):
        score += 10 - abs(sour - 3) * 2.4
    elif re.search(r"不酸|不要酸|别酸", text):
        score += 10 - sour * 2.3
    elif "酸" in text:
        score += sour * 1.4
    if re.search(r"有酒味|酒感|喝得出酒|烈一点", text):
        score += strong * 1.8
    if re.search(r"清爽|清新|爽口|长饮", text):
        score += aroma * 1.2 + max(0, 6 - body)
    if re.search(r"低度|低酒精|不烈", text):
        score += max(0, 25 - float(recipe.get("abv") or 0)) * .45
    profile = profile or {}
    dimensions = {
        "sweetness": "sweet", "sourness": "sour", "bitterness": "bitter",
        "strong": "strong", "body": "body", "aroma": "aroma",
    }
    legacy_keys = {"sourness": "acidity", "strong": "strength"}
    for profile_key, flavor_key in dimensions.items():
        target = profile.get(profile_key)
        if target is None and profile_key in legacy_keys:
            target = profile.get(legacy_keys[profile_key])
        if isinstance(target, (int, float)):
            score += max(0.0, 10.0 - abs(float(flavor.get(flavor_key, 5)) - float(target))) * 1.4
    preferred = {canonical(item) for item in profile.get("preferred_spirits") or []}
    if preferred:
        ingredients = _recipe_ingredients(recipe)
        score += 14 if ingredients & preferred else 0
    style_notes = set(profile.get("style_notes") or [])
    if style_notes & {"清爽", "清新", "爽口"}:
        score += aroma * 1.2 + max(0, 6 - body)
    if style_notes & {"草本", "香草感"}:
        score += aroma * 1.3
    if style_notes & {"绵密", "奶油感", "浓郁"}:
        score += body * 1.2
    if style_notes & {"果味", "水果感"}:
        score += sweet * .6 + aroma
    return score


def _profile_ranking_preferences(profile: dict | None, query: str,
                                 required_bases: set[str]) -> dict:
    """Keep long-term memory subordinate to the user's current request."""
    ranking = dict(profile or {})
    text = query or ""
    if "甜" in text or re.search(r"sweet", text, re.I):
        ranking.pop("sweetness", None)
    if "酸" in text or re.search(r"sour", text, re.I):
        ranking.pop("sourness", None)
        ranking.pop("acidity", None)
    if re.search(r"酒感|酒味|烈|低度|低酒精|柔和|strong", text, re.I):
        ranking.pop("strong", None)
        ranking.pop("strength", None)
    if required_bases:
        ranking.pop("preferred_spirits", None)
    if re.search(r"清爽|清新|爽口|草本|香草|果味|水果|绵密|奶油|浓郁", text):
        ranking.pop("style_notes", None)
    return ranking


def build_inventory_answer(query: str, stock: list[str] | None = None,
                           count: int = 3, profile: dict | None = None,
                           exclude_recipe_ids: set[str] | None = None) -> DeterministicAnswer:
    """Evidence-only inventory recommendation used when model reasoning is unavailable."""
    merged_stock = list(dict.fromkeys(
        [canonical(item) for item in (stock or []) if item]
        + extract_inventory_mentions(query)
    ))
    if not merged_stock:
        answer = (
            "我还没有拿到任何可用材料，不能凭空推荐。请把手边的基酒、果汁、"
            "糖浆和气泡材料列出来，或先在“我的酒柜”中添加库存。"
        )
        return DeterministicAnswer(answer=answer, parts=[answer])

    matches = inventory_matches(merged_stock, limit=441)
    profile = profile or {}
    avoided = _expand_ingredient_families({
        canonical(item) for item in profile.get("disliked_ingredients") or []
    })
    excluded = {str(item) for item in (exclude_recipe_ids or set())}
    candidates = matches["ready"] + [item for item in matches["nearby"]
                                      if len(item.get("missing_ingredients") or []) <= 2]
    candidates = [item for item in candidates
                  if str(item.get("id")) not in excluded
                  and not (_recipe_ingredients(item) & avoided)]
    candidates.sort(key=lambda item: (-_inventory_preference_score(item, query, profile),
                                      item.get("name") or ""))
    chosen = candidates[:max(1, min(5, count))]
    if not chosen:
        owned = "、".join(ingredient_zh(item) for item in merged_stock)
        answer = f"我按当前材料（{owned}）检查了本地配方库，没有找到覆盖度足够的配方；先不硬凑。"
        return DeterministicAnswer(answer=answer, parts=[answer])

    cards = [recipe_card(item) for item in chosen]
    lines = []
    for index, item in enumerate(chosen, 1):
        missing = item.get("missing_ingredients") or []
        coverage = round(float(item.get("match_ratio") or 0) * 100)
        availability = "现有材料可以直接调" if not missing else (
            f"库存覆盖 {coverage}%，还缺" + "、".join(ingredient_zh(name) for name in missing)
        )
        flavor = item.get("flavor") or {}
        lines.append(
            f"{index}. {item.get('name_cn') or item.get('name')}：{availability}；"
            f"甜 {flavor.get('sweet', 0)}/10、酸 {flavor.get('sour', 0)}/10、"
            f"酒感 {flavor.get('strong', 0)}/10。"
        )
    owned = "、".join(ingredient_zh(item) for item in merged_stock)
    profile_note = ""
    if avoided:
        profile_note = "；已避开画像中的忌口：" + "、".join(ingredient_zh(item) for item in sorted(avoided))
    intro = (
        f"当前模型推理不可用；我没有假装调用 Agent，而是用本地 441 款配方按"
        f"库存覆盖和你明确的口味条件排序。识别到的材料：{owned}{profile_note}。\n\n"
    )
    guidance = "\n".join(lines) + "\n\n点开卡片可以查看经过数据校验的完整材料与分步调制。"
    evidence = [HybridRetriever._cocktail_doc(item, 1.0) for item in chosen]
    return DeterministicAnswer(
        answer=intro + guidance, recipes=cards, docs=evidence,
        doc=evidence[0] if evidence else None, parts=[intro, guidance],
    )


def _recipes_in_message(message: dict) -> list[dict]:
    metadata = message.get("metadata") if isinstance(message, dict) else None
    matches: list[dict] = []
    recipe_list = metadata.get("recipes") if isinstance(metadata, dict) else None
    for item in recipe_list if isinstance(recipe_list, list) else []:
        recipe = get_recipe(str(item.get("id") or item.get("name") or "")) if isinstance(item, dict) else None
        if recipe:
            matches.append(recipe)
    recipe_meta = metadata.get("recipe") if isinstance(metadata, dict) else None
    if isinstance(recipe_meta, dict) and recipe_meta.get("id"):
        recipe = get_recipe(str(recipe_meta["id"]))
        if recipe:
            matches.append(recipe)

    content = str(message.get("content") or "") if isinstance(message, dict) else ""
    lowered = content.lower()
    for recipe in all_recipes():
        names = [name for name in (recipe.get("name"), recipe.get("name_cn")) if name]
        if any(len(name) >= 3 and name.lower() in lowered for name in names):
            matches.append(recipe)
    return list({str(item["id"]): item for item in matches}.values())


def resolve_recipe_context(query: str, history: list[dict] | None = None) -> RecipeConversationContext:
    """Resolve elliptical follow-ups such as ``还有吗`` from persisted messages.

    The result is derived from the user's actual previous request and the recipe
    metadata stored with prior answers. It does not invent a preference or rely
    on a canned query.
    """
    current = (query or "").strip()
    recent = list(history or [])[-20:]
    count = requested_recommendation_count(current)

    ordinal = _ORDINAL_RE.search(current)
    if ordinal:
        index = _number(ordinal.group(1)) - 1
        for message in reversed(recent):
            if message.get("role") != "assistant":
                continue
            candidates = _recipes_in_message(message)
            if 0 <= index < len(candidates):
                selected = candidates[index]
                if _REVISION_RE.search(current):
                    excluded = {
                        str(recipe.get("id"))
                        for prior in recent if prior.get("role") == "assistant"
                        for recipe in _recipes_in_message(prior) if recipe.get("id")
                    }
                    inherited = _latest_preference(recent)
                    effective = "；".join(filter(None, [
                        inherited,
                        f"用户对上一轮第{index + 1}款的反馈：{current}",
                        "推荐一款不同且符合修正后口味的鸡尾酒",
                    ]))
                    return RecipeConversationContext(
                        query=effective, followup=True,
                        exclude_recipe_ids=excluded | {str(selected["id"])},
                        inherited_preference=inherited,
                        recommendation_count=count,
                    )
                return RecipeConversationContext(
                    query=f"{selected.get('name_cn') or selected['name']} {current}",
                    followup=True,
                    recommendation_count=1,
                    selected_recipe_id=str(selected["id"]),
                )

    has_prior_recipes = any(
        message.get("role") == "assistant" and _recipes_in_message(message)
        for message in recent
    )
    # Inherit history only when the user actually points at the prior result.
    # A complete new request such as "今天心情不好，想喝清爽刺激、不要太甜"
    # contains "太甜", but it is not feedback about the previous cocktail.
    revision_signal = bool(_REVISION_RE.search(current))
    explicit_prior_reference = bool(_PRIOR_RESULT_RE.search(current))
    explicit_new_request = bool(_NEW_REQUEST_RE.search(current))
    short_feedback = len(current) <= 18 and not explicit_new_request
    revision_followup = bool(
        has_prior_recipes and revision_signal
        and (explicit_prior_reference or short_feedback)
    )
    count_followup = bool(count > 1 and recent and _MORE_COUNT_FOLLOWUP_RE.search(current))
    is_followup = bool(
        _FOLLOWUP_RE.fullmatch(current) or count_followup or revision_followup
    )
    if not is_followup:
        return RecipeConversationContext(query=current, recommendation_count=count)

    excluded: set[str] = set()
    for message in recent:
        if message.get("role") != "assistant":
            continue
        excluded.update(
            str(recipe.get("id")) for recipe in _recipes_in_message(message) if recipe.get("id")
        )

    inherited = ""
    explicit_preference = bool(re.search(
        r"甜|不酸|酸|苦|清爽|浓郁|奶油|果味|低度|低酒精|烈|柔和|刺激|冲击|醒神",
        current,
    ))
    if revision_followup or not explicit_preference:
        inherited = _latest_preference(recent)

    if revision_followup:
        effective = "；".join(filter(None, [
            inherited, f"用户对上一轮的反馈：{current}",
            "推荐一款不同且符合修正后口味的鸡尾酒",
        ]))
    elif inherited:
        effective = f"{inherited}；再推荐一款不同的鸡尾酒"
    elif excluded:
        effective = "推荐一款不同但风格相近的鸡尾酒"
    else:
        effective = current
    return RecipeConversationContext(
        query=effective,
        followup=True,
        exclude_recipe_ids=excluded,
        inherited_preference=inherited,
        recommendation_count=count,
    )


def _latest_preference(history: list[dict]) -> str:
    for message in reversed(history):
        if message.get("role") != "user":
            continue
        prior = str(message.get("content") or "").strip()
        if prior and not _FOLLOWUP_RE.fullmatch(prior) and _RECOMMEND_RE.search(prior):
            return prior
    return ""


def find_named_recipe(query: str) -> dict | None:
    lowered = (query or "").lower()
    matches = []
    for recipe in all_recipes():
        names = [name for name in (recipe.get("name"), recipe.get("name_cn")) if name]
        if any(len(name) >= 3 and name.lower() in lowered for name in names):
            matches.append(recipe)
    return max(matches, key=lambda item: len(item.get("name") or ""), default=None)


def recommend_many_for_query(query: str, count: int = 1,
                             exclude_recipe_ids: set[str] | None = None,
                             profile: dict | None = None) -> list[dict]:
    """Rank the whole catalog with explicit negative preferences as hard constraints."""
    text = (query or "").lower()
    moderate_sweet = bool(re.search(
        r"不要太甜|别太甜|不太甜|不是很甜|少甜|低甜|中低甜|微甜|"
        r"甜.{0,8}(?:不|别|不要).{0,3}(?:很|太)?甜", text,
    ))
    sweet_feedback = bool(re.search(r"太甜(?:了|啦|呀)?\s*[。！!?]?$|甜过头|甜腻|腻得", text))
    wants_sweet = bool(re.search(r"甜|甜口|sweet", text)) and not moderate_sweet and not sweet_feedback
    avoid_sour = bool(re.search(r"不酸|不要酸|别酸|无酸|not sour", text))
    moderate_sour = bool(re.search(
        r"不要太酸|别太酸|不太酸|不是很酸|少酸|低酸|中低酸|微酸|"
        r"酸.{0,8}(?:不|别|不要).{0,3}(?:很|太)?酸", text,
    ))
    wants_low = bool(re.search(r"低度|低酒精|不烈|柔和", text))
    wants_strong = bool(re.search(r"高度|烈一点|酒感强|有酒味|有酒感|喝得出酒", text))
    sunny_scene = bool(re.search(r"晴朗|阳光|艳阳|天气好|夏天|炎热|落日|户外", text))
    wants_fresh = bool(re.search(r"清爽|清新|爽口", text)) or sunny_scene
    wants_punchy = bool(re.search(r"刺激|带劲|有冲击|醒神|提神|有张力", text))
    sour_feedback = bool(re.search(r"太酸(?:了|啦|呀)?\s*[。！!?]?$|酸过头|酸得", text))
    required_bases = {
        item for item in extract_inventory_mentions(text)
        if item in {"gin", "vodka", "rum", "white rum", "dark rum", "tequila",
                    "whiskey", "whisky", "bourbon", "brandy", "cognac"}
    }
    avoided: set[str] = {
        canonical(item) for item in (profile or {}).get("disliked_ingredients") or []
    }
    for fragment in re.findall(r"(?:不要|不用|别用|不含|不能用)([^，、。；！？!?,]{1,28})", text):
        avoided.update(extract_inventory_mentions(fragment))
    avoided = _expand_ingredient_families(avoided)
    ranking_profile = _profile_ranking_preferences(profile, text, required_bases)

    excluded = {str(item) for item in (exclude_recipe_ids or set())}
    ranked: list[tuple[float, dict]] = []
    for recipe in all_recipes():
        if str(recipe.get("id")) in excluded:
            continue
        flavor = recipe.get("flavor") or {}
        ingredients = _ingredients_text(recipe)
        canonical_ingredients = _recipe_ingredients(recipe)
        if required_bases and not required_bases & canonical_ingredients:
            continue
        if avoided & canonical_ingredients:
            continue
        if wants_sweet and float(flavor.get("sweet", 0)) < 5:
            if not moderate_sweet:
                continue
        if moderate_sweet and not 3 <= float(flavor.get("sweet", 0)) <= 5:
            continue
        if sweet_feedback and float(flavor.get("sweet", 0)) > 4:
            continue
        if avoid_sour and any(marker in ingredients for marker in _SOUR_INGREDIENTS):
            continue
        if moderate_sour and not 2 <= float(flavor.get("sour", 0)) <= 4:
            continue
        if sour_feedback and float(flavor.get("sour", 0)) > 4:
            continue
        if wants_low and float(recipe.get("abv") or 0) > 22:
            continue
        if wants_strong and float(flavor.get("strong", 0)) < 4:
            continue
        score = 0.0
        if moderate_sweet:
            score += 10.0 - abs(float(flavor.get("sweet", 0)) - 4.0) * 2.2
        elif wants_sweet:
            score += float(flavor.get("sweet", 0)) * 1.5
            score += 2.0 if any(marker in ingredients for marker in _SWEET_INGREDIENTS) else 0.0
        if avoid_sour:
            score += max(0.0, 6.0 - float(flavor.get("sour", 0)))
        elif moderate_sour or sour_feedback:
            score += 9.0 - abs(float(flavor.get("sour", 0)) - 3.0) * 2.0
        if wants_low:
            score += max(0.0, 24.0 - float(recipe.get("abv") or 0)) / 4
        if wants_strong:
            score += float(flavor.get("strong", 0))
        if wants_fresh:
            score += float(flavor.get("aroma", 0)) + (2.0 if float(flavor.get("body", 0)) <= 5 else 0.0)
        if sunny_scene:
            sparkling = any(marker in ingredients for marker in (
                "tonic", "soda", "sparkling", "champagne", "ginger ale",
            ))
            score += 3.0 if sparkling else 0.0
            score += max(0.0, 6.0 - float(flavor.get("body", 0))) * .45
            score -= max(0.0, float(flavor.get("sweet", 0)) - 5.0) * .4
        if wants_punchy:
            # "刺激" is a sensory direction, not permission to maximize ABV.
            # Favor aromatic, crisp and clearly structured drinks, then let the
            # flavor Agent make the final contextual choice from this shortlist.
            score += (float(flavor.get("aroma", 0)) * .9
                      + float(flavor.get("strong", 0)) * .8
                      + float(flavor.get("sour", 0)) * .35)
        score += _inventory_preference_score(recipe, "", ranking_profile)
        score += _POPULAR.get(recipe.get("name") or "", 0.0) * .35
        score += 1.0 if recipe.get("name") in RECIPE_NAMES else 0.0
        score += 0.5 if recipe.get("category") != "Shot" else -1.0
        ranked.append((score, recipe))
    ranked.sort(key=lambda item: (-item[0], item[1].get("name") or ""))
    return [item[1] for item in ranked[:max(1, min(10, count))]]


def recommend_for_query(query: str, exclude_recipe_ids: set[str] | None = None,
                        profile: dict | None = None) -> dict | None:
    recipes = recommend_many_for_query(query, 1, exclude_recipe_ids, profile=profile)
    return recipes[0] if recipes else None


def _amount_text(amount: str) -> str:
    amount = (amount or "").strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*oz", amount, re.I)
    if match:
        return f"{amount}（约 {round(float(match.group(1)) * 30):g} ml）"
    return amount or "适量（原配方未注明）"


def _method(recipe: dict) -> str:
    if recipe.get("method"):
        return str(recipe["method"])
    instructions = f"{recipe.get('instructions') or ''} {recipe.get('instructions_en') or ''}".lower()
    if "shake" in instructions or "摇" in instructions:
        return "摇和 Shake"
    if "stir" in instructions or "搅拌" in instructions:
        return "搅拌 Stir"
    if "blend" in instructions or "搅打" in instructions:
        return "搅打 Blend"
    return "杯中直调 Build"


def _steps(recipe: dict) -> list[str]:
    if recipe.get("steps"):
        return list(recipe["steps"])
    ingredients = recipe.get("ingredients") or []
    measured = "；".join(
        f"{item.get('name_zh') or ingredient_zh(item.get('name') or '')} {_amount_text(item.get('amount') or '')}"
        for item in ingredients
    )
    glass = recipe.get("glass") or "合适杯具"
    source = (recipe.get("instructions") or recipe.get("instructions_en") or "").strip()
    source_steps = [part.strip() for part in re.split(r"[。！？.!?]+", source) if part.strip()]
    steps = [
        f"准备 {glass}、量酒器和所需调制工具；先把杯具清洁并冰镇。",
        f"逐项量取材料：{measured}。",
    ]
    steps.extend(source_steps or ["按配方顺序混合所有材料。"])
    steps.append(f"按 {_method(recipe)} 完成调制，装入 {glass}；原资料未注明的装饰不要随意添加。")
    return list(dict.fromkeys(steps))


def recipe_card(recipe: dict) -> dict:
    return {
        "id": recipe.get("id"), "name": recipe.get("name"), "name_cn": recipe.get("name_cn"),
        "ingredients": [
            {"name": item.get("name_zh") or ingredient_zh(item.get("name") or ""),
             "name_en": item.get("name"), "amount": _amount_text(item.get("amount") or "")}
            for item in recipe.get("ingredients") or []
        ],
        "steps": _steps(recipe), "method": _method(recipe), "glass": recipe.get("glass") or "",
        "garnish": "原配方未注明", "flavor": recipe.get("flavor") or {},
        "abv": recipe.get("abv"), "is_alcoholic": bool(recipe.get("alcoholic")),
        "tips": "首次制作先按原比例，试饮后再小幅调整甜度；饮酒请适量。",
        "source": recipe.get("source"), "version": recipe.get("version", 1),
        "image": recipe.get("image") or "",
    }


def _find_exact_recipe(query: str, docs: list[RetrievedDoc]) -> dict | None:
    named = find_named_recipe(query)
    if named:
        return named
    lowered = (query or "").lower()
    for doc in docs:
        if doc.collection != "cocktails":
            continue
        recipe = get_recipe(doc.pk)
        if recipe and any(name and name.lower() in lowered for name in (recipe.get("name"), recipe.get("name_cn"))):
            return recipe
    return None


def should_answer_with_recipe(query: str, docs: list[RetrievedDoc],
                              history: list[dict] | None = None) -> bool:
    context = resolve_recipe_context(query, history)
    return bool(context.selected_recipe_id or _find_exact_recipe(query, docs) or _preference_query(context.query)
                or re.search(r"配方|做法|怎么调|如何调|调制步骤", query or ""))


def build_deterministic_answer(query: str, docs: list[RetrievedDoc],
                               history: list[dict] | None = None,
                               profile: dict | None = None) -> DeterministicAnswer:
    context = resolve_recipe_context(query, history)
    exact = get_recipe(context.selected_recipe_id) if context.selected_recipe_id else None
    if exact is None and not context.followup:
        exact = _find_exact_recipe(query, docs)
    recipes = [exact] if exact else []
    if not recipes and _preference_query(context.query):
        recipes = recommend_many_for_query(
            context.query, context.recommendation_count, context.exclude_recipe_ids,
            profile=profile,
        )
    if not recipes:
        first = next((doc for doc in docs if doc.collection == "cocktails"), None)
        recipe = get_recipe(first.pk) if first else None
        recipes = [recipe] if recipe else []

    if len(recipes) > 1:
        cards = [recipe_card(item) for item in recipes]
        if context.inherited_preference:
            intro = f"我记得刚才那条口味线。这次没有拿同一杯换个说法，而是另外挑了 {len(cards)} 款。"
        else:
            intro = f"我认真比了一轮，留下了 {len(cards)} 款方向不同、但都贴近这次口味的酒。"
        guidance = "我把更贴合的放在前面了。你不用重新描述需求，直接说哪一杯最有感觉，或者问我“第二杯怎么调”。"
        parts = [intro + "\n", guidance]
        evidence = [HybridRetriever._cocktail_doc(item, 1.0) for item in recipes]
        return DeterministicAnswer(
            answer="".join(parts), recipes=cards, docs=evidence,
            doc=evidence[0] if evidence else None, parts=parts,
        )

    recipe = recipes[0] if recipes else None
    if recipe:
        card = recipe_card(recipe)
        ingredients = "\n".join(f"- {item['name']}：{item['amount']}" for item in card["ingredients"])
        steps = "\n".join(f"{index}. {step}" for index, step in enumerate(card["steps"], 1))
        preference = ""
        if re.search(r"不酸|不要酸|别酸|无酸", context.query):
            preference = "这杯不含柠檬、青柠或酸甜汁，和你“不酸”的要求更一致。"
        prior = next((get_recipe(doc.pk) for doc in docs if doc.collection == "cocktails"), None)
        correction = ""
        if prior and prior.get("id") != recipe.get("id") and "sweet and sour" in _ingredients_text(prior):
            correction = f"我没有继续选 {prior.get('name_cn') or prior.get('name')}，因为它含酸甜汁，和“不酸”冲突。\n\n"
        if context.followup and context.inherited_preference:
            intro = "我记得刚才的取向。这次不重复上一杯，我会换成"
        elif context.followup:
            intro = "有，而且这次换个方向。我会选"
        else:
            intro = "这轮我会选"
        answer = (
            f"{intro} {recipe.get('name_cn') or recipe.get('name')}"
            f"（{recipe.get('name')}）。{preference}\n\n{correction}"
            "我把可靠的材料和动作都整理在下面；你边调边看就行，少了哪样直接告诉我，我再一起换。\n\n"
            f"材料（1 杯）\n{ingredients}\n\n"
            f"杯具：{card['glass']}\n方法：{card['method']}\n"
            f"预计酒精度：约 {recipe.get('abv') or 0}% ABV\n\n"
            f"分步调制\n{steps}\n\n"
            f"风味：甜 {card['flavor'].get('sweet', 0)}/10，酸 {card['flavor'].get('sour', 0)}/10，"
            f"酒感 {card['flavor'].get('strong', 0)}/10。"
        )
        doc = HybridRetriever._cocktail_doc(recipe, 1.0)
        sections = answer.split("\n\n")
        parts = [section + ("\n\n" if index < len(sections) - 1 else "")
                 for index, section in enumerate(sections)]
        return DeterministicAnswer(answer=answer, recipe=card, doc=doc,
                                   recipes=[card], docs=[doc], parts=parts)

    knowledge = [doc for doc in docs if doc.collection == "knowledge"]
    if knowledge:
        lines = [f"- {doc.title}：{(doc.content_cn or doc.content).strip()}" for doc in knowledge[:3]]
        answer = "根据现有知识卡，可以确认：\n" + "\n".join(lines)
        return DeterministicAnswer(answer=answer, doc=knowledge[0], docs=knowledge[:3], parts=[answer])
    return DeterministicAnswer(answer="我暂时没有找到足够可靠的资料，先不编造答案。")
