# -*- coding: utf-8 -*-
"""AI 配方创作 API（M5/M6）：生成-校验-重试闭环 + 多人格 + 替代 + 解构。

M6 叠加：创作限流 + 审计日志 + LLM 用量打点。
"""
from __future__ import annotations

import json
import queue
import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.schemas import RecipeGenRequest
from app.core.auth import current_user
from app.core.audit import audit_log
from app.core.ratelimit import check_gen_quota
from app.core.usage import usage_scope
from app.core.events import sse_format
from app.services.deconstruct import deconstruct_recipe
from app.services.gamification import bump
from app.services.recipe_gen import PERSONAS, generate_recipe
from app.services.substitution import explain_substitution
from app.services.recipe_catalog import all_recipes, get_recipe, search_recipes
from app.db import repositories as repo
from app.db.database import db

router = APIRouter(prefix="/api/recipes", tags=["recipes"])


def _creation_payload(result: dict) -> dict:
    return {key: result.get(key) for key in (
        "recipe", "brief", "review", "collaboration", "references", "persona", "attempts",
        "capability_mode",
    )}


def _creation_item(row) -> dict:
    payload = json.loads(row["recipe_json"])
    if isinstance(payload, dict) and isinstance(payload.get("recipe"), dict):
        return {"id": row["id"], "created_at": row["created_at"], **payload}
    return {"id": row["id"], "created_at": row["created_at"], "recipe": payload,
            "brief": None, "review": None, "collaboration": [], "references": []}


def _store_creation(user: dict, result: dict) -> int | None:
    if not result.get("ok"):
        return None
    bump(user["username"], "recipe_generate")
    with db() as conn:
        cursor = conn.execute("INSERT INTO creations(user_id,recipe_json) VALUES(?,?)",
                              (user["id"], json.dumps(_creation_payload(result), ensure_ascii=False)))
    creation_id = int(cursor.lastrowid)
    result["creation_id"] = creation_id
    return creation_id


@router.get("/personas")
def list_personas() -> dict:
    return {"personas": [{"key": k, **v} for k, v in PERSONAS.items()]}


@router.post("/generate")
def create_recipe(req: RecipeGenRequest, user: dict = Depends(current_user)) -> dict:
    """AI 创作一张通过规则引擎质检的配方卡。"""
    username = user["username"]
    check_gen_quota(username)
    audit_log(action="recipe_generate", user=username,
              detail=f"persona={req.persona} base={len(req.base_spirits)}")
    with usage_scope(task="recipe_generate", user=username):
        result = generate_recipe(req.preferences, req.persona, req.base_spirits)
    audit_log(action="recipe_generate_done", user=username,
              detail=f"ok={result['ok']} attempts={result['attempts']}")
    _store_creation(user, result)
    return result


@router.post("/generate/stream")
def stream_create_recipe(req: RecipeGenRequest,
                         user: dict = Depends(current_user)) -> StreamingResponse:
    """Stream real collaboration stages while creator and reviewer work."""
    username = user["username"]
    check_gen_quota(username)
    events: "queue.Queue[dict]" = queue.Queue()

    def worker() -> None:
        try:
            audit_log(action="recipe_generate", user=username,
                      detail=f"stream persona={req.persona} base={len(req.base_spirits)}")
            with usage_scope(task="recipe_generate", user=username):
                result = generate_recipe(req.preferences, req.persona, req.base_spirits,
                                         on_event=lambda event: events.put({"type": "status", **event}))
            _store_creation(user, result)
            audit_log(action="recipe_generate_done", user=username,
                      detail=f"ok={result['ok']} attempts={result['attempts']}")
            events.put({"type": "done", "result": result})
        except Exception:
            events.put({"type": "error", "message": "创作过程暂时中断，请稍后重试。"})

    def generate():
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while True:
            event = events.get()
            yield sse_format(json.dumps(event, ensure_ascii=False))
            if event["type"] in ("done", "error"):
                break

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/substitute")
def substitute(q: str, context: str = "", _: dict = Depends(current_user)) -> dict:
    """推理式替代：解释某材料为什么能替、怎么替。"""
    return explain_substitution(q, cocktail_context=context)


@router.post("/deconstruct")
def deconstruct(card: dict, _: dict = Depends(current_user)) -> dict:
    """解构一张配方卡 → 风味骨架 + 重组方向。"""
    if not card:
        raise HTTPException(status_code=400, detail="需要配方卡内容")
    return deconstruct_recipe(card)


@router.get("")
def catalog(q: str = "", category: str = "", alcoholic: bool | None = None,
            base_spirit: str = "", available_only: bool = False,
            flavor: str = "", abv_min: float | None = Query(None, ge=0, le=100),
            abv_max: float | None = Query(None, ge=0, le=100),
            sort: str = Query("", pattern="^(|name|abv_asc|abv_desc|sweet|sour|aroma)$"),
            page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=100),
            user: dict = Depends(current_user)) -> dict:
    inventory = repo.list_inventory(user["username"]) if available_only else None
    items = search_recipes(q=q, category=category, alcoholic=alcoholic,
                           base_spirit=base_spirit, inventory=inventory,
                           available_only=available_only, flavor=flavor,
                           abv_min=abv_min, abv_max=abv_max, sort=sort)
    start = (page - 1) * page_size
    return {"items": items[start:start + page_size], "page": page,
            "page_size": page_size, "total": len(items)}


@router.get("/creations")
def creations(user: dict = Depends(current_user)) -> dict:
    with db() as conn:
        rows = conn.execute("SELECT id,recipe_json,created_at FROM creations WHERE user_id=? ORDER BY id DESC",
                            (user["id"],)).fetchall()
    items = [_creation_item(row) for row in rows]
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}


@router.get("/creations/{creation_id}")
def creation_detail(creation_id: int, user: dict = Depends(current_user)) -> dict:
    with db() as conn:
        row = conn.execute(
            "SELECT id,recipe_json,created_at FROM creations WHERE id=? AND user_id=?",
            (creation_id, user["id"]),
        ).fetchone()
    if row is None:
        raise HTTPException(404, detail="未找到原创配方")
    return _creation_item(row)


@router.delete("/creations/{creation_id}", status_code=204)
def delete_creation(creation_id: int, user: dict = Depends(current_user)) -> None:
    with db() as conn:
        cursor = conn.execute("DELETE FROM creations WHERE id=? AND user_id=?",
                              (creation_id, user["id"]))
    if not cursor.rowcount:
        raise HTTPException(404, detail="未找到原创配方")


@router.get("/{recipe_id}")
def recipe_detail(recipe_id: str, _: dict = Depends(current_user)) -> dict:
    recipe = get_recipe(recipe_id)
    if recipe is None:
        raise HTTPException(404, detail="未找到配方")
    return recipe
