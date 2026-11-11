# -*- coding: utf-8 -*-
"""SQLAlchemy 2 models for user data, conversations and AI operations."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(80), default="", server_default="")
    role: Mapped[str] = mapped_column(String(20), default="user", server_default="user")
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    created_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class Profile(Base):
    __tablename__ = "profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    profile_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    updated_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class Inventory(Base):
    __tablename__ = "inventory"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    item_name: Mapped[str] = mapped_column(String(128), primary_key=True)
    added_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class ChatHistory(Base):
    """Compatibility storage for the prototype single-thread chat API."""
    __tablename__ = "chat_history"
    __table_args__ = (Index("idx_chat_user", "user_id", "id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="新对话", server_default="新对话")
    created_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    created_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "recipe_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    recipe_name: Mapped[str] = mapped_column(String(160))
    recipe_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    token_type: Mapped[str] = mapped_column(String(20))
    expires_at: Mapped[str] = mapped_column(String)
    used_at: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[str] = mapped_column(String)
    revoked_at: Mapped[str | None] = mapped_column(String)
    replaced_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    recipe_id: Mapped[str] = mapped_column(String(80), default="", server_default="")
    recipe_name: Mapped[str] = mapped_column(String(160), default="", server_default="")
    rating: Mapped[int] = mapped_column(Integer)
    tags_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class Creation(Base):
    __tablename__ = "creations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    recipe_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("task", "version"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task: Mapped[str] = mapped_column(String(80), index=True)
    version: Mapped[str] = mapped_column(String(32))
    system_text: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", server_default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    result_json: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    error: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class UsageLog(Base):
    __tablename__ = "usage_log"
    __table_args__ = (Index("idx_usage_user", "user_id", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), default="", server_default="")
    task: Mapped[str] = mapped_column(String(80), default="", server_default="")
    provider: Mapped[str] = mapped_column(String(80), default="", server_default="")
    model: Mapped[str] = mapped_column(String(120), default="", server_default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    cost_cny: Mapped[float] = mapped_column(Float, default=0, server_default=text("0"))
    created_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class KnowledgeVersion(Base):
    __tablename__ = "knowledge_versions"
    __table_args__ = (Index("idx_kv_file", "filename", "created_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    created_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class UserProgress(Base):
    __tablename__ = "user_progress"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    stat_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    stat_value: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    updated_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class UserBadge(Base):
    __tablename__ = "user_badges"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    badge_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    earned_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class UserActionClaim(Base):
    __tablename__ = "user_action_claims"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    action: Mapped[str] = mapped_column(String(64), primary_key=True)
    claim_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    created_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))


class EvalRun(Base):
    __tablename__ = "eval_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    scores_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String, default=_now, server_default=text("CURRENT_TIMESTAMP"))
