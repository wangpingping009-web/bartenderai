# -*- coding: utf-8 -*-
"""多维拆解：把复杂问题拆成多个子查询，分别检索再融合。

为什么需要（对应 REQUIREMENTS 3.2 多维拆解检索）:
- "夏日派对喝什么清爽的" 这种问题一次检索容易漏召
- 拆成 ["适合夏日的鸡尾酒", "清爽的鸡尾酒", "派对饮品"] 分别检索，
  再合并去重，召回覆盖显著提升（每路漏的，另一路能补上）

用法:
  检索 Agent 判断问题复杂 → 拆解 → 每路子查询走混合检索+重排 → 合并
  简单问题不拆（省 token，配合"智能准入线"）
"""
from __future__ import annotations

import json
import re

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.core.llm import get_llm

# 专名启发式短路：查询已含明确配方名/材料词且较短 → 无需拆解，直接检索。
# 省一次拆解 LLM 调用（实测 ~4.5s），专名查询多路拆解收益低。
_KNOWN_NAMES = [
    "玛格丽特", "莫吉托", "金汤力", "威士忌酸", "长岛冰茶", "自由古巴",
    "大都会", "曼哈顿", "尼格罗尼", "教父", "螺丝刀", "血腥玛丽",
    "椰林飘香", "得其利", "边车", "白俄罗斯", "莫斯科骡子", "古典",
    "萨泽拉克", "薄荷朱莉普", "马天尼", "干马天尼",
]
_MATERIALS = [
    "朗姆", "金酒", "伏特加", "威士忌", "白兰地", "龙舌兰", "苦艾酒",
    "青柠", "柠檬", "薄荷", "糖浆", "苦精", "汤力水", "苏打水",
    "味美思", "君度", "蛋清", "姜汁", "苹果", "菠萝", "葡萄柚",
]


def _looks_specific(query: str) -> bool:
    """查询里已点名配方/材料 → 单查询检索即可（跳过 LLM 拆解）。"""
    if len(query) < 20 and any(n in query for n in _KNOWN_NAMES + _MATERIALS):
        return True
    try:
        from app.services.deterministic_chat import find_named_recipe, is_preference_query
        return bool(find_named_recipe(query) or is_preference_query(query))
    except Exception:
        return False


def decompose_query(query: str) -> list[str]:
    """把复杂问题拆成子查询；简单/专名问题返回 [原查询]。"""
    if _looks_specific(query):
        return [query]
    chain = _get_chain()  # 此时才构造 LLM
    try:
        result = chain.invoke({"query": query,
                               "format_instructions": _parser.get_format_instructions()})
        if not result.should_decompose:
            return [query]
        subs = [s for s in result.sub_queries if s.strip()]
        return subs if subs else [query]
    except Exception:
        return [query]  # 拆解失败退回原查询
_SYSTEM_PROMPT = """你是一个检索策略专家。把用户的提问拆解成多个独立子查询，每个子查询针对问题的一个维度。
规则：
1. 子查询要"各自独立、可单独检索"（不要互相依赖）
2. 每个子查询都应包含具体可检索的词（配方名/基酒/材料/技法/风味/场合）
3. 拆解 1-4 个即可，不要过度拆分
4. 简单问题不要拆（返回 1 个原始查询即可）"""


class QueryDecomposition(BaseModel):
    """拆解结果。"""
    sub_queries: list[str] = Field(description="拆解后的子查询列表（1-4个）")
    should_decompose: bool = Field(description="该问题是否真的需要拆解")


_parser = PydanticOutputParser(pydantic_object=QueryDecomposition)

_chain = None  # 懒加载


def _get_chain():
    """懒加载拆解链，便于测试 mock。"""
    global _chain
    if _chain is None:
        prompt = ChatPromptTemplate.from_messages([
            ("system", _SYSTEM_PROMPT),
            ("human", "用户提问：{query}\n\n{format_instructions}"),
        ])
        _chain = prompt | get_llm(temperature=0, max_tokens=512) | _parser
    return _chain
