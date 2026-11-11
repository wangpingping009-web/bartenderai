# -*- coding: utf-8 -*-
"""LangGraph 图状态定义：六 Agent 共享的中间产物载体。

设计要点（对应"动态协作"核心原则）:
- 状态是"整个多 Agent 系统的共享黑板"：总控的决策、检索的命中、
  库存 Agent 的推荐、审校的修正指令，都写到这里
- 各 Agent 从状态里读它需要的上游结果（传递中间产物），
  而不是"总控收集后自己拼"（那是集中式，不是真协作）
- LangGraph 的 reducer（add 语义）让多个 Agent 的产出可以合并进列表
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages

from app.agents.orchestrator_agent import OrchestratorPlan


@dataclass
class AgentOutput:
    """某个 Agent 的一次产出（含谁产的、结果、状态）。"""
    agent: str                     # 产出者（retriever/stock/flavor/tutor/reviewer）
    content: str = ""              # 产出内容
    ok: bool = True                # 是否成功
    meta: dict = field(default_factory=dict)  # 附加（引用、库存覆盖度等）


class GraphState(TypedDict, total=False):
    """LangGraph 状态。所有字段可选，各节点按需读取/写入。"""

    # ---- 输入 ----
    user_query: str                        # 用户本轮提问
    history: list[dict]                    # 会话历史
    user_id: str | None                    # 当前用户（画像/库存用）
    session_id: str | None                 # 当前会话

    # ---- 总控决策 ----
    plan: OrchestratorPlan | None          # 总控的路由计划
    direct_answer: str                     # 简单问题直接答（不走多Agent）
    effective_query: str                   # 从真实历史恢复后的完整检索问题
    contextual_followup: bool              # 是否为“还有吗/换一个”等省略式追问
    excluded_recipe_ids: list[str]         # 本会话已推荐配方，续推时去重
    constraint_handoff: dict               # 全部专业 Agent 共享的结构化调酒约束

    # ---- 专业 Agent 产出（列表，reducer 追加）----
    agent_outputs: Annotated[list[AgentOutput], _merge_outputs]  # 各 Agent 结果
    retrieved: list                        # 检索命中的 RetrievedDoc 列表
    references: list[str]                  # 引用来源（供审校校验）

    # ---- 审校与反思自纠 ----
    review_verdict: str                    # pass / revise / clarify
    review_issues: list[str]               # 审校发现的问题
    revise_instructions: list[str]         # 修正指令（圆桌讨论用）
    revise_count: int                      # 已讨论轮数（限轮数防死循环）
    final_answer: str                      # 最终整合答案
    recipe: dict                           # 可直接展示的结构化配方卡
    recipes: list[dict]                    # 一次推荐多款时的结构化候选列表
    creative_brief: dict                   # 多轮共同创作的结构化需求简报
    capability_mode: str                   # model / local_parser / local_retrieval
    local_validated: bool                  # 模型降级时由确定性规则与真实证据完成
    retrieval_meta: dict                   # mode / confidence / field coverage

    # ---- 圆桌讨论（Agent 自由对话，见 graph.debate_node）----
    debate: list[dict]                     # 讨论消息流 [{speaker, content, round}, ...]

    # ---- SSE 事件流 ----
    events: Annotated[list[str], _merge_events]  # 实时回传前端


def _merge_outputs(a: list, b: list) -> list:
    """LangGraph reducer：合并 agent_outputs（多个 Agent 并行产出互不覆盖）。"""
    return a + b if isinstance(a, list) else b


def _merge_events(a: list, b: list) -> list:
    """LangGraph reducer：合并事件流（追加）。"""
    return a + b if isinstance(a, list) else b
