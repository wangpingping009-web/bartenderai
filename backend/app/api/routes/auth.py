# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field

from app.core import auth
from app.core.config import settings
from app.core.ratelimit import SlidingWindowLimiter
from app.services.mail import send_password_reset, send_verification

router = APIRouter(prefix="/api/auth", tags=["auth"])
login_limiter = SlidingWindowLimiter(limit=settings.LOGIN_RATE_LIMIT, window_seconds=60)


def _development_link(path: str, token: str) -> str | None:
    if settings.ENV == "prod":
        return None
    return f"{settings.FRONTEND_URL}/{path}?token={token}"


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(default="", max_length=80)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=512)


class EmailIn(BaseModel):
    email: EmailStr


class ResetIn(TokenIn):
    password: str = Field(min_length=10, max_length=128)


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=128)


def _tokens(user: dict, response: Response) -> dict:
    access = auth.create_access_token(user)
    refresh = auth.issue_refresh_token(user["id"])
    auth.set_refresh_cookie(response, refresh)
    return {"access_token": access, "token_type": "bearer", "expires_in": 900, "user": user}


@router.post("/register", status_code=201)
def register(payload: RegisterIn) -> dict:
    user, token = auth.register_user(str(payload.email), payload.password, payload.display_name)
    try:
        send_verification(user["email"], token)
    except Exception as exc:
        development_url = _development_link("verify", token)
        if development_url:
            return {"message": "邮件服务不可用，请使用开发验证链接", "email": user["email"],
                    "verification_url": development_url}
        raise HTTPException(503, detail="账号已创建，但验证邮件暂时无法发送，请稍后重试") from exc
    result = {"message": "验证邮件已发送", "email": user["email"]}
    development_url = _development_link("verify", token)
    if development_url:
        result["verification_url"] = development_url
    return result


@router.post("/resend-verification")
def resend(payload: EmailIn) -> dict:
    row = auth.get_user_by_email(str(payload.email))
    development_url = None
    if row and not row["is_verified"]:
        token = auth.create_one_time_token(row["id"], "verify", 24)
        try:
            send_verification(row["email"], token)
        except Exception:
            development_url = _development_link("verify", token)
            if development_url is None:
                raise HTTPException(503, detail="验证邮件暂时无法发送")
    result = {"message": "如果账号存在，验证邮件已发送"}
    if development_url:
        result.update(message="邮件服务不可用，请使用开发验证链接",
                      verification_url=development_url)
    return result


@router.post("/verify")
def verify(payload: TokenIn) -> dict:
    return {"user": auth.verify_email(payload.token), "message": "邮箱验证成功"}


@router.post("/login")
def login(payload: LoginIn, request: Request, response: Response) -> dict:
    key = f"{request.client.host if request.client else 'unknown'}:{str(payload.email).lower()}"
    if not login_limiter.allow(key):
        raise HTTPException(429, detail="登录尝试过于频繁，请一分钟后重试")
    return _tokens(auth.authenticate(str(payload.email), payload.password), response)


@router.post("/refresh")
def refresh(request: Request, response: Response) -> dict:
    raw = request.cookies.get("bartender_refresh")
    if not raw:
        raise HTTPException(401, detail="缺少刷新令牌")
    user, new_refresh = auth.rotate_refresh_token(raw)
    auth.set_refresh_cookie(response, new_refresh)
    return {"access_token": auth.create_access_token(user), "token_type": "bearer",
            "expires_in": 900, "user": user}


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    auth.revoke_refresh_token(request.cookies.get("bartender_refresh"))
    response.delete_cookie("bartender_refresh", path="/api/auth")


@router.post("/forgot-password")
def forgot(payload: EmailIn) -> dict:
    row = auth.get_user_by_email(str(payload.email))
    development_url = None
    if row and row["is_active"]:
        token = auth.create_one_time_token(row["id"], "reset", 1)
        try:
            send_password_reset(row["email"], token)
        except Exception:
            development_url = _development_link("reset-password", token)
            if development_url is None:
                raise HTTPException(503, detail="重置邮件暂时无法发送")
    result = {"message": "如果账号存在，重置邮件已发送"}
    if development_url:
        result.update(message="邮件服务不可用，请使用开发重置链接",
                      reset_url=development_url)
    return result


@router.post("/reset-password")
def reset(payload: ResetIn) -> dict:
    row = auth.consume_one_time_token(payload.token, "reset")
    encoded = auth.hash_password(payload.password)
    from app.db.database import db
    with db() as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (encoded, row["id"]))
        conn.execute("UPDATE refresh_tokens SET revoked_at=datetime('now') WHERE user_id=? AND revoked_at IS NULL",
                     (row["id"],))
    return {"message": "密码已重置，请重新登录"}
