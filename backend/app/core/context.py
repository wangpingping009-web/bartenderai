# -*- coding: utf-8 -*-
"""ContextVars 请求级上下文隔离（REQUIREMENTS 并发隔离原则）。

为什么需要:
- FastAPI 是异步并发服务，多个用户的请求同时到达
- 如果用全局变量存"当前库存/画像/会话"，会串数据（用户A看到用户B的库存）
- ContextVars 是 Python 的线程/协程级隔离变量：每个请求设置一次，
  该请求内部的任意函数都能读到，但请求之间互不干扰

用法:
  set_current_session(user_id, session_id)   # 请求入口设置
  get_current_session()                       # Agent 内部读取
  reset_current_session()                     # 请求结束清理（防泄漏）

M6 会扩展：请求 ID 透传 / 审计日志关联 / Langfuse trace 绑定。
"""
from __future__ import annotations

import contextvars
from typing import Any

# 每个请求的会话上下文。用 contextvars 隔离，天然线程/协程安全。
_current: contextvars.ContextVar[dict] = contextvars.ContextVar("bartenderai_session",
                                                                 default={})


def set_current_session(user_id: str | None = None, session_id: str | None = None,
                        **extra: Any) -> contextvars.Token:
    """设置当前请求的会话上下文，返回 Token（用于 reset）。

    在请求入口调用一次。内部会合并到一个 dict，供各 Agent 读取。
    """
    data = {"user_id": user_id, "session_id": session_id, "stock": None,
            "profile": None, "request_id": None, **extra}
    return _current.set(data)


def get_current_session() -> dict:
    """读取当前请求的会话上下文（Agent 内部用）。"""
    return _current.get()


def update_current_session(**extra: Any) -> None:
    """就地更新当前会话的部分字段（如放入库存、画像）。"""
    data = _current.get()
    data.update(extra)
    _current.set(data)


def reset_current_session(token: contextvars.Token | None = None) -> None:
    """清理当前请求上下文（防线程池复用污染）。"""
    try:
        if token is not None:
            _current.reset(token)
        else:
            _current.set({})
    except (ValueError, LookupError):
        pass
