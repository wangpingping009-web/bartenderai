# -*- coding: utf-8 -*-
"""健康检查：LLM 配置 / Milvus / DB / 状态图。

语义：组件全部可用 = 200 status ok；部分降级 = 200 status degraded
（不返回 500，让前端能展示"哪些能力可用"而不是报错）。
"""
from __future__ import annotations

import socket
import time

from fastapi import APIRouter

from app.core.config import settings
from app.db.database import db
from app.core.llm import _is_placeholder, llm_provider_health, llm_runtime_health

router = APIRouter(tags=["health"])

_MILVUS_CACHE_TTL_SECONDS = 15.0
_milvus_cache = {"checked_at": 0.0, "available": False}
_smtp_cache = {"checked_at": 0.0, "available": False}


def _milvus_available(*, timeout: float = 0.75, use_cache: bool = True) -> bool:
    """Probe Milvus without making capability discovery a long blocking call."""
    now = time.monotonic()
    if use_cache and now - _milvus_cache["checked_at"] < _MILVUS_CACHE_TTL_SECONDS:
        return bool(_milvus_cache["available"])

    available = False
    alias = "_health"
    try:
        from pymilvus import connections
        connections.connect(
            alias=alias,
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
            timeout=timeout,
        )
        available = True
        connections.disconnect(alias)
    except Exception:
        try:
            from pymilvus import connections
            connections.disconnect(alias)
        except Exception:
            pass

    _milvus_cache.update(checked_at=now, available=available)
    return available


def _smtp_available(*, timeout: float = 0.25) -> bool:
    now = time.monotonic()
    if now - _smtp_cache["checked_at"] < _MILVUS_CACHE_TTL_SECONDS:
        return bool(_smtp_cache["available"])
    available = False
    if settings.SMTP_HOST:
        try:
            with socket.create_connection((settings.SMTP_HOST, settings.SMTP_PORT), timeout=timeout):
                available = True
        except OSError:
            pass
    _smtp_cache.update(checked_at=now, available=available)
    return available


@router.get("/api/capabilities")
def capabilities() -> dict:
    qwen = bool(settings.QWEN_API_KEY and not _is_placeholder(settings.QWEN_API_KEY))
    deepseek = bool(settings.DEEPSEEK_API_KEY and not _is_placeholder(settings.DEEPSEEK_API_KEY))
    local = bool(settings.LOCAL_LLM_BASE_URL.strip() and settings.LOCAL_LLM_MODEL.strip())
    configured = qwen or deepseek or local
    runtime = llm_runtime_health()
    available = configured and runtime["available"] is True
    status = ("available" if available else
              "unverified" if configured and runtime["available"] is None else
              "unavailable")
    return {
        "llm": {"available": available, "configured": configured,
                "status": status,
                "reason": runtime["reason"] if configured and not available else None,
                "providers": llm_provider_health()},
        "retrieval": {"milvus": _milvus_available(), "local": True},
        "web_search": {"available": bool(settings.TAVILY_API_KEY)},
        "vision": {"available": qwen, "model": settings.QWVL_MODEL if qwen else None},
        "mail": {"available": _smtp_available(), "configured": bool(settings.SMTP_HOST),
                 "mode": "smtp" if settings.ENV == "prod" else "mailpit"},
    }


@router.get("/api/health", response_model=dict)
def health_check() -> dict:
    # LLM：任一供应商配置了真实 key（占位符视为未配置）
    qwen_ok = settings.QWEN_API_KEY and not _is_placeholder(settings.QWEN_API_KEY)
    ds_ok = settings.DEEPSEEK_API_KEY and not _is_placeholder(settings.DEEPSEEK_API_KEY)
    local_ok = bool(settings.LOCAL_LLM_BASE_URL.strip() and settings.LOCAL_LLM_MODEL.strip())
    llm_configured = bool(qwen_ok or ds_ok or local_ok)
    # Keep the advertised primary provider identical to the actual runtime
    # order from LLM_PROVIDER_PRIORITY. This avoids showing Qwen as primary
    # while every Agent is in fact routed to DeepSeek first.
    providers = llm_provider_health()
    provider = providers[0]["name"] if providers else None

    # Milvus：可达性探测（连不上不算致命，走 LLM 兜底）
    milvus = "up" if _milvus_available(timeout=1.5, use_cache=False) else "down"

    # DB：SQLite 可建表即可
    db_ok = False
    try:
        from app.db.database import init_db
        init_db()
        with db() as conn:
            conn.execute("SELECT 1")
        db_ok = True
    except Exception:
        pass

    # 状态图：能构建即可
    graph_ok = False
    try:
        from app.graph.graph import get_graph
        get_graph()
        graph_ok = True
    except Exception:
        pass

    # 检索模式：Milvus 可达 = 完整向量检索；否则本地文件兜底 = 关键词检索（功能仍完整）
    retrieval_mode = "milvus" if milvus == "up" else "none"
    if retrieval_mode == "none":
        try:
            from app.rag.hybrid import _load_local_kb
            if _load_local_kb().get("cocktails"):
                retrieval_mode = "local"
        except Exception:
            pass

    runtime = llm_runtime_health()
    llm_available = llm_configured and runtime["available"] is True
    status = "ok" if (llm_available and milvus == "up") else "degraded"
    return {
        "status": status,
        "llm_configured": llm_configured,
        "llm_available": llm_available,
        "llm_failure_reason": runtime["reason"] if llm_configured and not llm_available else None,
        "llm_provider": provider,
        "llm_providers": providers,
        "milvus": milvus,
        "retrieval_mode": retrieval_mode,
        "db": "up" if db_ok else "down",
        "graph": "up" if graph_ok else "down",
    }
