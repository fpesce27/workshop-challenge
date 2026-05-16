"""Setup de SQLite y migraciones del esquema."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Generator, Optional

# Ruta por defecto — se puede sobreescribir via variable de entorno o parámetro
DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "second_brain.db"


def get_db_path() -> Path:
    import os
    env_path = os.environ.get("SECOND_BRAIN_DB")
    if env_path:
        return Path(env_path)
    return DEFAULT_DB_PATH


@contextmanager
def get_connection(db_path: Optional[Path] = None) -> Generator[sqlite3.Connection, None, None]:
    """Context manager que entrega una conexión con WAL habilitado."""
    path = db_path or get_db_path()
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Habilitar WAL para soporte de concurrencia de lectores múltiples
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Conexión persistente para el hot path de lecturas
# sqlite3.connect() en Windows tiene overhead de filesystem por llamada.
# Para lecturas del motor de reglas, reutilizamos la misma conexión.
# ---------------------------------------------------------------------------

_read_conns: dict[str, sqlite3.Connection] = {}
_read_conns_lock = threading.Lock()


def get_read_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Retorna una conexión persistente para lecturas. Thread-safe."""
    path = str(db_path or get_db_path())
    with _read_conns_lock:
        if path not in _read_conns:
            conn = sqlite3.connect(path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA cache_size=-65536")  # 64MB de cache de páginas
            _read_conns[path] = conn
        return _read_conns[path]


def close_read_connection(db_path: Optional[Path] = None) -> None:
    """Cierra y elimina la conexión persistente — útil en teardown de tests."""
    path = str(db_path or get_db_path())
    with _read_conns_lock:
        conn = _read_conns.pop(path, None)
    if conn:
        conn.close()


# ---------------------------------------------------------------------------
# DDL — tablas e índices
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS rules (
    id                  TEXT PRIMARY KEY,
    scope               TEXT NOT NULL CHECK(scope IN ('client', 'global')),
    client_id           TEXT,
    pattern_canonical   TEXT NOT NULL,
    pattern_simhash     INTEGER NOT NULL,
    action_json         TEXT NOT NULL,
    confidence          REAL NOT NULL DEFAULT 1.0,
    hit_count           INTEGER NOT NULL DEFAULT 0,
    confirmation_count  INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL,
    last_used_at        TEXT,
    last_modified_at    TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'shadow'
                            CHECK(status IN ('active', 'shadow', 'deprecated', 'archived'))
);

-- Lookup principal: scope + client + patrón exacto
CREATE INDEX IF NOT EXISTS idx_rules_scope_client_pattern
    ON rules(scope, client_id, pattern_canonical)
    WHERE status = 'active';

-- Búsqueda por simhash para matching aproximado
CREATE INDEX IF NOT EXISTS idx_rules_simhash
    ON rules(pattern_simhash)
    WHERE status = 'active';

-- Monitoreo y auditoría
CREATE INDEX IF NOT EXISTS idx_rules_status       ON rules(status);
CREATE INDEX IF NOT EXISTS idx_rules_last_used    ON rules(last_used_at);


CREATE TABLE IF NOT EXISTS compilation_queue (
    id              TEXT PRIMARY KEY,
    observation_json TEXT NOT NULL,
    user_response   TEXT NOT NULL,
    original_rule_id TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'processing', 'done', 'failed')),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_queue_status ON compilation_queue(status, created_at);


-- Historial de invalidaciones — memoria negativa
-- Las reglas deprecadas NO se borran; acá queda el registro de por qué murieron.
CREATE TABLE IF NOT EXISTS invalidations (
    id              TEXT PRIMARY KEY,
    rule_id         TEXT NOT NULL REFERENCES rules(id),
    client_id       TEXT NOT NULL,
    comprobante_id  TEXT NOT NULL,
    observation_text TEXT NOT NULL,
    user_correction TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_invalidations_rule  ON invalidations(rule_id, created_at);
CREATE INDEX IF NOT EXISTS idx_invalidations_client ON invalidations(client_id);
"""


def init_db(db_path: Optional[Path] = None) -> None:
    """Crea todas las tablas si no existen. Idempotente."""
    with get_connection(db_path) as conn:
        conn.executescript(_DDL)


# ---------------------------------------------------------------------------
# Helpers de serialización para los modelos Pydantic
# ---------------------------------------------------------------------------

def rule_to_row(rule) -> dict:
    """Convierte un modelo Rule a un dict apto para INSERT/UPDATE."""
    from second_brain.normalizer import to_db_int
    return {
        "id": rule.id,
        "scope": rule.scope,
        "client_id": rule.client_id,
        "pattern_canonical": rule.pattern_canonical,
        "pattern_simhash": to_db_int(rule.pattern_simhash),
        "action_json": rule.action.model_dump_json(),
        "confidence": rule.confidence,
        "hit_count": rule.hit_count,
        "created_at": rule.created_at.isoformat(),
        "last_used_at": rule.last_used_at.isoformat() if rule.last_used_at else None,
        "last_modified_at": rule.last_modified_at.isoformat(),
        "status": rule.status,
    }


def row_to_rule(row: sqlite3.Row):
    """Convierte una fila de SQLite al modelo Rule."""
    from second_brain.models import Rule
    from second_brain.normalizer import from_db_int

    data = dict(row)
    action_data = json.loads(data.pop("action_json"))
    # confirmation_count es estado operacional — no forma parte del modelo Rule
    data.pop("confirmation_count", None)
    # Recuperar los campos de tiempo (vienen como string ISO desde SQLite)
    created_at = datetime.fromisoformat(data.pop("created_at"))
    last_used_raw = data.pop("last_used_at")
    last_used_at = datetime.fromisoformat(last_used_raw) if last_used_raw else None
    last_modified_at = datetime.fromisoformat(data.pop("last_modified_at"))
    # Convertir simhash de signed (SQLite) a unsigned (Python)
    data["pattern_simhash"] = from_db_int(data["pattern_simhash"])

    return Rule(
        **data,
        action=action_data,
        created_at=created_at,
        last_used_at=last_used_at,
        last_modified_at=last_modified_at,
    )


def insert_rule(rule, db_path: Optional[Path] = None) -> None:
    """Inserta una regla nueva en SQLite."""
    row = rule_to_row(rule)
    sql = """
        INSERT INTO rules
            (id, scope, client_id, pattern_canonical, pattern_simhash,
             action_json, confidence, hit_count, created_at,
             last_used_at, last_modified_at, status)
        VALUES
            (:id, :scope, :client_id, :pattern_canonical, :pattern_simhash,
             :action_json, :confidence, :hit_count, :created_at,
             :last_used_at, :last_modified_at, :status)
    """
    with get_connection(db_path) as conn:
        conn.execute(sql, row)


def update_rule_status(rule_id: str, status: str, db_path: Optional[Path] = None) -> None:
    """Actualiza el status de una regla."""
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE rules SET status=?, last_modified_at=? WHERE id=?",
            (status, datetime.now(UTC).isoformat(), rule_id),
        )
