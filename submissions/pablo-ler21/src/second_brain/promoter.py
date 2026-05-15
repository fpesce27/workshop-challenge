"""Promotor: eleva reglas de cliente a globales cuando N≥5 clientes las comparten."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from second_brain.db import get_connection, get_db_path, insert_rule
from second_brain.models import Rule
from second_brain.normalizer import from_db_int, simhash

logger = logging.getLogger(__name__)

# Umbral de clientes distintos para proponer promoción a global
PROMOTION_THRESHOLD = 5


def _get_vault_path(db_path: Path) -> Path:
    import os
    env_path = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env_path:
        return Path(env_path)
    return db_path.parent / "obsidian_vault"


def _write_promotion_note(
    pattern: str,
    client_ids: list[str],
    new_rule: Rule,
    vault_path: Path,
) -> None:
    """Escribe una nota en pendientes-revision/promociones/ para revisión humana."""
    dest_dir = vault_path / "pendientes-revision" / "promociones"
    dest_dir.mkdir(parents=True, exist_ok=True)

    slug = pattern.replace(" ", "-").replace("/", "_")[:40]
    note_path = dest_dir / f"promocion-{slug}-{new_rule.id[:8]}.md"
    now = datetime.now(UTC).isoformat()

    clientes_md = "\n".join(f"- {cid}" for cid in sorted(client_ids))

    content = (
        "---\n"
        "tipo: promocion-global\n"
        f"rule_id: {new_rule.id}\n"
        f"pattern: \"{pattern}\"\n"
        f"client_count: {len(client_ids)}\n"
        f"created_at: {now}\n"
        "approved: false\n"
        "---\n\n"
        f"# Propuesta de promoción global: `{pattern}`\n\n"
        f"El patrón aparece en **{len(client_ids)} clientes distintos**. "
        "Se propone elevar a regla global (scope=global, status=shadow).\n\n"
        "## Clientes que la tienen\n\n"
        f"{clientes_md}\n\n"
        "## Para aprobar\n\n"
        "Cambiá `approved: false` por `approved: true` en el frontmatter "
        "y el watcher actualizará la regla a `active`.\n"
    )

    note_path.write_text(content, encoding="utf-8")
    logger.info("Nota de promoción escrita en %s", note_path)


def run_promotion_scan(
    db_path: Optional[Path] = None,
    vault_path: Optional[Path] = None,
) -> list[Rule]:
    """Escanea reglas activas de cliente y promueve a global las que superan el umbral.

    Retorna la lista de reglas globales shadow creadas en este scan.
    """
    path = db_path or get_db_path()
    vpath = vault_path or _get_vault_path(path)

    # Patrones con ≥ PROMOTION_THRESHOLD clientes distintos
    with get_connection(path) as conn:
        candidates = conn.execute(
            """SELECT pattern_canonical, COUNT(DISTINCT client_id) AS cnt
               FROM rules
               WHERE scope = 'client' AND status = 'active'
               GROUP BY pattern_canonical
               HAVING COUNT(DISTINCT client_id) >= ?""",
            (PROMOTION_THRESHOLD,),
        ).fetchall()

    created: list[Rule] = []

    for row in candidates:
        pattern = row["pattern_canonical"]

        # Saltar si ya existe una regla global no-deprecada para este patrón
        with get_connection(path) as conn:
            existing = conn.execute(
                """SELECT id FROM rules
                   WHERE scope = 'global'
                     AND pattern_canonical = ?
                     AND status NOT IN ('deprecated', 'archived')""",
                (pattern,),
            ).fetchone()

        if existing:
            continue

        # Obtener los clientes que tienen este patrón y la acción de uno de ellos
        with get_connection(path) as conn:
            client_rows = conn.execute(
                """SELECT DISTINCT client_id, action_json, pattern_simhash
                   FROM rules
                   WHERE scope = 'client' AND pattern_canonical = ? AND status = 'active'""",
                (pattern,),
            ).fetchall()

        client_ids = [r["client_id"] for r in client_rows]
        # Tomar la acción del primer cliente como base de la regla global
        action_data = json.loads(client_rows[0]["action_json"])
        h = from_db_int(client_rows[0]["pattern_simhash"])

        global_rule = Rule(
            scope="global",
            client_id=None,
            pattern_canonical=pattern,
            pattern_simhash=h,
            action=action_data,
            status="shadow",
        )

        insert_rule(global_rule, path)
        _write_promotion_note(pattern, client_ids, global_rule, vpath)
        created.append(global_rule)

        logger.info(
            "Regla global shadow creada para patrón '%s' (clientes: %d)",
            pattern, len(client_ids),
        )

    return created
