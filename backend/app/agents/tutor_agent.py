# -*- coding: utf-8 -*-
"""教学讲解 Agent：技法 / 步骤 / 杯具 / 术语讲解，服务小白。

职责（对应六 Agent 里的"教学讲解"）:
- 检索技法库、术语表，给出清晰讲解
- 面向小白的逐步指导（分步调制引导的前置知识）
- 可带难度/进阶建议（呼应"技能树成长系统"M7）

reAct 工具:
- search_technique: 检索技法/术语知识卡片
- get_cocktail_steps: 取配方的完整调制步骤
- finalize_lesson: 给出教学结论
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from app.agents.base import AgentContext, build_debate_block
from app.core.llm import get_llm


@tool
def search_technique(topic: str) -> str:
    """检索调酒技法/术语/知识卡片。topic 为技法名或术语。"""
    from app.rag.retriever import retrieve_once
    res = retrieve_once(topic, limit=3)
    if not res.docs:
        return f"知识库未收录 '{topic}' 的教学内容。"
    lines = []
    for d in res.docs[:3]:
        body = d.content_cn or d.content
        body = body[:200]
        if d.collection == "knowledge" and d.meta.get("doc_type") == "technique":
            lines.append(f"[技法] {d.title}\n{body}")
        elif d.collection == "cocktails":
            lines.append(f"[配方] {d.title}\n步骤: {body}")
        else:
            lines.append(f"{d.title}\n{body}")
    return "\n\n".join(lines)


@tool
def get_cocktail_steps(name: str) -> str:
    """获取指定鸡尾酒的完整调制步骤（面向教学）。"""
    from app.rag.retriever import retrieve_once
    res = retrieve_once(name, limit=2)
    if not res.docs:
        return f"未找到 '{name}' 的做法。"
    d = res.docs[0]
    ing = str(d.meta.get('ingredients', ''))[:200]
    step = (d.content_cn or d.content)[:300]
    return f"{d.title}\n材料: {ing}\n做法:\n{step}"


@tool
def finalize_lesson(conclusion: str) -> str:
    """给出教学讲解的最终结论。"""
    return conclusion


def _grounded_lesson(ctx: AgentContext) -> str:
    """Render actual upstream cards when the model cannot synthesize them."""
    lessons = []
    for doc in ctx.retrieved[:4]:
        body = (doc.content_cn or doc.content or "").strip()
        if doc.collection == "cocktails":
            ingredients = doc.meta.get("ingredients_text") or doc.meta.get("ingredients") or ""
            prefix = f"材料：{ingredients}\n" if ingredients else ""
            lessons.append(f"{doc.title}\n{prefix}{body}".strip())
        elif body:
            lessons.append(f"{doc.title}\n{body}")
    if not lessons:
        return "现有知识卡不足以支持这个教学问题，我先不编造步骤。"
    return "根据已检索到的标准知识卡：\n\n" + "\n\n".join(lessons)


def _answer_from_upstream_evidence(ctx: AgentContext, debate: dict | None) -> None:
    evidence = "\n\n".join(
        f"[{doc.collection}:{doc.pk}] {doc.evidence_text()}" for doc in ctx.retrieved[:5]
    )
    system = """你是耐心但不死板的调酒老师。直接回答用户当前的问题。
只能依据给定知识卡；步骤、用量和技法原理不得凭记忆补写。讲清楚动作、判断标准和常见错误，
不要复述内部流程，不要调用工具。"""
    if debate:
        system += build_debate_block(debate)
    from app.services.mixology_constraints import constraint_prompt_block
    constraints_text = constraint_prompt_block(ctx.extra.get("constraints"))
    prompt = (
        f"{system}\n\n【总控共享约束交接单】\n{constraints_text}"
        f"\n\n【上游检索证据】\n{evidence}\n\n用户问题：{ctx.user_query}"
    )
    try:
        response = get_llm(temperature=0.3, max_tokens=800).invoke(prompt)
        ctx.final_answer = str(response.content or "").strip()
        if not ctx.final_answer:
            raise ValueError("empty grounded lesson")
        ctx.extra["capability_mode"] = "model"
    except Exception:
        ctx.final_answer = _grounded_lesson(ctx)
        ctx.extra["capability_mode"] = "local_retrieval"
        ctx.extra["local_validated"] = True
        ctx.add_event("教学模型不可用，已使用共享知识卡回答")
    ctx.references = [doc.to_reference() for doc in ctx.retrieved]


def run_tutor_agent(ctx: AgentContext, debate: dict | None = None) -> AgentContext:
    """执行教学讲解 Agent 的 reAct 循环。"""
    if ctx.retrieved:
        _answer_from_upstream_evidence(ctx, debate)
        ctx.add_event("教学讲解完成")
        return ctx

    from langgraph.prebuilt import create_react_agent

    tools = [search_technique, get_cocktail_steps, finalize_lesson]
    system = """你是一个耐心的小白调酒老师。负责讲解调酒技法、术语和具体做法。

原则：
1. 先检索知识卡片再讲解，不凭记忆编造步骤
2. 讲解要分步骤、通俗，假设用户是第一次调酒
3. 术语给出中英对照（如"摇和法 Shake"）
4. 可提示难度等级与新手建议（呼应用户成长）
5. 用 finalize_lesson 收尾，结论清晰有条理
6. 【性能】工具已内置检索，一次调用拿全信息，避免反复调工具；
   信息足够就直接 finalize_lesson 收尾"""
    if debate:
        system += build_debate_block(debate)
    from app.services.mixology_constraints import constraint_prompt_block
    system += "\n\n【总控共享约束交接单】\n" + constraint_prompt_block(
        ctx.extra.get("constraints")
    )
    agent = create_react_agent(model=get_llm(temperature=0.3, max_tokens=800),
                               tools=tools, prompt=system)

    try:
        # recursion_limit 留足步数，防误截断正常 reAct；防空转靠 prompt
        result = agent.invoke({"messages": [HumanMessage(content=ctx.user_query)]},
                              config={"recursion_limit": 20})
        final = next((m.content for m in reversed(result["messages"])
                      if getattr(m, "type", "") == "ai" and m.content), "")
        ctx.final_answer = final or "(教学讲解未给出结论)"
    except Exception:
        if ctx.retrieved:
            from app.services.deterministic_chat import build_deterministic_answer
            from app.core.context import get_current_session
            profile = get_current_session().get("profile") or {}
            fallback = build_deterministic_answer(
                ctx.user_query, ctx.retrieved, ctx.history, profile=profile,
            )
            ctx.final_answer = fallback.answer
            ctx.extra["recipe"] = fallback.recipe
            ctx.add_event("模型不可用，已使用标准配方步骤")
        else:
            ctx.final_answer = "当前模型服务暂时不可用，请提供具体配方名，我可以用本地配方库给出完整步骤。"
    return ctx


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ctx = AgentContext(user_query="新手怎么学摇和法？", history=[])
    run_tutor_agent(ctx)
    print(ctx.final_answer)
