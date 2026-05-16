"""Escritura de notas Markdown en el vault de Obsidian."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from second_brain.models import (
    LiteralInstructionAction,
    MultiTaxIDAction,
    Observation,
    Rule,
    SplitInvoiceAction,
)

logger = logging.getLogger(__name__)


def get_vault_path(db_path: Optional[Path] = None) -> Path:
    import os
    env_path = os.environ.get("OBSIDIAN_VAULT_PATH")
    if env_path:
        return Path(env_path)
    if db_path:
        return db_path.parent / "obsidian_vault"
    from second_brain.db import get_db_path
    return get_db_path().parent / "obsidian_vault"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Convierte un texto en un slug apto para nombre de archivo."""
    text = text.lower()
    text = re.sub(r"[^\w\s/-]", "", text)
    text = re.sub(r"[\s/]+", "-", text)
    return text[:50].strip("-")


def _action_to_natural_language(action) -> str:
    """Explica la acción en lenguaje natural para el cuerpo de la nota."""
    if isinstance(action, SplitInvoiceAction):
        return (
            f"Dividir la factura en dos partes: "
            f"**{action.type_a_pct}%** tipo A y **{action.type_b_pct}%** tipo B."
        )
    if isinstance(action, MultiTaxIDAction):
        if action.conditions:
            cond = action.conditions[0]
            op_labels = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "eq": "="}
            op = op_labels.get(cond.operator, cond.operator)
            return (
                f"Elegir razón social según el monto: "
                f"si {cond.field} {op} {cond.value} usar CUIT `{action.condition_cuit}`, "
                f"si no usar CUIT `{action.default_cuit}` (default)."
            )
        return f"Usar siempre CUIT `{action.default_cuit}`."
    if isinstance(action, LiteralInstructionAction):
        return action.natural_language
    return str(action)


def _note_dest(rule: Rule, vault_path: Path) -> Path:
    """Determina la carpeta y nombre de archivo según scope y status."""
    slug = _slugify(rule.pattern_canonical)

    if rule.status == "active":
        if rule.scope == "client":
            folder = vault_path / "clientes"
            filename = f"{rule.client_id}_{slug}.md"
        else:
            folder = vault_path / "globales"
            filename = f"{slug}.md"
    else:
        folder = vault_path / "pendientes-revision"
        filename = f"{slug}-{rule.id[:8]}.md"

    folder.mkdir(parents=True, exist_ok=True)
    return folder / filename


# ---------------------------------------------------------------------------
# Escritura de notas
# ---------------------------------------------------------------------------

def write_rule_note(
    rule: Rule,
    observation: Observation,
    user_response: str,
    vault_path: Optional[Path] = None,
) -> Path:
    """Escribe o actualiza la nota Markdown de una regla en el vault.

    Retorna el path de la nota escrita.
    """
    vpath = vault_path or get_vault_path()
    dest = _note_dest(rule, vpath)

    # Serializar la acción como dict para que sea legible en YAML
    action_dict = json.loads(rule.action.model_dump_json())

    tags = ["second-brain"]
    if rule.status in ("shadow", "deprecated", "archived"):
        tags.append("pendiente-revision")
    if rule.scope == "global":
        tags.append("global")

    # Frontmatter YAML construido manualmente para control total del formato
    fm_lines = [
        "---",
        f"rule_id: {rule.id}",
        f"scope: {rule.scope}",
        f"client_id: {rule.client_id or 'null'}",
        f"status: {rule.status}",
        f"approved: {'true' if rule.status == 'active' else 'false'}",
        f"hit_count: {rule.hit_count}",
        f"confidence: {rule.confidence}",
        f"created_at: \"{rule.created_at.isoformat()}\"",
        f"last_used_at: {('\"' + rule.last_used_at.isoformat() + '\"') if rule.last_used_at else 'null'}",
        f"simhash: {rule.pattern_simhash}",
        "action:",
    ]
    for k, v in action_dict.items():
        if isinstance(v, list):
            fm_lines.append(f"  {k}:")
            for item in v:
                if isinstance(item, dict):
                    first = True
                    for ik, iv in item.items():
                        prefix = "  - " if first else "    "
                        fm_lines.append(f"{prefix}{ik}: {iv}")
                        first = False
                else:
                    fm_lines.append(f"  - {item}")
        else:
            fm_lines.append(f"  {k}: {v}")
    fm_lines.append("tags:")
    for tag in tags:
        fm_lines.append(f"  - {tag}")
    fm_lines.append("---")

    frontmatter = "\n".join(fm_lines)

    action_explanation = _action_to_natural_language(rule.action)

    scope_label = "cliente" if rule.scope == "client" else "global"
    status_emoji = {
        "active": "✅",
        "shadow": "🔵",
        "deprecated": "🔴",
        "archived": "📦",
    }.get(rule.status, "")

    body = (
        f"\n# {status_emoji} Regla: `{rule.pattern_canonical}`\n\n"
        f"**Scope:** {scope_label}"
        + (f" — cliente `{rule.client_id}`" if rule.client_id else "")
        + f"\n**Status:** {rule.status}\n\n"
        "## Observación original\n\n"
        f"> {observation.text}\n\n"
        "## Respuesta del operador\n\n"
        f"{user_response}\n\n"
        "## Regla compilada\n\n"
        f"{action_explanation}\n\n"
        "## Cuándo se aplica\n\n"
        f"Cuando un comprobante de `{rule.client_id or 'cualquier cliente'}` "
        f"tenga una observación similar a `{observation.text}`.\n\n"
        f"**Usos registrados:** {rule.hit_count}  \n"
        f"**Confianza:** {rule.confidence:.0%}\n"
    )

    if rule.status == "shadow":
        body += (
            "\n---\n"
            "> 🔵 **Pendiente de validación** — "
            "Cambiá `approved: false` a `approved: true` en el frontmatter "
            "para activar esta regla.\n"
        )

    dest.write_text(frontmatter + body, encoding="utf-8")
    logger.info("Nota escrita en %s", dest)
    return dest
