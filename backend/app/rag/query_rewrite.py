# -*- coding: utf-8 -*-
"""多轮对话查询改写：把指代词/模糊表达改写为可检索的查询。

为什么需要（对应 REQUIREMENTS 核心原则"查询改写"）:
- 多轮对话里用户常省略语境: "这个太甜了" "那款能换成朗姆吗" "再来一杯"
- 直接拿这些去检索必然失败: 向量库里没有"这个""那款"
- 改写器用 LLM 结合对话历史，还原出"完整、可检索"的查询

改写策略:
- 有指代 → 还原成具体配方/意图（"这个" → "玛格丽特"）
- 无指代但问题独立 → 原样返回，不重写（省一次 LLM 调用）
- 同时输出"检索关键词"（抽取可命中知识库的短语）

本模块用 Pydantic 结构化输出，保证 LLM 返回可解析的 JSON。
"""
from __future__ import annotations

import json
import re

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.core.llm import get_llm
from app.services.recipe_catalog import INGREDIENTS, RECIPE_NAMES

_SYSTEM_PROMPT = """你是一个鸡尾酒对话助手的前置处理器。用户在多轮对话中的提问可能包含指代词（这个/那个/它/这款/那款）或省略语境。
你的任务：结合对话历史，把用户最新提问改写成"独立、可检索"的查询。

规则：
1. 若最新提问包含指代词，必须还原为具体内容（如"它太甜了" → "把玛格丽特的糖浆减少一半"）
2. 若最新提问是独立的（如"推荐一款威士忌鸡尾酒"），直接原样保留
3. keywords 提取检索关键词：抽取最可能命中知识库的短语（配方名/基酒名/材料/技法/风味），中英文均可
4. 只改写成事实性内容，不要编造知识库不存在的信息"""


class QueryRewrite(BaseModel):
    """一次查询改写的结果。"""
    rewritten: str = Field(description="改写后的完整查询（独立可检索）")
    keywords: list[str] = Field(description="检索关键词列表（中英文均可）")
    needs_retrieve: bool = Field(description="是否真的需要检索知识库（闲聊/感谢类为 false）")


_parser = PydanticOutputParser(pydantic_object=QueryRewrite)

# 注意: 链在这里只是"模板"，真正的 LLM 在 rewrite_query 内注入，
# 这样测试可以 mock get_llm，业务代码也能按需换模型（延迟绑定）。
_chain = None  # 懒加载: _get_chain() 首次调用时构造


def _get_chain():
    """懒加载改写链。独立函数便于测试替换。"""
    global _chain
    if _chain is None:
        prompt = ChatPromptTemplate.from_messages([
            ("system", _SYSTEM_PROMPT),
            ("human", "对话历史：\n{history}\n\n用户最新提问：{query}\n\n{format_instructions}"),
        ])
        _chain = prompt | get_llm(temperature=0, max_tokens=512) | _parser
    return _chain


def rewrite_query(query: str, history: list[dict] | None = None) -> QueryRewrite:
    """把用户最新提问改写成可检索查询。

    Args:
        query:   用户本轮提问
        history: 最近 N 轮对话 [{role, content}, ...]，用于还原指代
    """
    keywords = _expand_aliases(query)
    # 独立问题即使带历史也无需模型；只有明确指代/省略才需要还原上下文。
    if not history or not re.search(r"(这个|那个|它|这款|那款|上一杯|刚才|再来|换成)", query):
        return QueryRewrite(rewritten=query, keywords=keywords, needs_retrieve=True)

    chain = _get_chain()  # 此时才真正构造 LLM

    # 只取最近 5 轮，避免历史过长稀释意图
    recent = history[-5:]
    history_text = "\n".join(f"{h['role']}: {h['content']}" for h in recent)

    try:
        result = chain.invoke({"history": history_text, "query": query,
                               "format_instructions": _parser.get_format_instructions()})
        # 关键词去重、去除空串
        result.keywords = list(dict.fromkeys(keywords + [k for k in result.keywords if k.strip()]))
        return result
    except Exception as e:
        # 改写失败不阻断流程：退回原查询
        return QueryRewrite(rewritten=query, keywords=keywords, needs_retrieve=True)


def _expand_aliases(query: str) -> list[str]:
    """Deterministically add bilingual recipe and ingredient aliases."""
    expanded = [query]
    lower = query.lower()
    for english, chinese in RECIPE_NAMES.items():
        if chinese in query:
            expanded.append(english)
        elif english.lower() in lower:
            expanded.append(chinese)
    for english, chinese in INGREDIENTS.items():
        if chinese in query:
            expanded.append(english)
        elif english in lower:
            expanded.append(chinese)
    return list(dict.fromkeys(expanded))
