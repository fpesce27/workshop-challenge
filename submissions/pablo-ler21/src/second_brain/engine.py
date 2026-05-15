"""Motor de reglas — hot path determinístico sin LLMs.

Contrato de performance: lookup() debe responder en < 5ms p99
con hasta 10.000 reglas activas en SQLite.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from second_brain.db import get_connection, get_db_path, get_read_connection, row_to_rule
from second_brain.models import RuleMatch
from second_brain.normalizer import from_db_int, hamming_distance, normalize, simhash

logger = logging.getLogger(__name__)

# Umbral de distancia de Hamming para considerar dos SimHashes como "similares"
SIMHASH_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Índice en memoria de SimHashes activos
# Evita un scan completo de SQLite en cada request del hot path.
# Solo almacena lo mínimo necesario para la comparación de Hamming.
# ---------------------------------------------------------------------------

class _SimHashIndex:
    """Caché in-process particionado por client_id para el SimHash scan.

    Particionamos para escanear solo las reglas del cliente + las globales
    en vez de las 10k totales. En producción: ~100-200 entradas por request.
    """

    def __init__(self) -> None:
        # Reglas de cliente: client_id → lista de (rule_id, simhash)
        self._by_client: dict[str, list[tuple[str, int]]] = {}
        # Reglas globales: lista de (rule_id, simhash)
        self._globals: list[tuple[str, int]] = []
        self._loaded = False
        self._lock = threading.Lock()

    def ensure_loaded(self, db_path: Path) -> None:
        with self._lock:
            if self._loaded:
                return
        self._reload(db_path)

    def _reload(self, db_path: Path) -> None:
        with get_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT id, pattern_simhash, scope, client_id FROM rules WHERE status = 'active'"
            ).fetchall()

        by_client: dict[str, list[tuple[str, int]]] = {}
        globals_: list[tuple[str, int]] = []

        for r in rows:
            h = from_db_int(r["pattern_simhash"])
            if r["scope"] == "global":
                globals_.append((r["id"], h))
            else:
                cid = r["client_id"] or ""
                if cid not in by_client:
                    by_client[cid] = []
                by_client[cid].append((r["id"], h))

        with self._lock:
            self._by_client = by_client
            self._globals = globals_
            self._loaded = True

    def invalidate(self) -> None:
        with self._lock:
            self._loaded = False

    def find_best(
        self,
        obs_hash: int,
        client_id: str,
        threshold: int,
        db_path: Path,
    ) -> tuple[Optional[str], int]:
        """Devuelve (rule_id, distancia) del mejor candidato, o (None, threshold+1)."""
        self.ensure_loaded(db_path)
        with self._lock:
            client_entries = list(self._by_client.get(client_id, []))
            global_entries = list(self._globals)

        best_id: Optional[str] = None
        best_dist = threshold + 1

        # Buscar primero entre reglas del cliente (mayor prioridad)
        for rule_id, h in client_entries:
            dist = hamming_distance(obs_hash, h)
            if dist <= threshold and dist < best_dist:
                best_id = rule_id
                best_dist = dist

        # Si ya encontramos un match de cliente, no necesitamos buscar globales
        # salvo que la distancia de alguna global sea menor (en ese caso, el cliente
        # ya ganó por prioridad de scope, así que igual lo ignoramos)
        if best_id is None:
            for rule_id, h in global_entries:
                dist = hamming_distance(obs_hash, h)
                if dist <= threshold and dist < best_dist:
                    best_id = rule_id
                    best_dist = dist

        return best_id, best_dist


# Índice global compartido por todos los workers
_simhash_index = _SimHashIndex()


def invalidate_index() -> None:
    """Forzar recarga del índice — llamar desde compiler/invalidator al modificar reglas."""
    _simhash_index.invalidate()


# ---------------------------------------------------------------------------
# Buffer de hits en memoria — evita un write por cada request
# ---------------------------------------------------------------------------

class _HitBuffer:
    """Acumula incrementos de hit_count y los flushea en batch."""

    def __init__(self, flush_interval: float = 5.0, max_pending: int = 100):
        self._counts: dict[str, int] = defaultdict(int)
        self._last_used: dict[str, datetime] = {}
        self._lock = threading.Lock()
        self._flush_interval = flush_interval
        self._max_pending = max_pending
        self._last_flush = time.monotonic()

    def record(self, rule_id: str) -> None:
        """Registra un hit para una regla. No bloquea el hot path."""
        now = datetime.now(UTC)
        with self._lock:
            self._counts[rule_id] += 1
            self._last_used[rule_id] = now
            pending = sum(self._counts.values())

        # Flush automático por tamaño o por tiempo — fuera del lock para no bloquear
        elapsed = time.monotonic() - self._last_flush
        if pending >= self._max_pending or elapsed >= self._flush_interval:
            self.flush()

    def flush(self, db_path: Optional[Path] = None) -> None:
        """Escribe los hits acumulados en SQLite en un solo batch."""
        with self._lock:
            if not self._counts:
                return
            counts = dict(self._counts)
            last_used = dict(self._last_used)
            self._counts.clear()
            self._last_used.clear()
            self._last_flush = time.monotonic()

        try:
            with get_connection(db_path or get_db_path()) as conn:
                for rule_id, count in counts.items():
                    conn.execute(
                        """UPDATE rules
                           SET hit_count = hit_count + ?,
                               last_used_at = ?
                           WHERE id = ?""",
                        (count, last_used[rule_id].isoformat(), rule_id),
                    )
        except Exception:
            logger.exception("Error flusheando hit buffer")


# Instancia global del buffer — compartida por todos los workers
_hit_buffer = _HitBuffer()


def flush_hit_buffer(db_path: Optional[Path] = None) -> None:
    """Fuerza el flush del buffer — útil en tests y al shutdown."""
    _hit_buffer.flush(db_path)


# ---------------------------------------------------------------------------
# Lookup principal — los tres pasos del hot path
# ---------------------------------------------------------------------------

def lookup(
    client_id: str,
    observation_text: str,
    db_path: Optional[Path] = None,
) -> RuleMatch:
    """Busca la regla más relevante para una observación.

    Paso 1 — Exact match: normalización + búsqueda exacta en SQLite.
    Paso 2 — SimHash match: distancia de Hamming ≤ SIMHASH_THRESHOLD.
    Paso 3 — No match: el agente debe preguntar al usuario.

    Solo se consideran reglas con status='active'.
    Las reglas shadow se loguean pero no se retornan al caller.
    """
    path = db_path or get_db_path()
    canonical = normalize(observation_text)
    obs_hash = simhash(canonical)

    # Usamos la conexión persistente para el hot path — evita el overhead de
    # sqlite3.connect() en cada request (especialmente notable en Windows).
    conn = get_read_connection(path)

    # --- Paso 1: exact match ---
    row = conn.execute(
        """SELECT * FROM rules
           WHERE status = 'active'
             AND pattern_canonical = ?
             AND (
                   (scope = 'client' AND client_id = ?)
                OR scope = 'global'
             )
           ORDER BY
             -- cliente tiene prioridad sobre global
             CASE WHEN scope = 'client' AND client_id = ? THEN 0 ELSE 1 END,
             hit_count DESC
           LIMIT 1""",
        (canonical, client_id, client_id),
    ).fetchone()

    if row:
        rule = row_to_rule(row)
        _hit_buffer.record(rule.id)
        return RuleMatch(rule=rule, match_type="exact", match_score=1.0)

    # --- Paso 2: SimHash match ---
    # El índice en memoria hace la comparación de Hamming sobre las entradas
    # del cliente + globales. Solo cuando hay match, traemos el full row.
    best_id, best_distance = _simhash_index.find_best(
        obs_hash, client_id, SIMHASH_THRESHOLD, path
    )

    if best_id is not None:
        best_row = conn.execute(
            "SELECT * FROM rules WHERE id = ?", (best_id,)
        ).fetchone()
        if best_row:
            rule = row_to_rule(best_row)
            # Las reglas shadow cercanas se loguean para monitoreo pero no se ejecutan
            if rule.status == "shadow":
                logger.info(
                    "Regla shadow candidata ignorada — rule_id=%s dist=%d",
                    rule.id, best_distance,
                )
                return RuleMatch(match_type="none", match_score=0.0)

            _hit_buffer.record(rule.id)
            score = 1.0 - (best_distance / 64.0)
            return RuleMatch(rule=rule, match_type="simhash", match_score=score)

    # --- Paso 3: no match ---
    return RuleMatch(match_type="none", match_score=0.0)
