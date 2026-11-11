# -*- coding: utf-8 -*-
"""全链路审计日志（M6 审计日志）。

落盘 JSONL（data/audit/audit.YYYY-MM-DD.jsonl），每天一个文件：
- 每次 HTTP 请求（中间件）：方法 / 路径 / 用户 / 状态码 / 耗时
- 关键业务动作（Agent 执行 / 配方生成 / 库存变更 / 注入告警）
  ：action + 用户 + 摘要 + 结果，不落敏感内容（明文消息只记哈希）

审计与数据分离：审计只追加不可改写，是"出了事能查"的凭证。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from app.core.config import settings

_AUDIT_DIR = Path(__file__).resolve().parents[2] / "data" / "audit"


def _safe_json(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _today_path() -> Path:
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    return _AUDIT_DIR / f"audit.{time.strftime('%Y-%m-%d')}.jsonl"


def audit_log(action: str, user: str = "", detail: str = "",
              status: int = 200, latency_ms: float | None = None,
              **extra) -> None:
    """写一条审计记录。detail 只记摘要，不落明文消息。"""
    record = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "user": (user or "")[:64],
        "detail": (detail or "")[:200],
        "status": status,
        "latency_ms": latency_ms,
        **extra,
    }
    try:
        with _today_path().open("a", encoding="utf-8") as f:
            f.write(_safe_json(record) + "\n")
    except OSError:
        pass  # 审计失败不拖垮业务


def summarize(text: str) -> str:
    """明文 → 摘要哈希（审计里不存明文）。"""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def query_audit(limit: int = 100, action: str | None = None,
                days: int = 1) -> list[dict]:
    """读取最近审计记录（管理端 / 测试用）。"""
    records: list[dict] = []
    for d in range(days):
        p = _AUDIT_DIR / f"audit.{time.strftime('%Y-%m-%d', time.localtime(time.time() - d * 86400))}.jsonl"
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if action and rec.get("action") != action:
                continue
            records.append(rec)
    return records[-limit:]
