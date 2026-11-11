# -*- coding: utf-8 -*-
"""Email authentication, Argon2id passwords and rotating refresh tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.db.database import db

_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_bearer = HTTPBearer(auto_error=False)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_password(password: str) -> None:
    if len(password) < 10 or not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise HTTPException(422, detail="密码至少10位，并同时包含字母和数字")


def hash_password(password: str) -> str:
    validate_password(password)
    return _hasher.hash(password)


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        return _hasher.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_access_token(user: dict) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    now = int(time.time())
    payload = _b64(json.dumps({
        "sub": str(user["id"]), "email": user.get("email"), "role": user.get("role", "user"),
        "type": "access", "iat": now, "exp": now + settings.ACCESS_TOKEN_MINUTES * 60,
    }, separators=(",", ":")).encode())
    sig = _b64(hmac.new(settings.SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def decode_access_token(token: str) -> dict:
    try:
        header, payload, sig = token.split(".")
        expected = _b64(hmac.new(settings.SECRET_KEY.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")
        data = json.loads(_unb64(payload))
        if data.get("type") != "access" or int(data.get("exp", 0)) <= int(time.time()):
            raise ValueError("expired")
        return data
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效") from exc


def public_user(row) -> dict:
    return {
        "id": row["id"], "email": row["email"], "display_name": row["display_name"] or "",
        "role": row["role"], "is_verified": bool(row["is_verified"]), "username": row["username"],
    }


def get_user_by_email(email: str):
    with db() as conn:
        return conn.execute("SELECT * FROM users WHERE lower(email) = lower(?)", (email.strip(),)).fetchone()


def get_user_by_id(user_id: int):
    with db() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def register_user(email: str, password: str, display_name: str = "") -> tuple[dict, str]:
    email = email.strip().lower()
    if get_user_by_email(email):
        raise HTTPException(409, detail="该邮箱已注册")
    encoded = hash_password(password)
    role = "admin" if settings.ADMIN_EMAIL and email == settings.ADMIN_EMAIL.lower() else "user"
    username = f"user_{hashlib.sha1(email.encode()).hexdigest()[:16]}"
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO users(username,email,password_hash,display_name,role,is_verified,is_active) "
            "VALUES(?,?,?,?,?,0,1)", (username, email, encoded, display_name.strip()[:80], role))
        user_id = cur.lastrowid
    token = create_one_time_token(user_id, "verify", settings.VERIFY_TOKEN_HOURS)
    return public_user(get_user_by_id(user_id)), token


def create_one_time_token(user_id: int, token_type: str, hours: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = _iso(_utcnow() + timedelta(hours=hours))
    with db() as conn:
        conn.execute("DELETE FROM auth_tokens WHERE user_id=? AND token_type=? AND used_at IS NULL", (user_id, token_type))
        conn.execute(
            "INSERT INTO auth_tokens(user_id,token_hash,token_type,expires_at) VALUES(?,?,?,?)",
            (user_id, _hash_token(token), token_type, expires))
    return token


def consume_one_time_token(token: str, token_type: str):
    digest = _hash_token(token)
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM auth_tokens WHERE token_hash=? AND token_type=? AND used_at IS NULL",
            (digest, token_type)).fetchone()
        if not row or datetime.fromisoformat(row["expires_at"]) <= _utcnow():
            raise HTTPException(400, detail="链接无效或已过期")
        conn.execute("UPDATE auth_tokens SET used_at=? WHERE id=?", (_iso(_utcnow()), row["id"]))
    return get_user_by_id(row["user_id"])


def verify_email(token: str) -> dict:
    user = consume_one_time_token(token, "verify")
    with db() as conn:
        conn.execute("UPDATE users SET is_verified=1 WHERE id=?", (user["id"],))
    return public_user(get_user_by_id(user["id"]))


def authenticate(email: str, password: str) -> dict:
    row = get_user_by_email(email)
    if not row or not verify_password(password, row["password_hash"]):
        raise HTTPException(401, detail="邮箱或密码错误")
    if not row["is_active"]:
        raise HTTPException(403, detail="账号已停用")
    if not row["is_verified"]:
        raise HTTPException(403, detail="请先完成邮箱验证")
    return public_user(row)


def issue_refresh_token(user_id: int) -> str:
    token = secrets.token_urlsafe(48)
    expires = _iso(_utcnow() + timedelta(days=settings.REFRESH_TOKEN_DAYS))
    with db() as conn:
        conn.execute("INSERT INTO refresh_tokens(user_id,token_hash,expires_at) VALUES(?,?,?)",
                     (user_id, _hash_token(token), expires))
    return token


def rotate_refresh_token(token: str) -> tuple[dict, str]:
    digest = _hash_token(token)
    with db() as conn:
        row = conn.execute("SELECT * FROM refresh_tokens WHERE token_hash=?", (digest,)).fetchone()
        if not row or row["revoked_at"] or datetime.fromisoformat(row["expires_at"]) <= _utcnow():
            raise HTTPException(401, detail="刷新令牌无效")
        new_token = secrets.token_urlsafe(48)
        new_hash = _hash_token(new_token)
        conn.execute("UPDATE refresh_tokens SET revoked_at=?, replaced_by=? WHERE id=?",
                     (_iso(_utcnow()), new_hash, row["id"]))
        conn.execute("INSERT INTO refresh_tokens(user_id,token_hash,expires_at) VALUES(?,?,?)",
                     (row["user_id"], new_hash, _iso(_utcnow() + timedelta(days=settings.REFRESH_TOKEN_DAYS))))
    user = get_user_by_id(row["user_id"])
    if not user or not user["is_active"]:
        raise HTTPException(401, detail="账号不可用")
    return public_user(user), new_token


def revoke_refresh_token(token: str | None) -> None:
    if not token:
        return
    with db() as conn:
        conn.execute("UPDATE refresh_tokens SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                     (_iso(_utcnow()), _hash_token(token)))


async def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="需要登录")
    claims = decode_access_token(credentials.credentials)
    row = get_user_by_id(int(claims["sub"]))
    if not row or not row["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="账号不可用")
    return public_user(row)


async def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def set_refresh_cookie(response, token: str) -> None:
    response.set_cookie(
        "bartender_refresh", token, max_age=settings.REFRESH_TOKEN_DAYS * 86400,
        httponly=True, secure=settings.ENV == "prod", samesite="lax", path="/api/auth")
