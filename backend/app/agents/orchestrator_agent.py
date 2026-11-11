# -*- coding: utf-8 -*-
"""总控规划 Agent（orchestrator）：意图识别 + 智能准入线 + 任务路由。

这是整个多 Agent 系统的"大脑"。它的三个核心职责：

1. **意图识别**：用户这句话想干什么？推荐/查询/教学/修改配方/聊天/玩法...
2. **智能准入线**（REQUIREMENTS 核心原则）：
   "简单问题不走多 Agent"。一句话能答的（"什么是鸡尾酒"）直接单 Agent 回答，
   省 token、更快；复杂问题（"按我库存推荐"）才触发完整多 Agent 流程。
   这是多 Agent 从 Demo 到生产的底线。
3. **任务路由**：决定要调用哪些专业 Agent、以什么顺序、是否需要澄清。

设计:
- 用 Pydantic 结构化输出（意图枚举 + 路由决策），LLM 只做"判断"，不生成大段文本
- 路由结果是一个计划（plan），LangGraph 状态图根据它走不同分支
"""
from __future__ import annotations

import re
from enum import Enum

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.core.llm import get_llm
from app.core.registry import get_prompt


class Intent(str, Enum):
    """用户意图分类（路由的核心依据）。"""
    RECOMMEND = "recommend"          # 要推荐（按库存/口味/场合）
    QUERY = "query"                  # 查配方/知识/做法
    MODIFY = "modify"                # 修改已推荐的配方（追问）
    TEACH = "teach"                  # 教学讲解（技法/术语/新手入门）
    PLAY = "play"                    # 玩法（每日一酒/挑战/主题酒单）
    CHITCHAT = "chitchat"            # 闲聊/寒暄（不需要检索）
    INVENTORY = "inventory"          # 管理库存（增删改查）
    CREATE = "create"                # 多轮共同创作原创配方
    OTHER = "other"                  # 其他


class OrchestratorPlan(BaseModel):
    """总控的决策结果，LangGraph 据此路由。"""
    intent: Intent = Field(description="用户意图分类")
    simple: bool = Field(description="是否为简单问题（简单则不走多Agent，直接回答）")
    need_retrieve: bool = Field(description="是否需要检索知识库")
    need_stock: bool = Field(description="是否需要参考用户库存")
    need_flavor: bool = Field(description="是否需要风味/替代分析")
    need_teach: bool = Field(description="是否需要教学讲解")
    need_clarify: bool = Field(description="是否存在重要歧义需要反问")
    clarify_question: str = Field(default="", description="若需澄清，反问的问题")
    direct_answer: str = Field(default="", description="若为简单问题，直接给出的回答（可含知识库引用，可空）")
    summary: str = Field(default="", description="总控对该问题的理解摘要")
    creation_ready: bool = Field(default=False, description="共同创作需求是否确认并可开始生成")
    creative_preferences: str = Field(default="", description="跨轮整合后的原创配方需求")
    creative_base_spirits: list[str] = Field(default_factory=list, description="共同创作明确的基酒")
    creative_brief: dict = Field(default_factory=dict, description="跨轮持久化的结构化创作简报")
    capability_mode: str = Field(default="unavailable", description="本轮理解使用的真实能力模式")
    context_relation: str = Field(
        default="standalone",
        description="standalone/previous_turn/prior_recipe，表示本轮与历史的真实关系",
    )
    resolved_query: str = Field(
        default="",
        description="只合并当前活跃语境后的完整任务；不得混入已结束话题",
    )


# 系统提示词来自 Prompt 注册中心（M6：唯一事实源，版本可审计）
_SYSTEM_PROMPT = get_prompt("orchestrator")["system"]

_parser = PydanticOutputParser(pydantic_object=OrchestratorPlan)

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", "用户问题：{query}\n\n用户库存（可空）：{stock}\n\n对话历史（最近几轮）：{history}\n\n{format_instructions}"),
])


_INVENTORY_HINTS = re.compile(
    r"库存|手头|手上|现有材料|现有的酒|家里有|我有.+(?:酒|水|汁|糖|薄荷|柠檬|青柠)"
    r"|按我的|根据我的|用我有的|能调什么"
)

_GENERIC_CONTEXT_QUERY = re.compile(
    r"^(?:那|那么|所以|这种情况|这样的话)?\s*(?:有|还有|那有)?\s*"
    r"(?:什么|哪些|哪(?:一)?个|哪(?:一)?款|哪(?:一)?杯)?\s*"
    r"(?:酒|鸡尾酒|饮品)?\s*(?:可以|值得|适合|比较)?\s*"
    r"(?:推荐|喝|来|选|试试)(?:的|什么|吗|呢|呀|啊)?\s*[？?！!。.]*$|"
    r"^(?:有)?什么推荐的(?:吗|呢|呀|啊)?\s*[？?！!。.]*$"
)


def needs_model_context_resolution(query: str) -> bool:
    """Identify elliptical requests whose meaning depends on the active topic.

    This gate only decides whether orchestration must wait for semantic context
    resolution. It never supplies an answer or invents the missing context.
    """
    text = " ".join((query or "").split())
    if not text:
        return False
    explicit_detail = re.search(
        r"甜|酸|苦|清爽|浓郁|奶油|果味|低度|烈|酒感|刺激|"
        r"金酒|伏特加|朗姆|威士忌|龙舌兰|白兰地|库存|手头|"
        r"天气|晴天|晴朗|阳光|下雨|夏天|冬天|聚会|约会|晚餐|餐前|餐后",
        text,
    )
    generic_action = re.search(
        r"推荐|喝(?:点|杯|款)?什么|来(?:点|杯|款)?什么|"
        r"选(?:哪|什么)|试(?:哪|什么)|哪(?:杯|款|个).{0,3}好|有什么好",
        text,
    )
    return bool(
        not explicit_detail
        and len(text) <= 24
        and (_GENERIC_CONTEXT_QUERY.fullmatch(text) or generic_action)
    )


def _explicitly_asks_for_inventory(query: str) -> bool:
    """只把明确提到现有材料/库存的问题路由给库存 Agent。

    普通的“推荐一杯清爽的”不应因为 intent=recommend 就被库存为空阻断。
    """
    return bool(_INVENTORY_HINTS.search(query or ""))


def _mentions_known_recipe(query: str) -> bool:
    lowered = (query or "").lower()
    if not lowered:
        return False
    try:
        from app.services.recipe_catalog import all_recipes
        return any(
            name and len(name) >= 3 and name.lower() in lowered
            for recipe in all_recipes()
            for name in (recipe.get("name"), recipe.get("name_cn"))
        )
    except Exception:
        return False


def _needs_flavor_reasoning(query: str) -> bool:
    """Route experiential recommendations through real model reasoning.

    These turns require comparing grounded candidates against mood and several
    interacting flavor constraints. Returning the catalog's first ranked row
    would be deterministic filtering presented as intelligence.
    """
    text = query or ""
    flavor_or_scene = bool(re.search(
        r"甜|酸|苦|清爽|清新|爽口|浓郁|奶油|果味|低度|低酒精|烈|酒感|"
        r"刺激|带劲|冲击|醒神|提神|心情|状态|场景|聚会|晚餐|约会|"
        r"天气|晴朗|阳光|艳阳|下雨|夏天|冬天|炎热|落日|户外",
        text,
    ))
    recommendation = bool(re.search(r"推荐|想喝|来一杯|适合|换(?:一杯|一款|一个)", text))
    return flavor_or_scene and (recommendation or len(re.findall(
        r"甜|酸|苦|清爽|浓郁|果味|低度|烈|酒感|刺激|冲击|"
        r"天气|晴朗|阳光|艳阳|夏天|炎热|落日|户外",
        text,
    )) >= 2)


def plan_query(query: str, history: list[dict] | None = None,
               stock: list[str] | None = None) -> OrchestratorPlan:
    """分析用户问题，返回路由计划。

    Args:
        query:   用户本轮提问
        history: 最近对话（判断是否是追问/修改）
        stock:   用户当前库存（材料名列表），帮助总控判断"推荐"类意图
    """
    # 目标优先于口味词。“一起创作”不能被“想喝/甜/酸”抢先路由到现成配方推荐。
    from app.services.creative_dialogue import (
        creation_goal_in_history, has_creation_goal, plan_creative_dialogue,
    )
    if has_creation_goal(query) or creation_goal_in_history(history):
        creative = plan_creative_dialogue(query, history, stock)
        if creative.active:
            return OrchestratorPlan(
                intent=Intent.CREATE, simple=False, need_retrieve=False,
                need_stock=False, need_flavor=False, need_teach=False,
                need_clarify=not creative.ready,
                clarify_question=creative.response if not creative.ready else "",
                direct_answer=creative.response,
                summary="共同创作：已结合对话历史维护结构化需求简报",
                creation_ready=creative.ready,
                creative_preferences=creative.preferences,
                creative_base_spirits=creative.base_spirits,
                creative_brief=creative.brief,
                capability_mode=creative.capability,
                context_relation="previous_turn" if creation_goal_in_history(history) else "standalone",
                resolved_query=creative.preferences or query,
            )

    # 明确的知识/推荐问题不需要先花一次 LLM 做路由；直接检索更快，
    # 也避免模型把“推荐一杯清爽的”误判成闲聊或简单问题。
    from app.services.deterministic_chat import resolve_recipe_context
    context = resolve_recipe_context(query, history)
    route_query = context.query
    wants_inventory = _explicitly_asks_for_inventory(query) or _explicitly_asks_for_inventory(route_query)
    if context.selected_recipe_id:
        return OrchestratorPlan(
            intent=Intent.QUERY, simple=False, need_retrieve=True,
            need_stock=False, need_flavor=False, need_teach=False,
            need_clarify=False,
            summary="已从上一轮候选中解析用户指定的序号",
            context_relation="prior_recipe", resolved_query=context.query,
        )
    if context.followup and (context.inherited_preference or context.exclude_recipe_ids):
        return OrchestratorPlan(
            intent=Intent.RECOMMEND, simple=False, need_retrieve=True,
            need_stock=wants_inventory, need_flavor=_needs_flavor_reasoning(route_query), need_teach=False,
            need_clarify=False,
            summary="结合真实会话历史继续推荐，并排除已推荐配方",
            context_relation="prior_recipe", resolved_query=context.query,
        )
    if not wants_inventory:
        recommendation = bool(re.search(r"推荐|想喝|想来|来一杯|适合(?:我|什么)|给我(?:找|选)", route_query))
        knowledge = bool(re.search(
            r"配方|做法|怎么调|如何调|调制|是什么|区别|为什么|原理|作用|什么时候|"
            r"怎么判断|技法|干摇|湿摇|摇和|搅拌|杯具",
            route_query,
        )) or _mentions_known_recipe(route_query)
        # “有什么推荐的吗”本身没有口味或场景，必须先让模型判断它承接
        # 最近哪一个话题。把它直接送进目录排序只会得到无语境的首条记录。
        if (recommendation and not needs_model_context_resolution(query)) or knowledge:
            return OrchestratorPlan(
                intent=Intent.RECOMMEND if recommendation else Intent.QUERY,
                simple=False, need_retrieve=True, need_stock=False,
                need_flavor=bool(recommendation and _needs_flavor_reasoning(route_query)),
                need_teach=False, need_clarify=False,
                summary="确定性快速路由：直接检索知识库",
                context_relation="standalone", resolved_query=route_query,
            )

    history_text = "\n".join(
        f"{'用户原话' if h['role'] == 'user' else '助手旧回复（不能当作用户偏好）'}: {h['content']}"
        for h in (history or [])[-6:]
    ) or "(无)"
    stock_text = ", ".join(stock) if stock else "(空，未查询库存)"

    try:
        llm = get_llm(temperature=0, max_tokens=1024)  # 判断要稳定，温度 0
        chain = _PROMPT | llm | _parser
        plan = chain.invoke({
            "query": query, "stock": stock_text, "history": history_text,
            "format_instructions": _parser.get_format_instructions(),
        })
        # This label is assigned by runtime evidence, never trusted from model output.
        plan.capability_mode = "model"
        plan.resolved_query = (plan.resolved_query or query).strip()
        if plan.context_relation not in {"standalone", "previous_turn", "prior_recipe"}:
            plan.context_relation = "standalone"

        # 推荐有两种语义：普通推荐和“按我的库存推荐”。库存只属于后者。
        # 这里对 need_stock 做无条件确定性兜底，避免 LLM 即使误判 intent
        # 为 query/other，仍把普通问题送进库存 Agent。
        wants_inventory = _explicitly_asks_for_inventory(query)
        if not wants_inventory:
            plan.need_stock = False
            if plan.intent == Intent.RECOMMEND or re.search(
                    r"推荐|想喝|来一杯|适合|配方|做法|怎么调|如何调|调制", query):
                # 防止模型返回 simple=true 但同时漏填 need_retrieve，
                # 导致“推荐/配方”被 direct_answer 直接截断。
                plan.simple = False
                plan.need_retrieve = True
                if plan.intent == Intent.RECOMMEND and _needs_flavor_reasoning(query):
                    plan.need_flavor = True
        else:
            plan.need_stock = True
        if plan.intent == Intent.RECOMMEND:
            plan.simple = False
            plan.need_retrieve = True
            plan.need_flavor = bool(
                plan.need_flavor
                or _needs_flavor_reasoning(plan.resolved_query)
                or plan.context_relation == "previous_turn"
            )
        return plan
    except Exception:
        # 模型不可用时仍保留确定性语义：库存请求不能退化成普通查询，
        # 否则用户明明说“我有金酒”却会收到无库存约束的随机推荐。
        preference = bool(re.search(
            r"甜|酸|苦|清爽|浓郁|奶油|果味|低度|低酒精|烈|酒感|柔和|"
            r"刺激|冲击|醒神|心情|场景", query or ""
        ))
        if wants_inventory:
            return OrchestratorPlan(
                intent=Intent.RECOMMEND, simple=False,
                need_retrieve=True, need_stock=True, need_flavor=preference,
                need_teach=False, need_clarify=False,
                summary="模型路由不可用；保留库存与口味约束进入本地证据链",
                resolved_query=route_query,
            )
        # 其他解析失败保守走查询+检索，不阻断。
        return OrchestratorPlan(
            intent=Intent.QUERY, simple=False,
            need_retrieve=True, need_stock=False, need_flavor=preference,
            need_teach=False, need_clarify=False,
            summary="（意图识别失败，按通用查询处理）",
            resolved_query=route_query,
        )
