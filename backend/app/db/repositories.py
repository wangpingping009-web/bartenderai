# -*- coding: utf-8 -*-
"""数据访问层：用户 / 库存 / 画像 / 对话历史的 CRUD。

约定：对外统一用 username（字符串）标识用户，内部映射到 users.id。
get_or_create 语义：拿用户名即返回用户，不存在则自动创建（guest 免注册开箱即用）。
"""
from __future__ import annotations

import json

from app.db.database import db


# ---------- 用户 ----------

def get_or_create_user(username: str) -> dict:
    """按用户名取用户，不存在则创建。返回 {"id", "username"}。"""
    with db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if row is not None:
            return {"id": row["id"], "username": row["username"]}
        cur = conn.execute("INSERT INTO users (username) VALUES (?)", (username,))
        return {"id": cur.lastrowid, "username": username}


def _user_id(username: str) -> int:
    return get_or_create_user(username)["id"]


# ---------- 库存 ----------

def list_inventory(username: str) -> list[str]:
    """用户库存 = 材料名列表（stock Agent 的输入格式），按添加顺序。"""
    with db() as conn:
        rows = conn.execute(
            "SELECT item_name FROM inventory WHERE user_id = ? ORDER BY rowid",
            (_user_id(username),)).fetchall()
    return [r["item_name"] for r in rows]


def add_inventory_item(username: str, item_name: str) -> None:
    """添加一件库存（重名幂等）。"""
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO inventory (user_id, item_name) VALUES (?, ?)",
            (_user_id(username), item_name.strip()))


def remove_inventory_item(username: str, item_name: str) -> bool:
    """移除一件库存，返回是否真的删了。"""
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM inventory WHERE user_id = ? AND item_name = ?",
            (_user_id(username), item_name))
        return cur.rowcount > 0


def set_inventory(username: str, items: list[str]) -> None:
    """整体替换库存（如前端批量导入）。"""
    with db() as conn:
        uid = _user_id(username)
        conn.execute("DELETE FROM inventory WHERE user_id = ?", (uid,))
        conn.executemany(
            "INSERT OR IGNORE INTO inventory (user_id, item_name) VALUES (?, ?)",
            [(uid, it.strip()) for it in items if it.strip()])


# ---------- 画像 ----------

def get_profile(username: str) -> dict:
    """读取用户画像（空则返回默认）。"""
    with db() as conn:
        row = conn.execute(
            "SELECT profile_json FROM profiles WHERE user_id = ?",
            (_user_id(username),)).fetchone()
    if row is None:
        return {}
    try:
        return json.loads(row["profile_json"] or "{}")
    except json.JSONDecodeError:
        return {}


def save_profile(username: str, profile: dict) -> dict:
    """覆盖保存画像。"""
    with db() as conn:
        uid = _user_id(username)
        conn.execute(
            "INSERT INTO profiles (user_id, profile_json) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET profile_json = excluded.profile_json, "
            "updated_at = datetime('now', 'localtime')",
            (uid, json.dumps(profile, ensure_ascii=False)))
    return profile


def merge_profile(username: str, new_profile: dict) -> dict:
    """增量合并画像（新的覆盖旧的，列表去重）。"""
    from app.services.profile import merge_profiles
    merged = merge_profiles(get_profile(username), new_profile)
    return save_profile(username, merged)


# ---------- 对话历史（M6：落库加密）----------

def append_chat(username: str, role: str, content: str) -> None:
    from app.core.crypto import encrypt_text
    with db() as conn:
        conn.execute(
            "INSERT INTO chat_history (user_id, role, content) VALUES (?, ?, ?)",
            (_user_id(username), role, encrypt_text(content)))


def list_chat_history(username: str, limit: int = 20) -> list[dict]:
    """最近对话（旧→新），供 Agent 记忆上下文。密文自动解密，老明文透传。"""
    from app.core.crypto import decrypt_text
    with db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM chat_history WHERE user_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (_user_id(username), limit)).fetchall()
    return [{"role": r["role"], "content": decrypt_text(r["content"])} for r in reversed(rows)]


# ---------- 收藏 ----------

def list_favorites(username: str) -> list[dict]:
    """用户收藏的配方卡（新→旧）。"""
    with db() as conn:
        rows = conn.execute(
            "SELECT recipe_name, recipe_json, created_at FROM favorites "
            "WHERE user_id = ? ORDER BY id DESC",
            (_user_id(username),)).fetchall()
    out = []
    for r in rows:
        try:
            card = json.loads(r["recipe_json"])
        except json.JSONDecodeError:
            card = {}
        out.append({"name": r["recipe_name"], "recipe": card,
                    "created_at": r["created_at"]})
    return out


def add_favorite(username: str, recipe: dict) -> None:
    """收藏一个配方（同名幂等覆盖）。"""
    name = (recipe.get("name") or "未命名配方").strip()
    with db() as conn:
        conn.execute(
            "INSERT INTO favorites (user_id, recipe_name, recipe_json) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, recipe_name) DO UPDATE SET "
            "recipe_json = excluded.recipe_json, created_at = datetime('now', 'localtime')",
            (_user_id(username), name, json.dumps(recipe, ensure_ascii=False)))


def remove_favorite(username: str, recipe_name: str) -> bool:
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM favorites WHERE user_id = ? AND recipe_name = ?",
            (_user_id(username), recipe_name))
        return cur.rowcount > 0
