# -*- coding: utf-8 -*-
"""性能画像：流式跑一轮真实多 Agent 对话，记录各 Agent 完成时间。

用法（容器内）: PYTHONPATH=/app python scripts/profile_chat.py "问题"
输出: 总耗时 / 每 Agent 完成时间戳 / 答案字数
"""
from __future__ import annotations

import io
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.core.context import set_current_session, reset_current_session
from app.graph.graph import get_graph

QUERY = sys.argv[1] if len(sys.argv) > 1 else "我想喝点酸甜的度数不高的，推荐几款"

t0 = time.time()
t_done: dict[str, float] = {}
answer_len = 0

token = set_current_session(user_id="profile_user", session_id="profile_sess")
try:
    graph = get_graph()
    initial = {
        "user_query": QUERY,
        "history": [],
        "user_id": "profile_user",
        "session_id": "profile_sess",
        "agent_outputs": [],
        "events": [],
        "references": [],
        "revise_count": 0,
    }
    start_events: dict[str, float] = {}
    done_events: dict[str, float] = {}
    last: dict = {}
    for item in graph.stream(initial, stream_mode=["updates", "custom"]):
        if not isinstance(item, tuple):
            continue
        mode, chunk = item
        if mode == "custom":
            if chunk.get("kind") == "agent_event":
                agent = chunk.get("agent", "")
                msg = chunk.get("message", "")
                if "开始" in msg:
                    start_events.setdefault(agent, time.time() - t0)
                if "完成" in msg:
                    done_events.setdefault(agent, time.time() - t0)
        elif mode == "updates":
            for node, upd in chunk.items():
                done_events.setdefault(node, time.time() - t0)
                last.update(upd)
    final = last
finally:
    reset_current_session(token)

total = time.time() - t0
print(f"profile: 总耗时 {total:.1f}s, 答案{len(final.get('final_answer',''))}字")
print(f"verdict: {final.get('review_verdict','')}, revise={final.get('revise_count',0)}")
print(f"回炉issues: {final.get('review_issues', [])}")
print("完成时间: " + ", ".join(f"{k}={v:.1f}s" for k, v in sorted(done_events.items(), key=lambda x: x[1])))
print("---")
print(final.get("final_answer", "")[:600])
