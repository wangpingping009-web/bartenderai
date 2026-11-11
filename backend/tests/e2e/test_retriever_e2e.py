# -*- coding: utf-8 -*-
"""端到端测试：真实 LLM + 真实 Milvus。

这类测试验证"整条链路真的能用"（模型/检索/入库都真实），但：
- 需要 Milvus 在线 + 已入库（否则失败）
- 需要真实 API Key（.env 配置）
- 会消耗 token / 网络

因此标记为 @pytest.mark.e2e，默认被 pytest.ini 排除，
只在显式声明时运行：
    pytest -m e2e

这是 REQUIREMENTS 11 质量层的"端到端测试"一环。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/

import pytest

pytestmark = pytest.mark.e2e


@pytest.mark.skipif(not __import__("app.core.config", fromlist=["settings"]).settings.QWEN_API_KEY,
                    reason="未配置 QWEN_API_KEY")
class TestRetrieverE2E:
    """真实检索链路（改写→拆解→混合检索→重排）。"""

    def test_retrieve_mojito(self):
        from app.rag.retriever import multi_round_retrieve
        res = multi_round_retrieve("青柠朗姆薄荷能调什么", history=[])
        assert res.docs, "应检索到结果"
        assert any("Mojito" in d.title for d in res.docs), f"应命中莫吉托, 实际: {[d.title for d in res.docs[:3]]}"

    def test_retrieve_with_history_rewrite(self):
        """带历史时触发改写。"""
        from app.rag.retriever import multi_round_retrieve
        history = [{"role": "user", "content": "推荐一款龙舌兰鸡尾酒"}, {"role": "assistant", "content": "推荐玛格丽特"}]
        res = multi_round_retrieve("它的做法是什么", history=history)
        assert res.docs
        assert any("Margarita" in d.title for d in res.docs[:3]), f"改写后应命中玛格丽特: {[d.title for d in res.docs[:3]]}"
