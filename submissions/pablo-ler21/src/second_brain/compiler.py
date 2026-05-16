"""Compilador asíncrono: respuesta de usuario → Rule ejecutable vía Claude Haiku."""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import anthropic

from second_brain.db import get_connection, get_db_path, insert_rule
from second_brain.models import (
    CompilationRequest,
    LiteralInstructionAction,
    MultiTaxIDAction,
    Observation,
    Rule,
    SplitInvoiceAction,
)
from second_brain.normalizer import normalize, simhash

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5-20251001"
MAX_RETRIES = 3
CONFIRMATIONS_NEEDED = 3

# ---------------------------------------------------------------------------
# Prompt del compilador con few-shot examples del dominio Galo
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
Sos el compilador de reglas del sistema Second Brain de Galo.
Tu tarea es analizar la observación de un comprobante bancario y la respuesta del operador,
y compilar esa respuesta en una regla JSON estructurada y ejecutable.

La regla debe tener exactamente uno de estos formatos:

1. split_invoice — para dividir la factura en tipo A y tipo B:
   {"type": "split_invoice", "type_a_pct": <int 0-100>, "type_b_pct": <int 0-100>}
   Los porcentajes deben sumar exactamente 100.

2. multi_tax_id — para elegir razón social / CUIT según una condición (ej: monto):
   {"type": "multi_tax_id", "default_cuit": "<CUIT>", "conditions": [{"field": "amount", "operator": "gt", "value": <número>}], "condition_cuit": "<CUIT>"}
   Operadores válidos para "operator": gt, gte, lt, lte, eq.

3. literal_instruction — fallback cuando no encaja en los tipos anteriores:
   {"type": "literal_instruction", "natural_language": "<instrucción clara en español>"}

Respondé ÚNICAMENTE con el JSON de la regla. Sin texto adicional, sin backticks, sin explicaciones.\
"""

# Few-shot del dominio: facturación B2B de alimentos
_FEW_SHOT: list[dict] = [
    {
        "role": "user",
        "content": (
            'Observación del comprobante: "hacer 50/50"\n'
            'Respuesta del operador: "partir la factura mitad factura A y mitad factura B"'
        ),
    },
    {
        "role": "assistant",
        "content": '{"type": "split_invoice", "type_a_pct": 50, "type_b_pct": 50}',
    },
    {
        "role": "user",
        "content": (
            'Observación del comprobante: "70/30"\n'
            'Respuesta del operador: "70% en factura tipo A, 30% en factura tipo B"'
        ),
    },
    {
        "role": "assistant",
        "content": '{"type": "split_invoice", "type_a_pct": 70, "type_b_pct": 30}',
    },
    {
        "role": "user",
        "content": (
            'Observación del comprobante: "facturar a Distribuidora Sur si mayor a 500k, sino a Sur Logística"\n'
            'Respuesta del operador: "si el monto supera 500000 usar CUIT 20-12345678-9 (Distribuidora Sur), si no usar CUIT 30-98765432-1 (Sur Logística)"'
        ),
    },
    {
        "role": "assistant",
        "content": '{"type": "multi_tax_id", "default_cuit": "30-98765432-1", "conditions": [{"field": "amount", "operator": "gt", "value": 500000}], "condition_cuit": "20-12345678-9"}',
    },
    {
        "role": "user",
        "content": (
            'Observación del comprobante: "siempre a la empresa del grupo"\n'
            'Respuesta del operador: "usar siempre razón social Alimentos del Sur SA, CUIT 30-11111111-1"'
        ),
    },
    {
        "role": "assistant",
        "content": '{"type": "literal_instruction", "natural_language": "Facturar siempre a Alimentos del Sur SA, CUIT 30-11111111-1"}',
    },
]


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> str:
    """Extrae el JSON crudo de la respuesta, ignorando eventuales backticks."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        return match.group(1)
    return text


def _get_vault_path(db_path: Path) -> Path:
    """Devuelve el path del vault Obsidian relativo a la DB (o via env var)."""
    import os
    env_path = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env_path:
        return Path(env_path)
    return db_path.parent / "obsidian_vault"


def _write_failed_note(row: object, exc: Exception, vault_path: Path) -> None:
    """Escribe una nota Markdown en pendientes-revision/ cuando un job alcanza max retries."""
    dest_dir = vault_path / "pendientes-revision"
    dest_dir.mkdir(parents=True, exist_ok=True)

    job_id = row["id"]
    note_path = dest_dir / f"compilation-failed-{job_id[:8]}.md"

    obs_data = json.loads(row["observation_json"])
    now = datetime.now(UTC).isoformat()

    content = (
        "---\n"
        "tipo: compilation-failed\n"
        f"job_id: {job_id}\n"
        f"created_at: {now}\n"
        f"retry_count: {row['retry_count'] + 1}\n"
        "estado: fallido\n"
        "---\n\n"
        "# Error de compilación — revisión manual requerida\n\n"
        f"**Observación:** {obs_data.get('text', '')}\n"
        f"**Cliente:** {obs_data.get('client_id', '')}\n"
        f"**Comprobante:** {obs_data.get('comprobante_id', '')}\n"
        f"**Respuesta del operador:** {row['user_response']}\n\n"
        f"**Error:** {exc}\n\n"
        "Revisá esta observación manualmente, cargá la regla desde Obsidian "
        "o corregí el input y reencola.\n"
    )

    note_path.write_text(content, encoding="utf-8")
    logger.info("Nota de fallo escrita en %s", note_path)


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def compile_rule(
    observation: Observation,
    user_response: str,
    client: Optional[anthropic.Anthropic] = None,
) -> Rule:
    """Llama a Claude Haiku y compila la respuesta del operador en un Rule con status='shadow'."""
    if client is None:
        client = anthropic.Anthropic()

    user_message = (
        f'Observación del comprobante: "{observation.text}"\n'
        f'Respuesta del operador: "{user_response}"'
    )

    messages = _FEW_SHOT + [{"role": "user", "content": user_message}]

    response = client.messages.create(
        model=MODEL,
        max_tokens=256,
        system=_SYSTEM_PROMPT,
        messages=messages,
    )

    raw = response.content[0].text
    json_str = _extract_json(raw)
    action_data = json.loads(json_str)

    t = action_data.get("type")
    if t == "split_invoice":
        action = SplitInvoiceAction(**action_data)
    elif t == "multi_tax_id":
        action = MultiTaxIDAction(**action_data)
    elif t == "literal_instruction":
        action = LiteralInstructionAction(**action_data)
    else:
        # Tipo desconocido → fallback a instrucción literal con el texto crudo
        action = LiteralInstructionAction(natural_language=raw)

    canonical = normalize(observation.text)
    return Rule(
        scope="client",
        client_id=observation.client_id,
        pattern_canonical=canonical,
        pattern_simhash=simhash(canonical),
        action=action,
        status="shadow",
    )


def enqueue_compilation(req: CompilationRequest, db_path: Optional[Path] = None) -> None:
    """Inserta un job en la cola de compilación con status='pending'."""
    path = db_path or get_db_path()
    now = datetime.now(UTC).isoformat()

    with get_connection(path) as conn:
        conn.execute(
            """INSERT INTO compilation_queue
               (id, observation_json, user_response, original_rule_id,
                retry_count, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (
                req.id,
                req.observation.model_dump_json(),
                req.user_response,
                req.original_rule_id,
                req.retry_count,
                now,
                now,
            ),
        )


def process_compilation_queue(
    db_path: Optional[Path] = None,
    client: Optional[anthropic.Anthropic] = None,
    vault_path: Optional[Path] = None,
) -> int:
    """Procesa todos los jobs pending en orden FIFO. Retorna la cantidad procesada."""
    path = db_path or get_db_path()
    vpath = vault_path or _get_vault_path(path)

    with get_connection(path) as conn:
        rows = conn.execute(
            "SELECT * FROM compilation_queue WHERE status='pending' ORDER BY created_at LIMIT 50"
        ).fetchall()

    processed = 0

    for row in rows:
        job_id = row["id"]

        # Marcar como 'processing' para evitar doble procesamiento concurrente
        with get_connection(path) as conn:
            conn.execute(
                "UPDATE compilation_queue SET status='processing', updated_at=? WHERE id=?",
                (datetime.now(UTC).isoformat(), job_id),
            )

        try:
            obs = Observation(**json.loads(row["observation_json"]))
            rule = compile_rule(obs, row["user_response"], client)
            insert_rule(rule, path)

            with get_connection(path) as conn:
                conn.execute(
                    "UPDATE compilation_queue SET status='done', updated_at=? WHERE id=?",
                    (datetime.now(UTC).isoformat(), job_id),
                )

            processed += 1
            logger.info("Regla compilada %s desde job %s", rule.id, job_id)

        except Exception as exc:
            logger.warning("Error compilando job %s: %s", job_id, exc)
            new_retry = row["retry_count"] + 1

            if new_retry >= MAX_RETRIES:
                with get_connection(path) as conn:
                    conn.execute(
                        "UPDATE compilation_queue SET status='failed', retry_count=?, updated_at=? WHERE id=?",
                        (new_retry, datetime.now(UTC).isoformat(), job_id),
                    )
                _write_failed_note(row, exc, vpath)
                logger.error("Job %s falló tras %d intentos", job_id, MAX_RETRIES)
            else:
                with get_connection(path) as conn:
                    conn.execute(
                        "UPDATE compilation_queue SET status='pending', retry_count=?, updated_at=? WHERE id=?",
                        (new_retry, datetime.now(UTC).isoformat(), job_id),
                    )

    return processed


def confirm_shadow_rule(rule_id: str, db_path: Optional[Path] = None) -> bool:
    """Incrementa el contador de confirmaciones de una regla shadow.

    Retorna True si la regla fue promovida a active (al alcanzar CONFIRMATIONS_NEEDED).
    """
    path = db_path or get_db_path()
    now = datetime.now(UTC).isoformat()

    with get_connection(path) as conn:
        conn.execute(
            """UPDATE rules
               SET confirmation_count = confirmation_count + 1,
                   last_modified_at = ?
               WHERE id = ? AND status = 'shadow'""",
            (now, rule_id),
        )
        row = conn.execute(
            "SELECT confirmation_count FROM rules WHERE id = ?", (rule_id,)
        ).fetchone()

        if row and row["confirmation_count"] >= CONFIRMATIONS_NEEDED:
            conn.execute(
                "UPDATE rules SET status='active', last_modified_at=? WHERE id=? AND status='shadow'",
                (now, rule_id),
            )
            logger.info(
                "Regla %s promovida a active tras %d confirmaciones",
                rule_id, CONFIRMATIONS_NEEDED,
            )
            return True

    return False


# ---------------------------------------------------------------------------
# Worker en background — procesa la cola cada `interval` segundos
# ---------------------------------------------------------------------------

_worker_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def start_compilation_worker(
    db_path: Optional[Path] = None,
    interval: float = 5.0,
) -> None:
    """Arranca el worker de compilación en un thread daemon."""
    global _worker_thread
    if _worker_thread and _worker_thread.is_alive():
        return

    _stop_event.clear()

    def _loop() -> None:
        while not _stop_event.is_set():
            try:
                process_compilation_queue(db_path)
            except Exception:
                logger.exception("Error en compilation worker")
            _stop_event.wait(interval)

    _worker_thread = threading.Thread(target=_loop, daemon=True, name="compilation-worker")
    _worker_thread.start()
    logger.info("Compilation worker iniciado (interval=%.1fs)", interval)


def stop_compilation_worker(timeout: float = 10.0) -> None:
    """Detiene el worker de compilación de forma limpia."""
    _stop_event.set()
    if _worker_thread:
        _worker_thread.join(timeout=timeout)
    logger.info("Compilation worker detenido")
