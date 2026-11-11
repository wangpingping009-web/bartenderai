# -*- coding: utf-8 -*-
"""Model-led, multi-turn requirement discovery for collaborative creation."""
from __future__ import annotations

import re
import logging

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.core.llm import (
    iter_configured_llms, is_non_retryable_llm_error,
    llm_error_reason,
)


logger = logging.getLogger(__name__)


class CreativeDialogueDecision(BaseModel):
    active: bool = Field(description="当前消息是否仍在共同创作一杯原创鸡尾酒")
    ready: bool = Field(description="需求是否已确认完整，且用户明确同意开始生成")
    preferences: str = Field(default="", description="整合全部历史后的自然语言创作需求")
    base_spirits: list[str] = Field(default_factory=list, description="用户明确指定或现有的基酒")
    confirmed: list[str] = Field(default_factory=list, description="用户明确说过、不能擅自补充的条件")
    missing: list[str] = Field(default_factory=list, description="仍会显著影响配方结构的关键信息")
    response: str = Field(description="本轮直接回复用户的自然中文")
    brief: dict = Field(default_factory=dict, description="可跨轮保存的结构化创作简报")
    capability: str = Field(default="unavailable", description="model 或 local_parser")


_CREATE_HINTS = re.compile(
    r"一起(?:创作|设计|做)|带我(?:一起)?(?:创作|设计|做)|自己创作|原创(?:一杯|鸡尾酒|配方)|"
    r"创作(?:一杯|鸡尾酒|配方)|设计(?:一杯|一款|鸡尾酒|配方)|定制(?:一杯|鸡尾酒|配方)|"
    r"开发(?:一杯|一款|鸡尾酒|配方)|不要现成配方"
)
_CONFIRM_HINTS = re.compile(
    r"^(?:就这样|确认|可以开始|开始(?:吧|创作)?|"
    r"按(?:这个|这版|刚才的)(?:来|开始|做)|"
    r"就按(?:这个|这版|刚才的)(?:来|开始|做)?|就这么(?:来|做)|"
    r"可以了?[，, ]*(?:开始|生成)(?:吧)?|"
    r"需求(?:没问题|确认)[，, ]*(?:开始|生成)(?:吧)?|"
    r"没问题|确定|生成吧)[。！! ]*$"
)


def has_creation_goal(query: str) -> bool:
    """High precision guard: goals outrank broad words such as 想喝/甜/酸."""
    return bool(_CREATE_HINTS.search(query or ""))


def creation_goal_in_history(history: list[dict] | None, turns: int = 8) -> bool:
    recent = list(history or [])[-turns:]
    last_goal = -1
    last_recipe = -1
    for index, message in enumerate(recent):
        if message.get("role") == "user" and has_creation_goal(str(message.get("content") or "")):
            last_goal = index
        metadata = message.get("metadata") if isinstance(message, dict) else None
        if message.get("role") == "assistant" and isinstance(metadata, dict) and metadata.get("recipe"):
            last_recipe = index
    return last_goal >= 0 and last_goal > last_recipe


_parser = PydanticOutputParser(pydantic_object=CreativeDialogueDecision)
_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """你是原创鸡尾酒共同创作流程的需求导演，不是现成配方推荐器。

你要真正理解用户本轮表达、最近对话和现有酒柜，维护一份连续的创作简报。
规则：
1. 只记录用户明确表达的条件，不能把示例或你的猜测写成已确认需求。
2. 同时理解程度词与否定，例如“甜但不要很甜”=中低甜，“酸但不要很酸”=中低酸，
   “有酒味”=保留明确酒感；“有金酒等”表示金酒可用，但其他库存仍不完整。
3. 用户要求“一起创作/先确定需求”时，绝不能推荐数据库里的现成鸡尾酒，也不能立刻输出最终配方。
4. 每轮先用简短自然语言复述新确认的信息，再只问一个当前信息增益最高的问题。
   问题根据缺口动态产生，不使用固定问卷；可给少量容易回答的方向，但不强迫选项。
5. 一般至少确认：风味强弱、酒感、可用/禁用材料、饮用形态或场景。已有的信息不要重复问。
6. 只有需求足够，而且用户明确说“开始/确认/按这个来”等同意生成时，ready=true。
7. 若用户明显转向无关话题，active=false，交还普通对话总控。
8. response 像资深调酒师与用户并肩讨论，具体、有判断、不过度热情，不出现“作为AI”。

输出必须符合给定结构。"""),
    ("human", "本轮用户：{query}\n\n服务端保存的上一轮创作简报：\n{existing_brief}"
              "\n\n最近对话：\n{history}\n\n现有酒柜：{stock}\n\n{format_instructions}"),
])


def _history_text(history: list[dict] | None) -> str:
    rows = []
    for item in list(history or [])[-8:]:
        role = "用户" if item.get("role") == "user" else "助手"
        rows.append(f"{role}: {str(item.get('content') or '')[:600]}")
    return "\n".join(rows) or "（无）"


def _existing_brief(history: list[dict] | None) -> dict:
    """Recover the latest server-authored brief instead of parsing our prose."""
    for item in reversed(list(history or [])):
        metadata = item.get("metadata") if isinstance(item, dict) else None
        brief = metadata.get("creative_brief") if isinstance(metadata, dict) else None
        if isinstance(brief, dict) and brief:
            return dict(brief)
    return {}


def _user_text(history: list[dict] | None, query: str) -> str:
    turns = [
        str(item.get("content") or "")
        for item in list(history or [])[-10:]
        if item.get("role") == "user"
    ]
    return " ".join([*turns, query or ""])


_BASE_ALIASES = (
    (("金酒", "琴酒", "gin"), "gin"), (("伏特加", "vodka"), "vodka"),
    (("朗姆", "rum"), "rum"), (("威士忌", "whiskey", "whisky"), "whiskey"),
    (("龙舌兰", "tequila"), "tequila"), (("白兰地", "brandy"), "brandy"),
)


def _latest_choice(text: str, choices: tuple[tuple[str, str], ...]) -> str:
    found: list[tuple[int, str]] = []
    for pattern, value in choices:
        found.extend((match.start(), value) for match in re.finditer(pattern, text, re.I))
    return max(found, default=(-1, ""))[1]


def _apply_brief_turn(brief: dict, text: str) -> dict:
    """Apply one user turn so corrections replace, rather than coexist with, old intent."""
    text = " ".join((text or "").split())
    if not text:
        return brief

    if re.search(r"再甜一点|更甜|甜一点|加点甜", text):
        brief["sweetness"] = "中等甜味，较上一版提高"
    elif re.search(r"(?:不要|不想要|别要|去掉)(?:明显)?甜味?|完全不甜|干型|干爽", text):
        brief["sweetness"] = "不甜，保持干爽"
    elif re.search(r"太甜|降低甜度|减甜|中低甜|微甜|少甜|甜.{0,5}(?:不|别|不要).{0,3}太?甜|甜.{0,5}不是很甜", text):
        brief["sweetness"] = "中低甜，能尝到甜味但不腻"
    elif "甜" in text and "不甜" not in text:
        brief.setdefault("sweetness", "带甜味，强度待确认")

    if re.search(r"再酸一点|更酸|酸一点|加点酸", text):
        brief["acidity"] = "中等酸度，较上一版提高"
    elif re.search(r"不酸|不要酸味?|别酸|去掉酸味?|完全不酸", text):
        brief["acidity"] = "避免明显酸味"
    elif re.search(r"太酸|降低酸度|减酸|中低酸|微酸|少酸|酸.{0,5}(?:不|别|不要).{0,3}太?酸|酸.{0,5}不是很酸", text):
        brief["acidity"] = "中低酸，有明亮感但不尖锐"
    elif "酸" in text:
        brief.setdefault("acidity", "带酸味，强度待确认")

    if re.search(r"不要酒味|没酒味|低度|低酒精|不要烈|不烈|酒味轻", text):
        brief["alcohol"] = "低酒精感"
    elif re.search(r"有酒味|酒感|喝得出酒|酒味明显|烈一点|酒味重", text):
        brief["alcohol"] = "保留清晰酒感"

    bases = list(brief.get("base_spirits") or [])
    lowered = text.lower()
    replacement_target = ""
    for aliases, value in _BASE_ALIASES:
        label_pattern = "|".join(re.escape(alias) for alias in aliases)
        if re.search(rf"换(?:成|用)\s*(?:{label_pattern})", lowered, re.I):
            replacement_target = value
            break
    if replacement_target:
        bases = [replacement_target]

    explicitly_removed: set[str] = set()
    for aliases, value in _BASE_ALIASES:
        label_pattern = "|".join(re.escape(alias) for alias in aliases)
        negative = re.search(
            rf"(?:不要|不用|别用|去掉|拿掉|换掉)\s*(?:{label_pattern})|"
            rf"(?:{label_pattern})[^，、。；！？!?,]{{0,4}}(?:不要|不用|没有|换掉)",
            lowered, re.I,
        )
        mentioned = re.search(rf"(?<![a-z])(?:{label_pattern})(?![a-z])", lowered, re.I)
        if negative:
            explicitly_removed.add(value)
            bases = [item for item in bases if item != value]
        elif mentioned and not replacement_target and value not in bases:
            bases.append(value)
    if replacement_target not in explicitly_removed and replacement_target:
        bases = [replacement_target]
    brief["base_spirits"] = list(dict.fromkeys(bases))

    available = list(brief.get("available_ingredients") or [])
    avoided = list(brief.get("avoid_ingredients") or [])
    try:
        from app.services.deterministic_chat import extract_inventory_mentions
        mentioned = extract_inventory_mentions(text)
        forbidden_fragments = re.findall(
            r"(?:不要|别用|不想用|不能用|去掉|拿掉|没有|过敏(?:于)?)"
            r"([^，、。；！？!?,]{1,24})",
            text,
        )
        forbidden_fragments.extend(re.findall(
            r"([^，、。；！？!?,]{1,24})(?:没有了?|用完了|去掉|拿掉)", text,
        ))
        restored_fragments = re.findall(
            r"(?:可以用|能用|改用|加上|保留)([^，、。；！？!?,]{1,24})", text,
        )
        forbidden = {
            item for fragment in forbidden_fragments
            for item in extract_inventory_mentions(fragment)
        } | explicitly_removed
        restored = {
            item for fragment in restored_fragments
            for item in extract_inventory_mentions(fragment)
        }
        forbidden.difference_update(restored)
        avoided = [item for item in avoided if item not in restored]
        for item in forbidden:
            if item not in avoided:
                avoided.append(item)
        available = [item for item in available if item not in forbidden]
        for item in mentioned:
            if item not in brief["base_spirits"] and item not in avoided and item not in available:
                available.append(item)
    except Exception:
        pass
    brief["avoid_ingredients"] = avoided
    brief["available_ingredients"] = available

    serve_style = _latest_choice(text, (
        (r"长饮|highball|嗨棒|慢慢喝|清爽型", "清爽长饮"),
        (r"短饮|短款|酒体集中|马天尼杯|coupe", "集中短饮"),
    ))
    if serve_style:
        brief["serve_style"] = serve_style
    occasion = _latest_choice(text, (
        (r"餐前|开胃", "餐前"), (r"餐后|甜点", "餐后"),
        (r"聚会|派对|朋友", "聚会"),
    ))
    if occasion:
        brief["occasion"] = occasion

    if re.search(r"就这些|只有这些|材料就这些|没有别的|只有.{1,40}(?:能用|可用|现有|手边|了)?$", text):
        brief["inventory_complete"] = True
    elif re.search(r"(?:有|现有|现在有|手边).{0,18}(?:等|之类|还有)", text):
        brief["inventory_complete"] = False
    return brief


def _extract_brief(query: str, history: list[dict] | None,
                   stock: list[str] | None) -> dict:
    """Replay user-authored deltas only when no persisted server brief exists."""
    brief = _existing_brief(history)
    turns = [query]
    if not brief:
        turns = [
            str(item.get("content") or "") for item in list(history or [])[-10:]
            if item.get("role") == "user"
        ] + turns
    for turn in turns:
        brief = _apply_brief_turn(brief, turn)

    from app.services.recipe_catalog import canonical
    available = list(brief.get("available_ingredients") or [])
    for item in stock or []:
        normalized = canonical(item)
        if normalized and normalized not in brief.get("base_spirits", []) \
                and normalized not in brief.get("avoid_ingredients", []) \
                and normalized not in available:
            available.append(normalized)
    brief["available_ingredients"] = available
    if stock:
        brief.setdefault("inventory_complete", True)
    return brief


def _reconcile_model_brief(query: str, history: list[dict] | None,
                           stock: list[str] | None, model_brief: dict | None) -> dict:
    """Keep model understanding while making explicit current corrections authoritative."""
    brief = {**_existing_brief(history), **dict(model_brief or {})}
    brief = _apply_brief_turn(brief, query)

    from app.services.recipe_catalog import canonical
    available = list(brief.get("available_ingredients") or [])
    for item in stock or []:
        normalized = canonical(item)
        if normalized and normalized not in brief.get("base_spirits", []) \
                and normalized not in brief.get("avoid_ingredients", []) \
                and normalized not in available:
            available.append(normalized)
    brief["available_ingredients"] = available
    if stock:
        brief.setdefault("inventory_complete", True)
    return brief


_BASE_ZH = {"gin": "金酒", "vodka": "伏特加", "rum": "朗姆酒",
            "whiskey": "威士忌", "tequila": "龙舌兰", "brandy": "白兰地"}


def _confirmed_from_brief(brief: dict) -> list[str]:
    from app.services.recipe_catalog import ingredient_zh

    confirmed = [
        brief[key] for key in ("sweetness", "acidity", "alcohol", "serve_style", "occasion")
        if brief.get(key)
    ]
    confirmed.extend(f"可使用{_BASE_ZH.get(item, item)}" for item in brief.get("base_spirits") or [])
    if brief.get("avoid_ingredients"):
        confirmed.append("不用" + "、".join(
            ingredient_zh(item) for item in brief["avoid_ingredients"]
        ))
    return list(dict.fromkeys(confirmed))


def _next_question(brief: dict) -> tuple[str, list[str]]:
    bases = brief.get("base_spirits") or []
    base_text = "、".join(_BASE_ZH.get(item, item) for item in bases) or "基酒"
    if brief.get("inventory_complete") is False or not brief.get("available_ingredients"):
        return (
            f"{base_text}已经确定。你手边除基酒外还有哪些材料可以用，"
            "比如气泡水、果汁、糖浆、利口酒或香草？也告诉我明确不想用的材料。",
            ["可用与禁用材料"],
        )
    if not brief.get("serve_style"):
        return (
            "这杯你更想慢慢喝、清爽展开的长饮，还是杯量更短、酒体更集中的短饮？",
            ["饮用形态"],
        )
    if not brief.get("occasion"):
        return (
            "最后定一下它出现的时刻：更像餐前开胃、餐后慢饮，还是朋友聚会时喝？",
            ["饮用场景"],
        )
    return ("这份方向已经足够创作。你确认按它开始，还是还想改一个条件？", [])


def _brief_summary(brief: dict) -> str:
    values = _confirmed_from_brief(brief)
    return "；".join(values) if values else "共同创作一杯原创鸡尾酒"


def _fallback(query: str, history: list[dict] | None, stock: list[str] | None,
              reason: str = "request_failed") -> CreativeDialogueDecision:
    """Connection-safe fallback. It protects intent but never pretends to be model reasoning."""
    brief = _extract_brief(query, history, stock)
    confirmed = _confirmed_from_brief(brief)
    bases = list(brief.get("base_spirits") or [])
    ready = bool(_CONFIRM_HINTS.fullmatch((query or "").strip())) and len(confirmed) >= 3
    if ready:
        response = "需求已经确认，我会按这份简报进入创作、比例校验和独立审校。"
        missing: list[str] = []
    else:
        summary = _brief_summary(brief)
        question, missing = _next_question(brief)
        unavailable = {
            "insufficient_balance": "智能模型额度不足",
            "authentication_failed": "智能模型认证失败",
            "connection_failed": "智能模型暂时连接失败",
            "rate_limited": "智能模型当前请求受限",
        }.get(reason, "智能模型暂时不可用")
        response = (
            f"我目前只可靠识别并保存了你明确说出的条件：{summary}。\n\n"
            f"{unavailable}，所以这一轮没有把固定规则包装成完整的智能理解，"
            f"也不会拿现成配方顶替原创。先继续补齐一个关键缺口：{question}"
        )
    return CreativeDialogueDecision(
        active=True, ready=ready, preferences=_brief_summary(brief),
        base_spirits=bases, confirmed=confirmed, missing=missing, response=response,
        brief=brief, capability="local_parser",
    )


def plan_creative_dialogue(query: str, history: list[dict] | None = None,
                           stock: list[str] | None = None) -> CreativeDialogueDecision:
    existing_brief = _existing_brief(history)
    values = {
        "query": query,
        "existing_brief": repr(existing_brief) if existing_brief else "（无）",
        "history": _history_text(history),
        "stock": "、".join(stock or []) or "（未提供完整酒柜）",
        "format_instructions": _parser.get_format_instructions(),
    }
    messages = _PROMPT.format_messages(**values)
    # Prefer provider-native JSON mode. If a provider does not implement it,
    # retry through the portable Pydantic parser. A parse miss is retried once
    # because it is not evidence that the user's intent was recommendation.
    last_error: Exception | None = None
    try:
        providers = iter_configured_llms(temperature=0.15, max_tokens=900)
    except Exception as error:
        providers = []
        last_error = error

    # Retry the actual structured task on every configured provider. This is
    # real failover; it does not rely on a disconnected health-check prompt.
    for llm in providers:
        try:
            structured = llm.with_structured_output(CreativeDialogueDecision, method="json_mode")
            decision = structured.invoke(messages)
            if isinstance(decision, dict):
                decision = CreativeDialogueDecision.model_validate(decision)
            if decision.active and not decision.response.strip():
                raise ValueError("creative dialogue returned an empty response")
            decision.brief = _reconcile_model_brief(
                query, history, stock, decision.brief,
            )
            decision.base_spirits = list(decision.brief.get("base_spirits") or [])
            decision.capability = "model"
            # The model may judge the brief complete, but generation still needs
            # an explicit go-ahead from the user.
            decision.ready = bool(decision.ready and _CONFIRM_HINTS.fullmatch((query or "").strip()))
            return decision
        except Exception as error:
            last_error = error
            if is_non_retryable_llm_error(error):
                continue
            try:
                decision = (_PROMPT | llm | _parser).invoke(values)
                if decision.active and not decision.response.strip():
                    raise ValueError("creative dialogue returned an empty response")
                decision.brief = _reconcile_model_brief(
                    query, history, stock, decision.brief,
                )
                decision.base_spirits = list(decision.brief.get("base_spirits") or [])
                decision.capability = "model"
                decision.ready = bool(decision.ready and _CONFIRM_HINTS.fullmatch((query or "").strip()))
                return decision
            except Exception as parser_error:
                last_error = parser_error
                if is_non_retryable_llm_error(parser_error):
                    continue

    logger.warning("creative dialogue degraded to deterministic guard: %s", last_error)
    return _fallback(query, history, stock,
                     llm_error_reason(last_error) if last_error else "request_failed")


def stream_creative_clarification(query: str, brief: dict, draft: str):
    """Generate the user-facing clarification as a real model token stream."""
    prompt = (
        "你正在与用户共同创作原创鸡尾酒。根据结构化简报和本轮表达，先自然复述已确认内容，"
        "再只问一个信息增益最高的问题。不要推荐任何现成配方，不要输出材料表或最终配方，"
        "不要提系统、提示词或模型。语气像并肩创作的资深调酒师，控制在120字以内。\n\n"
        f"本轮表达：{query}\n结构化简报：{brief}\n语义草稿：{draft}"
    )
    last_error: Exception | None = None
    for llm in iter_configured_llms(temperature=0.35, max_tokens=220):
        emitted = False
        try:
            for chunk in llm.stream(prompt):
                text = getattr(chunk, "content", "") or ""
                if text:
                    emitted = True
                    yield text
            if emitted:
                return
        except Exception as error:
            last_error = error
            if emitted:
                raise
    if last_error:
        raise last_error
    raise RuntimeError("没有可用的创作模型")
