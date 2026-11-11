# -*- coding: utf-8 -*-
"""确定性测试：RAG 检索链路（不依赖真实 LLM / Milvus）。

测试对象:
- query_rewrite:   多轮改写（mock LLM）
- query_decompose: 多维拆解（mock LLM）
- retriever:       multi_round_retrieve 的兜底/流程分支（mock 依赖）

这些测试的意义（对应 REQUIREMENTS 11）:
  验证"流程正确"而非"模型聪明"。LLM 会变、会出错，但路由逻辑、
  兜底分支、字段合并必须是确定性的、可回归的。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

import pytest

from app.rag.query_decompose import decompose_query
from app.rag.query_rewrite import QueryRewrite, rewrite_query


class TestQueryRewrite:
    """改写器测试：重点验证"无历史不调 LLM"的省成本分支。"""

    def test_no_history_returns_as_is(self, monkeypatch):
        """无历史时不调用 LLM，原样返回。"""
        called = []

        # 替换 get_llm，若被调用则标记
        import app.rag.query_rewrite as qr
        monkeypatch.setattr(qr, "get_llm", lambda *a, **k: called.append(1) or object())

        result = rewrite_query("推荐一款金酒鸡尾酒", history=None)
        assert result.rewritten == "推荐一款金酒鸡尾酒"
        assert result.needs_retrieve is True
        assert called == [], "无历史时不应调用 LLM"

    def test_empty_history_no_call(self, monkeypatch):
        """空历史列表同样不调 LLM。"""
        import app.rag.query_rewrite as qr
        called = []
        monkeypatch.setattr(qr, "get_llm", lambda *a, **k: called.append(1) or object())
        rewrite_query("什么是古典鸡尾酒", history=[])
        assert called == []

    def test_rewrite_parse_failure_falls_back(self, monkeypatch):
        """LLM 返回非法 JSON 时，退回原查询（不抛异常、不阻断）。"""
        import app.rag.query_rewrite as qr

        # 构造一个 invoke 抛异常的假链
        class BoomChain:
            def invoke(self, *a, **k):
                raise Exception("llm down")

        monkeypatch.setattr(qr, "_get_chain", lambda: BoomChain())

        result = rewrite_query("它太甜了", history=[{"role": "user", "content": "推荐玛格丽特"}])
        # 兜底：原样返回，仍标记需检索
        assert result.rewritten == "它太甜了"
        assert result.needs_retrieve is True


class TestQueryDecompose:
    """拆解器测试：验证失败兜底。"""

    def test_decompose_failure_falls_back(self, monkeypatch):
        """LLM 拆解失败时退回 [原查询]，不阻断。"""
        import app.rag.query_decompose as qd

        class BoomChain:
            def invoke(self, *a, **k):
                raise Exception("llm down")

        monkeypatch.setattr(qd, "_get_chain", lambda: BoomChain())
        subs = decompose_query("夏日派对喝什么")
        assert subs == ["夏日派对喝什么"]


class TestRetrieverFallback:
    """检索兜底分支（不连 Milvus，只测流程逻辑）。"""

    def test_rewrite_no_retrieve_skips(self, monkeypatch):
        """改写器判断无需检索时，直接返回 no_retrieve_needed。"""
        import app.rag.retriever as rtr
        from app.rag.query_rewrite import QueryRewrite

        # 改写返回 needs_retrieve=False
        monkeypatch.setattr(rtr, "rewrite_query",
                            lambda q, h: QueryRewrite(rewritten="谢谢", keywords=[], needs_retrieve=False))
        res = rtr.multi_round_retrieve("谢谢", history=[{"role": "user", "content": "你好"}])
        assert res.is_retrieved is False
        assert res.fallback_reason == "no_retrieve_needed"

    def test_retrieve_once_no_docs_fallback(self, monkeypatch):
        """检索无结果时，fallback_reason 标记 no_hit。"""
        import app.rag.retriever as rtr

        # mock 拆解：直接返回原查询（跳过 LLM）
        monkeypatch.setattr(rtr, "decompose_query", lambda q: [q])

        # mock get_retriever 返回空
        class EmptyRetriever:
            def search(self, *a, **k):
                return []

        monkeypatch.setattr(rtr, "get_retriever", lambda: EmptyRetriever())
        res = rtr.retrieve_once("不存在的材料组合")
        assert res.is_retrieved is False
        assert res.fallback_reason == "no_hit_in_knowledge_base"


class TestAdaptiveRetrieval:
    def test_local_fallback_reports_bm25_instead_of_hybrid(self, monkeypatch):
        import app.rag.retriever as rtr
        from app.rag.hybrid import HybridRetriever

        retriever = HybridRetriever()
        retriever._milvus_down = True
        monkeypatch.setattr(rtr, "get_retriever", lambda: retriever)

        result = rtr.retrieve_once("Margarita 怎么调", limit=3)

        assert result.retrieval_mode == "local_bm25"
        assert any("本地 BM25" in event for event in result.events)
        assert not any("混合检索" in event for event in result.events)

    def test_query_profile_adapts_dense_sparse_weights(self):
        from app.rag.hybrid import analyze_query

        exact = analyze_query("Margarita 怎么调")
        semantic = analyze_query("为什么含蛋清的鸡尾酒需要干摇")
        preference = analyze_query("推荐一杯清爽、微甜的金酒")

        assert exact.exact_named_recipe is True
        assert exact.sparse_weight > exact.dense_weight
        assert semantic.intent == "knowledge"
        assert semantic.dense_weight > semantic.sparse_weight
        assert preference.intent == "recommendation"
        assert preference.dense_weight > preference.sparse_weight

    def test_recommendation_revision_is_not_misrouted_as_substitution_knowledge(self):
        from app.rag.hybrid import analyze_query

        revision = analyze_query("上一杯太酸，换一个甜但不要太甜、清爽的")
        substitution = analyze_query("青柠汁可以换成什么材料")

        assert revision.intent == "recommendation"
        assert revision.filters.min_sweet == 3
        assert revision.filters.max_sweet == 5
        assert substitution.intent == "knowledge"

    def test_explicit_taste_and_ingredient_filters_are_hard_constraints(self):
        from app.rag.hybrid import HybridRetriever, _doc_ingredients, analyze_query

        query = "推荐一杯金酒，甜但不是很甜，酸但不是很酸，有酒味，不要蛋清"
        profile = analyze_query(query)
        docs = HybridRetriever()._local_search(
            query, 10, ("cocktails",), profile.filters,
        )

        assert docs
        for doc in docs:
            ingredients = _doc_ingredients(doc)
            flavor = doc.meta["flavor"]
            assert "gin" in ingredients
            assert "egg white" not in ingredients
            assert 3 <= flavor["sweet"] <= 5
            assert 2 <= flavor["sour"] <= 4
            assert flavor["strong"] >= 4

    def test_taste_only_query_uses_structured_flavor_evidence(self):
        from app.rag.hybrid import HybridRetriever, analyze_query

        query = "想喝甜但不要太甜、酸但不要太酸，而且有酒味的"
        profile = analyze_query(query)
        docs = HybridRetriever()._local_search(
            query, 8, ("cocktails",), profile.filters,
        )

        assert docs
        assert profile.filters.min_sour == 2
        assert profile.filters.max_sour == 4
        for doc in docs:
            flavor = doc.meta["flavor"]
            assert 3 <= flavor["sweet"] <= 5
            assert 2 <= flavor["sour"] <= 4
            assert flavor["strong"] >= 4

    def test_inventory_query_requires_every_explicit_material(self):
        from app.rag.hybrid import HybridRetriever, _doc_ingredients, analyze_query

        query = "我有金酒和汤力水，能调什么"
        profile = analyze_query(query)
        docs = HybridRetriever()._local_search(query, 10, ("cocktails",), profile.filters)

        assert set(profile.filters.required_all_ingredients) == {"tonic water", "gin"}
        assert docs
        assert all({"gin", "tonic water"} <= _doc_ingredients(doc) for doc in docs)

    def test_exact_recipe_is_first_in_local_index(self):
        from app.rag.hybrid import HybridRetriever

        docs = HybridRetriever()._local_search("Margarita 怎么调", 5, ("cocktails",))

        assert docs[0].pk == "11007"

    def test_multi_query_rrf_keeps_original_and_rewards_consensus(self, monkeypatch):
        from app.rag.hybrid import HybridRetriever, QueryProfile, RetrievedDoc

        retriever = HybridRetriever()
        calls = []

        def encode(texts):
            calls.append(texts[0])
            return {"query": texts[0]}

        def search_collection(collection, qvec, limit, fields, profile):
            if qvec["query"] == "用户原句":
                return [RetrievedDoc("cocktails", "a", "A", 1.0),
                        RetrievedDoc("cocktails", "b", "B", .8)]
            return [RetrievedDoc("cocktails", "b", "B", .99),
                    RetrievedDoc("cocktails", "c", "C", .9)]

        monkeypatch.setattr(retriever, "_encode", encode)
        monkeypatch.setattr(retriever, "_search_collection", search_collection)
        docs = retriever._milvus_search(
            "用户原句", 3, ["领域扩展"], ("cocktails",),
            QueryProfile("general", .6, .4),
        )

        assert calls == ["用户原句", "领域扩展"]
        assert docs[0].pk == "b"


class TestEvidenceCalibration:
    @staticmethod
    def _recipe(pk: str, title: str, score: float, ingredients: list[dict],
                content: str = "完整调制步骤"):
        from app.rag.hybrid import RetrievedDoc
        return RetrievedDoc(
            collection="cocktails", pk=pk, title=title, score=score,
            content_cn=content,
            meta={"name": title, "name_cn": title, "ingredients": ingredients,
                  "flavor": {"sweet": 4, "sour": 3, "strong": 5}, "abv": 20},
        )

    def test_exact_recipe_requires_named_hit_and_recipe_fields(self):
        from app.rag.retriever import assess_evidence

        wrong = self._recipe("x", "Whitecap Margarita", 1.0,
                             [{"name": "Tequila", "amount": "45 ml"}])
        exact = self._recipe("11007", "Margarita", 0.9, [
            {"name": "Tequila", "amount": "45 ml"},
            {"name": "Lime juice", "amount": "20 ml"},
        ])

        assert assess_evidence("Margarita 怎么调", [wrong]).enough is False
        result = assess_evidence("Margarita 怎么调", [exact])
        assert result.enough is True
        assert result.field_coverage == 1.0

    def test_complete_but_irrelevant_recipe_is_not_sufficient_evidence(self):
        from app.rag.retriever import assess_evidence

        complete = self._recipe(
            "11007", "Margarita", 1.0,
            [{"name": "Tequila", "amount": "45 ml"},
             {"name": "Lime juice", "amount": "20 ml"}],
        )

        result = assess_evidence("Python 字典和金酒的共同发明人是谁", [complete])

        assert result.enough is False
        assert result.confidence < 0.72

    def test_multi_round_retrieval_drops_unresolved_irrelevant_evidence(self, monkeypatch):
        import app.rag.retriever as retriever_mod

        complete = self._recipe(
            "11007", "Margarita", 1.0,
            [{"name": "Tequila", "amount": "45 ml"}],
        )

        def partial(query, **_):
            return retriever_mod.RetrievalResult(
                query=query, docs=[complete], references=[complete.to_reference()],
                is_retrieved=True, retrieval_mode="local_bm25",
            )

        monkeypatch.setattr(retriever_mod, "retrieve_once", partial)
        monkeypatch.setattr(retriever_mod, "_reflect", lambda *a, **k: (False, "继续查找"))

        result = retriever_mod.multi_round_retrieve("Python 字典和金酒的共同发明人是谁")

        assert result.docs == []
        assert result.references == []
        assert result.fallback_reason == "insufficient_evidence"

    def test_fixed_eval_set_contains_at_least_one_hundred_cases(self):
        from app.rag.evalset import fixed_eval_set

        rows = fixed_eval_set()

        assert len(rows) >= 100
        assert sum(not row["relevant"] for row in rows) >= 20

    def test_mmr_keeps_relevance_but_removes_near_duplicate(self):
        from app.rag.rerank import diversify

        first = self._recipe("1", "Citrus One", 1.0, [
            {"name": "Gin", "amount": "45 ml"}, {"name": "Lemon", "amount": "20 ml"},
        ])
        duplicate = self._recipe("2", "Citrus Two", .98, [
            {"name": "Gin", "amount": "45 ml"}, {"name": "Lemon", "amount": "20 ml"},
        ])
        distinct = self._recipe("3", "Herbal Highball", .96, [
            {"name": "Whiskey", "amount": "45 ml"}, {"name": "Soda water", "amount": "90 ml"},
        ])

        selected = diversify([first, duplicate, distinct], top_n=2, lambda_mult=.55)

        assert selected[0] is first
        assert distinct in selected
        assert duplicate not in selected
