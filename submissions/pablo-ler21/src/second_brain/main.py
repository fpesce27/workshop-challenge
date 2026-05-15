"""API FastAPI del sistema Second Brain de Galo."""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from second_brain.compiler import (
    CompilationRequest,
    enqueue_compilation,
    start_compilation_worker,
    stop_compilation_worker,
)
from second_brain.db import get_connection, get_db_path, init_db
from second_brain.engine import flush_hit_buffer, invalidate_index, lookup
from second_brain.invalidator import register_invalidation
from second_brain.models import Observation
from second_brain.obsidian_writer import get_vault_path
from second_brain.promoter import run_promotion_scan
from second_brain.watcher import start_vault_watcher, stop_vault_watcher


# ---------------------------------------------------------------------------
# Almacén temporal de observaciones pendientes de respuesta
# En producción: tabla SQLite o Redis con TTL
# ---------------------------------------------------------------------------
_pending: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Lifespan: init DB, workers, watcher
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_compilation_worker(interval=5.0)
    if os.environ.get("ENABLE_WATCHER") == "1":
        vault = get_vault_path()
        start_vault_watcher(vault, interval=30.0)
    yield
    flush_hit_buffer()
    stop_compilation_worker()
    if os.environ.get("ENABLE_WATCHER") == "1":
        stop_vault_watcher()


app = FastAPI(
    title="Second Brain — Galo",
    description="Sistema de memoria determinístico para el agente de WhatsApp de Galo.",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Schemas de request/response
# ---------------------------------------------------------------------------

class ObservationIn(BaseModel):
    client_id: str
    text: str
    comprobante_id: str


class ObservationOut(BaseModel):
    observation_id: str
    action: Literal["execute", "ask"]
    rule_id: Optional[str] = None
    match_type: Optional[str] = None
    match_score: Optional[float] = None
    action_details: Optional[dict] = None
    question: Optional[str] = None


class UserResponseIn(BaseModel):
    user_response: str


class LearnOut(BaseModel):
    status: str = "learning"
    compilation_job_id: str
    will_apply_next_time: bool = True


class InvalidateIn(BaseModel):
    user_correction: str


class InvalidateOut(BaseModel):
    status: str
    rule_id: str
    deprecated: bool


class RuleOut(BaseModel):
    id: str
    scope: str
    client_id: Optional[str]
    pattern_canonical: str
    status: str
    hit_count: int
    confidence: float
    action_type: str
    created_at: str


class StatsOut(BaseModel):
    total_rules: int
    active_rules: int
    shadow_rules: int
    deprecated_rules: int
    archived_rules: int
    total_clients: int
    global_rules: int
    queue_pending: int
    queue_failed: int
    top_patterns: list[dict]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.post("/observations", response_model=ObservationOut, status_code=200)
def process_observation(body: ObservationIn):
    """Recibe una observación de comprobante y decide si ejecutar o preguntar."""
    import uuid

    obs = Observation(
        client_id=body.client_id,
        text=body.text,
        comprobante_id=body.comprobante_id,
    )
    observation_id = str(uuid.uuid4())
    match = lookup(obs.client_id, obs.text)

    # Guardar contexto para respuesta/invalidación posterior
    _pending[observation_id] = {
        "observation": obs,
        "rule_id": match.rule.id if match.rule else None,
    }

    if match.rule and match.match_type in ("exact", "simhash"):
        action_details = json.loads(match.rule.action.model_dump_json())
        return ObservationOut(
            observation_id=observation_id,
            action="execute",
            rule_id=match.rule.id,
            match_type=match.match_type,
            match_score=match.match_score,
            action_details=action_details,
        )

    question = f"¿Qué significa \"{obs.text}\"? ¿Cómo lo proceso?"
    return ObservationOut(
        observation_id=observation_id,
        action="ask",
        question=question,
    )


@app.post("/observations/{observation_id}/response", response_model=LearnOut)
def record_user_response(observation_id: str, body: UserResponseIn):
    """Recibe la respuesta del usuario y encola la compilación de la regla."""
    pending = _pending.get(observation_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Observación no encontrada o ya procesada")

    obs: Observation = pending["observation"]
    req = CompilationRequest(
        observation=obs,
        user_response=body.user_response,
        original_rule_id=pending.get("rule_id"),
    )
    enqueue_compilation(req)

    del _pending[observation_id]
    return LearnOut(compilation_job_id=req.id)


@app.post("/observations/{observation_id}/invalidate", response_model=InvalidateOut)
def invalidate_observation(observation_id: str, body: InvalidateIn):
    """Marca la ejecución de una regla como incorrecta y dispara el flujo de invalidación."""
    pending = _pending.get(observation_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Observación no encontrada o ya procesada")

    rule_id = pending.get("rule_id")
    if not rule_id:
        raise HTTPException(status_code=422, detail="No había regla aplicada — no hay qué invalidar")

    obs: Observation = pending["observation"]
    deprecated = register_invalidation(rule_id, obs, body.user_correction)

    if deprecated:
        invalidate_index()

    del _pending[observation_id]
    return InvalidateOut(
        status="registered",
        rule_id=rule_id,
        deprecated=deprecated,
    )


@app.get("/rules", response_model=list[RuleOut])
def list_rules(
    scope: Optional[str] = Query(None, description="client | global"),
    client_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="active | shadow | deprecated | archived"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    """Lista reglas con filtros opcionales, paginada."""
    clauses = []
    params: list = []

    if scope:
        clauses.append("scope = ?")
        params.append(scope)
    if client_id:
        clauses.append("client_id = ?")
        params.append(client_id)
    if status:
        clauses.append("status = ?")
        params.append(status)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM rules {where} ORDER BY hit_count DESC LIMIT ? OFFSET ?"
    params += [limit, skip]

    with get_connection(get_db_path()) as conn:
        rows = conn.execute(sql, params).fetchall()

    result = []
    for r in rows:
        action_data = json.loads(r["action_json"])
        result.append(RuleOut(
            id=r["id"],
            scope=r["scope"],
            client_id=r["client_id"],
            pattern_canonical=r["pattern_canonical"],
            status=r["status"],
            hit_count=r["hit_count"],
            confidence=r["confidence"],
            action_type=action_data.get("type", "unknown"),
            created_at=r["created_at"],
        ))
    return result


@app.get("/stats", response_model=StatsOut)
def get_stats():
    """Estadísticas globales del sistema."""
    with get_connection(get_db_path()) as conn:
        counts = {
            row["status"]: row["cnt"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM rules GROUP BY status"
            ).fetchall()
        }
        total_clients = conn.execute(
            "SELECT COUNT(DISTINCT client_id) AS cnt FROM rules WHERE scope='client'"
        ).fetchone()["cnt"]
        global_rules = conn.execute(
            "SELECT COUNT(*) AS cnt FROM rules WHERE scope='global' AND status='active'"
        ).fetchone()["cnt"]
        queue_counts = {
            row["status"]: row["cnt"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM compilation_queue GROUP BY status"
            ).fetchall()
        }
        top_patterns = conn.execute(
            """SELECT pattern_canonical, SUM(hit_count) AS total_hits
               FROM rules WHERE status='active'
               GROUP BY pattern_canonical
               ORDER BY total_hits DESC LIMIT 10"""
        ).fetchall()

    return StatsOut(
        total_rules=sum(counts.values()),
        active_rules=counts.get("active", 0),
        shadow_rules=counts.get("shadow", 0),
        deprecated_rules=counts.get("deprecated", 0),
        archived_rules=counts.get("archived", 0),
        total_clients=total_clients,
        global_rules=global_rules,
        queue_pending=queue_counts.get("pending", 0),
        queue_failed=queue_counts.get("failed", 0),
        top_patterns=[
            {"pattern": r["pattern_canonical"], "hits": r["total_hits"]}
            for r in top_patterns
        ],
    )


@app.post("/admin/promotion-scan", status_code=200)
def trigger_promotion_scan():
    """Dispara manualmente el scan de promoción cliente→global."""
    created = run_promotion_scan()
    invalidate_index()
    return {"promoted": len(created), "rules": [r.id for r in created]}
