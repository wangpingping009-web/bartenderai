# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import admin_user
from app.core.audit import query_audit
from app.core.registry import PROMPTS, list_knowledge_versions, list_prompts, snapshot_knowledge
from app.core.usage import query_usage_summary
from app.db.database import db

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(admin_user)])
BACKEND = Path(__file__).resolve().parents[3]


class PromptIn(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+(?:\.\d+)?$")
    system_text: str = Field(min_length=20, max_length=30000)
    description: str = Field(default="", max_length=500)


def _rag_observability(limit: int = 200) -> dict:
    """Aggregate persisted retrieval metadata without exposing conversation text."""
    with db() as conn:
        rows = conn.execute(
            "SELECT metadata_json,created_at FROM messages WHERE role='assistant' "
            "ORDER BY id DESC LIMIT ?", (max(1, min(limit, 1000)),),
        ).fetchall()

    retrieval_modes: dict[str, int] = {}
    capability_modes: dict[str, int] = {}
    confidences: list[float] = []
    coverages: list[float] = []
    recent: list[dict] = []
    with_retrieval = 0
    for row in rows:
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        capability = str(metadata.get("capability_mode") or "unavailable")
        capability_modes[capability] = capability_modes.get(capability, 0) + 1
        retrieval = metadata.get("retrieval") if isinstance(metadata.get("retrieval"), dict) else {}
        mode = str(retrieval.get("mode") or "")
        if not mode:
            continue
        with_retrieval += 1
        retrieval_modes[mode] = retrieval_modes.get(mode, 0) + 1
        confidence = retrieval.get("confidence")
        coverage = retrieval.get("field_coverage")
        if isinstance(confidence, (int, float)):
            confidences.append(float(confidence))
        if isinstance(coverage, (int, float)):
            coverages.append(float(coverage))
        if len(recent) < 12:
            recent.append({
                "trace_id": metadata.get("trace_id"), "created_at": row["created_at"],
                "mode": mode, "confidence": confidence, "field_coverage": coverage,
                "candidate_count": retrieval.get("candidate_count"),
                "missing_fields": retrieval.get("missing_fields") or [],
                "capability_mode": capability,
            })
    return {
        "samples": len(rows), "with_retrieval": with_retrieval,
        "retrieval_modes": retrieval_modes, "capability_modes": capability_modes,
        "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
        "avg_field_coverage": round(sum(coverages) / len(coverages), 4) if coverages else None,
        "recent": recent,
    }


@router.get("/overview")
def overview() -> dict:
    usage = query_usage_summary(7)
    return {"usage": usage, "prompts": len(list_prompts()),
            "knowledge_versions": len(list_knowledge_versions()),
            "recent_audit": query_audit(limit=10, days=1),
            "rag": _rag_observability()}


@router.get("/rag/observability")
def rag_observability(limit: int = 200) -> dict:
    return _rag_observability(limit)


@router.get("/audit")
def audit(limit: int = 100, action: str | None = None, days: int = 1) -> dict:
    records = query_audit(max(1, min(limit, 1000)), action, max(1, min(days, 30)))
    return {"items": records, "page": 1, "page_size": len(records), "total": len(records)}


@router.get("/usage")
def usage(days: int = 7) -> dict:
    return query_usage_summary(max(1, min(days, 90)))


@router.get("/prompts")
def prompts() -> dict:
    with db() as conn:
        rows = conn.execute(
            "SELECT id,task,version,description,is_active,created_at FROM prompt_versions ORDER BY task,id DESC"
        ).fetchall()
    return {"defaults": list_prompts(), "versions": [dict(r) for r in rows]}


@router.post("/prompts/{task}/versions", status_code=201)
def create_prompt_version(task: str, payload: PromptIn, user: dict = Depends(admin_user)) -> dict:
    if "{" in payload.system_text:
        try:
            payload.system_text.format()
        except (KeyError, IndexError):
            # Prompt variables are allowed, but unmatched literal braces are not.
            if payload.system_text.count("{") != payload.system_text.count("}"):
                raise HTTPException(422, detail="Prompt 花括号不匹配")
    try:
        with db() as conn:
            cur = conn.execute(
                "INSERT INTO prompt_versions(task,version,system_text,description,is_active,created_by) "
                "VALUES(?,?,?,?,0,?)", (task, payload.version, payload.system_text,
                                         payload.description, user["id"]))
    except Exception as exc:
        raise HTTPException(409, detail="该任务版本已存在") from exc
    return {"id": cur.lastrowid, "task": task, "version": payload.version}


@router.post("/prompts/{task}/versions/{version}/activate")
def activate_prompt(task: str, version: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM prompt_versions WHERE task=? AND version=?",
                           (task, version)).fetchone()
        if not row:
            raise HTTPException(404, detail="Prompt 版本不存在")
        conn.execute("UPDATE prompt_versions SET is_active=0 WHERE task=?", (task,))
        conn.execute("UPDATE prompt_versions SET is_active=1 WHERE id=?", (row["id"],))
    PROMPTS[task] = {"task": task, "version": version, "system": row["system_text"],
                     "description": row["description"], "registered_at": row["created_at"]}
    return {"ok": True, "task": task, "version": version}


@router.get("/knowledge")
def knowledge() -> dict:
    snapshot_knowledge()
    records = list_knowledge_versions()
    return {"items": records, "page": 1, "page_size": len(records), "total": len(records)}


def _run_job(job_id: str, command: list[str]) -> None:
    with db() as conn:
        conn.execute("UPDATE jobs SET status='running',progress=0.1,updated_at=datetime('now') WHERE id=?",
                     (job_id,))
    try:
        proc = subprocess.run(command, cwd=BACKEND, capture_output=True, text=True, timeout=3600)
        output = (proc.stdout + "\n" + proc.stderr)[-12000:]
        status = "succeeded" if proc.returncode == 0 else "failed"
        with db() as conn:
            conn.execute("UPDATE jobs SET status=?,progress=1,result_json=?,error=?,updated_at=datetime('now') WHERE id=?",
                         (status, json.dumps({"output": output}, ensure_ascii=False),
                          "" if proc.returncode == 0 else f"exit {proc.returncode}", job_id))
    except Exception as exc:
        with db() as conn:
            conn.execute("UPDATE jobs SET status='failed',error=?,updated_at=datetime('now') WHERE id=?",
                         (str(exc)[:1000], job_id))


def _queue(kind: str, command: list[str], tasks: BackgroundTasks, user: dict) -> dict:
    job_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute("INSERT INTO jobs(id,kind,status,created_by) VALUES(?,?,'queued',?)",
                     (job_id, kind, user["id"]))
    tasks.add_task(_run_job, job_id, command)
    return {"id": job_id, "kind": kind, "status": "queued"}


@router.post("/knowledge/reindex", status_code=202)
def reindex(tasks: BackgroundTasks, user: dict = Depends(admin_user)) -> dict:
    return _queue("knowledge_reindex", [sys.executable, "scripts/ingest_knowledge.py", "--reset"], tasks, user)


@router.post("/rag/evaluations", status_code=202)
def evaluate(tasks: BackgroundTasks, user: dict = Depends(admin_user)) -> dict:
    return _queue("rag_evaluation", [sys.executable, "scripts/run_ragas_eval.py", "--limit", "10"], tasks, user)


@router.get("/jobs")
def jobs() -> dict:
    with db() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT 100").fetchall()
    items = [dict(r) for r in rows]
    return {"items": items, "page": 1, "page_size": len(items), "total": len(items)}
