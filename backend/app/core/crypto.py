# -*- coding: utf-8 -*-
"""静态数据加密（M6 数据隔离+加密）。

对话内容 / 画像敏感字段在落库前用 Fernet 对称加密，
密钥由 SECRET_KEY 派生 —— 数据库文件泄露也读不出明文内容。

设计：
- 密钥不落盘：由 SECRET_KEY 经 SHA-256 派生，换 SECRET_KEY 即失效（安全前提）
- 加密/解密都带版本前缀 v1:，将来换算法可平滑迁移
- 解密失败优雅降级：老数据是明文，直接透传，不崩
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        key = base64.urlsafe_b64encode(
            hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest())
        _fernet = Fernet(key)
    return _fernet


def encrypt_text(text: str) -> str:
    """加密普通文本，返回 v1: 前缀的密文。空串原样返回。"""
    if not text:
        return text
    return "v1:" + _get_fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt_text(cipher: str) -> str:
    """解密密文。明文 / 损坏 / 密钥不符 → 原样或空串返回（不抛）。"""
    if not cipher:
        return cipher
    if not cipher.startswith("v1:"):
        return cipher  # 历史明文数据
    try:
        return _get_fernet().decrypt(cipher[3:].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""
