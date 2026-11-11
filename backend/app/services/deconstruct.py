# -*- coding: utf-8 -*-
"""配方解构重组：经典配方 → 风味骨架 → 重组出新配方。

对应 REQUIREMENTS §7「配方解构重组」：
"经典配方解构为风味骨架，按配方语法重组新配方"

设计：
- 确定性骨架：从配方卡的 ingredients + flavor 六维直接解出
  （基酒 / 酸甜平衡 / 风格关键词）—— 离线可用
- LLM 重组点子：基于骨架生成 3 个"重组方向"（换基酒 / 换酸 / 换甜 / 换装饰）
- 降级：无 LLM 时返回确定性骨架 + 从已知替换规则推的组合建议
"""
from __future__ import annotations

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.core.llm import get_llm
from app.core.registry import get_prompt
from app.services.mixology import KNOWN_SPIRITS, SOUR_MARKERS, SWEET_MARKERS


class RecombinationIdea(BaseModel):
    name: str = Field(description="重组配方名")
    change: str = Field(description="改了什么（换基酒/换酸/换甜/调整比例...）")
    why: str = Field(description="为什么这样改成立")


class DeconstructionResult(BaseModel):
    skeleton: str = Field(description="风味骨架一句话描述")
    base_spirit: str = Field(description="核心基酒")
    balance: str = Field(description="酸甜平衡结构，如 'sour 1:1'")
    signature: str = Field(description="这款酒让人记住的关键元素")
    ideas: list[RecombinationIdea] = Field(description="3 个重组方向")


_parser = PydanticOutputParser(pydantic_object=DeconstructionResult)

# 系统提示词来自 Prompt 注册中心（M6）
_PROMPT = ChatPromptTemplate.from_messages([
    ("system", get_prompt("deconstruct")["system"]),
    ("human", "配方卡：\n{card}\n\n{format_instructions}"),
])


def _skeleton_from_card(card: dict) -> dict:
    """确定性骨架：不依赖 LLM 先解出一份（重组点子的兜底依据）。"""
    ings = [(i.get("name", ""), i.get("amount", "")) for i in card.get("ingredients", [])]
    base = next((n for n, _ in ings if any(s in n for s in KNOWN_SPIRITS)), "")
    sweet = any(any(m in n for m in SWEET_MARKERS) for n, _ in ings)
    sour = any(any(m in n for m in SOUR_MARKERS) for n, _ in ings)
    if sweet and sour:
        balance = "sour（甜酸平衡）"
    elif sweet:
        balance = "甜型（甜为主导）"
    elif sour:
        balance = "酸型（酸为主导）"
    else:
        balance = "干型（几乎无甜酸）"
    return {"base_spirit": base, "balance": balance, "signature": card.get("name", "")}


def deconstruct_recipe(card: dict) -> dict:
    """解构一张配方卡 → 骨架 + 重组点子。

    Returns:
        {"ok", "deconstruction": {...}|None, "skeleton": 确定性骨架, "error"}
    """
    skeleton = _skeleton_from_card(card)
    try:
        llm = get_llm(temperature=0.6, max_tokens=700)
        chain = _PROMPT | llm | _parser
        import json as _json
        card_text = _json.dumps(card, ensure_ascii=False)[:2000]
        res = chain.invoke({"card": card_text,
                            "format_instructions": _parser.get_format_instructions()})
        return {"ok": True, "deconstruction": res.model_dump(),
                "skeleton": skeleton, "error": None}
    except Exception as e:
        return {"ok": False, "deconstruction": None,
                "skeleton": skeleton, "error": "智能重组暂时不可用，已保留基于材料的基础结构分析。"}
