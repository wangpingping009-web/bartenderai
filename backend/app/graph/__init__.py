# -*- coding: utf-8 -*-
"""graph: LangGraph 状态图编排层。

把 agents/ 中的六个角色编排成有状态、可条件路由、可反思自纠的
多 Agent 系统。这是"真智能"与"写死流程"的分水岭：
状态转移由 LLM 实时决策，而不是代码 if-else 决定。

- state.py: 图状态定义（共享上下文，Agent 间传递中间产物）
- graph.py: 节点与边的编排
"""
