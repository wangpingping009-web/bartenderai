# -*- coding: utf-8 -*-
"""滑动窗口限流（M6 限流+成本看板）。

纯内存实现（单机够用，多实例可平滑换 Redis）：
- 每 key 维护一个时间戳队列，窗口内请求数超限则拒绝
- 线程安全（SSE 流式执行在 worker 线程，需加锁）
- 被拒返回 429 + Retry-After
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    """滑动窗口限流器。key 粒度由调用方决定（IP / user_id / 全局）。"""

    def __init__(self, limit: int, window_seconds: float = 60.0):
        assert limit > 0
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """当前请求是否放行（窗口内计数 < limit）。放行则记账。"""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            # 清掉窗口外的旧时间戳
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def remaining(self, key: str) -> int:
        """窗口内剩余可用次数（用于 Retry-After / 前端提示）。"""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= self.window:
                q.popleft()
            return max(0, self.limit - len(q))


# 全局单例：聊天按 user_id 限流，创作按 user_id 限流
from app.core.config import settings  # noqa: E402

chat_limiter = SlidingWindowLimiter(settings.CHAT_RATE_LIMIT)
gen_limiter = SlidingWindowLimiter(settings.GEN_RATE_LIMIT)


# ---------- FastAPI 依赖 ----------

def check_chat_quota(user_id: str) -> str:
    """聊天限流依赖：超限抛 429，否则返回 user_id。"""
    from fastapi import HTTPException
    if not chat_limiter.allow(user_id):
        raise HTTPException(
            status_code=429,
            detail=f"请求过于频繁，请稍后再试（{chat_limiter.remaining(user_id)} 秒后可恢复）",
        )
    return user_id


def check_gen_quota(user_id: str) -> str:
    """配方创作限流依赖。"""
    from fastapi import HTTPException
    if not gen_limiter.allow(user_id):
        raise HTTPException(
            status_code=429,
            detail=f"创作过于频繁，请稍后再试（{gen_limiter.remaining(user_id)} 秒后可恢复）",
        )
    return user_id
