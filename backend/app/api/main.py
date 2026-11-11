# -*- coding: utf-8 -*-
"""FastAPI 应用入口：uvicorn app.api.main:app --reload

组装路由 + 安全工程化（M6）：
- CORS 白名单（config.CORS_ORIGINS，dev 默认全放）
- 全链路审计中间件（每请求落 JSONL，见 core/audit）
- 安全响应头
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.audit import audit_log
from app.core.config import settings, validate_runtime_settings
from app.core.registry import snapshot_knowledge
from app.db.database import init_db
from app.api.routes import admin, auth, conversations, feedback, fun, health, me, recipes, themes, vision


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_runtime_settings()
    init_db()          # 启动建表（幂等）
    snapshot_knowledge()  # 知识版本快照（内容变更自动留痕，M6）
    from app.core.registry import load_prompt_overrides
    load_prompt_overrides()
    yield


app = FastAPI(
    title="BartenderAI",
    version="0.5.0",
    description="六 Agent 调酒智能体（LangGraph + RAG + SSE 流式）",
    lifespan=lifespan,
)

# 前端跨域：白名单收口（M6 不再无条件 *)
_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()] or ["*"]
if settings.ENV == "prod" and "*" in _origins:
    _origins = [settings.FRONTEND_URL]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", "")
    return JSONResponse(status_code=exc.status_code, headers=exc.headers,
                        content={"code": f"http_{exc.status_code}", "message": str(exc.detail),
                                 "details": None, "request_id": request_id})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422,
                        content={"code": "validation_error", "message": "请求参数不正确",
                                 "details": exc.errors(),
                                 "request_id": getattr(request.state, "request_id", "")})


@app.exception_handler(Exception)
async def unexpected_error(request: Request, _: Exception):
    return JSONResponse(status_code=500,
                        content={"code": "internal_error", "message": "服务暂时不可用",
                                 "details": None,
                                 "request_id": getattr(request.state, "request_id", "")})


@app.middleware("http")
async def request_identity(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    """全链路审计：每个 HTTP 请求记一条（含耗时/状态）。"""
    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    audit_log(
        action="http",
        user=request.query_params.get("username", "")
             or request.headers.get("x-user-id", ""),
        detail=f"{request.method} {request.url.path}",
        status=response.status_code,
        latency_ms=latency_ms,
        ip=(request.client.host if request.client else ""),
    )
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """安全响应头：防嗅探 / 防嵌入 / 防 MIME 混淆。"""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store" if not request.url.path.startswith("/static") else "public")
    return response


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(me.router)
app.include_router(conversations.router)
app.include_router(themes.router)
app.include_router(recipes.router)
app.include_router(feedback.router)
app.include_router(admin.router)
app.include_router(fun.router)
app.include_router(vision.router)


@app.get("/")
def root() -> dict:
    return {"app": settings.APP_NAME, "version": "0.5.0", "docs": "/docs"}
