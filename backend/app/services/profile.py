# -*- coding: utf-8 -*-
"""用户画像服务：跨会话口味偏好 / 忌口 / 历史反馈 的自适应记忆。

对应 REQUIREMENTS 核心原则"画像自适应"：
"记忆用户口味偏好/忌口/历史反馈，每次推荐基于画像调整（'上次说太甜' → '这次减糖'）"

实现策略（分层）:
- 短期（会话内）: 直接从对话历史提取画像信号，即时生效（无需存储）
- 长期（跨会话）: 画像持久化到数据库（M4 接 MySQL/用户模型），
  本模块先定义抽象的 profile 接口，M4 落地持久化

本模块提供:
- `extract_profile_from_history()`: 从对话中提取口味画像（LLM 结构化抽取）
- `apply_profile_to_recommendation()`: 把画像约束注入推荐 prompt
- 画像 schema: 甜度/酸度/酒精度/忌口/偏好基酒/风格

画像抽取是"自我更新"的：每次对话后抽取一次，增量合并到已有画像。
"""
from __future__ import annotations

import json
import re

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.core.llm import get_llm
from app.core.registry import get_prompt

# 画像 schema：六维偏好 + 忌口 + 反馈
# 甜度/酸度用 0-10 表示（0=完全不, 10=极致），None=未知
_DEFAULT_PROFILE: dict = {
    "sweetness": None,     # 甜度偏好 0-10
    "sourness": None,      # 酸度偏好 0-10
    "strong": None,        # 酒精度偏好 0-10（高=喜欢烈的）
    "preferred_spirits": [],  # 偏好基酒，如 ["gin", "rum"]
    "disliked_ingredients": [],  # 忌口材料
    "style_notes": [],     # 风格偏好描述，如 ["清爽", "草本"]
    "feedback": [],        # 历史反馈，如 ["上次玛格丽特太酸"]
    "last_updated": "",    # 最后更新时间（M4 持久化时用）
}


class ExtractedProfile(BaseModel):
    """从对话中抽取的画像增量。字段可空，未提及时为 None/空。"""
    sweetness: int | None = Field(default=None, ge=0, le=10, description="甜度偏好0-10")
    sourness: int | None = Field(default=None, ge=0, le=10, description="酸度偏好0-10")
    strong: int | None = Field(default=None, ge=0, le=10, description="酒精度偏好0-10")
    preferred_spirits: list[str] = Field(default_factory=list, description="偏好基酒，英文名")
    disliked_ingredients: list[str] = Field(default_factory=list, description="忌口材料")
    style_notes: list[str] = Field(default_factory=list, description="风格偏好，中文短语")
    feedback: list[str] = Field(default_factory=list, description="对上次推荐的具体反馈")


_parser = PydanticOutputParser(pydantic_object=ExtractedProfile)

# 系统提示词来自 Prompt 注册中心（M6）
_PROMPT = ChatPromptTemplate.from_messages([
    ("system", get_prompt("profile_extract")["system"]),
    ("human", "用户对话（含助手回复）：\n{history}\n\n{format_instructions}"),
])


def extract_profile_from_history(history: list[dict]) -> dict:
    """从一段对话历史中抽取画像增量（合并进默认画像返回）。"""
    if not history:
        return dict(_DEFAULT_PROFILE)

    history_text = "\n".join(f"{h['role']}: {h['content']}" for h in history[-10:])

    try:
        llm = get_llm(temperature=0, max_tokens=512)
        chain = _PROMPT | llm | _parser
        ext = chain.invoke({"history": history_text,
                            "format_instructions": _parser.get_format_instructions()})
        profile = dict(_DEFAULT_PROFILE)
        profile.update({
            "sweetness": ext.sweetness,
            "sourness": ext.sourness,
            "strong": ext.strong,
            "preferred_spirits": ext.preferred_spirits,
            "disliked_ingredients": ext.disliked_ingredients,
            "style_notes": ext.style_notes,
            "feedback": ext.feedback,
        })
        return profile
    except Exception:
        return dict(_DEFAULT_PROFILE)  # 抽取失败返回空画像，不阻断


def apply_profile_to_prompt(profile: dict, base_prompt: str) -> str:
    """把画像约束注入推荐 prompt（让 Agent 基于画像调整推荐）。"""
    if not profile or not any(v for v in profile.values()):
        return base_prompt

    lines = []
    if profile.get("sweetness") is not None:
        s = profile["sweetness"]
        lines.append(f"- 甜度偏好 {'高' if s >= 7 else '中' if s >= 4 else '低'}（{s}/10）")
    if profile.get("sourness") is not None:
        s = profile["sourness"]
        lines.append(f"- 酸度偏好 {'高' if s >= 7 else '中' if s >= 4 else '低'}（{s}/10）")
    if profile.get("strong") is not None:
        s = profile["strong"]
        lines.append(f"- 酒精度偏好 {'喜欢烈的' if s >= 7 else '喜欢温和的' if s <= 3 else '适中'}（{s}/10）")
    if profile.get("preferred_spirits"):
        lines.append(f"- 偏好基酒: {', '.join(profile['preferred_spirits'])}")
    if profile.get("disliked_ingredients"):
        lines.append(f"- 忌口材料: {', '.join(profile['disliked_ingredients'])}（务必避开）")
    if profile.get("style_notes"):
        lines.append(f"- 风格偏好: {'、'.join(profile['style_notes'])}")
    if profile.get("feedback"):
        lines.append(f"- 历史反馈（据此调整）: {'；'.join(profile['feedback'][-3:])}")

    return base_prompt + "\n\n【用户口味画像（推荐时请遵守）】\n" + "\n".join(lines)


def merge_profiles(base: dict, new: dict) -> dict:
    """增量合并画像：新的覆盖旧的同字段，列表字段去重合并。

    M4 持久化时用于"更新已有画像"。
    """
    merged = dict(base)
    for k, v in new.items():
        if isinstance(v, list) and v:
            merged[k] = list(dict.fromkeys(list(merged.get(k, [])) + v))
        elif v is not None and v != "":
            merged[k] = v
    return merged


def deterministic_profile_delta(query: str) -> dict:
    """Extract only explicit, high-confidence taste feedback without an LLM."""
    text = " ".join((query or "").split())
    if not text:
        return {}
    delta: dict = {}
    if re.search(r"太甜|甜过头|腻|不要太甜|别太甜", text):
        delta["sweetness"] = 3 if re.search(r"太甜|甜过头|腻", text) else 4
    elif re.search(r"再甜一点|甜一点", text):
        delta["sweetness"] = 6
    if re.search(r"太酸|酸过头|不要太酸|别太酸", text):
        delta["sourness"] = 3 if re.search(r"太酸|酸过头", text) else 4
    elif re.search(r"再酸一点|酸一点", text):
        delta["sourness"] = 6
    if re.search(r"太烈|酒味太重|酒精感太强", text):
        delta["strong"] = 3
    elif re.search(r"太淡|没酒味|酒感不足|有酒味|酒感明显", text):
        delta["strong"] = 7 if re.search(r"太淡|没酒味|酒感不足", text) else 6

    styles = [label for pattern, label in (
        (r"清爽|清新|爽口", "清爽"), (r"草本|香草感", "草本"),
        (r"果味|水果感", "果味"), (r"奶油|绵密", "绵密"),
    ) if re.search(pattern, text)]
    if styles and re.search(r"喜欢|想要|想喝|换|更|偏好", text):
        delta["style_notes"] = styles

    forbidden_fragments = re.findall(
        r"(?:不要|别用|不想用|不能用|过敏(?:于)?)([^，、。；！？!?,]{1,24})", text,
    )
    if forbidden_fragments:
        try:
            from app.services.deterministic_chat import extract_inventory_mentions
            disliked = [
                item for fragment in forbidden_fragments
                for item in extract_inventory_mentions(fragment)
            ]
            if disliked:
                delta["disliked_ingredients"] = list(dict.fromkeys(disliked))
        except Exception:
            pass

    if re.search(r"太甜|太酸|太烈|太淡|不喜欢|不合适|不要第|前\s*[一二三四五六七八九十两0-9]+\s*个", text):
        delta["feedback"] = [text[:120]]
    return delta
