"""Watcher del vault de Obsidian — detecta cambios y los sincroniza con SQLite."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

import yaml

from second_brain.db import get_connection, get_db_path, update_rule_status

logger = logging.getLogger(__name__)

POLL_INTERVAL = 30  # segundos entre scans


# ---------------------------------------------------------------------------
# Parsing del frontmatter
# ---------------------------------------------------------------------------

def parse_frontmatter(content: str) -> Optional[dict]:
    """Extrae y parsea el bloque YAML del frontmatter de una nota Markdown."""
    if not content.startswith("---"):
        return None
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        logger.warning("Error parseando frontmatter YAML: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Handlers de cambios
# ---------------------------------------------------------------------------

def _handle_approval(rule_id: str, note_path: Path, db_path: Path) -> None:
    """Promueve una regla shadow a active cuando approved: true aparece en la nota."""
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT status FROM rules WHERE id=?", (rule_id,)
        ).fetchone()

    if row is None:
        logger.warning("Regla %s no encontrada en DB (nota: %s)", rule_id, note_path)
        return

    if row["status"] != "shadow":
        return

    update_rule_status(rule_id, "active", db_path)
    logger.info(
        "Regla %s promovida a active via aprobación manual en vault (%s)",
        rule_id, note_path.name,
    )


def _handle_action_edit(rule_id: str, action_dict: dict, db_path: Path) -> None:
    """Actualiza la action de una regla si fue editada a mano en la nota."""
    try:
        action_json = json.dumps(action_dict)
        with get_connection(db_path) as conn:
            conn.execute(
                "UPDATE rules SET action_json=?, last_modified_at=? WHERE id=?",
                (action_json, _now_iso(), rule_id),
            )
        logger.info("Acción de regla %s actualizada desde vault", rule_id)
    except Exception as exc:
        logger.warning("Error actualizando acción de regla %s: %s", rule_id, exc)


def _handle_scope_change(rule_id: str, new_scope: str, new_client_id: Optional[str], db_path: Path) -> None:
    """Actualiza el scope de una regla si fue cambiado en la nota."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE rules SET scope=?, client_id=?, last_modified_at=? WHERE id=?",
            (new_scope, new_client_id, _now_iso(), rule_id),
        )
    logger.info("Scope de regla %s actualizado a '%s' desde vault", rule_id, new_scope)


def _now_iso() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# Procesamiento de un archivo cambiado
# ---------------------------------------------------------------------------

def _handle_note_change(note_path: Path, db_path: Path, prev_fm: Optional[dict]) -> None:
    """Analiza una nota que cambió y aplica los cambios correspondientes en SQLite."""
    try:
        content = note_path.read_text(encoding="utf-8")
    except OSError:
        return

    fm = parse_frontmatter(content)
    if fm is None or not isinstance(fm, dict):
        return

    rule_id = fm.get("rule_id")
    if not rule_id:
        return

    # 1. approved: true → promover shadow a active
    if fm.get("approved") is True:
        _handle_approval(str(rule_id), note_path, db_path)

    if prev_fm is None:
        return

    # 2. Acción editada a mano
    new_action = fm.get("action")
    old_action = prev_fm.get("action")
    if new_action and new_action != old_action and isinstance(new_action, dict):
        _handle_action_edit(str(rule_id), new_action, db_path)

    # 3. Scope cambiado
    new_scope = fm.get("scope")
    old_scope = prev_fm.get("scope")
    if new_scope and new_scope != old_scope and new_scope in ("client", "global"):
        new_client = fm.get("client_id")
        _handle_scope_change(
            str(rule_id),
            new_scope,
            str(new_client) if new_client and new_client != "null" else None,
            db_path,
        )


# ---------------------------------------------------------------------------
# Scan completo del vault
# ---------------------------------------------------------------------------

def process_vault_changes(
    vault_path: Path,
    db_path: Path,
    state: Optional[dict] = None,
) -> dict:
    """Detecta archivos .md que cambiaron desde el último scan.

    `state` es un dict {path_str: (mtime, frontmatter)}. Se retorna el estado
    actualizado para el próximo scan.
    """
    if state is None:
        state = {}

    new_state: dict = {}

    for note_path in vault_path.rglob("*.md"):
        path_key = str(note_path)
        try:
            mtime = note_path.stat().st_mtime
        except OSError:
            continue

        prev_mtime, prev_fm = state.get(path_key, (None, None))

        if mtime != prev_mtime:
            # El archivo es nuevo o fue modificado
            logger.debug("Cambio detectado en %s", note_path.name)
            _handle_note_change(note_path, db_path, prev_fm)

            # Actualizar frontmatter en estado para el próximo scan
            try:
                content = note_path.read_text(encoding="utf-8")
                current_fm = parse_frontmatter(content)
            except OSError:
                current_fm = prev_fm

            new_state[path_key] = (mtime, current_fm)
        else:
            new_state[path_key] = (mtime, prev_fm)

    return new_state


# ---------------------------------------------------------------------------
# Watch loop y thread management
# ---------------------------------------------------------------------------

_watcher_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def watch_vault(
    vault_path: Path,
    db_path: Optional[Path] = None,
    interval: float = POLL_INTERVAL,
    stop_event: Optional[threading.Event] = None,
) -> None:
    """Corre el loop de watch en el thread actual (bloqueante).

    Usá start_vault_watcher() para correr en background.
    """
    path = db_path or get_db_path()
    ev = stop_event or _stop_event
    state: dict = {}

    logger.info("Vault watcher iniciado — vault=%s interval=%.0fs", vault_path, interval)

    # Primer scan: cargar estado inicial sin procesar cambios
    for note_path in vault_path.rglob("*.md"):
        try:
            mtime = note_path.stat().st_mtime
            content = note_path.read_text(encoding="utf-8")
            fm = parse_frontmatter(content)
            state[str(note_path)] = (mtime, fm)
        except OSError:
            pass

    while not ev.is_set():
        ev.wait(interval)
        if ev.is_set():
            break
        try:
            state = process_vault_changes(vault_path, path, state)
        except Exception:
            logger.exception("Error en vault watcher scan")

    logger.info("Vault watcher detenido")


def start_vault_watcher(
    vault_path: Path,
    db_path: Optional[Path] = None,
    interval: float = POLL_INTERVAL,
) -> None:
    """Arranca el watcher en un thread daemon."""
    global _watcher_thread
    if _watcher_thread and _watcher_thread.is_alive():
        return

    _stop_event.clear()
    local_stop = _stop_event

    def _run() -> None:
        watch_vault(vault_path, db_path, interval, local_stop)

    _watcher_thread = threading.Thread(target=_run, daemon=True, name="vault-watcher")
    _watcher_thread.start()
    logger.info("Vault watcher thread iniciado")


def stop_vault_watcher(timeout: float = 5.0) -> None:
    """Detiene el watcher de forma limpia."""
    _stop_event.set()
    if _watcher_thread:
        _watcher_thread.join(timeout=timeout)
    logger.info("Vault watcher detenido")
