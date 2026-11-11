# -*- coding: utf-8 -*-
"""确定性测试：替代推理引擎 + 配方解构（M5）。

- 替代：确定性匹配离线可用；无 LLM 时降级返回规则原文
- 解构：确定性骨架不依赖 LLM；LLM 失败优雅降级
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from app.services.deconstruct import _skeleton_from_card, deconstruct_recipe
from app.services.substitution import find_substitutions


class TestSubstitutionMatch:
    def test_find_lime_matches(self):
        """青柠汁应命中 青柠汁↔柠檬汁 规则。"""
        hits = find_substitutions("lime")
        assert hits, "应命中 lime/lemon 替代规则"
        texts = " ".join(h.get("title_cn", "") for h in hits)
        assert "柠檬" in texts

    def test_unknown_ingredient_no_match(self):
        assert find_substitutions("龙舌兰仙人掌果") == []

    def test_empty_query(self):
        assert find_substitutions("") == []

    def test_rules_have_both_sides(self):
        for rule in find_substitutions("lime"):
            assert rule["a"] and rule["b"]


class TestSubstitutionExplain:
    def test_no_match_returns_offline(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("不应调 LLM")
        monkeypatch.setattr("app.services.substitution.get_llm", boom)
        from app.services.substitution import explain_substitution
        r = explain_substitution("不存在的材料xyz")
        assert r["matched"] == []
        assert r["error"]

    def test_llm_failure_falls_back_to_rules(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no key")
        monkeypatch.setattr("app.services.substitution.get_llm", boom)
        from app.services.substitution import explain_substitution
        r = explain_substitution("青柠汁换成柠檬汁可以吗")
        assert r["matched"], "知识库命中了"
        assert r["offline"] is True       # 降级：直接返回规则
        assert r["explanation"] is None


class TestDeconstruct:
    def test_skeleton_deterministic(self):
        """确定性骨架：识别基酒 + 酸甜结构，不需要 LLM。"""
        sk = _skeleton_from_card({
            "name": "玛格丽特",
            "ingredients": [
                {"name": "龙舌兰", "amount": "50ml"},
                {"name": "君度", "amount": "20ml"},
                {"name": "青柠汁", "amount": "25ml"},
            ]})
        assert sk["base_spirit"] == "龙舌兰"
        assert "sour" in sk["balance"]

    def test_deconstruct_llm_failure_graceful(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("no key")
        monkeypatch.setattr("app.services.deconstruct.get_llm", boom)
        r = deconstruct_recipe({"name": "x", "ingredients": [
            {"name": "金酒", "amount": "50ml"}, {"name": "柠檬汁", "amount": "20ml"}]})
        assert r["ok"] is False
        assert r["skeleton"]["base_spirit"] == "金酒"   # 降级仍有确定性骨架
