"""Invalidador: memoria negativa — registra correcciones y depreca reglas que fallan."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional

from second_brain.db import get_connection, get_db_path, insert_rule, update_rule_status
from second_brain.models import LiteralInstructionAction, Observation, Rule
from second_brain.normalizer import normalize, simhash

logger = logging.getLogger(__name__)

# Una regla se depreca si recibe ≥3 invalidaciones en una ventana de 7 días
INVALIDATION_THRESHOLD = 3
INVALIDATION_WINDOW_DAYS = 7


def _get_vault_path(db_path: Path) -> Path:
    import os
    env_path = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env_path:
        return Path(env_path)
    return db_path.parent / "obsidian_vault"


def _write_invalidation_note(
    rule_id: str,
    observation: Observation,
    user_correction: str,
    invalidation_count: int,
    vault_path: Path,
) -> None:
    """Escribe una nota en pendientes-revision/invalidaciones/ para auditoría humana."""
    dest_dir = vault_path / "pendientes-revision" / "invalidaciones"
    dest_dir.mkdir(parents=True, exist_ok=True)

    note_path = dest_dir / f"invalidacion-{rule_id[:8]}-{uuid.uuid4().hex[:6]}.md"
    now = datetime.now(UTC).isoformat()

    content = (
        "---\n"
        "tipo: invalidacion\n"
        f"rule_id: {rule_id}\n"
        f"client_id: {observation.client_id}\n"
        f"comprobante_id: {observation.comprobante_id}\n"
        f"invalidation_count: {invalidation_count}\n"
        f"created_at: {now}\n"
        "---\n\n"
        "# Invalidación de regla\n\n"
        f"**Regla deprecada:** `{rule_id}`\n"
        f"**Cliente:** {observation.client_id}\n"
        f"**Observación original:** {observation.text}\n"
        f"**Corrección del usuario:** {user_correction}\n\n"
        f"Esta regla recibió **{invalidation_count} invalidaciones** en los últimos "
        f"{INVALIDATION_WINDOW_DAYS} días y fue marcada como `deprecated`.\n"
        "Se compiló una nueva regla shadow con la corrección. Revisá y aprobá.\n"
    )

    note_path.write_text(content, encoding="utf-8")
    logger.info("Nota de invalidación escrita en %s", note_path)


def register_invalidation(
    rule_id: str,
    observation: Observation,
    user_correction: str,
    db_path: Optional[Path] = None,
    vault_path: Optional[Path] = None,
    client=None,
) -> bool:
    """Registra una corrección del usuario sobre una regla activa.

    Si la regla acumula ≥ INVALIDATION_THRESHOLD invalidaciones en la ventana
    de tiempo, pasa a 'deprecated' y se compila una regla shadow con la corrección.

    Retorna True si la regla fue deprecada.
    """
    path = db_path or get_db_path()
    vpath = vault_path or _get_vault_path(path)
    now = datetime.now(UTC)
    inv_id = str(uuid.uuid4())

    # Insertar la invalidación en el historial
    with get_connection(path) as conn:
        conn.execute(
            """INSERT INTO invalidations
               (id, rule_id, client_id, comprobante_id, observation_text, user_correction, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                inv_id,
                rule_id,
                observation.client_id,
                observation.comprobante_id,
                observation.text,
                user_correction,
                now.isoformat(),
            ),
        )

    # Contar invalidaciones recientes para esta regla (ventana deslizante)
    window_start = (now - timedelta(days=INVALIDATION_WINDOW_DAYS)).isoformat()
    with get_connection(path) as conn:
        count_row = conn.execute(
            """SELECT COUNT(*) AS cnt FROM invalidations
               WHERE rule_id = ? AND created_at >= ?""",
            (rule_id, window_start),
        ).fetchone()

    inv_count = count_row["cnt"]

    if inv_count < INVALIDATION_THRESHOLD:
        logger.info(
            "Invalidación registrada para regla %s (%d/%d)",
            rule_id, inv_count, INVALIDATION_THRESHOLD,
        )
        return False

    # Umbral alcanzado → deprecar la regla vieja (nunca se borra, solo cambia status)
    update_rule_status(rule_id, "deprecated", path)
    logger.warning(
        "Regla %s deprecada tras %d invalidaciones en %d días",
        rule_id, inv_count, INVALIDATION_WINDOW_DAYS,
    )

    # Compilar nueva regla shadow con la corrección
    new_rule = _compile_corrected_rule(observation, user_correction, path, client)
    _write_invalidation_note(rule_id, observation, user_correction, inv_count, vpath)

    return True


def _compile_corrected_rule(
    observation: Observation,
    user_correction: str,
    db_path: Path,
    client=None,
) -> Rule:
    """Crea una regla shadow con la corrección. Usa Claude Haiku si hay cliente disponible,
    si no crea una LiteralInstructionAction como fallback."""
    if client is not None:
        from second_brain.compiler import compile_rule
        rule = compile_rule(observation, user_correction, client)
    else:
        canonical = normalize(observation.text)
        rule = Rule(
            scope="client",
            client_id=observation.client_id,
            pattern_canonical=canonical,
            pattern_simhash=simhash(canonical),
            action=LiteralInstructionAction(natural_language=user_correction),
            status="shadow",
        )

    insert_rule(rule, db_path)
    logger.info(
        "Nueva regla shadow %s compilada como reemplazo de la invalidada", rule.id
    )
    return rule
