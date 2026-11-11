# -*- coding: utf-8 -*-
"""BartenderAI 后端应用包。

分层说明（自顶向下调用）:
- app.api        REST 接口 + SSE 流式，面向前端
- app.graph      LangGraph 状态图，编排六 Agent 协作（项目灵魂所在）
- app.agents     六个 Agent 角色的定义（reAct 循环）
- app.rag        检索链路：混合检索 / 重排 / 查询改写
- app.knowledge  知识库 schema 与数据入库
- app.services   业务服务：库存 / 用户画像 / 收藏 / 玩法
- app.models     数据库 ORM 模型
- app.core       基础设施：配置 / LLM 路由 / 日志 / 安全

学习建议：从 app.core 读到 app.api，理解每层职责边界，再看 app.graph
如何把 agents 编排成完整的智能体系统。
"""
