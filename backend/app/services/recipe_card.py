# -*- coding: utf-8 -*-
"""结构化配方卡：把 Agent 的文本答案抽成可交互的配方卡片。

对应 REQUIREMENTS §5「回答风格：结构化配方卡片（材料/比例/步骤/杯具/装饰/备注）」，
也是收藏（§6）、风味雷达图（§6）、分享图的基础数据。

设计（省 token + 可靠）：
- 启发式预判：只有答案明显像配方（含"材料/原料"与"步骤"）才抽卡，闲聊不抽
- LLM 结构化抽取（Pydantic 强约束输出六维风味 + 结构化步骤）
- 失败优雅降级：抽不出 → 返回 None，聊天照常显示纯文本

风味六维（雷达图用）: sweet甜 / sour酸 / bitter苦 / strong烈 / body酒体 / aroma香气，均 0-10。
"""
from __future__ import annotations

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.core.llm import get_llm


class FlavorProfile(BaseModel):
    """六维风味雷达（0-10）。"""
    sweet: int = Field(default=0, ge=0, le=10, description="甜度")
    sour: int = Field(default=0, ge=0, le=10, description="酸度")
    bitter: int = Field(default=0, ge=0, le=10, description="苦度")
    strong: int = Field(default=0, ge=0, le=10, description="酒精度烈度")
    body: int = Field(default=0, ge=0, le=10, description="酒体厚重感")
    aroma: int = Field(default=0, ge=0, le=10, description="香气复杂度")


class Ingredient(BaseModel):
    name: str = Field(description="材料名")
    amount: str = Field(default="", description="用量，如 60ml / 1 片")


class RecipeCard(BaseModel):
    """结构化配方卡。"""
    name: str = Field(description="鸡尾酒名称")
    name_cn: str = Field(default="", description="中文名称")
    description: str = Field(default="", description="面向饮用者的一句话风味描述")
    spirit_base: str = Field(default="", description="基酒，如 金酒")
    ingredients: list[Ingredient] = Field(default_factory=list, description="材料与用量")
    steps: list[str] = Field(default_factory=list, description="调制步骤（按序）")
    glass: str = Field(default="", description="杯具")
    garnish: str = Field(default="", description="装饰")
    flavor: FlavorProfile = Field(default_factory=FlavorProfile, description="六维风味")
    alcohol_units: float = Field(default=0, ge=0, description="酒精单位（1 单位 ≈ 10g 纯酒精）")
    is_alcoholic: bool = Field(default=True, description="是否含酒精")
    tips: str = Field(default="", description="备注/小贴士")


_parser = PydanticOutputParser(pydantic_object=RecipeCard)

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """把下面的鸡尾酒调酒答案整理成结构化配方卡。
规则：
1. 材料与用量尽量准确（原答案没有用量就留空）
2. 步骤按操作顺序，每步一句话
3. 六维风味（0-10）按这类酒的口味常识估算
4. 酒精单位：1 标准单位 ≈ 10g 纯酒精（约 30ml 40度烈酒）"""),
    ("human", "调酒答案：\n{text}\n\n{format_instructions}"),
])

# 启发式预判：像配方才抽卡（省 token，避免闲聊也抽）
_RECIPE_MARKERS = ("材料", "原料", "配料", "成分", "步骤", "做法")


def _looks_like_recipe(text: str) -> bool:
    if not text or len(text) < 40:
        return False
    return all(m in text for m in ("材料", "步骤"))


def extract_recipe_card(text: str) -> RecipeCard | None:
    """从答案文本抽配方卡；不是配方 / 抽取失败 → None。"""
    if not _looks_like_recipe(text):
        return None

    try:
        llm = get_llm(temperature=0, max_tokens=800)
        chain = _PROMPT | llm | _parser
        return chain.invoke({"text": text[:4000],
                             "format_instructions": _parser.get_format_instructions()})
    except Exception:
        return None  # 抽不出就纯文本展示，不阻断


def card_to_dict(card: RecipeCard | None) -> dict | None:
    """RecipeCard → dict（塞进 SSE done 事件）。None 透传。"""
    if card is None:
        return None
    return card.model_dump()
