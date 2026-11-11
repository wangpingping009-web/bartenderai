# -*- coding: utf-8 -*-
"""Collaborative recipe creation grounded in catalog evidence and bar rules."""
from __future__ import annotations

import json
from collections.abc import Callable

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.core.llm import get_creative_llm, get_llm
from app.core.registry import get_prompt
from app.services.mixology import ValidationIssue, validate_recipe
from app.services.recipe_card import RecipeCard
from app.services.recipe_catalog import all_recipes, canonical, ingredient_zh


PERSONAS: dict[str, dict] = {
    "classic": {"name": "经典平衡", "emoji": "C", "prompt": "你是一位恪守经典结构的调酒师。比例清晰、材料常见、技法传统，不为猎奇牺牲平衡。"},
    "molecular": {"name": "现代实验", "emoji": "M", "prompt": "你是一位现代调酒师。可以使用澄清、泡沫和烟熏，但必须说明可在家庭或普通吧台执行的方法。"},
    "japanese": {"name": "日式精细", "emoji": "J", "prompt": "你是一位日式吧台调酒师。用量精确到 5ml，明确冰、时间、稀释和出品细节。"},
    "playful": {"name": "轻松创意", "emoji": "P", "prompt": "你是一位有趣但克制的创意调酒师。名称和风味可以活泼，配方结构必须成立且容易执行。"},
}


class CreativeReview(BaseModel):
    approved: bool = Field(description="是否满足需求并能真实执行")
    intent_match: str = Field(description="配方如何对应用户的口味和场景")
    feasibility: str = Field(description="材料、比例与技法的可执行性")
    issues: list[str] = Field(default_factory=list)
    revision_instruction: str = Field(default="")
    review_mode: str = Field(default="model")


class CreativeBrief(BaseModel):
    summary: str
    scene: str = ""
    must_have: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    flavor_targets: dict[str, int] = Field(default_factory=dict)
    constraints: list[str] = Field(default_factory=list)
    available_ingredients: list[str] = Field(default_factory=list)
    inventory_complete: bool = False


_recipe_parser = PydanticOutputParser(pydantic_object=RecipeCard)
_review_parser = PydanticOutputParser(pydantic_object=CreativeReview)
_CREATE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", get_prompt("recipe_gen")["system"] + "\n\n本次创作角色：{persona_prompt}\n所有材料必须给出明确用量，steps 至少 4 步并写明冰块、时间、过滤和杯具。description 用一句自然中文说明入口风味。"),
    ("human", "创作需求：{preferences}\n指定基酒：{base_spirits}\n\n需求分析师交接单：\n{creative_brief}\n\n可借鉴结构但不可照抄：\n{references}\n\n{feedback}\n\n{format_instructions}"),
])
_REVIEW_PROMPT = ChatPromptTemplate.from_messages([
    ("system", "你是独立的资深吧台审校。你不参与创作，只核对候选配方是否忠实满足用户需求、比例合理、材料可得、技法可执行。发现问题必须给出可操作的定向修订要求。"),
    ("human", "用户需求：{preferences}\n指定基酒：{base_spirits}\n\n需求分析师交接单：\n{creative_brief}\n\n候选配方：\n{recipe}\n\n规则检查：\n{validation}\n\n{format_instructions}"),
])
GEN_MAX_RETRY = 2

_BASE_LABELS = {
    "gin": ("金酒", "Juniper"), "vodka": ("伏特加", "Silver"),
    "rum": ("朗姆", "Cane"), "white rum": ("白朗姆", "Cane"),
    "dark rum": ("黑朗姆", "Cane"), "tequila": ("龙舌兰", "Agave"),
    "whiskey": ("威士忌", "Oak"), "whisky": ("威士忌", "Oak"),
    "brandy": ("白兰地", "Orchard"), "cognac": ("干邑", "Orchard"),
}
_SCENE_EN = {"夏夜": "Summer Night", "晚宴": "Supper", "约会": "Rendezvous",
             "派对": "Party", "餐前": "Aperitif", "餐后": "After Dinner",
             "独饮": "Quiet Hour", "慢饮": "Slow Hour", "夜色": "Nightfall"}


def _local_rule_card(preferences: str, base_spirits: list[str] | None,
                     brief: CreativeBrief, references: list[dict]) -> RecipeCard:
    """Build a conservative, executable draft without impersonating an LLM."""
    requested = [canonical(item) for item in (base_spirits or []) if item]
    base = requested[0] if requested else ""
    if not base and references:
        for item in references[0].get("ingredients") or []:
            candidate = canonical(item.get("name") or "")
            if candidate in _BASE_LABELS:
                base = candidate
                break
    base = base if base in _BASE_LABELS else "gin"
    base_zh, base_en = _BASE_LABELS[base]
    targets = brief.flavor_targets
    low_strength = targets.get("strong", 5) <= 3
    base_ml = 30 if low_strength else 45
    text = (preferences or "").lower()
    try:
        from app.services.deterministic_chat import extract_inventory_mentions
        owned = set(extract_inventory_mentions(preferences))
    except Exception:
        owned = set()
    owned.update(canonical(item) for item in brief.available_ingredients if item)
    owned.update(requested)
    avoided_materials = {canonical(item) for item in brief.avoid if item != "明显酸味"}
    owned.difference_update(avoided_materials)

    def prefer(candidates: tuple[str, ...], fallback: str) -> str:
        match = next((item for item in candidates if canonical(item) in owned), "")
        return match or ("" if brief.inventory_complete else fallback)

    ingredients = [{"name": base_zh, "amount": f"{base_ml}ml"}]
    has_citrus = any(word in text for word in ("柑橘", "柠檬", "青柠", "citrus"))
    wants_sour = targets.get("sour", 4) >= 6
    avoid_sour = targets.get("sour", 4) <= 3 or "明显酸味" in brief.avoid
    wants_sweet = targets.get("sweet", 4) >= 6
    wants_aroma = targets.get("aroma", 4) >= 7 or any(word in text for word in ("草本", "花香", "香气"))

    if wants_sour:
        acid = prefer(("lime juice", "lemon juice"), "lime juice")
        sweetener = prefer(("honey syrup", "simple syrup", "sugar syrup", "grenadine"), "honey syrup")
        if acid:
            ingredients.append({"name": ingredient_zh(acid), "amount": "20ml"})
        if sweetener:
            ingredients.append({"name": ingredient_zh(sweetener), "amount": "10ml"})
        method = "摇和" if acid or sweetener else "杯中直调"
    elif has_citrus and avoid_sour:
        acid = prefer(("lime juice", "lemon juice"), "lime juice")
        sweetener = prefer(("honey syrup", "simple syrup", "sugar syrup", "grenadine"), "honey syrup")
        if acid:
            ingredients.append({"name": ingredient_zh(acid), "amount": "5ml"})
        if sweetener:
            ingredients.append({"name": ingredient_zh(sweetener), "amount": "5ml"})
        method = "摇和" if acid or sweetener else "杯中直调"
    elif wants_sweet:
        sweetener = prefer(("honey syrup", "simple syrup", "sugar syrup", "grenadine"), "honey syrup")
        if sweetener:
            ingredients.append({"name": ingredient_zh(sweetener), "amount": "10ml"})
        method = "摇和" if sweetener else "杯中直调"
    else:
        modifier = prefer(("dry vermouth", "sweet vermouth", "campari"), "dry vermouth")
        if modifier:
            ingredients.append({"name": ingredient_zh(modifier), "amount": "15ml"})
        method = "杯中直调"

    default_mixer = "tonic water" if wants_aroma and base == "gin" else "soda water"
    mixer_key = prefer(("tonic water", "soda water", "ginger beer", "cola"), default_mixer)
    mixer = ingredient_zh(mixer_key) if mixer_key else ""
    if mixer:
        ingredients.append({"name": mixer, "amount": "90ml" if low_strength else "60ml"})
    if brief.inventory_complete and len(ingredients) < 2:
        raise ValueError("确认的库存不足以组成一杯可执行鸡尾酒，请先补充至少一种调和材料")

    scene = brief.scene.split("、", 1)[0] if brief.scene else "夜色"
    scene_en = _SCENE_EN.get(scene, "Nightfall")
    if wants_aroma:
        motif_zh, motif_en = "草本微光", "Herbal Glow"
    elif wants_sour:
        motif_zh, motif_en = "柑橘锋芒", "Citrus Edge"
    elif wants_sweet:
        motif_zh, motif_en = "蜜色余温", "Honey Afterglow"
    else:
        motif_zh, motif_en = "清风", "Breeze"
    name_cn = f"{scene}{motif_zh}"
    name = f"{scene_en} {base_en} {motif_en}"

    measured = "、".join(f"{item['name']} {item['amount']}" for item in ingredients)
    if method == "摇和":
        steps = [
            "冰镇高球杯，并准备雪克壶、量酒器、滤冰器和足量新鲜冰块。",
            f"逐项量取本杯材料：{measured}；气泡材料暂时保留。",
            "把除气泡材料外的材料与冰块加入雪克壶，用力摇和约 12 秒。",
            "过滤到装有新鲜冰块的高球杯，再沿杯壁补入气泡材料。",
            "用吧匙从杯底轻提一次使其均匀，检查温度后立即饮用。",
        ]
    else:
        combined = "和".join(item["name"] for item in ingredients)
        steps = [
            "冰镇高球杯，并准备量酒器、吧匙和足量新鲜冰块。",
            f"逐项量取本杯材料：{measured}。",
            f"在高球杯中加入大块冰，倒入{combined}，轻柔搅拌约 10 秒。",
            (f"沿杯壁补入{mixer}，避免快速倾倒损失气泡。" if mixer
             else "继续搅拌至杯壁充分冰凉，检查稀释度。"),
            "用吧匙从杯底轻提一次，检查香气、温度和液面后立即饮用。",
        ]

    flavor = {
        "sweet": targets.get("sweet", 7 if wants_sweet else 3),
        "sour": targets.get("sour", 2 if avoid_sour else (7 if wants_sour else 3)),
        "bitter": 4 if mixer == "汤力水" else 2,
        "strong": targets.get("strong", 3 if low_strength else 6),
        "body": targets.get("body", 3 if "清爽" in text else 4),
        "aroma": targets.get("aroma", 8 if wants_aroma else 5),
    }
    return RecipeCard(
        name=name, name_cn=name_cn,
        description=f"以{base_zh}为骨架，{motif_zh}展开；甜酸和酒感按你的条件收紧。",
        spirit_base=base_zh, ingredients=ingredients, steps=steps, glass="高球杯",
        garnish="一小片柑橘皮（可选，不挤汁）" if wants_aroma or has_citrus else "不额外装饰",
        flavor=flavor, alcohol_units=round(base_ml * 0.4 * 0.789 / 10, 1),
        is_alcoholic=True,
        tips="这是本地规则创作稿，比例与技法已校验；首次制作后可按实际试饮每次微调 5ml。",
    )


def _analyze_brief(preferences: str, base_spirits: list[str] | None) -> CreativeBrief:
    text = " ".join((preferences or "").split())
    lowered = text.lower()
    targets: dict[str, int] = {}
    avoid: list[str] = []
    constraints: list[str] = []
    scenes = [name for name in ("夏夜", "晚宴", "约会", "派对", "餐前", "餐后", "独饮", "慢饮") if name in text]

    if any(word in lowered for word in ("低甜", "少甜", "不甜", "dry")):
        targets["sweet"] = 3
        constraints.append("控制甜味材料比例")
    elif any(word in lowered for word in ("甜", "甜口", "dessert")):
        targets["sweet"] = 7
    if any(word in lowered for word in ("不酸", "少酸", "低酸", "不要太酸")):
        targets["sour"] = 2
        avoid.append("明显酸味")
    elif any(word in lowered for word in ("酸", "sour")):
        targets["sour"] = 7
    if any(word in lowered for word in ("低度", "低酒精", "不烈", "柔和")):
        targets["strong"] = 3
        constraints.append("降低总体酒精强度")
    elif any(word in lowered for word in ("烈", "酒感强", "高度")):
        targets["strong"] = 8
    if any(word in lowered for word in ("草本", "花香", "香气", "herbal")):
        targets["aroma"] = 8
    if any(word in lowered for word in ("清爽", "轻盈", "fresh")):
        targets["body"] = 3

    must_have = [canonical(item) for item in (base_spirits or []) if item]
    if must_have:
        constraints.append("必须使用指定基酒")
    summary = text[:140] or "自由创作一杯结构平衡、可实际调制的鸡尾酒"
    return CreativeBrief(summary=summary, scene="、".join(scenes), must_have=must_have,
                          avoid=avoid, flavor_targets=targets,
                          constraints=list(dict.fromkeys(constraints)))


def _merge_dialogue_brief(preferences: str, base_spirits: list[str] | None,
                          raw: dict | None) -> CreativeBrief:
    """Translate the persisted dialogue contract without reparsing assistant prose."""
    brief = _analyze_brief(preferences, base_spirits)
    raw = raw or {}
    targets = dict(brief.flavor_targets)
    for source, dimension, low, high in (
        (raw.get("sweetness"), "sweet", 3, 7),
        (raw.get("acidity"), "sour", 3, 7),
        (raw.get("alcohol"), "strong", 3, 7),
    ):
        text = str(source or "")
        if not text:
            continue
        targets[dimension] = low if any(word in text for word in ("低", "少", "避免", "柔和")) else high
    available = list(dict.fromkeys(
        canonical(item) for item in raw.get("available_ingredients") or [] if item
    ))
    avoid = list(dict.fromkeys([
        *brief.avoid,
        *(canonical(item) for item in raw.get("avoid_ingredients") or [] if item),
    ]))
    must_have = list(dict.fromkeys([
        *brief.must_have,
        *(canonical(item) for item in raw.get("base_spirits") or [] if item),
    ]))
    constraints = list(brief.constraints)
    if raw.get("inventory_complete"):
        constraints.append("只能使用用户确认库存中的材料")
    if raw.get("serve_style"):
        constraints.append(f"饮用形态：{raw['serve_style']}")
    scene = str(raw.get("occasion") or brief.scene or "")
    summary_parts = [brief.summary]
    if available:
        summary_parts.append("可用材料：" + "、".join(ingredient_zh(item) for item in available))
    if avoid:
        ingredient_avoid = [item for item in avoid if item != "明显酸味"]
        if ingredient_avoid:
            summary_parts.append("禁用材料：" + "、".join(ingredient_zh(item) for item in ingredient_avoid))
    return CreativeBrief(
        summary="；".join(summary_parts), scene=scene, must_have=must_have,
        avoid=avoid, flavor_targets=targets,
        constraints=list(dict.fromkeys(constraints)),
        available_ingredients=available,
        inventory_complete=bool(raw.get("inventory_complete")),
    )


def _reference_recipes(preferences: str, base_spirits: list[str] | None,
                       brief: CreativeBrief | None = None) -> list[dict]:
    text = (preferences or "").lower()
    requested = [canonical(item) for item in (base_spirits or []) if item]
    hints = {
        "sweet": ("甜", "sweet", "奶油", "dessert"),
        "sour": ("酸", "sour", "柑橘", "citrus"),
        "aroma": ("草本", "香", "herbal", "aroma", "清爽"),
        "strong": ("烈", "酒感", "strong"),
    }
    ranked: list[tuple[float, dict]] = []
    for recipe in all_recipes():
        names = [item.get("canonical") or canonical(item.get("name") or "") for item in recipe.get("ingredients") or []]
        if requested and not any(any(base == name or base in name for name in names) for base in requested):
            continue
        score = 0.0
        for dimension, words in hints.items():
            if any(word in text for word in words):
                score += float(recipe.get("flavor", {}).get(dimension, 0))
        for dimension, target in (brief.flavor_targets if brief else {}).items():
            score += max(0.0, 10.0 - abs(float(recipe.get("flavor", {}).get(dimension, 5)) - target))
        if brief and "明显酸味" in brief.avoid and float(recipe.get("flavor", {}).get("sour", 0)) > 4:
            continue
        ranked.append((score, recipe))
    ranked.sort(key=lambda item: (-item[0], item[1].get("name") or ""))
    return [item[1] for item in ranked[:3]]


def _reference_text(recipes: list[dict]) -> str:
    if not recipes:
        return "没有合适的目录参考，请使用可靠的经典调酒结构自行推导。"
    lines = []
    for recipe in recipes:
        ingredients = ", ".join(
            f"{item.get('name_zh') or item.get('name')} {item.get('amount') or ''}".strip()
            for item in recipe.get("ingredients") or []
        )
        lines.append(f"- {recipe.get('name_cn') or recipe['name']}（{recipe['name']}）：{ingredients}；{recipe.get('method')}")
    return "\n".join(lines)


def _requested_base_issue(card: dict, base_spirits: list[str] | None) -> ValidationIssue | None:
    requested = [canonical(item) for item in (base_spirits or []) if item]
    if not requested:
        return None
    names = [canonical(item.get("name") or "") for item in card.get("ingredients") or []]
    if any(any(base == name or base in name for name in names) for base in requested):
        return None
    return ValidationIssue("error", "requested_base", "配方没有使用用户指定的基酒")


def _brief_alignment_issues(card: dict, brief: CreativeBrief) -> list[ValidationIssue]:
    flavor = card.get("flavor") or {}
    labels = {"sweet": "甜度", "sour": "酸度", "strong": "酒感", "body": "酒体", "aroma": "香气"}
    issues: list[ValidationIssue] = []
    for dimension, target in brief.flavor_targets.items():
        if dimension not in flavor:
            continue
        actual = int(flavor.get(dimension) or 0)
        if abs(actual - target) > 2:
            issues.append(ValidationIssue(
                "error", f"brief_{dimension}",
                f"{labels.get(dimension, dimension)}为 {actual}/10，与需求目标 {target}/10 偏差过大",
            ))
    return issues


def _brief_inventory_issues(card: dict, brief: CreativeBrief) -> list[ValidationIssue]:
    if not brief.inventory_complete or not brief.available_ingredients:
        return []
    allowed = {canonical(item) for item in [*brief.available_ingredients, *brief.must_have]}
    used = {
        canonical(item.get("name") or "")
        for item in card.get("ingredients") or [] if item.get("name")
    }
    forbidden = used - allowed
    if not forbidden:
        return []
    return [ValidationIssue(
        "error", "brief_inventory",
        "配方使用了确认库存之外的材料：" + "、".join(ingredient_zh(item) for item in sorted(forbidden)),
    )]


def _review(preferences: str, base_spirits: list[str] | None,
            card: dict, validation: dict, brief: CreativeBrief) -> CreativeReview:
    try:
        chain = _REVIEW_PROMPT | get_llm(temperature=0, max_tokens=500) | _review_parser
        return chain.invoke({
            "preferences": preferences,
            "base_spirits": ", ".join(base_spirits or []) or "未指定",
            "creative_brief": json.dumps(brief.model_dump(), ensure_ascii=False),
            "recipe": json.dumps(card, ensure_ascii=False),
            "validation": json.dumps(validation, ensure_ascii=False),
            "format_instructions": _review_parser.get_format_instructions(),
        })
    except Exception:
        return CreativeReview(
            approved=bool(validation.get("ok")),
            intent_match="配方已按你的口味条件完成结构化创作。",
            feasibility="独立模型审校暂时不可用，本次仅确认本地比例与技法规则通过。",
            review_mode="rules",
        )


def generate_recipe(preferences: str, persona: str = "classic",
                    base_spirits: list[str] | None = None,
                    on_event: Callable[[dict], None] | None = None,
                    creative_brief: dict | None = None) -> dict:
    persona_key = persona if persona in PERSONAS else "classic"
    persona_info = PERSONAS[persona_key]
    collaboration: list[dict] = []

    def emit(stage: str, title: str, detail: str, status: str = "done") -> None:
        event = {"stage": stage, "title": title, "detail": detail, "status": status}
        collaboration.append(event)
        if on_event:
            on_event(event)

    emit("brief", "需求分析正在拆解目标", "识别口味、场景、禁用项和指定基酒。", "working")
    brief = _merge_dialogue_brief(preferences, base_spirits, creative_brief)
    locked = len(brief.flavor_targets) + len(brief.constraints) + len(brief.avoid)
    emit("brief", "需求交接单已锁定", f"保留原始创作方向，并锁定 {locked} 项明确约束。")
    references = _reference_recipes(preferences, base_spirits, brief)
    emit("evidence", "参考检索完成交接", f"从 441 款真实配方中选择 {len(references)} 个相近结构，只借鉴比例骨架。")
    feedback = "（首次创作）"
    last_validation: dict = {"ok": False, "issues": []}
    last_review: dict | None = None
    capability_mode = "model"

    for attempt in range(GEN_MAX_RETRY + 1):
        if attempt:
            emit("revise", f"第 {attempt} 次定向修订", "只修正上一轮明确发现的问题，不改变原始创作目标。", "working")
        emit("create", "配方创作中" if attempt == 0 else "配方重写中", f"采用{persona_info['name']}方向组织材料、比例和步骤。", "working")
        try:
            chain = _CREATE_PROMPT | get_creative_llm() | _recipe_parser
            card = chain.invoke({
                "persona_prompt": persona_info["prompt"],
                "preferences": preferences,
                "base_spirits": ", ".join(base_spirits or []) or "自由选择",
                "creative_brief": json.dumps(brief.model_dump(), ensure_ascii=False),
                "references": _reference_text(references),
                "feedback": feedback,
                "format_instructions": _recipe_parser.get_format_instructions(),
            })
        except Exception:
            capability_mode = "local_rules"
            try:
                card = _local_rule_card(preferences, base_spirits, brief, references)
            except ValueError as local_error:
                return {
                    "ok": False, "recipe": None, "validation": last_validation,
                    "persona": persona_key, "attempts": attempt + 1,
                    "error": str(local_error), "collaboration": collaboration,
                    "references": [], "review": last_review,
                    "brief": brief.model_dump(), "capability_mode": "local_rules",
                }
            emit("create", "本地规则创作完成",
                 "模型创作不可用；已用真实参考结构和确定性调酒规则生成可执行草案。")
        else:
            emit("create", "配方初稿已完成", f"生成 {len(card.ingredients)} 种材料和 {len(card.steps)} 个操作步骤。")

        card_dict = card.model_dump()
        validation_result = validate_recipe(card_dict)
        requested_issue = _requested_base_issue(card_dict, base_spirits)
        if requested_issue:
            validation_result.issues.append(requested_issue)
            validation_result.ok = False
        alignment_issues = _brief_alignment_issues(card_dict, brief)
        if alignment_issues:
            validation_result.issues.extend(alignment_issues)
            validation_result.ok = False
        inventory_issues = _brief_inventory_issues(card_dict, brief)
        if inventory_issues:
            validation_result.issues.extend(inventory_issues)
            validation_result.ok = False
        last_validation = validation_result.to_dict()
        emit("rules", "比例与技法检查完成", "规则检查通过。" if validation_result.ok else f"发现 {len(validation_result.issues)} 个需要修正的问题。")

        if not validation_result.ok:
            feedback = "上一版未通过规则检查，请严格修正：\n" + "\n".join(
                f"- [{issue.code}] {issue.message}" for issue in validation_result.issues
            )
            continue

        if capability_mode == "local_rules":
            emit("review", "本地规则复核中", "再次核对明确需求、材料比例、指定基酒和操作步骤。", "working")
            review = CreativeReview(
                approved=True,
                intent_match="配方的风味数值、基酒和结构均与需求交接单一致。",
                feasibility="已通过本地比例、酒精单位、指定基酒和技法规则；未冒充模型审校。",
                review_mode="rules",
            )
        else:
            emit("review", "独立吧台审校中", "正在核对需求匹配、材料可得性和真实操作可行性。", "working")
            review = _review(preferences, base_spirits, card_dict, last_validation, brief)
            if review.review_mode != "model":
                capability_mode = "model_rules_review"
        last_review = review.model_dump()
        emit("review", "规则复核完成" if capability_mode == "local_rules" else "独立吧台审校完成",
             review.intent_match if review.approved else f"提出 {len(review.issues)} 项定向修改。")
        if review.approved:
            emit("ready", "原创配方已完成", review.intent_match)
            return {
                "ok": True, "recipe": card_dict, "validation": last_validation,
                "persona": persona_key, "attempts": attempt + 1, "error": None,
                "collaboration": collaboration, "review": last_review,
                "brief": brief.model_dump(),
                "capability_mode": capability_mode,
                "references": [{"id": item["id"], "name": item["name"],
                                "name_cn": item.get("name_cn"), "method": item.get("method")}
                               for item in references],
            }
        if attempt == GEN_MAX_RETRY:
            break
        feedback = "独立审校要求修订：\n" + (review.revision_instruction or "\n".join(review.issues))

    reasons = "；".join((last_review or {}).get("issues") or [])
    error = "独立审校仍未通过，本次结果未保存。"
    if reasons:
        error = f"独立审校仍未通过：{reasons}。本次结果未保存。"
    return {"ok": False, "recipe": None, "validation": last_validation,
            "persona": persona_key, "attempts": GEN_MAX_RETRY + 1,
            "error": error,
            "collaboration": collaboration, "references": [], "review": last_review,
            "brief": brief.model_dump(), "capability_mode": capability_mode}
