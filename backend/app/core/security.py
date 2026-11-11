# -*- coding: utf-8 -*-
"""输入防护 + Prompt 注入防御（M6 输入/隔离防护）。

一道防线：用户输入在进入 Agent 系统前，先做两件事
1. 净化 sanitize：去掉控制字符 / 极端长度 / 只给 Agent 干净的文本
2. 注入检测 injection：识别"试图改写系统提示"的典型句式，
   命中即打标 —— 不硬拦截正常提问，但记录审计 + 提示系统层加强防御

注入特征按语言分两组（中/英），关键词是"命令式覆盖系统指令"的典型措辞，
不是普通内容词。宁可少杀不可误伤普通问题。
"""
from __future__ import annotations

import re

_MAX_LEN = 2000

# 控制字符（保留换行与制表，去掉其余 \x00-\x1f）
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 连续空白折叠（中文场景保留单空格）
_WS_RE = re.compile(r"[ \t]{3,}")

# Prompt 注入特征（系统指令覆盖类措辞）
_INJECTION_PATTERNS: list[tuple[str, str]] = [
    # (代码, 正则)
    ("ignore_previous", r"忽略(之前|前面|以上|所有).{0,12}(指令|要求|规则|提示|约束)"),
    ("ignore_previous", r"ignore\s+(all\s+|any\s+|the\s+)?(previous|above|prior).{0,12}(instructions|prompts?|rules)"),
    ("override_system", r"(你不是(系统|AI助手|assistant).{0,20}你是|假装你是|直接扮演(系统|AI|assistant))"),
    ("override_system", r"(you\s+are\s+not\s+(the\s+)?(system|assistant).{0,30}you\s+are|pretend\s+(you'?re|to\s+be)\s+(the\s+)?(system|assistant))"),
    ("extract_prompt", r"(泄露|输出|展示|打印)(你的)?(系统)?(提示词|system\s*prompt|指令)"),
    ("extract_prompt", r"(print|reveal|show|leak|repeat)\s+(your|the|system)\s+(prompt|instructions)"),
    ("jailbreak", r"jailbreak|脱狱|越狱|DAN\b"),
    ("deception", r"不要告诉我|别告诉我你(是|的)"),
]


def sanitize_input(text: str) -> str:
    """净化：去控制字符、折叠空白、截断超长。"""
    if text is None:
        return ""
    text = _CTRL_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()[:_MAX_LEN]


def detect_injection(text: str) -> list[str]:
    """返回命中的注入特征代码列表（空 = 干净）。"""
    hits: list[str] = []
    for code, pattern in _INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            if code not in hits:
                hits.append(code)
    return hits


def defend_prompt(text: str) -> dict:
    """净化 + 检测，返回前端可见结果。

    Returns:
        {"clean": bool, "sanitized": str, "injection_flags": [code...]}
    """
    sanitized = sanitize_input(text)
    flags = detect_injection(sanitized)
    return {"clean": not flags, "sanitized": sanitized, "injection_flags": flags}
