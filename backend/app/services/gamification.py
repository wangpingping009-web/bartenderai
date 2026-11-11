# -*- coding: utf-8 -*-
"""技能树 + 徽章（M7 玩法彩蛋）：完全确定性，无需 LLM。

记录用户成长动作 → 攒 XP → 升级（技能树）+ 达成徽章。
所有规则集中在 _BADGES / _LEVELS / _XP，纯函数可单测。

数据落库（user_progress / user_badges），按 user_id 隔离（M6 数据隔离原则）。
"""
from __future__ import annotations

from app.db.database import db

# ---------- 规则表（唯一事实源）----------

# 每个动作给的 XP
_XP: dict[str, int] = {
    "chat": 2,            # 聊一次天
    "favorite": 3,        # 收藏一杯
    "recipe_generate": 5, # AI 创作一杯
    "inventory": 1,       # 添加一个库存
    "mocktail": 6,        # 做一杯零酒精
    "daily": 1,           # 看每日一酒
    "banquet": 4,         # 规划一次晚宴
}

# 徽章：达成条件 = 累计某动作次数达到阈值
_BADGES: list[dict] = [
    {"id": "first_hello",   "name": "初次问候",    "emoji": "👋", "stat": "chat",    "threshold": 1,  "desc": "第一次与调酒师聊天"},
    {"id": "chat_10",       "name": "健谈者",      "emoji": "💬", "stat": "chat",    "threshold": 10, "desc": "累计聊天 10 次"},
    {"id": "collector_5",   "name": "收藏家",      "emoji": "📌", "stat": "favorite", "threshold": 5,  "desc": "收藏 5 杯配方"},
    {"id": "creator_3",     "name": "原创调酒师",  "emoji": "🧪", "stat": "recipe_generate", "threshold": 3, "desc": "AI 创作 3 杯"},
    {"id": "bar_owner",     "name": "吧台主理",    "emoji": "🏮", "stat": "inventory", "threshold": 10, "desc": "库存添加 10 种"},
    {"id": "mocktail_master", "name": "清醒调酒师", "emoji": "🍹", "stat": "mocktail", "threshold": 3,  "desc": "做 3 杯零酒精"},
    {"id": "daily_streak",  "name": "每日一酒",    "emoji": "📅", "stat": "daily",    "threshold": 7,  "desc": "连续看 7 天每日一酒"},
    {"id": "host_banquet",  "name": "晚宴主理",    "emoji": "🥂", "stat": "banquet",  "threshold": 1,  "desc": "规划一次晚宴"},
]

# 技能树等级（按累计 XP 升级）
_LEVELS: list[dict] = [
    {"level": 1, "min_xp": 0,   "name": "吧台萌新",     "emoji": "🌱"},
    {"level": 2, "min_xp": 10,  "name": "摇壶新手",     "emoji": "🥄"},
    {"level": 3, "min_xp": 30,  "name": "见习调酒师",   "emoji": "🥃"},
    {"level": 4, "min_xp": 60,  "name": "熟练调酒师",   "emoji": "🍸"},
    {"level": 5, "min_xp": 100, "name": "首席调酒师",   "emoji": "👑"},
]


def total_xp(stats: dict[str, int]) -> int:
    """按动作次数折算出累计 XP。"""
    return sum(_XP.get(k, 0) * v for k, v in stats.items())


def level_for_xp(xp: int) -> dict:
    """返回 xp 对应的等级（含下一级所需的缺口）。"""
    level = _LEVELS[0]
    for lv in _LEVELS:
        if xp >= lv["min_xp"]:
            level = lv
        else:
            break
    next_lv = _LEVELS[level["level"]] if level["level"] < len(_LEVELS) else None
    out = dict(level)
    out["xp"] = xp
    out["next_level"] = next_lv["name"] if next_lv else None
    out["xp_to_next"] = (next_lv["min_xp"] - xp) if next_lv else 0
    return out


def earned_badges(stats: dict[str, int]) -> list[dict]:
    """当前统计下已达成（且未被授予）的徽章。"""
    return [b for b in _BADGES if stats.get(b["stat"], 0) >= b["threshold"]]


def get_stats(user_id: int) -> dict[str, int]:
    """读取用户全部动作统计。"""
    with db() as conn:
        rows = conn.execute(
            "SELECT stat_key, stat_value FROM user_progress WHERE user_id = ?", (user_id,)).fetchall()
    return {r["stat_key"]: r["stat_value"] for r in rows}


def get_badges(user_id: int) -> set[str]:
    """用户已获得的徽章 id。"""
    with db() as conn:
        rows = conn.execute(
            "SELECT badge_id FROM user_badges WHERE user_id = ?", (user_id,)).fetchall()
    return {r["badge_id"] for r in rows}


def record_action(user_id: int, action: str) -> dict:
    """记录一次成长动作：加统计 + 结算新徽章。返回本次变化（可空）。

    幂等动作类型校验：未知动作静默忽略（不影响主流程，例如 GET 上报）。
    """
    if action not in _XP:
        return {"ok": False, "action": action, "earned": []}
    with db() as conn:
        conn.execute(
            """INSERT INTO user_progress (user_id, stat_key, stat_value) VALUES (?, ?, 1)
               ON CONFLICT(user_id, stat_key) DO UPDATE SET
                 stat_value = stat_value + 1,
                 updated_at = datetime('now', 'localtime')""",
            (user_id, action))
        # 结算徽章：读最新统计，比对已授予，补发
        stats = {
            row["stat_key"]: row["stat_value"]
            for row in conn.execute(
                "SELECT stat_key, stat_value FROM user_progress WHERE user_id = ?", (user_id,)
            ).fetchall()
        }
        have = {r["badge_id"] for r in conn.execute(
            "SELECT badge_id FROM user_badges WHERE user_id = ?", (user_id,)).fetchall()}
        newly = []
        for b in earned_badges(stats):
            if b["id"] not in have:
                conn.execute("INSERT INTO user_badges (user_id, badge_id) VALUES (?, ?)",
                             (user_id, b["id"]))
                newly.append(b)
    return {"ok": True, "action": action, "earned": newly}


def record_action_once(user_id: int, action: str, claim_key: str) -> dict:
    """Record idempotent events such as one daily pick view per calendar day."""
    if action not in _XP:
        return {"ok": False, "action": action, "earned": []}
    with db() as conn:
        exists = conn.execute(
            "SELECT 1 FROM user_action_claims WHERE user_id=? AND action=? AND claim_key=?",
            (user_id, action, claim_key),
        ).fetchone()
        if exists:
            return {"ok": True, "action": action, "earned": [], "duplicate": True}
        conn.execute(
            "INSERT INTO user_action_claims(user_id,action,claim_key) VALUES(?,?,?)",
            (user_id, action, claim_key),
        )
    result = record_action(user_id, action)
    result["duplicate"] = False
    return result


def get_progress(user_id: int) -> dict:
    """用户成长全貌：统计 / XP / 等级 / 已获徽章 / 未获徽章。"""
    stats = get_stats(user_id)
    xp = total_xp(stats)
    level = level_for_xp(xp)
    have = get_badges(user_id)
    badges = [
        {**b, "earned": b["id"] in have, "progress": min(stats.get(b["stat"], 0), b["threshold"])}
        for b in _BADGES
    ]
    return {"user_id": user_id, "stats": stats, "xp": xp,
            "level": level, "badges": badges, "earned_count": len(have)}


def resolve_user(username: str) -> int:
    """username → users.id；不存在则创建。业务接口统一用这个名字记成长。"""
    from app.db.database import db
    with db() as conn:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if row is None:
            cur = conn.execute("INSERT INTO users (username) VALUES (?)", (username,))
            return cur.lastrowid
        return row["id"]


def bump(username: str, action: str) -> dict:
    """业务侧一行上报：username + 动作 → 结算徽章。未知动作静默。"""
    return record_action(resolve_user(username), action)
