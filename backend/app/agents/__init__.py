# -*- coding: utf-8 -*-
"""agents: 六个 Agent 角色的定义。

每个 Agent 是一个 reAct 循环：
1. LLM 观察当前上下文，决定调用哪个工具
2. 执行工具，把结果加入上下文
3. 重复直到 LLM 判断可以给出结论

- orchestrator: 总控规划（意图识别 + 任务路由 + 是否澄清）
- retriever:    RAG 检索 Agent
- stock:        库存推荐 Agent
- flavor:       风味搭配 / 材料替代 Agent
- tutor:        教学讲解 Agent
- reviewer:     审校整合 Agent（发现问题回炉修正）
"""
