# -*- coding: utf-8 -*-
"""情境感知（M7）：时间 / 天气 / 心情 → 风味方向（确定性规则）。

把外部情境转成一组可检索的风味关键词，供推荐引擎使用（无 LLM 的离线路径）。
规则可扩展，这里给常见组合。
"""
from __future__ import annotations

# 时间 → 风味倾向（带说明）
_TIME = {
    "morning": {"keywords": ["清爽", "果香", "低酒精"], "reason": "清晨适合轻盈、低酒精的鸡尾酒，如含咖啡/果汁类"},
    "afternoon": {"keywords": ["酸甜", "气泡", "茶感"], "reason": "午后偏休闲，酸甜与气泡感提神"},
    "evening": {"keywords": ["浓郁", "微醺", "经典"], "reason": "傍晚适合经典款，风味可以更厚重"},
    "night": {"keywords": ["烈", "浓香", "气泡"], "reason": "夜晚氛围，烈度和仪式感都可以拉满"},
}

# 天气 → 风味倾向
_WEATHER = {
    "hot": {"keywords": ["清爽", "冰爽", "低酒精"], "reason": "炎热时偏好冰爽、果味充足的低酒精款"},
    "cold": {"keywords": ["温热", "浓郁", "香料"], "reason": "寒冷适合热托蒂这类温热浓郁的酒"},
    "rain": {"keywords": ["治愈", "温暖", "柔和"], "reason": "雨天想要一杯柔和治愈的，降低刺激感"},
    "windy": {"keywords": ["均衡", "经典", "顺口"], "reason": "风大的日子适合稳妥经典的均衡款"},
}

# 心情 → 风味倾向
_MOOD = {
    "happy": {"keywords": ["气泡", "果香", "庆祝"], "reason": "开心时来点气泡感和果味，放大快乐"},
    "tired": {"keywords": ["提神", "咖啡", "清爽"], "reason": "疲惫时需要清爽提神，少烈度"},
    "stressed": {"keywords": ["舒缓", "草本", "低酒精"], "reason": "压力大时选舒缓的草本款，避免高烈度"},
    "sad": {"keywords": ["温暖", "浓郁", "甜蜜"], "reason": "低落时温润浓香的甜感更治愈"},
    "curious": {"keywords": ["新奇", "实验", "创意"], "reason": "好奇时正好尝试你没喝过的创意款"},
}

_FALLBACK = {"keywords": ["经典", "均衡"], "reason": "无特别情境输入时，推荐稳妥的经典款"}


def situational_profile(time_of_day: str = "", weather: str = "", mood: str = "") -> dict:
    """时间/天气/心情 → 风味方向 + 关键词 + 推荐说明。"""
    t = _TIME.get(time_of_day.lower(), {})
    w = _WEATHER.get(weather.lower(), {})
    m = _MOOD.get(mood.lower(), {})
    parts = [x for x in (t, w, m) if x]
    if not parts:
        return _FALLBACK
    keywords: list[str] = []
    for p in parts:
        for k in p["keywords"]:
            if k not in keywords:
                keywords.append(k)
    reasons = [r["reason"] for r in parts]
    return {
        "time_of_day": time_of_day or "",
        "weather": weather or "",
        "mood": mood or "",
        "keywords": keywords,
        "reasons": reasons,
        "summary": "结合" + " + ".join(reasons),
    }
