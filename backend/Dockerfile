# -*- coding: utf-8 -*-
# 后端镜像（M6 完整 Docker 栈）
# 构建: docker build -f backend/Dockerfile -t bartenderai-backend backend
# 运行: docker compose up 里的 backend 服务
FROM python:3.12-slim

WORKDIR /app

# 系统依赖（curl 用于健康检查）
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# 先装 CPU 版 torch：requirements 里的 torch 默认解析为 CUDA 版
# （Linux 上会拉一堆 nvidia-*cu13 轮子，镜像膨胀到 6GB+）。
# 本容器只用 CPU 推理（bge-m3/reranker 模型很小），先装 CPU 版，
# 后续 pip 见 torch 已满足即跳过，镜像降到 ~2GB。
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data
COPY scripts ./scripts
COPY .env.example ./

EXPOSE 8000

# 生产入口：不 --reload，线程池处理 SSE
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
