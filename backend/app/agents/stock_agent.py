# -*- coding: utf-8 -*-
"""库存推荐 Agent：结合用户库存 + 口味画像，推荐能调的鸡尾酒。

职责（对应六 Agent 里的"库存推荐"）:
- 先看用户库存（防幻觉约束：不凭空推荐，先看手头有什么）
- 结合口味画像（M3.5）过滤/排序
- 检索知识库里的配方，匹配"库存能覆盖哪些"
- 给出推荐清单 + 每款的覆盖度说明（缺的材料也如实告知）

reAct 工具设计:
- get_stock:           读用户当前库存（先看库存）
- get_profile:         读用户口味画像（偏好/忌口）
- search_cocktails:    按材料检索可调配方
- finalize_recommend:  给出推荐结论
LLM 自主决定调用顺序与次数。
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from app.agents.base import AgentContext, build_debate_block
from app.core.llm import get_llm


@tool
def get_stock() -> str:
    """读取用户当前库存（酒水与配料）。先看库存再推荐。"""
    # 注：调用方（streaming/图）已把库存塞进会话上下文；没设置时默认空，
    #    不要给默认库存，否则会把"用户没库存"误判成"有威士忌/柠檬"。
    from app.core.context import get_current_session
    session = get_current_session()
    stock = session.get("stock") or []
    if not stock:
        return ("库存为空。用户还没有添加任何酒水配料。"
                "请引导用户：在左侧栏添加库存，或直接询问用户手头有哪些酒和材料。"
                "【禁止】不要编造'检索服务不可用/系统故障/后台异常/稍后重试'等理由——"
                "库存为空不是系统故障，如实告知并引导即可。")
    return "当前库存: " + ", ".join(stock)


@tool
def get_profile() -> str:
    """读取用户口味画像（偏好/忌口/历史反馈）。"""
    from app.core.context import get_current_session
    session = get_current_session()
    profile = session.get("profile", {})
    if not profile:
        return "暂无画像。用户尚未透露口味偏好。"
    parts = [f"{k}: {v}" for k, v in profile.items()]
    return "口味画像: " + "; ".join(parts)


@tool
def search_cocktails(preferences: str) -> str:
    """按用户偏好/库存检索可调的鸡尾酒配方。preferences 描述口味或材料偏好。"""
    # 用 retrieve_once（单轮）而非 multi_round_retrieve：推荐场景首轮候选已够，
    # 且上游检索 Agent 已做过完整反思检索，这里轻量即可，避免双重多轮拖慢。
    from app.rag.retriever import retrieve_once
    res = retrieve_once(preferences, limit=5)
    if not res.docs:
        return "知识库无匹配配方。"
    lines = [f"{d.title}  (来源: {d.to_reference()})" for d in res.docs[:5]]
    return "可考虑配方:\n" + "\n".join(lines)


@tool
def finalize_recommend(conclusion: str) -> str:
    """综合库存与检索结果，给出最终推荐结论。"""
    return conclusion


# 系统提示词提为常量：直接生成路径（有候选）与 reAct 路径共用角色设定。
_STOCK_SYSTEM = """你是店里的首席调酒师 Leo——专业、热情、会聊天，像朋友一样给建议。

【人格要求 · 回答要有"人味"不要模板】
- 先接住用户的场景/情绪（"夏天想来杯清爽的？懂你"），再讲推理，最后给建议
- 推理要具体：为什么是这几杯（你的库存能覆盖什么、风味怎么搭、缺什么）
- 禁止"推荐1: xxx\n推荐2: xxx"式干巴巴的列表，用自然连贯的话讲，像真人聊天
- 仍要说清材料/做法要点，让小白照着能做

职责与原则：
1. 先看库存再推荐，不凭空推荐
2. 推荐 2-3 款，每款说明：为什么适合/覆盖了哪些库存材料
3. 库存缺少的材料要如实说明（"需要再买"），不强行凑配方
4. 结合口味画像调整（偏好甜就多推甜型，忌口就避开）
5. 结论要具体可操作，适合小白
6. 【铁律】候选/知识库没有的具体用量（毫升/盎司/几份）和酒精度，一律不编数字，
   用定性描述（"度数较低""适合新手"）替代。说材料有没有、适合不适合可以，编克数不行
7. 【铁律】库存为空时，如实告诉用户"还没添加库存"，引导其添加或列出材料；
   绝不允许说"检索服务不可用/系统故障/后台异常/稍后重试"——那不是事实"""


def _build_stock_system(ctx: AgentContext, debate: dict | None) -> str:
    """统一构造 system：角色 + 库存/画像 + 候选 + 圆桌讨论上下文。

    库存与画像直接注入 system（而非让 LLM 调 get_stock/get_profile 工具再读），
    prompt 强制"一次收尾"——reAct 结构保留（工具仍可用），但 LLM 首轮即可
    基于注入信息直接 finalize，实测省 1-2 次 LLM 往返（每次 2-20s 不等）。
    """
    from app.core.context import get_current_session

    system = _STOCK_SYSTEM
    session = get_current_session()
    stock = session.get("stock") or []
    profile = session.get("profile") or {}
    stock_text = "、".join(stock) if stock else "（暂无库存）"
    profile_text = ("; ".join(f"{k}: {v}" for k, v in profile.items())
                    if profile else "（暂无画像）")
    system += f"\n\n【我的库存】{stock_text}\n【我的口味画像】{profile_text}"
    from app.services.mixology_constraints import constraint_prompt_block
    system += "\n\n【总控共享约束交接单】\n" + constraint_prompt_block(
        ctx.extra.get("constraints")
    )
    if ctx.retrieved:
        cand_lines = []
        for d in ctx.retrieved[:5]:
            ing = str(d.meta.get("ingredients_text")
                      or d.meta.get("ingredients") or "")[:200]
            cand_lines.append(f"- {d.title}（{ing}）")
        cand_text = "\n".join(cand_lines)
        system += (f"\n\n【上游检索 Agent 提供的候选配方】\n{cand_text}\n\n"
                   "候选已包含所需信息，无需再调用 search_cocktails；"
                   "只依据候选内容，不编造。")
    if debate:
        system += build_debate_block(debate)
    system += """

reAct 执行要点：
1. 库存与画像已注入上方【我的库存】【我的口味画像】，无需调用 get_stock/get_profile
2. 候选/讨论信息已注入上方，无需调用 search_cocktails
3. 直接基于以上信息，用 finalize_recommend 一次性收尾，结论要具体可操作
4. 【性能】不要再调用任何工具，首轮直接收尾（库存为空时如实引导，不编造系统故障）"""
    return system


def run_stock_agent(ctx: AgentContext, debate: dict | None = None) -> AgentContext:
    """执行库存推荐 Agent 的 reAct 循环（统一入口）。

    已有检索候选时直接单次生成；只有没有候选时才使用工具循环补充检索。
    """
    from langgraph.prebuilt import create_react_agent

    def requested_count(constraints: dict) -> int:
        count = int(constraints.get("target_count") or 1)
        # A first inventory exploration should present a small choice set;
        # an elliptical replacement turn should return exactly one replacement.
        return count if count > 1 or constraints.get("contextual_followup") else 3

    def local_fallback() -> AgentContext:
        from app.core.context import get_current_session
        from app.services.deterministic_chat import build_inventory_answer
        session = get_current_session()
        constraints = ctx.extra.get("constraints") or {}
        result = build_inventory_answer(
            ctx.user_query, session.get("stock") or [],
            count=requested_count(constraints),
            profile=session.get("profile") or {},
            exclude_recipe_ids=set(constraints.get("excluded_recipe_ids") or []),
        )
        ctx.final_answer = result.answer
        ctx.extra.update(local_validated=True, recipes=result.recipes,
                         docs=result.docs, capability="local_inventory")
        ctx.add_event("模型不可用，库存 Agent 已切换本地可验证匹配")
        return ctx

    from app.core.context import get_current_session
    from app.services.deterministic_chat import build_inventory_answer
    session = get_current_session()
    constraints = ctx.extra.get("constraints") or {}
    grounded = build_inventory_answer(
        ctx.user_query, session.get("stock") or [],
        count=requested_count(constraints),
        profile=session.get("profile") or {},
        exclude_recipe_ids=set(constraints.get("excluded_recipe_ids") or []),
    )
    # The stock specialist receives its own inventory-filtered evidence set.
    # Generic retrieval candidates must not override actual stock constraints.
    ctx.retrieved = grounded.docs
    ctx.references = [doc.to_reference() for doc in grounded.docs]
    ctx.extra.update(recipes=grounded.recipes, docs=grounded.docs,
                     capability="grounded_inventory")
    if not grounded.docs:
        ctx.final_answer = grounded.answer
        ctx.extra.update(local_validated=True, capability="local_inventory")
        ctx.add_event("库存证据不足，已如实返回而未调用生成模型")
        return ctx
    system = _build_stock_system(ctx, debate)

    # 上游已经给出候选时，不再启动 ReAct（至少一次工具调用 + 一次后续 LLM）。
    # 这是推荐链路最常见的路径，直接生成可减少 1~2 次远程往返。
    if ctx.retrieved:
        try:
            prompt = (f"{system}\n\n用户需求：{ctx.user_query}\n\n"
                      "请直接给出最终推荐，不要调用工具。")
            resp = get_llm(temperature=0.3, max_tokens=800).invoke(prompt)
            ctx.final_answer = getattr(resp, "content", "") or "(库存推荐未给出结论)"
            if not ctx.final_answer.strip():
                raise ValueError("empty grounded inventory answer")
            from app.services.recipe_catalog import all_recipes
            allowed_ids = {str(doc.pk) for doc in grounded.docs}
            mentioned_ids = {
                str(recipe.get("id"))
                for recipe in all_recipes()
                if any(
                    name and len(name) >= 3 and name.lower() in ctx.final_answer.lower()
                    for name in (recipe.get("name"), recipe.get("name_cn"))
                )
            }
            if not mentioned_ids or not mentioned_ids <= allowed_ids:
                raise ValueError("inventory model answer escaped grounded candidates")
            ctx.extra["capability_mode"] = "model"
        except Exception as e:
            return local_fallback()
        ctx.add_event("库存推荐完成")
        return ctx

    tools = [get_stock, get_profile, search_cocktails, finalize_recommend]
    try:
        agent = create_react_agent(model=get_llm(temperature=0.3, max_tokens=800),
                                   tools=tools, prompt=system)
        # recursion_limit 留足步数，防误截断正常 reAct；防空转靠 prompt
        result = agent.invoke({"messages": [HumanMessage(content=ctx.user_query)]},
                              config={"recursion_limit": 20})
        final = next((m.content for m in reversed(result["messages"])
                      if getattr(m, "type", "") == "ai" and m.content), "")
        ctx.final_answer = final or "(库存推荐未给出结论)"
    except Exception as e:
        return local_fallback()
    ctx.add_event("库存推荐完成")
    return ctx


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ctx = AgentContext(user_query="我用这些能调什么酒？", history=[])
    run_stock_agent(ctx)
    print(ctx.final_answer)
