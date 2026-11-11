# -*- coding: utf-8 -*-
"""LangGraph 六 Agent 状态图编排——项目灵魂所在。

这是"真智能"与"写死流程"的分水岭：
状态转移（是否检索/调哪个 Agent/是否回炉）由总控 LLM 决策，
而不是代码 if-else 决定。LangGraph 提供状态管理与有条件转移。

图结构：
```
                  ┌─────────────────────────┐
                  │       START             │
                  └───────────┬─────────────┘
                              ▼
                  ┌─────────────────────────┐
                  │   orchestrator_node     │  总控: 意图+准入线+路由
                  └───────────┬─────────────┘
                    ┌─────────┼──────────┐
              simple│      clarify │     complex
                    ▼         ▼         ▼
         ┌──────────────┐  ┌──────────┐  ┌──────────────────┐
         │ direct_answer│  │ clarify  │  │ route_to_agents  │  按 plan 并行/顺序
         │    node      │  │  node    │  │  (dispatch)      │
         └──────┬───────┘  └────┬─────┘  └────────┬─────────┘
                │               │                 ▼
                │               │        ┌────────────────────┐
                │               │        │ retriever / stock / │  专业 Agent 节点
                │               │        │ flavor / tutor      │  (可并行)
                │               │        └─────────┬──────────┘
                │               │                  ▼
                │               │        ┌────────────────────┐
                │               │        │   reviewer_node     │  审校: 一致性+引用
                │               │        └───────┬────────────┘
                │               │       revise(圆桌讨论,<2)│   │pass
                │               │            ▲         │    ▼
                │               │            │         └──► END
                │               │       (debate: 被点名 Agent 轮流
                │               │        发言互见、修订后交回审校)
                ▼               ▼
             ┌──────────────────────────────┐
             │            END               │
             └──────────────────────────────┘
```

反思自纠循环（圆桌讨论版）：审校发现 revise → 被点名 Agent 进入讨论桌，
串行轮流发言（能看到彼此的立场和审校修正指令），修订后交回审校判定是否
收敛；最多 REVISE_LIMIT 轮（防死循环）。这就是"审校发现问题 → Agent 协商
修正"的落地，比旧"回炉重跑"更进一步：Agent 之间真实对话而非各说各话。
"""
from __future__ import annotations

import re

from langgraph.graph import END, StateGraph

from app.agents.base import AgentContext
from app.agents.orchestrator_agent import plan_query
from app.agents.retriever_agent import run_retriever_agent
from app.agents.reviewer_agent import ReviewVerdict, check_and_revise
from app.agents.stock_agent import run_stock_agent
from app.agents.flavor_agent import run_flavor_agent
from app.agents.tutor_agent import run_tutor_agent
from app.graph.state import AgentOutput, GraphState

REVISE_LIMIT = 2  # 圆桌讨论最大轮数（每轮 = 被点名 Agent 轮流发言 + 审校收敛判定；防死循环）


# ---------- 节点 ----------

def _prefetch_retrieve(query: str, history: list[dict] | None = None,
                       stock: list[str] | None = None,
                       profile: dict | None = None) -> dict:
    """无 LLM 的轻量预取检索：直接 retrieve_once 拿候选（供 specialists 复用）。

    v2 并行架构的核心：检索不再等总控判断完才启动，而是与 plan_query 并行跑。
    retrieve_once 内部：候选充足则跳过 decompose（无 LLM），Milvus 检索 ~0.3s；
    候选不足才触发 decompose（1 次 LLM）。总耗时被 orchestrator 的 LLM 判断掩盖。
    """
    try:
        from app.services.deterministic_chat import (
            find_named_recipe, is_preference_query, recommend_many_for_query,
            resolve_recipe_context,
        )
        from app.rag.hybrid import HybridRetriever
        from app.services.recipe_catalog import get_recipe
        context = resolve_recipe_context(query, history)
        from app.agents.orchestrator_agent import _explicitly_asks_for_inventory
        if _explicitly_asks_for_inventory(query) or _explicitly_asks_for_inventory(context.query):
            from app.services.deterministic_chat import build_inventory_answer
            inventory = build_inventory_answer(
                context.query, stock or [], context.recommendation_count,
                profile=profile or {}, exclude_recipe_ids=context.exclude_recipe_ids,
            )
            if inventory.docs:
                return {
                    "docs": inventory.docs,
                    "references": [doc.to_reference() for doc in inventory.docs],
                    "events": [f"已按真实库存与口味画像筛选 {len(inventory.docs)} 款候选"],
                    "effective_query": context.query,
                    "contextual_followup": context.followup,
                    "excluded_recipe_ids": sorted(context.exclude_recipe_ids),
                    "retrieval_meta": {"mode": "inventory_catalog", "confidence": 1.0,
                                       "field_coverage": 1.0, "candidate_count": len(inventory.docs),
                                       "missing_fields": []},
                }
        recipe = get_recipe(context.selected_recipe_id) if context.selected_recipe_id else None
        if recipe is None and not context.followup:
            recipe = find_named_recipe(query)
        recipes = [recipe] if recipe else []
        if not recipes and is_preference_query(context.query):
            # One answer still needs a real choice. Give the flavor Agent a
            # diverse grounded shortlist instead of preselecting one catalog row
            # and asking the model to rationalize it after the fact.
            shortlist_count = max(context.recommendation_count, 5)
            recipes = recommend_many_for_query(
                context.query, shortlist_count, context.exclude_recipe_ids,
                profile=profile,
            )
        if recipes:
            docs = [HybridRetriever._cocktail_doc(item, 1.0) for item in recipes]
            return {"docs": docs, "references": [doc.to_reference() for doc in docs],
                    "events": [f"已结合会话上下文匹配 {len(recipes)} 款不同配方" if context.followup
                               else f"本地配方目录匹配完成（{len(recipes)} 款）"],
                    "effective_query": context.query,
                    "contextual_followup": context.followup,
                    "excluded_recipe_ids": sorted(context.exclude_recipe_ids),
                    "retrieval_meta": {"mode": "recipe_catalog", "confidence": 1.0,
                                       "field_coverage": 1.0, "candidate_count": len(docs),
                                       "missing_fields": []}}
        from app.rag.retriever import retrieve_once
        res = retrieve_once(context.query, limit=5)
        evidence_ready = res.confidence >= 0.72 and not res.missing_fields
        docs = res.docs if evidence_ready else []
        references = res.references if evidence_ready else []
        events = list(res.events)
        if res.docs and not evidence_ready:
            events.append("预取候选相关性不足，转入完整反思检索")
        return {"docs": docs, "references": references,
                "events": events, "effective_query": context.query,
                "contextual_followup": context.followup,
                "excluded_recipe_ids": sorted(context.exclude_recipe_ids),
                "retrieval_meta": {"mode": res.retrieval_mode,
                                   "confidence": res.confidence,
                                   "field_coverage": res.field_coverage,
                                   "candidate_count": len(docs),
                                   "missing_fields": res.missing_fields}}
    except Exception:
        return {"docs": [], "references": [], "events": []}


def orchestrator_node(state: GraphState) -> GraphState:
    """总控：意图识别 + 准入线 + 路由，与预取检索并行执行。

    v2 并行架构：plan_query（LLM 判断）与 _prefetch_retrieve（无 LLM 检索）
    用线程并行跑——复杂问题几乎总需要候选，检索提前开始；若 plan 显示
    无需检索（简单问题/澄清），预取结果直接丢弃。省掉"总控→检索"的串行等待。
    """
    from app.core.context import get_current_session
    session = get_current_session()
    stock = session.get("stock")
    profile = session.get("profile") or {}
    current_query = state["user_query"]

    from app.services.creative_dialogue import creation_goal_in_history, has_creation_goal
    from app.agents.orchestrator_agent import needs_model_context_resolution
    history = state.get("history", [])
    creative_turn = has_creation_goal(current_query) or creation_goal_in_history(history)
    if creative_turn:
        # Requirement discovery is model-led and does not consume catalog retrieval.
        # recipe_gen selects grounded structural references only after confirmation.
        plan = plan_query(current_query, history, stock=stock)
        prefetch = {"docs": [], "references": [], "events": [],
                    "effective_query": current_query}
    elif needs_model_context_resolution(current_query):
        # Elliptical questions need semantic resolution before retrieval. Running
        # retrieval in parallel on the raw phrase would rank generic catalog rows
        # before the model has recovered the active scene from the previous turn.
        plan = plan_query(current_query, history, stock=stock)
        resolved = plan.resolved_query or current_query
        if plan.need_retrieve and not plan.simple and not plan.need_clarify:
            prefetch = _prefetch_retrieve(resolved, [], stock, profile)
        else:
            prefetch = {"docs": [], "references": [], "events": [],
                        "effective_query": resolved}
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_plan = ex.submit(plan_query, current_query, history, stock=stock)
            f_retr = ex.submit(_prefetch_retrieve, current_query, history, stock, profile)
            plan = f_plan.result()
            prefetch = f_retr.result()

    resolved_query = (plan.resolved_query or prefetch.get("effective_query")
                      or current_query).strip()
    from app.services.mixology_constraints import build_mixology_constraints
    if resolved_query != current_query:
        handoff = build_mixology_constraints(resolved_query, [], stock or [], profile)
        handoff.source_query = current_query
        handoff.contextual_followup = plan.context_relation != "standalone"
    else:
        handoff = build_mixology_constraints(current_query, history, stock or [], profile)
    if prefetch.get("excluded_recipe_ids"):
        handoff.excluded_recipe_ids = sorted(set(handoff.excluded_recipe_ids) | set(
            prefetch["excluded_recipe_ids"]
        ))

    events = [f"总控判断: {plan.intent.value}" + ("（简单问题）" if plan.simple else "")]
    if plan.need_clarify:
        events.append("共同创作需求尚需确认" if plan.intent.value == "create" else "问题存在关键歧义")
    elif plan.context_relation == "previous_turn":
        events.append("已识别为承接上一轮场景")
    elif plan.context_relation == "prior_recipe":
        events.append("已定位到先前推荐结果")

    out: GraphState = {
        "plan": plan,
        "direct_answer": plan.direct_answer,
        "effective_query": handoff.effective_query,
        "contextual_followup": handoff.contextual_followup,
        "excluded_recipe_ids": handoff.excluded_recipe_ids,
        "constraint_handoff": handoff.model_dump(),
        "retrieval_meta": prefetch.get("retrieval_meta", {}),
        "events": events,
    }
    # 只有计划明确需要检索时才接收预取候选。共同创作的需求确认与生成
    # 使用 recipe_gen 自己的结构参考，不能把普通推荐候选混进创作状态。
    if prefetch["docs"] and plan.need_retrieve and not plan.simple and not plan.need_clarify:
        out["retrieved"] = prefetch["docs"]
        out["references"] = prefetch["references"]
        events.append(f"预取检索完成（{len(prefetch['docs'])} 条候选）")
    return out


def direct_answer_node(state: GraphState) -> GraphState:
    """简单问题：不走多 Agent，直接回答。"""
    plan = state.get("plan")
    query = state.get("user_query") or ""
    answer = state.get("direct_answer") or ""
    # A standalone chitchat turn must not revive a cocktail preference merely
    # because an older assistant mentioned it. If the planner leaked that topic,
    # regenerate from the current user message only; the response remains model-
    # authored without falling back to a canned sentence.
    drink_topic = re.compile(r"鸡尾酒|调酒|喝一杯|来一杯|口味|酸甜|甜辣|酒款")
    user_mentions_drink = bool(re.search(r"酒|喝|调|配方|推荐", query))
    if (plan and plan.intent.value == "chitchat"
            and plan.context_relation == "standalone"
            and not user_mentions_drink and drink_topic.search(answer)):
        try:
            from app.core.llm import get_llm
            response = get_llm(temperature=0.55, max_tokens=220).invoke([
                ("system", "自然回应用户本轮这句话。只谈当前话题，不引用历史，不强行转向鸡尾酒，像朋友聊天，不用客服套话。"),
                ("human", query),
            ])
            answer = str(response.content or "").strip() or answer
        except Exception:
            pass
    return {
        "final_answer": answer or "我在听。你想从哪里聊起？",
        "capability_mode": plan.capability_mode if plan else "unavailable",
    }


def clarify_node(state: GraphState) -> GraphState:
    """需要澄清：反问用户。"""
    from langgraph.config import get_stream_writer
    plan = state.get("plan")
    q = plan.clarify_question if plan else "您能说得更具体一点吗？"
    writer = get_stream_writer()
    streamed = ""
    if plan and plan.capability_mode == "model" and plan.intent.value == "create":
        try:
            from app.services.creative_dialogue import stream_creative_clarification
            for text in stream_creative_clarification(
                    state["user_query"], plan.creative_brief, q):
                streamed += text
                writer({"kind": "partial", "text": text})
        except Exception:
            # If a provider disconnects after yielding tokens, keep the honest
            # partial answer instead of duplicating it with a second response.
            pass
    if not streamed:
        # Local mode is useful but is never presented as model token streaming.
        parts = [part for part in q.split("\n\n") if part]
        for index, part in enumerate(parts):
            writer({"kind": "partial", "text": part + ("\n\n" if index < len(parts) - 1 else "")})
    else:
        q = streamed
    return {
        "final_answer": q,
        "creative_brief": plan.creative_brief if plan else {},
        "capability_mode": plan.capability_mode if plan else "unavailable",
    }


def creative_node(state: GraphState) -> GraphState:
    """Confirmed co-creation: create, validate and independently review one original recipe."""
    from langgraph.config import get_stream_writer
    from app.services.recipe_gen import generate_recipe

    plan = state.get("plan")
    writer = get_stream_writer()

    def on_event(event: dict) -> None:
        writer({
            "kind": "agent_event",
            "agent": event.get("stage") or "create",
            "message": event.get("title") or event.get("detail") or "创作处理中",
        })

    result = generate_recipe(
        plan.creative_preferences or state["user_query"],
        base_spirits=plan.creative_base_spirits,
        creative_brief=plan.creative_brief,
        on_event=on_event,
    )
    if not result.get("ok"):
        return {
            "final_answer": result.get("error") or "这次原创配方没有通过审校，我没有把未达标结果交给你。",
            "events": ["共同创作未通过最终审校"],
            "creative_brief": result.get("brief") or {},
            "capability_mode": result.get("capability_mode") or "unavailable",
        }

    recipe = result["recipe"]
    name = recipe.get("name_cn") or recipe.get("name") or "原创鸡尾酒"
    review = result.get("review") or {}
    answer = (
        f"需求确认后，我们共同完成了「{name}」。\n\n"
        f"{recipe.get('description') or ''}\n\n"
        f"创作判断：{review.get('intent_match') or '已按确认的风味与材料约束完成。'}\n"
        "完整材料和分步调制已经整理在下方配方卡中。"
    )
    for paragraph in answer.split("\n\n"):
        writer({"kind": "partial", "text": paragraph + "\n\n"})
    return {
        "final_answer": answer,
        "recipe": recipe,
        "creative_brief": result.get("brief") or {},
        "capability_mode": result.get("capability_mode") or "unavailable",
        "events": [f"原创配方完成，经过 {result.get('attempts', 1)} 轮创作与审校"],
    }


def dispatch_node(state: GraphState) -> GraphState:
    """分发：根据 plan 决定本轮要跑哪些专业 Agent（把计划写进状态）。"""
    plan = state.get("plan")
    plan.need_retrieve if plan else False
    return {"events": ["开始多 Agent 协同..."]}


# 专业 Agent 中文标签（SSE 事件展示用）
_AGENT_LABEL = {
    "retriever": "检索 Agent",
    "stock": "库存推荐 Agent",
    "flavor": "风味分析 Agent",
    "tutor": "教学讲解 Agent",
}


def run_specialists(state: GraphState) -> GraphState:
    """专业 Agent 执行节点：按 plan 决定调哪些，结果写入 agent_outputs。

    两阶段执行（性能优化）：
    - 阶段 A：检索 Agent 单独先跑。它的 multi_round 检索含 CPU 重的 rerank，
      单独跑无争抢最快；结果（候选配方）作为"中间产物"传给下游。
    - 阶段 B：库存/风味/教学 Agent 并行。库存/风味直接复用检索候选
      （拼进 prompt 让 LLM 分析，不重复检索），教学独立检索技法知识。
      这样下游不再各自烧一次 CPU rerank（实测 flavor 从 ~110s 降到 ~15s），
      并行只并发 LLM（远程 API，不抢本地 CPU）。

    子线程用 contextvars.copy_context() 继承会话上下文（stock 读库存、
    flavor/tutor 读画像），否则 ContextVars 隔离会让子线程拿空。

    事件实时性：开始事件主线程直接 writer 推送；完成事件放线程安全 queue，
    主线程等待时实时 drain 推送——writer 只在主线程调用，避免跨线程并发。
    """
    import contextvars as _cv
    import queue as _queue
    from concurrent.futures import ThreadPoolExecutor

    from langgraph.config import get_stream_writer
    writer = get_stream_writer()
    plan = state.get("plan")
    query = state["user_query"]
    outputs: list[AgentOutput] = list(state.get("agent_outputs", []))
    structured_recipe: dict | None = None
    structured_recipes: list[dict] = []
    answer_capability = ""
    specialist_capabilities: list[str] = []
    # 只返回本轮新增事件（events 是 append reducer，返回完整列表会与状态累积重复）
    new_events: list[str] = []

    # 注：修订/纠错不再由本节点承担——审校判定 revise 后进"圆桌讨论"节点
    # （debate_node：Agent 互相可见地轮流发言、回应质疑、修订结论）。
    # 本节点只在首轮执行一次（orchestrator → dispatch → specialists → reviewer）。

    # 用户画像注入：从会话上下文读取，注入推荐 prompt（画像自适应）
    from app.core.context import get_current_session
    from app.services.profile import apply_profile_to_prompt
    session = get_current_session()
    profile = session.get("profile") or {}
    continuous_query = state.get("effective_query") or query
    effective_query = apply_profile_to_prompt(profile, continuous_query) if profile else continuous_query
    constraint_handoff = state.get("constraint_handoff") or {}

    def _push(agent: str, message: str) -> None:
        writer({"kind": "agent_event", "agent": agent, "message": message})

    # ---- 候选准备：优先复用 orchestrator 已预取的候选（零等待）----
    # v2：检索已在总控阶段与 plan_query 并行完成（_prefetch_retrieve），
    # 这里不再跑 retriever 的 reAct LLM 循环（省 2 次 LLM ~10-20s）。
    # - 推荐/教学场景：下游 stock/flavor/tutor 基于候选回答，retriever 只给摘要
    # - 纯查询场景（无下游 Agent）：用候选直接生成答案（单次 LLM，快）
    # - 预取失败且 plan 需要检索：补跑完整 reAct 兜底
    if not state.get("retrieved") and plan.need_retrieve:
        _push("retriever", f"→ {_AGENT_LABEL['retriever']} 开始")
        ctx_r = AgentContext(user_query=continuous_query, history=state.get("history", []),
                             extra={"constraints": constraint_handoff})
        run_retriever_agent(ctx_r)
        _push("retriever", f"{_AGENT_LABEL['retriever']}完成")
        outputs.append(AgentOutput(agent="retriever", content=ctx_r.final_answer,
                                   meta={"references": ctx_r.references}))
        # 中间产物传递：检索候选进状态，阶段 B 的 stock/flavor 复用
        state["retrieved"] = ctx_r.retrieved
        state["references"] = ctx_r.references
        answer_capability = str(ctx_r.extra.get("capability_mode") or "")
        new_events.extend(ctx_r.events)
    elif state.get("retrieved"):
        docs = state["retrieved"]
        has_downstream = bool(plan.need_stock or plan.need_flavor or plan.need_teach)
        if has_downstream:
            summary = "知识库候选:\n" + "\n".join(f"- {d.title}" for d in docs[:5])
            outputs.append(AgentOutput(agent="retriever", content=summary,
                                       meta={"references": state.get("references", [])}))
            new_events.append(f"检索完成（{len(docs)} 条候选）")
        else:
            # 配方/口味问题优先用结构化数据直接回答，模型不可用也能给完整步骤。
            from app.services.deterministic_chat import (
                build_deterministic_answer, should_answer_with_recipe,
            )
            if should_answer_with_recipe(query, docs, state.get("history", [])):
                fallback = build_deterministic_answer(
                    query, docs, state.get("history", []), profile=profile,
                )
                outputs.append(AgentOutput(agent="retriever", content=fallback.answer,
                                           meta={"references": state.get("references", [])}))
                structured_recipe = fallback.recipe
                structured_recipes = fallback.recipes
                evidence = fallback.docs or ([fallback.doc] if fallback.doc else [])
                if evidence:
                    state["retrieved"] = evidence
                    state["references"] = [doc.to_reference() for doc in evidence]
                for part in fallback.parts:
                    writer({"kind": "partial", "text": part})
                new_events.append(f"结构化配方匹配完成（{len(structured_recipes) or 1} 款）")
                answer_capability = "local_retrieval"
                docs = []

            # 非配方知识问答仍让模型润色；连接失败时回退到证据原文。
            if not docs:
                pass
            else:
                from app.core.llm import get_llm
                cand_lines = []
                for d in docs[:5]:
                    body = (d.content_cn or d.content or "")[:150]
                    cand_lines.append(f"- {d.title}: {body}")
                prompt = (f"你是知识渊博的调酒师。基于下面的【知识库检索结果】回答用户问题："
                          f"有观点、有推理、自然连贯，像朋友聊天；只能使用检索结果里的事实，"
                          f"禁止编造检索结果没有的配方/用量/度数。\n\n"
                          f"用户问题：{query}\n\n【知识库检索结果】\n{chr(10).join(cand_lines)}")
                try:
                    resp = get_llm(temperature=0.3, max_tokens=700).invoke(prompt)
                    outputs.append(AgentOutput(agent="retriever", content=resp.content,
                                               meta={"references": state.get("references", [])}))
                    new_events.append(f"检索完成（{len(docs)} 条候选）")
                    answer_capability = "model"
                except Exception:
                    fallback = build_deterministic_answer(
                        query, docs, state.get("history", []), profile=profile,
                    )
                    outputs.append(AgentOutput(agent="retriever", content=fallback.answer,
                                               meta={"references": state.get("references", [])}))
                    structured_recipe = fallback.recipe
                    structured_recipes = fallback.recipes
                    evidence = fallback.docs or ([fallback.doc] if fallback.doc else [])
                    if evidence:
                        state["references"] = [doc.to_reference() for doc in evidence]
                    for part in fallback.parts:
                        writer({"kind": "partial", "text": part})
                    new_events.append("模型不可用，已切换本地证据回答")
                    answer_capability = "local_retrieval"

    # ---- 阶段 B：库存/风味/教学并行（复用检索候选）----
    stage_b: list[tuple[str, str, callable]] = []
    if plan.need_stock:
        stage_b.append(("stock", effective_query, run_stock_agent))
    if plan.need_flavor:
        stage_b.append(("flavor", effective_query, run_flavor_agent))
    if plan.need_teach:
        stage_b.append(("tutor", effective_query, run_tutor_agent))

    if stage_b:
        for name, _, _ in stage_b:
            _push(name, f"→ {_AGENT_LABEL[name]} 开始")

        done_q: "_queue.Queue[tuple[str, AgentContext]]" = _queue.Queue()
        results_b: dict[str, AgentContext] = {}

        def _run_agent(name: str, user_query: str, fn: callable,
                       inherited_context: _cv.Context) -> None:
            def _inner() -> None:
                # 异常兜底：子线程必须把结果放回队列，否则主线程 done_q 空转
                # 会永远等不到结果（"一直思考"事故）。任一 Agent 内部报错都要
                # 把错误写进 final_answer 正常收尾，而不是让请求挂死。
                cc = AgentContext(user_query=user_query,
                                  history=state.get("history", []),
                                  retrieved=state.get("retrieved", []),
                                  extra={"constraints": constraint_handoff})
                try:
                    fn(cc)
                except Exception as e:
                    import traceback
                    cc.final_answer = (
                        f"{_AGENT_LABEL.get(name, name)}当前不可用，"
                        "本轮不会用未经验证的内容代替它的结论。"
                    )
                    cc.events.append(f"{name}异常: {traceback.format_exc()[-300:]}")
                finally:
                    done_q.put((name, cc))

            inherited_context.run(_inner)

        with ThreadPoolExecutor(max_workers=len(stage_b)) as ex:
            # Context must be captured on this request thread. Calling
            # copy_context() inside a pool worker only copies that worker's empty
            # context, which drops the user's inventory and taste profile.
            futs = {
                ex.submit(_run_agent, n, uq, fn, _cv.copy_context()): n
                for n, uq, fn in stage_b
            }
            pending = len(futs)
            while pending > 0:
                try:
                    name, cc = done_q.get(timeout=0.2)
                except _queue.Empty:
                    continue
                pending -= 1
                results_b[name] = cc
                _push(name, f"{_AGENT_LABEL[name]}完成")
            for f in futs:
                f.result()  # run_xxx_agent 内部已 try/except，正常不抛

        if plan.need_stock:
            ctx = results_b["stock"]
            outputs.append(AgentOutput(agent="stock", content=ctx.final_answer))
            new_events.extend(ctx.events)
            specialist_capabilities.append(str(
                ctx.extra.get("capability_mode") or ctx.extra.get("capability") or "unavailable"
            ))
            if ctx.extra.get("recipes"):
                structured_recipes = ctx.extra.get("recipes") or []
            if ctx.extra.get("docs"):
                state["retrieved"] = ctx.extra["docs"]
                state["references"] = [doc.to_reference() for doc in ctx.extra["docs"]]
            if ctx.extra.get("local_validated"):
                structured_recipes = ctx.extra.get("recipes") or []
                evidence = ctx.extra.get("docs") or []
                if evidence:
                    state["retrieved"] = evidence
                    state["references"] = [doc.to_reference() for doc in evidence]
                # A deterministic evidence answer is complete by construction.
                # Do not send it to an unavailable reviewer model or append errors
                # from other model-dependent specialists.
                result = {
                    "agent_outputs": [AgentOutput(agent="stock", content=ctx.final_answer,
                                                  meta={"capability": "local_inventory"})],
                    "events": new_events + ["本地库存证据链完成"],
                    "references": state.get("references", []),
                    "retrieved": state.get("retrieved", []),
                    "retrieval_meta": state.get("retrieval_meta", {}),
                    "final_answer": ctx.final_answer,
                    "recipes": structured_recipes,
                    "local_validated": True,
                    "capability_mode": "local_inventory",
                }
                for part in [ctx.final_answer[:160], ctx.final_answer[160:]]:
                    if part:
                        writer({"kind": "partial", "text": part})
                return result
        if plan.need_flavor:
            ctx = results_b["flavor"]
            outputs.append(AgentOutput(agent="flavor", content=ctx.final_answer))
            new_events.extend(ctx.events)
            specialist_capabilities.append(str(ctx.extra.get("capability_mode") or "unavailable"))
            if ctx.extra.get("recipe"):
                structured_recipe = ctx.extra["recipe"]
            if ctx.extra.get("recipes"):
                structured_recipes = ctx.extra["recipes"]
        if plan.need_teach:
            ctx = results_b["tutor"]
            outputs.append(AgentOutput(agent="tutor", content=ctx.final_answer))
            new_events.extend(ctx.events)
            specialist_capabilities.append(str(ctx.extra.get("capability_mode") or "unavailable"))

    if specialist_capabilities:
        from app.core.capabilities import combine_capability_modes
        answer_capability = combine_capability_modes(answer_capability, *specialist_capabilities)

    new_events.append("专业 Agent 完成，进入审校" if stage_b else "专业 Agent 完成")
    result = {
        "agent_outputs": outputs,
        "events": new_events,
        # 引用来源必须随节点 update 输出，否则 streaming 的 done 事件拿不到
        "references": state.get("references", []),
        "retrieved": state.get("retrieved", []),
        "retrieval_meta": state.get("retrieval_meta", {}),
    }
    if structured_recipe:
        result["recipe"] = structured_recipe
    if len(structured_recipes) > 1:
        result["recipes"] = structured_recipes
    if answer_capability:
        result["capability_mode"] = answer_capability
    # 只有检索 Agent 产出时，它已经负责带来源收尾；不再额外调用审校 LLM。
    # 这样普通知识问答/无库存推荐少一次远程往返。
    if not stage_b and outputs:
        result["final_answer"] = outputs[-1].content
    return result


def _enrich_references(references: list[str], retrieved: list) -> list[str]:
    """把检索候选的材料/要点附加到引用后（仅审校可见，不进前端引用）。

    为什么：references 只带标题（`[cocktails:14482] Darkwood Sling`），审校
    看不到候选内容，无法核实下游 Agent 提到的材料细节 → 误判"引用不实" →
    回炉空转（实测 revise 死循环 + 空答案）。附上材料后，引用真实性校验才有据。
    """
    if not retrieved:
        return list(references)
    by_key: dict[str, object] = {}
    for d in retrieved:
        by_key[f"{d.collection}:{d.pk}"] = d
    out: list[str] = []
    for ref in references:
        m = re.match(r"\[([^:\]]+):([^\]]+)\]", ref)
        if m:
            d = by_key.get(f"{m.group(1)}:{m.group(2)}")
            if d is not None and d.collection == "cocktails":
                ing = d.meta.get("ingredients_text") or d.meta.get("ingredients") or ""
                if ing:
                    out.append(f"{ref}\n    材料: {str(ing)[:300]}")
                    continue
        out.append(ref)
    return out


def reviewer_node(state: GraphState) -> GraphState:
    """审校：一致性 + 引用校验 + 决定是否进圆桌讨论。"""
    current_query = state["user_query"]
    query = state.get("effective_query") or current_query
    outputs: list[AgentOutput] = state.get("agent_outputs", [])
    references: list[str] = state.get("references", [])

    # 引用内容增强：让审校能核实材料级描述（见 _enrich_references）
    review_refs = _enrich_references(references, state.get("retrieved", []))

    # 按 Agent 名去重取最新（agent_outputs 是 append reducer：每轮讨论会追加
    # 新发言，旧条目仍留在列表里；审校只看每个 Agent 的最新结论）。
    latest_outputs = [(o.agent, o.content) for o in _latest_outputs(outputs).values()]
    constraints = state.get("constraint_handoff") or {}
    result = check_and_revise(query, latest_outputs, review_refs, constraints=constraints)

    nxt = {
        "review_verdict": result.verdict.value,
        "review_issues": result.issues,
        "revise_instructions": result.revise_instructions,
        "revise_agents": result.revise_agents,
        "revise_count": state.get("revise_count", 0),
    }

    # 流式生成最终答案（v2.1）：判定完成后，答案由 LLM 边生成边推 partial 事件，
    # 前端实时逐字显示；SSE 之外（invoke/测试）writer 为 no-op，行为不变。
    from app.agents.reviewer_agent import stream_final_answer
    from langgraph.config import get_stream_writer
    try:
        writer = get_stream_writer()
        final = stream_final_answer(
            current_query, latest_outputs, review_refs, result.issues, writer,
            constraints=constraints, history=state.get("history", []),
            resolved_query=query,
        )
    except Exception:
        final = ""
    if final:
        nxt["final_answer"] = final
    else:
        # 流式失败兜底：用审校的整合答案；仍无则原文拼接（绝不空回复）
        nxt["final_answer"] = result.final_answer or \
            "\n\n".join(c for _, c in latest_outputs)
    from app.core.capabilities import combine_capability_modes
    upstream_mode = state.get("capability_mode") or "unavailable"
    if result.review_mode == "model":
        nxt["capability_mode"] = combine_capability_modes(upstream_mode, "model")
    elif final:
        nxt["capability_mode"] = "model_unreviewed"
    elif upstream_mode.startswith("local_"):
        nxt["capability_mode"] = "local_unreviewed"
    else:
        nxt["capability_mode"] = "unavailable"
    return nxt


# ---------- 条件边 ----------

def route_after_orchestrator(state: GraphState) -> str:
    """总控后路由：简单→直接答；需澄清→反问；复杂→多 Agent。"""
    plan = state.get("plan")
    if plan.intent.value == "create" and plan.creation_ready:
        return "creative"
    if (plan.simple and not plan.need_clarify
            and not plan.need_retrieve and not plan.need_stock
            and not plan.need_flavor and not plan.need_teach):
        return "direct"
    if plan.need_clarify:
        return "clarify"
    return "specialists"


def route_after_specialists(state: GraphState) -> str:
    """检索-only 请求直接结束，其余复杂请求进入审校。"""
    if state.get("local_validated") and state.get("final_answer"):
        return "fast"
    plan = state.get("plan")
    if (plan and not plan.need_stock and not plan.need_flavor
            and not plan.need_teach and state.get("agent_outputs")):
        return "fast"
    return "reviewer"


def route_after_review(state: GraphState) -> str:
    """审校后路由：revise 且未超限 → 圆桌讨论（debate）；否则 → END。"""
    verdict = state.get("review_verdict")
    if verdict == ReviewVerdict.REVISE.value and state.get("revise_count", 0) < REVISE_LIMIT:
        return "debate"
    return "pass"


# 圆桌讨论：可参与讨论的"结论类" Agent（retriever 只产候选，不参与立场讨论）
_CONCLUSION_AGENTS = ("stock", "flavor", "tutor")


def _latest_outputs(outputs: list[AgentOutput]) -> dict[str, AgentOutput]:
    """按 Agent 名去重取最新输出（agent_outputs 是 append reducer，旧条目会残留）。"""
    latest: dict[str, AgentOutput] = {}
    for o in outputs:
        latest[o.agent] = o
    return latest


def debate_node(state: GraphState) -> GraphState:
    """圆桌讨论节点：审校点名的 Agent 串行轮流发言，互相可见，修订后交回审校。

    这是"自由对话"的落地：每个被点名 Agent 都能看到其他 Agent 的发言
    （以及审校的修正指令），先回应质疑再给出修订版结论；发言记录写入
    state["debate"]，供下一轮讨论与 SSE 展示。轮数由 route_after_review
    按 revise_count < REVISE_LIMIT 限制，防死循环。

    与旧"回炉重跑"的区别：
    - 旧：修正指令注入后静默重跑同一个 Agent，彼此看不到对方
    - 新：被点名 Agent 在"讨论桌"上轮流发言，后发言者能看到先发言者的
      立场并回应/反驳/采纳——协商收敛，而不是各说各话
    """
    from app.agents.base import AgentContext
    from app.core.context import get_current_session
    from app.services.profile import apply_profile_to_prompt

    query = state.get("effective_query") or state["user_query"]
    outputs = list(state.get("agent_outputs", []))
    debate_msgs = list(state.get("debate", []))
    revise_agents = list(state.get("revise_agents") or [])
    revise_instructions = list(state.get("revise_instructions") or [])
    round_no = state.get("revise_count", 0) + 1

    latest = _latest_outputs(outputs)
    # 参与者：审校点名 ∩ 结论类 Agent；未点名（LLM 漏填）则全部结论 Agent 参与
    participants = [a for a in revise_agents if a in _CONCLUSION_AGENTS] \
        if revise_agents else [a for a in latest if a in _CONCLUSION_AGENTS]

    if not participants:
        return {"events": ["[圆桌讨论] 无结论类 Agent 可讨论，跳过"],
                "revise_count": round_no}

    session = get_current_session()
    profile = session.get("profile") or {}
    run_map = {"stock": run_stock_agent, "flavor": run_flavor_agent,
               "tutor": run_tutor_agent}
    new_outputs: list[AgentOutput] = []

    # 串行轮流发言：后发言者能看到先发言者的内容（真对话感）
    for name in participants:
        prior = latest[name].content if name in latest else ""
        others = [m for m in debate_msgs if m["speaker"] != name]
        cc = AgentContext(
            user_query=apply_profile_to_prompt(profile, query) if profile else query,
            history=state.get("history", []),
            retrieved=state.get("retrieved", []),
            extra={"constraints": state.get("constraint_handoff") or {}},
        )
        try:
            run_map[name](cc, debate={
                "prior_output": prior,
                "other_speeches": others,
                "revise_instructions": revise_instructions,
            })
        except Exception as e:
            cc.final_answer = f"({_AGENT_LABEL.get(name, name)}讨论发言异常: {e})"
        debate_msgs.append({"speaker": name, "content": cc.final_answer,
                            "round": round_no})
        new_outputs.append(AgentOutput(agent=name, content=cc.final_answer))

    return {
        # 只返回本轮新增发言（append reducer 追加；审校侧按 agent 去重取最新）
        "agent_outputs": new_outputs,
        "debate": debate_msgs,
        "revise_count": round_no,
        "events": [f"[圆桌讨论 第{round_no}轮] " +
                   " → ".join(f"{_AGENT_LABEL.get(p, p)}发言" for p in participants)],
    }


# ---------- 构图 ----------

def build_graph():
    """构建完整六 Agent 状态图。"""
    g = StateGraph(GraphState)

    g.add_node("orchestrator", orchestrator_node)
    g.add_node("direct_answer", direct_answer_node)
    g.add_node("clarify", clarify_node)
    g.add_node("creative", creative_node)
    g.add_node("dispatch", dispatch_node)
    g.add_node("specialists", run_specialists)
    g.add_node("reviewer", reviewer_node)
    g.add_node("debate", debate_node)

    g.set_entry_point("orchestrator")

    g.add_conditional_edges("orchestrator", route_after_orchestrator,
                            {"direct": "direct_answer", "clarify": "clarify",
                             "creative": "creative", "specialists": "dispatch"})

    g.add_edge("direct_answer", END)
    g.add_edge("clarify", END)
    g.add_edge("creative", END)
    g.add_edge("dispatch", "specialists")
    g.add_conditional_edges("specialists", route_after_specialists,
                            {"fast": END, "reviewer": "reviewer"})

    g.add_conditional_edges("reviewer", route_after_review,
                            {"debate": "debate", "pass": END})

    # 圆桌讨论后交回审校：基于修订后的 Agent 输出再审校（收敛判定）
    g.add_edge("debate", "reviewer")

    return g


_graph = None


def get_graph():
    """全局单例：编译后的可执行图（构建一次复用）。

    注意：必须是 .compile() 之后的 CompiledStateGraph 才有 .invoke/.stream。
    StateGraph 只是构建器，直接调用会报 "has no attribute"。
    """
    global _graph
    if _graph is None:
        _graph = build_graph().compile()
    return _graph


def run_agent_system(user_query: str, history: list[dict] | None = None,
                     user_id: str | None = None, session_id: str | None = None,
                     stock: list[str] | None = None,
                     profile: dict | None = None) -> dict:
    """顶层入口：跑完整多 Agent 系统，返回最终结果。

    供 API 层（M4）调用，也供测试验证。返回含 final_answer / events / references。
    """
    from app.core.context import set_current_session

    token = set_current_session(user_id=user_id, session_id=session_id,
                                stock=stock, profile=profile)
    try:
        graph = get_graph()
        initial: GraphState = {
            "user_query": user_query,
            "history": history or [],
            "user_id": user_id,
            "session_id": session_id,
            "agent_outputs": [],
            "events": [],
            "references": [],
            "revise_count": 0,
        }
        final = graph.invoke(initial)
        return {
            "final_answer": final.get("final_answer", ""),
            "events": final.get("events", []),
            "references": final.get("references", []),
            "recipe": final.get("recipe"),
            "recipes": final.get("recipes", []),
            "revise_count": final.get("revise_count", 0),
            "verdict": final.get("review_verdict", ""),
        }
    finally:
        # 清理 ContextVars，防并发污染
        from app.core.context import reset_current_session
        reset_current_session(token)
