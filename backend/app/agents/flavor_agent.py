# -*- coding: utf-8 -*-
"""风味搭配/替代 Agent：风味平衡分析 + 推理式材料替代（M5 深化）。

职责（对应六 Agent 里的"风味搭配替代"）:
- 风味平衡分析：酸甜苦烈的骨架分析，判断一个配方是否平衡
- 推理式材料替代：不只给替代品，还解释"为什么能替"
  （风味相似/功能等价/浓度对应），依据来自知识库的替代规则

reAct 工具:
- analyze_flavor:     分析配方的风味平衡（基于知识库 + 规则）
- suggest_substitute: 检索替代规则，解释替代逻辑
- finalize_flavor:    给出风味/替代结论

M5 会用规则引擎 + 替代图深化；这里先搭 reAct 循环 + 检索式替代。
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.agents.base import AgentContext, build_debate_block
from app.core.llm import get_llm


@tool
def analyze_flavor(cocktail_name: str) -> str:
    """分析指定鸡尾酒的风味平衡（酸甜苦烈 + 口感）。"""
    from app.rag.retriever import retrieve_once
    res = retrieve_once(cocktail_name, limit=3)
    if not res.docs:
        return f"知识库中未找到 '{cocktail_name}' 的详细配方，无法精确分析风味。"
    doc = res.docs[0]
    ing = str(doc.meta.get('ingredients', ''))[:200]
    return (f"配方: {doc.title}\n"
            f"材料: {ing}\n"
            f"风味画像字段: {doc.meta.get('flavor_profile', '未标注')}")

@tool
def suggest_substitute(ingredient: str, reason: str = "") -> str:
    """为指定材料建议可替代材料，并解释替代逻辑。"""
    from app.rag.retriever import retrieve_once
    res = retrieve_once(f"{ingredient} 替代", limit=3)
    if not res.docs:
        return f"知识库未收录 '{ingredient}' 的替代规则。"
    lines = []
    for d in res.docs[:3]:
        body = d.content_cn or d.content
        lines.append(f"{d.title}\n{body[:200]}")
    return "\n\n".join(lines)


@tool
def finalize_flavor(conclusion: str) -> str:
    """给出风味/替代分析的最终结论。"""
    return conclusion


# 系统提示词提为常量：直接生成路径（有候选）与 reAct 路径共用同一角色设定。
_FLAVOR_SYSTEM = """你是一个懂风味的专业调酒师，说话像跟朋友品酒——有观点、有推理，不念稿。

【人格要求 · 回答要有"人味"不要模板】
- 先给一个判断（"这杯酸甜骨架很正"），再讲为什么（风味怎么平衡、替代为什么成立）
- 禁止"1. xxx\n2. xxx"式清单堆砌，用连贯的话讲清楚逻辑
- 替代建议要说清"为什么能替"（风味相似/功能等价/浓度对应），不是扔个替代品名单

原则：
1. 分析风味时，先拿到配方材料，再判断酸甜苦烈是否平衡
2. 材料替代时，解释"为什么能替"（风味相似/功能等价/浓度对应），不只给替代品列表
3. 结论语言通俗易懂，适合小白
4. 【铁律】只依据已知材料事实作答。候选/知识库没有的具体用量（毫升/盎司/几份）
   和酒精度，一律不编造数字，用定性描述（"酸甜平衡""口感绵密""度数适中偏低"）替代。
   说"酸甜""偏甜""度数较低"可以，说"青柠汁90ml"不行
5. 【性能】信息足够就收尾，避免反复调工具
6. 材料名以候选/知识库的 ingredients 列表为准；英文名可用常用中文译名
   （Allspice→多香果、Lime Juice→青柠汁/酸橙汁），但不得改成候选里没有的其他材料"""


def _build_flavor_system(ctx: AgentContext, debate: dict | None) -> str:
    """统一构造 system：角色 + 候选铁律 + 圆桌讨论上下文（候选不再决定捷径分支）。"""
    system = _FLAVOR_SYSTEM
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
                   "请基于以上候选做风味分析并给出推荐（含替代思路、为什么适合）。\n"
                   "铁律：\n"
                   "1. 只能讨论上面【候选配方】里列出的酒，严禁引入候选之外的任何酒名"
                   "（凭记忆想到的经典款也算编造）\n"
                   "2. 材料名以候选 ingredients 列表为准；英文名可用常见中文译名"
                   "（Allspice 可写'多香果'），不得改成候选里没有的其他材料\n"
                   "3. 替代建议与口感点评是'建议/可选'性质，用'可以试试''建议换用'措辞，"
                   "不得写成配方事实\n"
                   "4. 候选里没有的具体用量和度数，别编数字，用定性描述（酸甜平衡、"
                   "口感绵密）表达\n"
                   "5. 替代建议只能用候选内的其他酒，或用通用说法（如'可换其他酸甜基酒'），"
                   "不点名候选外的酒\n"
                   "6. 候选已包含所需信息，无需再调用检索类工具\n"
                   "7. 若用户表达心情、场景或多重口味约束，先比较候选再选择，"
                   "明确解释哪一处风味回应了当前感受；不要机械复述历史偏好\n"
                   "8. 用户本轮完整描述优先于旧对话。只在用户明确说'还有吗/换一个/刚才那杯'"
                   "时继承旧推荐关系")
    if debate:
        system += build_debate_block(debate)
    system += """

reAct 执行要点：
1. 候选配方已注入上方【上游检索 Agent 提供的候选配方】，含材料与替代规则，无需调用 analyze_flavor/suggest_substitute
2. 直接基于候选做风味分析与替代建议，用 finalize_flavor 一次性收尾，语言通俗易懂
3. 【性能】不要再调用任何工具，首轮直接收尾"""
    return system


def _grounded_evidence(ctx: AgentContext) -> str:
    """Serialize exactly the evidence selected upstream for one synthesis call."""
    rows = []
    for doc in ctx.retrieved[:5]:
        rows.append(f"[{doc.collection}:{doc.pk}] {doc.evidence_text()}")
    return "\n\n".join(rows)


class FlavorRecommendation(BaseModel):
    selected_recipe_ids: list[str] = Field(
        default_factory=list,
        description="最终选择的真实候选配方 ID，数量必须等于本轮要求",
    )
    recommendation: str = Field(
        min_length=1,
        description="基于候选比较后的自然中文结论，不包含内部 Agent 术语",
    )


_flavor_parser = PydanticOutputParser(pydantic_object=FlavorRecommendation)


def _attach_selected_recipes(ctx: AgentContext, recipe_ids: list[str]) -> None:
    """Attach cards only for IDs that actually exist in upstream evidence."""
    from app.services.deterministic_chat import recipe_card
    from app.services.recipe_catalog import get_recipe

    allowed = {str(doc.pk) for doc in ctx.retrieved if doc.collection == "cocktails"}
    selected = []
    selected_ids: set[str] = set()
    for recipe_id in recipe_ids:
        key = str(recipe_id)
        if key not in allowed or key in selected_ids:
            continue
        recipe = get_recipe(key)
        if recipe:
            selected.append(recipe_card(recipe))
            selected_ids.add(key)
    if not selected:
        return
    ctx.extra["recipes"] = selected
    if len(selected) == 1:
        ctx.extra["recipe"] = selected[0]


def _local_flavor_answer(ctx: AgentContext) -> str:
    """Give a useful evidence-only answer when no reasoning model is available."""
    rows = []
    for doc in ctx.retrieved[:3]:
        if doc.collection == "cocktails":
            flavor = doc.meta.get("flavor") or doc.meta.get("flavor_profile") or {}
            ingredients = doc.meta.get("ingredients_text") or doc.meta.get("ingredients") or "未标注"
            if isinstance(ingredients, list):
                ingredient_names = []
                for item in ingredients:
                    if isinstance(item, dict):
                        name = item.get("name_zh") or item.get("name")
                    else:
                        name = str(item)
                    if name:
                        ingredient_names.append(str(name))
                ingredients = "、".join(ingredient_names) or "未标注"
            if isinstance(flavor, dict):
                flavor_text = "、".join(
                    f"{label} {flavor.get(key)}/10"
                    for key, label in (("sweet", "甜"), ("sour", "酸"), ("strong", "酒感"))
                    if flavor.get(key) is not None
                ) or "风味强度未标注"
            else:
                flavor_text = str(flavor) or "风味强度未标注"
            rows.append(f"{doc.title}：{flavor_text}；材料依据为 {ingredients}。")
        else:
            body = (doc.content_cn or doc.content or "").strip()
            if body:
                rows.append(f"{doc.title}：{body}")
    if not rows:
        return "现有证据不足以完成风味判断，我先不补写不存在的结论。"
    return "我按这轮真实候选核对了风味：\n\n" + "\n\n".join(rows)


def _answer_from_upstream_evidence(ctx: AgentContext, debate: dict | None) -> None:
    """Synthesize shared evidence directly; never launch another retrieval loop."""
    system = _build_flavor_system(ctx, debate)
    constraints = ctx.extra.get("constraints") or {}
    target_count = max(1, min(10, int(constraints.get("target_count") or 1)))
    allowed_ids = [str(doc.pk) for doc in ctx.retrieved if doc.collection == "cocktails"]
    prompt = (
        f"{system}\n\n【可引用证据】\n{_grounded_evidence(ctx)}\n\n"
        f"用户问题：{ctx.user_query}\n\n"
        "先在候选之间完成比较，再按共享交接单的本轮数量给出最终选择。"
        f"selected_recipe_ids 必须从 {allowed_ids} 中选择恰好 {target_count} 个，"
        "按匹配度排序。recommendation 直接回答用户，只能使用上面的证据。"
        "不要调用工具，不要输出内部分析过程。严格输出 JSON，不要加代码围栏。\n\n"
        f"{_flavor_parser.get_format_instructions()}"
    )
    try:
        response = get_llm(temperature=0.3, max_tokens=900).invoke(prompt)
        decision = response if isinstance(response, FlavorRecommendation) \
            else _flavor_parser.parse(str(response.content or ""))
        chosen = [str(item) for item in decision.selected_recipe_ids if str(item) in allowed_ids]
        chosen = list(dict.fromkeys(chosen))[:target_count]
        if len(chosen) != target_count:
            raise ValueError("flavor selection did not return the required grounded IDs")
        ctx.final_answer = str(decision.recommendation or "").strip()
        if not ctx.final_answer:
            raise ValueError("empty grounded flavor response")
        _attach_selected_recipes(ctx, chosen)
        ctx.extra["capability_mode"] = "model"
    except Exception:
        ctx.final_answer = _local_flavor_answer(ctx)
        _attach_selected_recipes(ctx, allowed_ids[:target_count])
        ctx.extra["capability_mode"] = "local_retrieval"
        ctx.extra["local_validated"] = True
        ctx.add_event("风味模型不可用，已使用共享检索证据完成分析")
    ctx.references = [doc.to_reference() for doc in ctx.retrieved]


def run_flavor_agent(ctx: AgentContext, debate: dict | None = None) -> AgentContext:
    """执行风味搭配/替代 Agent 的 reAct 循环（统一入口）。

    与旧实现区别：候选注入 system prompt 后仍走真实 reAct 循环，
    不再有"有候选就单次 LLM"的捷径分支。
    """
    if ctx.retrieved:
        _answer_from_upstream_evidence(ctx, debate)
        ctx.add_event("风味分析完成")
        return ctx

    from langgraph.prebuilt import create_react_agent

    tools = [analyze_flavor, suggest_substitute, finalize_flavor]
    system = _build_flavor_system(ctx, debate)
    agent = create_react_agent(model=get_llm(temperature=0.3, max_tokens=800),
                               tools=tools, prompt=system)

    try:
        # recursion_limit 留足步数，防误截断正常 reAct；防空转靠 prompt
        result = agent.invoke({"messages": [HumanMessage(content=ctx.user_query)]},
                              config={"recursion_limit": 20})
        final = next((m.content for m in reversed(result["messages"])
                      if getattr(m, "type", "") == "ai" and m.content), "")
        ctx.final_answer = final or "(风味分析未给出结论)"
    except Exception:
        ctx.final_answer = "当前没有拿到足够的配方证据，暂时不能可靠判断风味或替代关系。"
        ctx.extra["capability_mode"] = "unavailable"
        ctx.add_event("风味分析能力暂时不可用")
    ctx.add_event("风味分析完成")
    return ctx


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ctx = AgentContext(user_query="玛格丽特里的龙舌兰能用什么替代？", history=[])
    run_flavor_agent(ctx)
    print(ctx.final_answer)
