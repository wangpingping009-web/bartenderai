# -*- coding: utf-8 -*-
"""One server-authored constraint handoff shared by every specialist Agent."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field


class MixologyConstraints(BaseModel):
    source_query: str
    effective_query: str
    contextual_followup: bool = False
    target_count: int = 1
    inventory: list[str] = Field(default_factory=list)
    mentioned_ingredients: list[str] = Field(default_factory=list)
    required_base_spirits: list[str] = Field(default_factory=list)
    excluded_ingredients: list[str] = Field(default_factory=list)
    excluded_recipe_ids: list[str] = Field(default_factory=list)
    hard_flavor_ranges: dict[str, list[float | None]] = Field(default_factory=dict)
    preference_targets: dict[str, float] = Field(default_factory=dict)
    style_preferences: list[str] = Field(default_factory=list)

    def prompt_block(self) -> str:
        parts = [f"连续需求：{self.effective_query}"]
        if self.inventory:
            parts.append("真实库存：" + "、".join(self.inventory))
        if self.required_base_spirits:
            parts.append("指定基酒：" + "、".join(self.required_base_spirits))
        if self.excluded_ingredients:
            parts.append("必须避开：" + "、".join(self.excluded_ingredients))
        if self.hard_flavor_ranges:
            ranges = "、".join(
                f"{name} {bounds[0] if bounds[0] is not None else '*'}–"
                f"{bounds[1] if bounds[1] is not None else '*'} /10"
                for name, bounds in self.hard_flavor_ranges.items()
            )
            parts.append("本轮硬风味范围：" + ranges)
        if self.preference_targets:
            parts.append("长期偏好目标：" + "、".join(
                f"{name} {value}/10" for name, value in self.preference_targets.items()
            ))
        if self.style_preferences:
            parts.append("风格方向：" + "、".join(self.style_preferences))
        if self.excluded_recipe_ids:
            parts.append("本会话禁止重复的配方 ID：" + "、".join(self.excluded_recipe_ids))
        parts.append(f"本轮数量：{self.target_count}")
        return "\n".join(parts)


_BASE_SPIRITS = {
    "gin", "vodka", "rum", "white rum", "dark rum", "tequila",
    "whiskey", "whisky", "bourbon", "brandy", "cognac",
}


def build_mixology_constraints(query: str, history: list[dict] | None = None,
                                stock: list[str] | None = None,
                                profile: dict | None = None) -> MixologyConstraints:
    """Normalize one conversation turn without asking each Agent to reinterpret it."""
    from app.rag.hybrid import analyze_query
    from app.services.deterministic_chat import (
        extract_inventory_mentions, resolve_recipe_context,
    )
    from app.services.recipe_catalog import canonical

    context = resolve_recipe_context(query, history)
    analyzed = analyze_query(context.query)
    filters = analyzed.filters
    profile = profile or {}
    inventory = list(dict.fromkeys(canonical(item) for item in (stock or []) if item))
    mentions = extract_inventory_mentions(context.query)
    excluded = list(dict.fromkeys([
        *filters.excluded_ingredients,
        *(canonical(item) for item in profile.get("disliked_ingredients") or []),
    ]))

    ranges: dict[str, list[float | None]] = {}
    if filters.min_sweet is not None or filters.max_sweet is not None:
        ranges["甜度"] = [filters.min_sweet, filters.max_sweet]
    if filters.min_sour is not None or filters.max_sour is not None:
        ranges["酸度"] = [filters.min_sour, filters.max_sour]
    if filters.min_strong is not None:
        ranges["酒感"] = [filters.min_strong, None]
    if filters.max_abv is not None:
        ranges["酒精度"] = [None, filters.max_abv]

    # Direct feedback overrides inherited ranges for this turn.
    current = query or ""
    if re.search(r"太甜(?:了|啦|呀)?\s*[。！!?]?$|甜过头|甜腻|腻得", current):
        ranges["甜度"] = [0.0, 3.0]
    elif re.search(r"不要太甜|别太甜|不太甜|不是很甜|少甜|低甜", current):
        ranges["甜度"] = [0.0, 4.0]
    elif re.search(r"再甜一点|更甜|甜一点", current):
        ranges["甜度"] = [5.0, None]
    if re.search(r"太酸|酸过头", current):
        ranges["酸度"] = [0.0, 3.0]
    elif re.search(r"再酸一点|更酸|酸一点", current):
        ranges["酸度"] = [4.0, None]
    if re.search(r"太烈|酒味太重|酒精感太强", current):
        ranges["酒感"] = [0.0, 3.0]
    elif re.search(r"太淡|没酒味|酒感不足", current):
        ranges["酒感"] = [6.0, None]

    targets = {}
    for source, target in (("sweetness", "甜度"), ("sourness", "酸度"),
                           ("strong", "酒感")):
        value = profile.get(source)
        if isinstance(value, (int, float)):
            targets[target] = float(value)

    styles = list(profile.get("style_notes") or [])
    for pattern, label in ((r"清爽|清新|爽口|晴天|晴朗|阳光|艳阳|天气好|夏天|炎热", "清爽"), (r"草本|香草感", "草本"),
                           (r"果味|水果感", "果味"), (r"绵密|奶油感", "绵密"),
                           (r"刺激|带劲|有冲击|醒神|提神|有张力", "有冲击感")):
        if re.search(pattern, context.query) and label not in styles:
            styles.append(label)

    required_bases = [item for item in filters.required_any_ingredients if item in _BASE_SPIRITS]
    if not required_bases:
        required_bases = [item for item in mentions if item in _BASE_SPIRITS]
    return MixologyConstraints(
        source_query=query,
        effective_query=context.query,
        contextual_followup=context.followup,
        target_count=context.recommendation_count,
        inventory=inventory,
        mentioned_ingredients=mentions,
        required_base_spirits=list(dict.fromkeys(required_bases)),
        excluded_ingredients=excluded,
        excluded_recipe_ids=sorted(context.exclude_recipe_ids),
        hard_flavor_ranges=ranges,
        preference_targets=targets,
        style_preferences=styles,
    )


def constraint_prompt_block(value: dict | MixologyConstraints | None) -> str:
    if not value:
        return "（无额外共享约束）"
    handoff = value if isinstance(value, MixologyConstraints) \
        else MixologyConstraints.model_validate(value)
    return handoff.prompt_block()
