# -*- coding: utf-8 -*-
"""确定性测试：用户画像服务（M3.5 画像自适应）。

测试目标:
- 画像注入 prompt：空画像不污染、有效画像追加约束块
- 画像增量合并：列表去重、标量覆盖
- 抽取的优雅降级：LLM 失败时返回空画像，不阻断主流程

方法：纯函数直接测；抽取的 happy path 留 e2e（需真实 LLM）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from app.services.profile import (
    _DEFAULT_PROFILE,
    apply_profile_to_prompt,
    extract_profile_from_history,
    merge_profiles,
)


class TestApplyProfileToPrompt:
    """画像约束注入推荐 prompt。"""

    def test_empty_profile_returns_base_unchanged(self):
        assert apply_profile_to_prompt({}, "请推荐一杯酒") == "请推荐一杯酒"

    def test_all_none_profile_returns_base_unchanged(self):
        assert apply_profile_to_prompt(dict(_DEFAULT_PROFILE), "推荐") == "推荐"

    def test_filled_profile_appends_constraints(self):
        out = apply_profile_to_prompt(
            {"sweetness": 8, "disliked_ingredients": ["vodka"]}, "推荐一杯")
        assert out.startswith("推荐一杯")
        assert "用户口味画像" in out
        assert "甜度偏好 高（8/10）" in out
        assert "忌口材料: vodka" in out

    def test_boundary_sweetness_levels(self):
        """甜度分档：7+高 / 4-6中 / <4低。"""
        low = apply_profile_to_prompt({"sweetness": 2}, "x")
        assert "甜度偏好 低（2/10）" in low
        mid = apply_profile_to_prompt({"sweetness": 5}, "x")
        assert "甜度偏好 中（5/10）" in mid


class TestMergeProfiles:
    """画像增量合并。"""

    def test_list_dedup_merge(self):
        merged = merge_profiles(
            {"preferred_spirits": ["gin"], "disliked_ingredients": []},
            {"preferred_spirits": ["rum", "gin"]},  # gin 重复应去重
        )
        assert merged["preferred_spirits"] == ["gin", "rum"]

    def test_scalar_override(self):
        merged = merge_profiles({"sweetness": 6}, {"sweetness": 3})
        assert merged["sweetness"] == 3

    def test_none_does_not_override(self):
        merged = merge_profiles({"sweetness": 6}, {"sweetness": None})
        assert merged["sweetness"] == 6


class TestExtractFallback:
    """LLM 抽取失败 → 空画像（不阻断）。"""

    def test_empty_history_returns_default(self):
        assert extract_profile_from_history([]) == _DEFAULT_PROFILE

    def test_llm_failure_returns_default(self, monkeypatch):
        """无 API key / 模型失败时优雅降级。"""
        def boom(*a, **k):
            raise RuntimeError("no api key")
        monkeypatch.setattr("app.services.profile.get_llm", boom)
        history = [{"role": "user", "content": "上次太甜了"}]
        assert extract_profile_from_history(history) == _DEFAULT_PROFILE
