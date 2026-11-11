# -*- coding: utf-8 -*-
"""调酒规则引擎：给 AI 生成的配方做质检，通过才展示。

对应 REQUIREMENTS §7「AI 新配方生成 + 调酒规则引擎校验
（风味平衡 / 结构 / 稀释度 / 技法可行性）」。

为什么需要规则引擎（而不是全交给 LLM 自查）：
- LLM 会"创作"出结构残缺 / 比例失衡 / 技法矛盾的配方（幻觉）
- 规则引擎是**确定性**的质检层：它不生成，只判断，绝不原谅
- 生成流程：LLM 创作 → 规则引擎校验 → 有 error 则带反馈重生成（≤2 次）→ 仍不过则拒收

校验维度（每条给 code + 严重级别）:
- structure   结构完整性（基酒存在 / 材料数 / 命名）
- balance     风味平衡（甜酸比，经典酸酒框架 1:2 到 1:1）
- dilution    稀释度（总量 / 是否该加冰）
- technique   技法可行性（有蛋/奶/果汁必须摇，全烈酒应搅）
- alcohol     酒精度（单杯单位数上限 / ABV 合理性）

本模块纯函数、无 LLM、无 IO —— 可完全确定性测试。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 常用基酒（英中皆可，用于判定"材料里是否有酒"）
KNOWN_SPIRITS = {
    "gin", "ginebra", "vodka", "rum", "ron", "whisky", "whiskey", "bourbon",
    "rye", "scotch", "tequila", "mezcal", "brandy", "cognac", "pisco",
    "白兰地", "威士忌", "金酒", "杜松子酒", "伏特加", "朗姆", "龙舌兰",
    "梅斯卡尔", "波本", "黑麦", "干邑", "皮斯科",
}
# 甜味材料（糖/糖浆/甜味利口酒/甜味美思/果汁带甜）
SWEET_MARKERS = ("糖", "蜂蜜", "枫糖", "甜", "君度", "橙皮利口", "利口", "甘露", "苦艾酒")
# 酸味材料（柑橘/醋）
SOUR_MARKERS = ("柠檬", "青柠", "酸橙", "醋", "西柚")
# 需要摇匀的材料（汁/蛋/奶/果泥 → 必须摇，否则口感不均）
SHAKE_MARKERS = ("汁", "蛋", "奶油", "椰", "牛奶", "果泥")
# 需要搅拌的材料（全烈酒 + 味美思）
STIR_ONLY = ("味美思", "苦艾")

LEVEL_ERROR = "error"
LEVEL_WARN = "warning"


@dataclass
class ValidationIssue:
    level: str                       # error / warning
    code: str                        # 规则代号
    message: str                     # 人类可读说明

    def to_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message}


@dataclass
class ValidationResult:
    ok: bool                         # 无 error（可展示）
    issues: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "issues": [i.to_dict() for i in self.issues]}


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _parse_amount(amount: str) -> tuple[float, str]:
    """把 '50ml' / '1/2 oz' / '一勺' 解析成 (数值, 单位)。解析失败 → (0, '')。"""
    a = _norm(amount).replace("⅓", "0.33").replace("½", "0.5").replace("¼", "0.25")
    import re
    m = re.search(r"(\d+(?:\.\d+)?)", a)
    if not m:
        return 0.0, ""
    num = float(m.group(1))
    unit = "ml" if "ml" in a else ("oz" if "oz" in a else "")
    # oz → ml
    if unit == "oz":
        return num * 30, "ml"
    return num, unit


def _volume_of(amount: str) -> float:
    return _parse_amount(amount)[0]


def validate_recipe(recipe: dict) -> ValidationResult:
    """校验一张配方卡（dict 结构，与 RecipeCard 兼容）。返回校验结果。"""
    issues: list[ValidationIssue] = []
    ingredients = recipe.get("ingredients", [])
    if not isinstance(ingredients, list):
        ingredients = []

    names = [_norm(i.get("name", "")) for i in ingredients if isinstance(i, dict)]
    amounts = [_volume_of(i.get("amount", "")) for i in ingredients if isinstance(i, dict)]

    # 1. 结构完整性
    if not recipe.get("name"):
        issues.append(ValidationIssue(LEVEL_ERROR, "structure", "配方缺名称"))
    has_spirit = any(any(s in n for s in KNOWN_SPIRITS) for n in names)
    if not has_spirit:
        issues.append(ValidationIssue(LEVEL_ERROR, "structure", "材料中找不到基酒（六大基酒之一）"))
    if len(names) < 2:
        issues.append(ValidationIssue(LEVEL_ERROR, "structure", "材料过少（至少 2 种）"))

    # 2. 风味平衡：经典酸酒框架 sweet:sour ≈ 1:2 ~ 1:1
    sweet_vol = sum(a for a, n in zip(amounts, names) if any(m in n for m in SWEET_MARKERS))
    sour_vol = sum(a for a, n in zip(amounts, names) if any(m in n for m in SOUR_MARKERS))
    if sweet_vol > 0 and sour_vol > 0:
        ratio = sweet_vol / sour_vol
        if ratio > 3.0:
            issues.append(ValidationIssue(LEVEL_ERROR, "balance",
                                          f"甜酸比 {ratio:.1f}:1 过甜（建议 ≤ 3:1）"))
        elif ratio < 0.33:
            issues.append(ValidationIssue(LEVEL_WARN, "balance",
                                          f"甜酸比 {ratio:.1f}:1 过酸（建议 ≥ 1:3）"))

    # 3. 稀释度/总量
    total = sum(amounts)
    if total > 0 and total < 45:
        issues.append(ValidationIssue(LEVEL_WARN, "dilution",
                                      f"总量仅约 {total:.0f}ml，单杯偏少"))
    if total > 300:
        issues.append(ValidationIssue(LEVEL_WARN, "dilution",
                                      f"总量约 {total:.0f}ml，超出单杯合理范围"))

    # 4. 技法可行性（依据步骤文本里是否写了"摇/搅"）
    steps_text = " ".join(str(s) for s in (recipe.get("steps") or []))
    has_shake = "摇" in steps_text
    has_stir = "搅" in steps_text
    juice_or_cream = any(any(m in n for m in SHAKE_MARKERS) for n in names)
    if juice_or_cream:
        if has_stir and not has_shake:
            issues.append(ValidationIssue(LEVEL_ERROR, "technique",
                                          "含果汁/蛋/奶却只写'搅拌'，应改为'摇匀'（乳化充分）"))
        elif not has_shake:
            issues.append(ValidationIssue(LEVEL_WARN, "technique",
                                          "含果汁/蛋/奶，建议标注'摇匀'时间"))

    # 5. 酒精度
    units = recipe.get("alcohol_units") or 0
    if units > 3:
        issues.append(ValidationIssue(LEVEL_ERROR, "alcohol",
                                      f"酒精单位 {units} 偏高（单杯建议 ≤ 3 单位）"))
    abv = recipe.get("abv")
    if abv and abv > 45:
        issues.append(ValidationIssue(LEVEL_WARN, "alcohol",
                                      f"ABV {abv}% 偏高，注意稀释"))

    return ValidationResult(ok=not any(i.level == LEVEL_ERROR for i in issues),
                            issues=issues)
