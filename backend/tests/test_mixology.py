# -*- coding: utf-8 -*-
"""确定性测试：调酒规则引擎（M5 高阶 AI 的质检层）。

规则引擎是纯函数，不依赖 LLM/Milvus —— 重点验证：
- 结构：缺基酒 / 材料过少 → error
- 平衡：甜酸比失衡 → error/warn
- 技法：含果汁却全烈酒 → error
- 酒精度：超单位 → error
- 合法配方 → ok
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from app.services.mixology import validate_recipe


def codes(result):
    return {i.code for i in result.issues}


def has_error(result, code=None):
    errs = [i for i in result.issues if i.level == "error"]
    if code is not None:
        return any(i.code == code for i in errs)
    return bool(errs)


class TestStructure:
    def test_valid_sour_passes(self):
        r = validate_recipe({
            "name": "边车", "spirit_base": "白兰地",
            "ingredients": [
                {"name": "白兰地", "amount": "45ml"},
                {"name": "君度", "amount": "22ml"},
                {"name": "柠檬汁", "amount": "22ml"},
            ],
            "alcohol_units": 1.2,
        })
        assert r.ok, r.issues

    def test_missing_name_error(self):
        r = validate_recipe({"ingredients": [{"name": "金酒", "amount": "50ml"}]})
        assert has_error(r, "structure")

    def test_no_base_spirit_error(self):
        r = validate_recipe({
            "name": "纯果汁", "ingredients": [
                {"name": "橙汁", "amount": "100ml"}, {"name": "柠檬", "amount": "10ml"}]})
        assert has_error(r, "structure")

    def test_too_few_ingredients_error(self):
        r = validate_recipe({"name": "x", "ingredients": [{"name": "金酒", "amount": "50ml"}]})
        assert has_error(r, "structure")


class TestBalance:
    def test_too_sweet_error(self):
        r = validate_recipe({
            "name": "过甜", "ingredients": [
                {"name": "朗姆", "amount": "50ml"},
                {"name": "糖浆", "amount": "120ml"},
                {"name": "青柠汁", "amount": "20ml"},
            ]})
        assert has_error(r, "balance")

    def test_balanced_sour_passes(self):
        r = validate_recipe({
            "name": "黛绮丽", "ingredients": [
                {"name": "朗姆", "amount": "60ml"},
                {"name": "糖浆", "amount": "20ml"},
                {"name": "青柠汁", "amount": "25ml"},
            ]})
        assert r.ok, r.issues


class TestTechnique:
    def test_juice_with_stir_only_error(self):
        """含果汁却只写'搅拌' → 技法矛盾（应摇匀）。"""
        r = validate_recipe({
            "name": "x",
            "steps": ["加冰", "搅拌", "滤入杯中"],
            "ingredients": [
                {"name": "金酒", "amount": "50ml"},
                {"name": "柠檬汁", "amount": "20ml"},
                {"name": "糖浆", "amount": "10ml"},
            ]})
        assert has_error(r, "technique")

    def test_juice_with_shake_passes(self):
        """含果汁且写了'摇匀' → 通过。"""
        r = validate_recipe({
            "name": "x",
            "steps": ["加冰", "摇匀 12 秒", "滤入杯中"],
            "ingredients": [
                {"name": "金酒", "amount": "50ml"},
                {"name": "柠檬汁", "amount": "20ml"},
                {"name": "糖浆", "amount": "10ml"},
            ]})
        assert r.ok, r.issues


class TestAlcohol:
    def test_high_units_error(self):
        r = validate_recipe({
            "name": "炸弹", "spirit_base": "伏特加", "alcohol_units": 5,
            "ingredients": [{"name": "伏特加", "amount": "60ml"}, {"name": "糖浆", "amount": "10ml"}]})
        assert has_error(r, "alcohol")

    def test_amount_oz_conversion(self):
        """oz 单位自动换算 ml（1oz≈30ml），边车 1.5oz 结构正确。"""
        r = validate_recipe({
            "name": "边车oz版",
            "ingredients": [
                {"name": "白兰地", "amount": "1.5 oz"},
                {"name": "君度", "amount": "0.75 oz"},
                {"name": "柠檬汁", "amount": "0.75 oz"},
            ]})
        assert r.ok, r.issues
