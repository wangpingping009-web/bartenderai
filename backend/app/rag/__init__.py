# -*- coding: utf-8 -*-
"""rag: 检索链路。

- hybrid.py:       混合检索（向量 + BM25）→ RRF 融合
- rerank.py:       BGE-Rerank 重排序
- query_rewrite.py: 多轮对话查询改写（指代词 → 具体配方/意图）
- retriever.py:    检索 Agent 使用的工具函数
"""
