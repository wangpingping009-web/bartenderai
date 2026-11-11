# -*- coding: utf-8 -*-
"""推理式替代引擎：不只给替代品，还解释"为什么能替"。

对应 REQUIREMENTS §7「推理式替代引擎」：
"不只给替代品，还解释'为什么能替'（图结构存替代关系）"

两层实现：
- 确定性匹配：从知识库 substitutions.json（策展替代规则）按材料名模糊命中
  —— 无需 LLM，离线可用，是"图结构替代关系"的数据落地
- 推理解释：LLM 结合命中规则 + 鸡尾酒上下文，讲清楚
  风味影响 / 用量换算 / 注意事项（为什么能替、替了差在哪）

降级：无 LLM / 无命中时，直接返回匹配到的规则原文，仍然可用。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.core.llm import get_llm
from app.core.registry import get_prompt

_RULES_PATH = Path(__file__).resolve().parents[2] / "data" / "knowledge" / "substitutions.json"
_cache: list[dict] | None = None


def _load_rules() -> list[dict]:
    global _cache
    if _cache is None:
        _cache = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
    return _cache


# ---------- 确定性匹配（离线可用）----------

def find_substitutions(ingredient: str) -> list[dict]:
    """在替代规则库里找含该材料的规则。

    命中策略：把规则 title（如 "Lime Juice ↔ Lemon Juice"）按 ↔ / ↔ / ↔
    切出两侧材料，任一侧与查询材料同名/近名即命中。
    """
    q = re.sub(r"\s+", " ", (ingredient or "").strip().lower())
    if not q:
        return []
    hits = []
    for rule in _load_rules():
        title = (rule.get("title") or "")
        sides = [s.strip() for s in re.split(r"↔|<-|->|<->", title) if s.strip()]
        sides += [s.strip() for s in (rule.get("title_cn") or "").split("↔") if s.strip()]
        if any(q in s.lower() or s.lower() in q for s in sides):
            hits.append(_rule_to_dict(rule))
    return hits


def _rule_to_dict(rule: dict) -> dict:
    """规则 → 前端可用 dict（含从 title 解析出的双方材料名）。"""
    title = rule.get("title", "")
    pairs = [s.strip() for s in re.split(r"↔|<-|->|<->", title) if s.strip()]
    return {
        "id": rule.get("id"),
        "a": pairs[0] if pairs else title,
        "b": pairs[1] if len(pairs) > 1 else "",
        "title_cn": rule.get("title_cn", ""),
        "content": rule.get("content_cn") or rule.get("content", ""),
    }


# ---------- LLM 推理解释 ----------

class SubstitutionExplanation(BaseModel):
    """一次替代的推理说明。"""
    can_substitute: bool = Field(description="是否能替代")
    ratio: str = Field(default="", description="用量换算，如 '1:1 或 1.25:1'")
    flavor_impact: str = Field(default="", description="风味影响（差在哪/好在哪）")
    caution: str = Field(default="", description="注意事项（何时不建议替代）")
    summary: str = Field(default="", description="一段面向用户的完整解释（为什么能替）")


_parser = PydanticOutputParser(pydantic_object=SubstitutionExplanation)

# 系统提示词来自 Prompt 注册中心（M6）
_PROMPT = ChatPromptTemplate.from_messages([
    ("system", get_prompt("substitution")["system"]),
    ("human", "用户问：{query}\n"
              "相关替代规则（知识库命中，可作依据，也可补充常识）：\n{rules}\n\n"
              "鸡尾酒上下文（可空）：{context}\n\n{format_instructions}"),
])


def explain_substitution(query: str, cocktail_context: str = "",
                         ingredient: str | None = None) -> dict:
    """回答一次替代问题：确定性命中 + LLM 推理，返回解释。

    Returns:
        {"query", "matched": [规则...], "explanation": {...}|None,
         "offline": bool, "error": str|None}
    """
    matched = find_substitutions(ingredient or query)
    if not matched:
        return {"query": query, "matched": [], "explanation": None,
                "offline": True, "error": "知识库暂无该材料的替代规则"}

    try:
        llm = get_llm(temperature=0.3, max_tokens=512)
        chain = _PROMPT | llm | _parser
        rules_text = "\n".join(
            f"- {r['a']} ↔ {r['b']}: {r['content'][:300]}" for r in matched)
        exp = chain.invoke({
            "query": query,
            "rules": rules_text,
            "context": cocktail_context or "(无)",
            "format_instructions": _parser.get_format_instructions(),
        })
        return {"query": query, "matched": matched, "explanation": exp.model_dump(),
                "offline": False, "error": None}
    except Exception as e:
        # 无 LLM → 直接把规则原文当解释返回（离线降级）
        return {"query": query, "matched": matched, "explanation": None,
                "offline": True, "error": "智能解释暂时不可用，以下建议来自已验证的替代规则。"}
