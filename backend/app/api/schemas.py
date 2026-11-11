# -*- coding: utf-8 -*-
"""API 请求/响应模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """SSE 聊天请求。user_id 默认 guest（免注册开箱即用）。"""
    message: str = Field(min_length=1, max_length=2000, description="用户提问")
    user_id: str = Field(default="guest", max_length=64, description="用户名/标识")
    session_id: str | None = Field(default=None, max_length=128, description="前端会话标识")


class InventoryItem(BaseModel):
    """库存单项（材料名，如 威士忌 / 柠檬 / 糖浆）。"""
    name: str = Field(min_length=1, max_length=64)


class InventoryBatch(BaseModel):
    """批量设置库存（整体替换）。"""
    items: list[str] = Field(default_factory=list)


class ProfileUpdate(BaseModel):
    """画像更新（增量合并，可只带部分字段）。"""
    profile: dict = Field(default_factory=dict)


class HealthOut(BaseModel):
    """健康检查：各组件状态。"""
    status: str = "ok"
    llm_configured: bool = False
    llm_provider: str | None = None
    milvus: str = "down"
    db: str = "down"
    graph: str = "down"


class RecipeGenRequest(BaseModel):
    """AI 配方创作请求。"""
    preferences: str = Field(min_length=1, max_length=500, description="创作需求，如'清爽夏夜、柑橘调'")
    persona: str = Field(default="classic", description="调酒师人格: classic/molecular/japanese/playful")
    base_spirits: list[str] = Field(default_factory=list, description="指定基酒，留空自由发挥")
