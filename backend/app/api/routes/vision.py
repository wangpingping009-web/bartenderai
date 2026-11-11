# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import json
import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.auth import current_user
from app.core.config import settings
from app.core.llm import _is_placeholder
from app.services.recipe_catalog import get_recipe, search_recipes

router = APIRouter(prefix="/api/vision", tags=["vision"])
ALLOWED = {"image/jpeg": "jpeg", "image/png": "png", "image/webp": "webp"}


def _valid_magic(data: bytes, kind: str) -> bool:
    return ((kind == "jpeg" and data.startswith(b"\xff\xd8\xff")) or
            (kind == "png" and data.startswith(b"\x89PNG\r\n\x1a\n")) or
            (kind == "webp" and data.startswith(b"RIFF") and data[8:12] == b"WEBP"))


@router.post("/identify")
async def identify(file: UploadFile = File(...), _: dict = Depends(current_user)) -> dict:
    kind = ALLOWED.get(file.content_type or "")
    if not kind:
        raise HTTPException(415, detail="仅支持 JPEG、PNG 或 WebP 图片")
    limit = settings.MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(limit + 1)
    await file.close()
    if len(data) > limit:
        raise HTTPException(413, detail=f"图片不能超过 {settings.MAX_UPLOAD_MB}MB")
    if not _valid_magic(data, kind):
        raise HTTPException(400, detail="图片内容与文件类型不一致")
    if not settings.QWEN_API_KEY or _is_placeholder(settings.QWEN_API_KEY):
        raise HTTPException(503, detail="视觉识别未配置，请设置 QWEN_API_KEY")

    from openai import OpenAI
    client = OpenAI(base_url=settings.QWEN_BASE_URL, api_key=settings.QWEN_API_KEY, timeout=45)
    encoded = base64.b64encode(data).decode("ascii")
    prompt = ("观察这张鸡尾酒成品照片。只根据可见的颜色、杯型、装饰、冰型和质地，"
              "给出最多3个可能的经典鸡尾酒候选。不要声称能确定配方。输出严格JSON："
              '{"observations":["..."],"candidates":[{"name":"英文经典名","confidence":"high|medium|low","reason":"..."}]}')
    try:
        result = client.chat.completions.create(
            model=settings.QWVL_MODEL,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{file.content_type};base64,{encoded}"}},
            ]}], max_tokens=600, temperature=0)
        text = result.choices[0].message.content or "{}"
        match = re.search(r"\{.*\}", text, re.S)
        parsed = json.loads(match.group() if match else "{}")
    except Exception as exc:
        raise HTTPException(502, detail="视觉模型识别失败，请稍后重试") from exc

    candidates = []
    for item in (parsed.get("candidates") or [])[:3]:
        name = str(item.get("name") or "").strip()
        recipe = get_recipe(name)
        if recipe is None and name:
            found = search_recipes(q=name)
            recipe = found[0] if found else None
        candidates.append({
            "name": name, "confidence": item.get("confidence", "low"),
            "reason": str(item.get("reason") or "")[:300],
            "recipe": ({k: recipe[k] for k in ("id", "name", "name_cn", "image", "glass", "abv")}
                       if recipe else None),
        })
    return {"observations": (parsed.get("observations") or [])[:8], "candidates": candidates,
            "disclaimer": "照片只能提供候选判断，实际配方需结合材料或酒单确认。"}
