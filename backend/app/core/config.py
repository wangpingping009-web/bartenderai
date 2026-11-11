# -*- coding: utf-8 -*-
"""全项目配置（基于 pydantic-settings）。

规则：
- 从 .env / 环境变量读取，未配置时用下方默认值（保证开箱即跑）
- 敏感信息（API Key）只在这里读取一次，业务代码不直接碰环境变量
- M6 会在此基础上扩展：多供应商路由 / 限流 / 成本等
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",          # 项目根目录的 .env（见 .env.example）
        env_file_encoding="utf-8",
        extra="ignore",           # 容忍 .env 里多余的键
    )

    # ---------- 应用 ----------
    APP_NAME: str = "BartenderAI"
    ENV: str = "dev"
    SECRET_KEY: str = "dev-secret-change-me"
    LOG_LEVEL: str = "INFO"

    # ---------- LLM（国内模型，多供应商）----------
    QWEN_API_KEY: str = ""
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    QWEN_MODEL: str = "qwen-plus"

    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    DEEPSEEK_MODEL: str = "deepseek-chat"

    # 任意 OpenAI-compatible 本地服务（Ollama / LM Studio / vLLM）。仅当
    # URL 和模型名同时填写时启用；本地服务通常不校验 key。
    LOCAL_LLM_BASE_URL: str = ""
    LOCAL_LLM_MODEL: str = ""
    LOCAL_LLM_API_KEY: str = ""
    LLM_PROVIDER_PRIORITY: str = "deepseek,qwen,local"

    # 交互式问答的尾延迟控制：一次重试足够，避免单轮请求最多等待数分钟
    LLM_TIMEOUT_SECONDS: int = 45
    LLM_MAX_RETRIES: int = 1
    LLM_CIRCUIT_BREAKER_SECONDS: int = 60
    AGENT_TIMEOUT_SECONDS: int = 60

    # 公网检索补充（Tavily Search API；留空则 search_web 返回未启用提示）
    TAVILY_API_KEY: str = ""

    # 多模态（拍照识别库存，M4）
    QWVL_MODEL: str = "qwen-vl-plus"

    # 嵌入 / 重排模型（首次运行联网下载）
    EMBED_MODEL_PATH: str = "BAAI/bge-m3"
    RERANK_MODEL_PATH: str = "BAAI/bge-reranker-v2-m3"

    # HuggingFace 镜像加速（国内下载 bge 模型必备）
    HF_ENDPOINT: str = "https://hf-mirror.com"

    # ---------- 数据库 ----------
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DB: str = "bartenderai"

    # 本地持久化（M4 用户/库存/画像/对话；生产可平滑切 MySQL）
    DATABASE_PATH: str = "data/app.db"
    DATABASE_URL: str = ""

    # ---------- 账号与邮件 ----------
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 30
    VERIFY_TOKEN_HOURS: int = 24
    RESET_TOKEN_HOURS: int = 1
    FRONTEND_URL: str = "http://localhost:5173"
    ADMIN_EMAIL: str = ""
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "BartenderAI <noreply@bartenderai.local>"
    SMTP_STARTTLS: bool = False
    SMTP_SSL: bool = False

    # ---------- 向量库 ----------
    MILVUS_HOST: str = "localhost"
    MILVUS_PORT: int = 19530

    # ---------- 可观测 ----------
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "http://localhost:3000"

    # ---------- 安全（M6）----------
    # CORS 白名单：逗号分隔的 origin，* = 全放（dev 默认）
    CORS_ORIGINS: str = "*"
    # 对话内容落库加密（Fernet，密钥派生自 SECRET_KEY）
    ENCRYPT_CHAT: bool = True
    # 聊天限流（次/分钟，按 user_id）
    CHAT_RATE_LIMIT: int = 20
    GEN_RATE_LIMIT: int = 10
    LOGIN_RATE_LIMIT: int = 10
    MAX_UPLOAD_MB: int = 8

    # ---------- 其他 ----------
    RATE_LIMIT_PER_MIN: int = 20
    # 检索硬约束（防 token 失控，见 REQUIREMENTS 3.2）
    # MAX_ROUNDS=2：反思检索每轮要跑一次 LLM 判断 + 全链路检索（decompose/
    # encode/rerank），3 轮实测 47s+。开放/推荐类问题首轮候选已够用，
    # 2 轮足以覆盖"配方问"场景且省 ~15s（RAGAS run#2 验证质量不降）。
    RETRIEVE_MAX_ROUNDS: int = 2
    RETRIEVE_MIN_ANGLES: int = 2


settings = Settings()


def validate_runtime_settings() -> None:
    """Fail closed when production is started with development security defaults."""
    if settings.ENV != "prod":
        return
    problems = []
    if settings.SECRET_KEY == "dev-secret-change-me" or len(settings.SECRET_KEY) < 32:
        problems.append("SECRET_KEY 必须是至少 32 位的随机值")
    origins = {item.strip() for item in settings.CORS_ORIGINS.split(",") if item.strip()}
    if not origins or "*" in origins:
        problems.append("CORS_ORIGINS 不能包含通配符")
    if not settings.FRONTEND_URL.startswith("https://"):
        problems.append("FRONTEND_URL 必须使用 HTTPS")
    if not settings.SMTP_HOST:
        problems.append("SMTP_HOST 未配置")
    if problems:
        raise RuntimeError("生产环境配置不安全: " + "; ".join(problems))
