# -*- coding: utf-8 -*-
"""Minimal SMTP delivery used by Mailpit in development and SMTP in production."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.core.config import settings


def send_mail(to: str, subject: str, text: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    smtp_cls = smtplib.SMTP_SSL if settings.SMTP_SSL else smtplib.SMTP
    with smtp_cls(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(msg)


def send_verification(email: str, token: str) -> None:
    url = f"{settings.FRONTEND_URL}/verify?token={token}"
    send_mail(email, "验证你的 BartenderAI 账号", f"请在24小时内打开以下链接完成验证：\n\n{url}\n")


def send_password_reset(email: str, token: str) -> None:
    url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    send_mail(email, "重置 BartenderAI 密码", f"请在1小时内打开以下链接设置新密码：\n\n{url}\n")
