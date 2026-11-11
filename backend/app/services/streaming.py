# -*- coding: utf-8 -*-
"""SSE 流式编排：把"六 Agent 协同"过程实时推到前端。

M4 的展示灵魂：不是等全部算完才返回一个答案，
而是每经过一个节点就推一条事件（总控判断 → 专业 Agent 执行中 → 审校 → 答案），
前端像看"幕后"一样看到多 Agent 是怎么协作的。这也复用了 M6 的可观测事件流。

实现：
- graph.stream(stream_mode="updates") 按节点产出状态增量
- 生成器经队列从 worker 线程喂给 SSE（图是阻塞的同步调用，不能占住事件循环）
- ContextVars 在 worker 线程内通过 copy_context 隔离设置（并发安全）
- 任一环节失败（LLM 未配置 / Milvus 未起）→ 优雅发 error 事件，而非 500
"""
from __future__ import annotations

import contextvars
import logging
import time
import uuid
import json
import queue
import re
import threading

from app.core.events import agent_event, done_event, error_event, partial_event, sse_format, status_event
from app.core.config import settings


logger = logging.getLogger(__name__)


def _build_initial(user_query: str, history: list[dict] | None,
                   user_id: str | None, session_id: str | None) -> dict:
    return {
        "user_query": user_query,
        "history": history or [],
        "user_id": user_id,
        "session_id": session_id,
        "agent_outputs": [],
        "events": [],
        "references": [],
        "revise_count": 0,
    }


def _produce(graph, initial: dict, q: "queue.Queue", cancelled: threading.Event) -> None:
    """在 worker 线程中执行图，把 SSE 事件按节点推进写入队列。"""
    seen: set[str] = set()          # 已推送过的事件（按内容去重，兼容非累计返回）
    final_answer = ""
    references: list[str] = []
    structured_recipe: dict | None = None
    structured_recipes: list[dict] = []
    creative_brief: dict = {}
    capability_mode = "unavailable"
    retrieval_meta: dict = {}
    citation_docs: dict[str, object] = {}
    trace: list[dict[str, object]] = []

    # LLM 用量打点范围：这轮图执行里的所有模型调用归到该任务/用户
    from app.core.usage import usage_scope
    with usage_scope(task="agent_chat", user=initial.get("user_id") or ""):
        # updates: 节点结束后的状态增量（总控判断/审校 verdict 等）
        # custom:  节点执行中的实时事件（专业 Agent 开始/完成——不等节点跑完）
        #   之前只 stream updates，run_specialists 是单一大节点，内部 3-4 个
        #   reAct Agent 串行跑完（200s+）才 emit，前端一直"思考中"。custom 事件
        #   让每个 Agent 开始/完成实时推出来，体验从"卡死"变"看得见进度"。
        for item in graph.stream(initial, stream_mode=["updates", "custom"]):
            if cancelled.is_set():
                return
            # 多模式流返回 (mode, chunk) 二元组；兼容单 dict（测试 mock/旧格式）
            if isinstance(item, tuple):
                mode, chunk = item
            else:
                mode, chunk = "updates", item
            if mode == "custom":
                # 节点内 writer() 推送的自定义事件（实时，不等节点结束）。
                # 同一事件也会出现在该节点 updates 的 events 里，用 seen 去重，
                # 保证只推送一次（实时那次）。
                if isinstance(chunk, dict):
                    if chunk.get("kind") == "agent_event":
                        msg = chunk["message"]
                        if msg not in seen:
                            agent = chunk.get("agent", "specialists")
                            q.put(sse_format(agent_event(agent, msg)))
                            trace.append({"agent": agent, "message": msg})
                            seen.add(msg)
                    elif chunk.get("kind") == "partial":
                        # 最终答案流式片段：实时推给前端（打字机式展示）
                        text = chunk.get("text") or ""
                        if text:
                            q.put(sse_format(partial_event(text)))
                continue

            for node, payload in chunk.items():
                # 新产生的事件（增量推送）
                for e in (payload.get("events") or []):
                    if e not in seen:
                        q.put(sse_format(agent_event(node, e)))
                        trace.append({"agent": node, "message": e})
                        seen.add(e)

                # 节点级状态（给前端看"现在到哪一步了"）
                if node == "orchestrator" and payload.get("plan"):
                    plan = payload["plan"]
                    need_clarify = bool(getattr(plan, "need_clarify", False))
                    intent_value = getattr(getattr(plan, "intent", None), "value", "other")
                    if need_clarify:
                        tag = "（继续确认创作需求）" if intent_value == "create" else "（需要澄清）"
                    else:
                        tag = "（简单问题，直接回答）" if plan.simple else "（走多 Agent 协同）"
                    q.put(sse_format(status_event(f"总控判断: {intent_value} {tag}")))
                    if payload.get("retrieved"):
                        message = f"检索 Agent 已提供 {len(payload['retrieved'])} 个真实候选"
                        if message not in seen:
                            q.put(sse_format(agent_event("retriever", message)))
                            trace.append({"agent": "retriever", "message": message})
                            seen.add(message)
                if node == "direct_answer":
                    q.put(sse_format(status_event("简单问题：直接回答")))
                if node == "creative":
                    q.put(sse_format(status_event("原创配方已完成创作与审校")))
                if node == "specialists":
                    q.put(sse_format(status_event("专业 Agent 执行中...")))
                if node == "reviewer" and payload.get("review_verdict"):
                    message = f"独立审校完成：{payload['review_verdict']}"
                    q.put(sse_format(status_event(message, agent="reviewer")))
                    trace.append({"agent": "reviewer", "message": message})
                if node == "debate":
                    n = payload.get("revise_count", 0)
                    q.put(sse_format(status_event(f"审校发现问题，进入圆桌讨论（第 {n} 轮）")))

                # 捕获最终答案与引用（done 事件用）
                if payload.get("final_answer"):
                    final_answer = payload["final_answer"]
                if payload.get("references"):
                    references = payload.get("references") or []
                if payload.get("retrieved"):
                    for doc in payload.get("retrieved") or []:
                        citation_docs[f"{doc.collection}:{doc.pk}"] = doc
                if payload.get("retrieval_meta"):
                    retrieval_meta = payload.get("retrieval_meta") or {}
                if payload.get("recipe"):
                    structured_recipe = payload["recipe"]
                if payload.get("recipes"):
                    structured_recipes = payload["recipes"]
                if payload.get("creative_brief"):
                    creative_brief = payload["creative_brief"]
                if payload.get("capability_mode"):
                    capability_mode = payload["capability_mode"]

    # 多级内容校验：答案命中高危建议 → 附免责提示（不改变主答案）
    if final_answer:
        from app.core.guard import guard_output
        guard = guard_output(final_answer)
        if guard["issues"]:
            final_answer = f"{final_answer}\n\n⚠️ {guard['tips']}"

    # 若答案像配方 → 抽结构化配方卡（失败则无卡，纯文本展示）
    recipe = structured_recipe
    if final_answer and recipe is None:
        try:
            from app.services.recipe_card import card_to_dict, extract_recipe_card
            recipe = card_to_dict(extract_recipe_card(final_answer))
        except Exception:
            recipe = None

    public_references = []
    for ref in references:
        match = re.match(r"\[([^:\]]+):([^\]]+)\]", str(ref))
        doc = citation_docs.get(f"{match.group(1)}:{match.group(2)}") if match else None
        public_references.append(doc.to_citation() if doc else ref)

    q.put(sse_format(done_event(final_answer, public_references, agent_trace=trace, recipe=recipe,
                                recipes=structured_recipes,
                                creative_brief=creative_brief,
                                capability_mode=capability_mode,
                                retrieval=retrieval_meta)))


def stream_agent_response(user_query: str, history: list[dict] | None = None,
                          user_id: str | None = None, session_id: str | None = None,
                          stock: list[str] | None = None,
                          profile: dict | None = None):
    """生成器：按图执行进度产出 SSE 事件字符串。

    Args:
        user_query: 用户本轮提问
        history:    之前几轮的对话（记忆上下文）
        user_id:    用户名（库存/画像/历史按它隔离）
        stock:      用户库存材料列表（None = 未设置）
        profile:    用户口味画像（None = 未设置）
    """
    from app.core.context import reset_current_session, set_current_session

    q: "queue.Queue" = queue.Queue()
    cancelled = threading.Event()
    trace_id = str(uuid.uuid4())
    started = time.perf_counter()
    ctx = contextvars.copy_context()
    initial = _build_initial(user_query, history, user_id, session_id)

    def _inner() -> None:
        from app.graph.graph import get_graph
        token = set_current_session(user_id=user_id, session_id=session_id,
                                    stock=stock, profile=profile)
        try:
            graph = get_graph()
            _produce(graph, initial, q, cancelled)
        finally:
            reset_current_session(token)

    def worker() -> None:
        try:
            ctx.run(_inner)
        except Exception:
            logger.exception("agent stream worker failed")
            q.put(sse_format(error_event(
                "本轮处理链路暂时不可用。已停止生成，不会用未经验证的内容补答。"
            )))
        finally:
            q.put(None)  # 结束哨兵

    threading.Thread(target=worker, daemon=True).start()

    def enrich(chunk: str) -> str:
        if not chunk.startswith("data: "):
            return chunk
        try:
            event = json.loads(chunk[6:])
            event["trace_id"] = trace_id
            event["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
            return sse_format(json.dumps(event, ensure_ascii=False))
        except Exception:
            return chunk

    yield enrich(sse_format(status_event("思考中...")))
    try:
        while True:
            remaining = settings.AGENT_TIMEOUT_SECONDS - (time.perf_counter() - started)
            if remaining <= 0:
                cancelled.set()
                yield enrich(sse_format(error_event("处理超时，请缩短问题或稍后重试")))
                break
            try:
                item = q.get(timeout=min(1.0, remaining))
            except queue.Empty:
                continue
            if item is None:
                break
            yield enrich(item)
    finally:
        cancelled.set()


def _parse_sse_event(chunk: str) -> dict | None:
    """解析一条 SSE 字符串为事件 dict（供持久化捕获 done 答案）。"""
    if chunk.startswith("data: "):
        try:
            return json.loads(chunk[6:])
        except json.JSONDecodeError:
            return None
    return None
