# -*- coding: utf-8 -*-
"""RAG 检索 Agent：第一个完整 reAct 循环的 Agent。

职责（对应六 Agent 里的"RAG 检索"）:
- 结合会话历史，把用户提问改写为可检索查询
- 拆解复杂问题、混合检索、重排（搜索-阅读-反思-再搜索）
- 无结果时：决定是公网检索补充（M4 接 API）还是 LLM 兜底
- 返回带引用来源的知识片段，供下游 Agent 使用

reAct 循环设计:
  本 Agent 提供的"工具"是三个能力边界清晰的工具：
    search_knowledge  混合检索 + 重排（带反思轮数上限）
    search_web        公网补充（M4 接入真实 API，此处预留）
    answer_final      信息足够，直接给出检索结论
  LLM 通过 reAct 循环自主决定：搜几次、要不要公网、何时收尾。

注：M3 会把本 Agent 挂进 LangGraph 状态图；此处先独立可跑，
    便于单独验证 reAct 循环是否正确。
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.agents.base import AgentContext
from app.core.llm import get_llm
from app.core.registry import get_prompt
from app.rag.retriever import multi_round_retrieve

# 系统提示词来自 Prompt 注册中心（M6）
SYSTEM_PROMPT = get_prompt("retriever")["system"]

# 检索结果引用在工具返回文本里的前缀（tool message 里每行一个）
_REF_PREFIX = "来源: "


def _extract_references(text: str) -> list[str]:
    """从 search_knowledge 工具返回文本里解析引用来源。

    工具返回形如 `[i] 标题\n内容\n来源: [cocktails:1] Margarita (score=0.123)`，
    解析 `[collection:pk] 标题 (score=…)` 引用，供调用方按引用回取结构化文档。
    """
    if not text:
        return []
    refs = []
    for line in text.splitlines():
        if _REF_PREFIX in line:
            refs.append(line.split(_REF_PREFIX, 1)[1].strip())
    return refs


@tool
def search_knowledge(query: str) -> str:
    """在鸡尾酒知识库中混合检索。返回命中片段及引用来源。"""
    res = multi_round_retrieve(query)
    # 中间产物传递：结果不跨上下文暂存（ContextVar 传不回调用方，实测失效），
    # 而是把引用写进返回文本，调用方按引用回取结构化文档传给下游 Agent。
    if not res.docs:
        return "知识库无命中。建议尝试其他关键词，或使用 search_web 查公网。"
    lines = []
    for i, d in enumerate(res.docs):
        content = d.evidence_text(500)
        # 截断到 200 字：完整长文会让 reAct 后续每轮 LLM 都背着大上下文，
        # 显著拖慢响应。引用来源保留完整（下游按引用回取全字段文档）。
        lines.append(f"[{i + 1}] {d.title}\n{content[:200]}\n来源: {d.to_reference()}")
    return "\n\n".join(lines)


@tool
def search_web(query: str) -> str:
    """公网检索补充（Tavily Search API）。当知识库查不到时，用此工具查公网。

    需要配置 TAVILY_API_KEY（见 .env.example）；未配置时返回未启用提示。
    公网结果视为参考信息，不可信；与知识库冲突时以知识库为准。
    """
    from app.core.config import settings

    api_key = settings.TAVILY_API_KEY
    if not api_key:
        return f"公网检索未配置（TAVILY_API_KEY 为空），无法联网。可在知识库尝试更精确的关键词：{query}"
    import httpx
    from app.core.security import detect_injection, sanitize_input
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": 3,
                  "search_depth": "basic", "include_answer": False},
            timeout=15,
        )
        resp.raise_for_status()
        results = (resp.json() or {}).get("results", [])
    except Exception as e:
        return f"公网检索失败: {e}"
    if not results:
        return f"公网无结果: {query}"
    lines = []
    for i, r in enumerate(results[:3]):
        title = sanitize_input(r.get("title") or "(无标题)") or "(无标题)"
        content = sanitize_input(r.get("content") or "")[:200].strip()
        # 公网内容视为不可信输入：命中注入特征（改写指令等）→ 不把原文喂给 LLM
        if detect_injection(content):
            content = "（该公网结果疑似包含指令性内容，正文已忽略）"
        url = sanitize_input(r.get("url") or "")
        lines.append(f"[公网{i + 1}] {title}\n{content}\n来源: {url}")
    return ("\n\n".join(lines) +
            "\n\n（公网内容为参考信息，不可信；与知识库冲突时以知识库为准，需标注来源）")


@tool
def answer_final(conclusion: str) -> str:
    """信息足够，用此工具收尾，conclusion 是完整结论。"""
    return conclusion


def run_retriever_agent(ctx: AgentContext) -> AgentContext:
    """执行检索并回答。

    常规命中路径直接“检索一次 + LLM 总结一次”，避免 ReAct 先决策工具、
    再观察结果、再收尾的额外远程往返；知识库无命中时才保留 ReAct 作为
    公网检索兜底。
    """
    from app.services.mixology_constraints import constraint_prompt_block
    constraints_text = constraint_prompt_block(ctx.extra.get("constraints"))

    # 常规路径：检索逻辑本身已经包含拆解/重排/反思，不需要再让 LLM 决定
    # 是否调用 search_knowledge。这样普通问题通常从 3 次模型调用降到 2 次
    # （总控 + 本次答案生成），并且把历史真正传给查询改写器。
    try:
        res = multi_round_retrieve(ctx.user_query, history=ctx.history, limit=5)
        if res.docs:
            ctx.retrieved = res.docs
            ctx.references = res.references
            evidence = "\n\n".join(
                f"[{i + 1}] {d.evidence_text(900)}\n"
                f"来源: {d.to_reference()}"
                for i, d in enumerate(res.docs[:5])
            )
            prompt = (
                f"{SYSTEM_PROMPT}\n\n"
                "系统已完成知识库检索，以下内容是可信候选。请直接回答用户，"
                "不要调用工具，不要要求用户先填写库存；只有用户明确询问库存时才参考库存。\n\n"
                f"【总控共享约束交接单】\n{constraints_text}\n\n"
                f"用户问题：{ctx.user_query}\n\n检索结果：\n{evidence}"
            )
            resp = get_llm(temperature=0, max_tokens=900).invoke(prompt)
            ctx.final_answer = getattr(resp, "content", "") or "(检索 Agent 未给出结论)"
            ctx.add_event("检索完成")
            return ctx

        # 无本地命中时不要再次重复整套 ReAct 检索。没有公网 key 就直接
        # 诚实返回“暂未找到”，避免为了一个空结果再付出多次 LLM 往返。
        from app.core.config import settings
        if not settings.TAVILY_API_KEY:
            ctx.final_answer = "我暂时没有在本地知识库找到足够可靠的相关配方，暂不编造具体答案。"
            ctx.add_event("知识库无命中")
            return ctx

        web_text = search_web.invoke({"query": ctx.user_query})
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            "本地知识库没有命中，下面是公网参考信息。请明确标注它是公网参考，"
            "不要把不确定内容说成事实，也不要要求用户先填写库存。\n\n"
            f"【总控共享约束交接单】\n{constraints_text}\n\n"
            f"用户问题：{ctx.user_query}\n\n公网参考：\n{web_text}"
        )
        resp = get_llm(temperature=0, max_tokens=900).invoke(prompt)
        ctx.final_answer = getattr(resp, "content", "") or "暂未找到可靠答案。"
        ctx.add_event("公网参考完成")
        return ctx
    except Exception as fast_error:
        ctx.add_event(f"快速检索路径失败，切换兜底: {type(fast_error).__name__}")
        if "res" in locals() and res.docs:
            from app.services.deterministic_chat import build_deterministic_answer
            from app.core.context import get_current_session
            profile = get_current_session().get("profile") or {}
            fallback = build_deterministic_answer(
                ctx.user_query, res.docs, ctx.history, profile=profile,
            )
            ctx.retrieved = [fallback.doc] if fallback.doc else res.docs
            ctx.references = ([fallback.doc.to_reference()] if fallback.doc else res.references)
            ctx.final_answer = fallback.answer
            ctx.extra["recipe"] = fallback.recipe
            ctx.add_event("模型不可用，已切换结构化配方回答")
            return ctx

    # 知识库无命中时保留 ReAct，允许按原设计尝试公网检索。
    from langgraph.prebuilt import create_react_agent

    tools = [search_knowledge, search_web, answer_final]
    agent = create_react_agent(model=get_llm(temperature=0), tools=tools,
                               prompt=SYSTEM_PROMPT)

    # 历史拼入（改写需要）
    history_text = "\n".join(f"{h['role']}: {h['content']}" for h in ctx.history[-5:])
    user_msg = (
        f"【总控共享约束交接单】\n{constraints_text}\n\n"
        f"用户提问：{ctx.user_query}"
        + (f"\n\n对话历史：\n{history_text}" if history_text else "")
    )

    try:
        # recursion_limit 只作兜底防死循环，不能截断正常 reAct：实测 limit=6/12
        # 都会被 DeepSeek 的工具调用循环耗尽，答案退化成 "Sorry, need more
        # steps"（准确性事故）。25 步对正常流程（1 次检索+1 次收尾）绰绰有余，
        # 防空转交给 prompt 强约束。
        result = agent.invoke({"messages": [HumanMessage(content=user_msg)]},
                              config={"recursion_limit": 25})
        # 取最后一条 AI 消息作为结论
        final = None
        for msg in reversed(result["messages"]):
            if getattr(msg, "type", "") == "ai" and msg.content:
                final = msg.content
                break
        ctx.final_answer = final or "(检索 Agent 未给出结论)"
        ctx.add_event("检索完成")
        # 中间产物传递：工具在 LangGraph 内部上下文/线程执行，ContextVar 传不回，
        # 改为从工具返回消息里解析引用，再按引用回取完整结构化文档（见
        # HybridRetriever.get_by_references）。下游 stock/flavor 据此复用候选，
        # 不必各自重复检索（省 CPU rerank + LLM 时间，详见 run_specialists）。
        refs: list[str] = []
        for msg in result["messages"]:
            if getattr(msg, "type", "") == "tool" and getattr(msg, "name", "") == "search_knowledge":
                parsed = _extract_references(getattr(msg, "content", ""))
                if parsed:
                    refs = parsed  # 取最后一次检索的候选（多轮反思的最优集）
        if refs:
            from app.rag.hybrid import get_retriever
            docs = get_retriever().get_by_references(refs)
            if docs:
                ctx.retrieved = docs
                ctx.references = refs
    except Exception:
        ctx.final_answer = "当前模型服务暂时不可用，本地知识库也没有足够证据回答这个问题。"
        ctx.add_event("模型不可用，且本地无可靠命中")

    return ctx


# 供测试 / M3 状态图复用的轻量入口
if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    ctx = AgentContext(user_query="青柠 朗姆 薄荷 能调什么？", history=[])
    run_retriever_agent(ctx)
    print("=== events ===")
    for e in ctx.events:
        print(" -", e)
    print("=== answer ===")
    print(ctx.final_answer)
