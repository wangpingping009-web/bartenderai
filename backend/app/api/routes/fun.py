# -*- coding: utf-8 -*-
"""玩法彩蛋 API（M7）：每日一酒 / 趣味挑战 / 零酒模式 / 晚宴规划 / 情境感知 / 技能徽章。

全部确定性逻辑（无 LLM），开箱即玩；技能徽章按 username 记录成长。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.audit import audit_log
from app.services import banquet, context, daily, gamification, zero_alcohol
from app.core.auth import current_user

router = APIRouter(prefix="/api/fun", tags=["fun"])


# ---------- 每日一酒 / 趣味挑战 ----------

@router.get("/daily")
def daily_pick(day: str = "", user: dict = Depends(current_user)) -> dict:
    """每日一酒：同一天所有人同一杯（确定性）。"""
    result = daily.daily_cocktail(day or None)
    gamification.record_action_once(user["id"], "daily", result["date"])
    audit_log(action="daily", user=user["username"], detail=f"date={result['date']}")
    return result


@router.get("/challenge")
def challenge(day: str = "") -> dict:
    """趣味挑战：用两种材料创作一杯。"""
    return daily.daily_challenge(day or None)


# ---------- 零酒模式 ----------

@router.get("/mocktail/list")
def mocktail_list() -> dict:
    """所有可改造成零酒精的配方（轻量列表）。"""
    items = zero_alcohol.list_mocktailable()
    return {"count": len(items), "items": items}


@router.post("/mocktail")
def make_mocktail(name: str, user: dict = Depends(current_user)) -> dict:
    """把一杯含酒精配方改造成零酒精 Mocktail。"""
    recipe = zero_alcohol.get_cocktail(name)
    if recipe is None:
        raise HTTPException(status_code=404, detail=f"未找到配方: {name}")
    gamification.record_action(user["id"], "mocktail")
    return zero_alcohol.mocktailize(recipe)


# ---------- 晚宴规划 ----------

class _BanquetRequest(BaseModel):
    names: list[str] = Field(..., min_length=1, description="选中的配方名列表")
    headcount: int = Field(2, ge=1, description="宾客人数")
    mocktail: bool = False


@router.post("/banquet")
def plan_banquet(req: _BanquetRequest, user: dict = Depends(current_user)) -> dict:
    """为多杯酒 × N 人计算备料量。"""
    gamification.record_action(user["id"], "banquet")
    return banquet.plan_banquet(req.names, req.headcount, req.mocktail)


# ---------- 情境感知 ----------

@router.get("/context")
def situational(time: str = "", weather: str = "", mood: str = "") -> dict:
    """时间/天气/心情 → 风味方向。示例：/api/fun/context?weather=hot&mood=happy"""
    return context.situational_profile(time_of_day=time, weather=weather, mood=mood)


# ---------- 技能树 + 徽章 ----------

@router.get("/progress")
def progress(user: dict = Depends(current_user)) -> dict:
    """用户成长全貌：XP / 等级 / 徽章。"""
    return gamification.get_progress(user["id"])
