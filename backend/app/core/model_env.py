# -*- coding: utf-8 -*-
"""模型下载/加载引导（国内网络）：HF_ENDPOINT 注入 + ModelScope 兜底。

背景：sentence_transformers / FlagEmbedding 首次加载 BAAI/bge-* 时
从 HuggingFace 下载（国内极慢/常连不上）。两套兜底：
1. HF_ENDPOINT 注入 os.environ（huggingface_hub 只在请求时读环境变量）
2. ModelScope 兜底：models/<模型名> 本地目录优先；本地没有且 HF 不可达时
   自动从 ModelScope 下载（阿里云，国内稳定）

用法：加载嵌入/重排模型前，先调 apply_hf_endpoint()；
模型路径统一走 resolve_model_dir()，自动命中本地缓存。
"""
from __future__ import annotations

import os
from pathlib import Path

_MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


def apply_hf_endpoint() -> None:
    from app.core.config import settings
    if settings.HF_ENDPOINT and not os.environ.get("HF_ENDPOINT"):
        os.environ["HF_ENDPOINT"] = settings.HF_ENDPOINT


def resolve_model_dir(model_id: str) -> str:
    """返回可用的模型路径（本地缓存命中时返回本地目录）。

    顺序：models/<模型短名>/ 本地目录 → 原 model_id（走 HF 镜像下载）。
    本地目录存在时，sentence-transformers 直接加载，不再联网。
    """
    slug = model_id.split("/")[-1]
    local = _MODELS_DIR / slug
    if local.exists():
        return str(local)
    return model_id


def ensure_local_model(model_id: str, force: bool = False) -> str:
    """确保模型可用：本地没有则尝试从 ModelScope 下载。

    Returns:
        可用的模型路径（本地目录或原 model_id）。
    """
    resolved = resolve_model_dir(model_id)
    if resolved != model_id and not force:
        return resolved
    try:
        from modelscope import snapshot_download
        print(f"[modelscope] 下载 {model_id} -> models/{model_id.split('/')[-1]} ...")
        _MODELS_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_download(model_id, local_dir=str(_MODELS_DIR / model_id.split("/")[-1]))
        print("[modelscope] 下载完成")
    except Exception as e:
        print(f"[modelscope] 不可用({e})，回退 HF 镜像下载")
    return resolve_model_dir(model_id)
