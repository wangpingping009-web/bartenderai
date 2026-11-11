# -*- coding: utf-8 -*-
"""多级内容校验（M6）：输出安全护栏。

对 Agent 最终答案做一轮"内容安全检查"，识别调酒场景的高危建议：
- 未成年饮酒 / 酒驾 / 劝酒过度 / 危险混饮，命中即追加免责提示并打标
- 启发式关键词 + 规则，离线可用，不依赖 LLM
- 与规则引擎（配方质检）构成两道不同性质的校验：规则引擎管"配方对不对"，
  内容校验管"说的话安不安全"。

使用方：审校 Agent 最终输出 / SSE done 事件。
"""
from __future__ import annotations

import re

# (代码, 正则, 提示语) —— 提示语是命中后附给用户的免责说明
_RULES: list[tuple[str, str, str]] = [
    ("minor", r"未成年|儿童|小朋友|孩子.{0,6}(喝|酒)", "请勿向未成年人提供酒精饮料。"),
    ("drink_drive", r"(喝完|酒后|喝了.{0,4}酒).{0,8}(开车|驾驶)", "酒后不开车，开车不喝酒。"),
    ("excess", r"灌醉|灌趴|喝到{1,4}醉|宿醉.*(解酒|狂饮)|一次性.{0,4}(喝|灌).{0,6}(一瓶|半瓶|大量)",
              "适量饮酒，过量伤身。本建议不构成医疗指导。"),
    ("danger", r"(掺|混)(头孢|感冒药|安眠药|处方药)|注射|吸食",
              "严禁将酒精与药物混用，请立即停止并寻求帮助。"),
]


def guard_output(text: str) -> dict:
    """检查一段输出。命中高危建议返回 issues，否则 ok。

    Returns:
        {"ok": bool, "issues": [{"code", "tip"}...], "tips": 拼接的提示语}
    """
    issues = []
    for code, pattern, tip in _RULES:
        if re.search(pattern, text or ""):
            issues.append({"code": code, "tip": tip})
    return {"ok": not issues, "issues": issues,
            "tips": " ".join(i["tip"] for i in issues)}
