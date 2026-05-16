"""Tests del motor de reglas — hot path."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from second_brain.db import init_db, insert_rule
from second_brain.engine import SIMHASH_THRESHOLD, flush_hit_buffer, lookup
from second_brain.models import LiteralInstructionAction, Rule, SplitInvoiceAction
from second_brain.normalizer import normalize, simhash, to_db_int


# ---------------------------------------------------------------------------
# Fixture: DB en memoria para tests aislados
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path: Path):
    """DB SQLite temporal inicializada en un directorio aislado."""
    from second_brain.db import close_read_connection
    from second_brain.engine import _simhash_index
    db_path = tmp_path / "test.db"
    init_db(db_path)
    yield db_path
    # Limpiar recursos para aislar tests
    close_read_connection(db_path)
    _simhash_index.invalidate()


def _make_rule(
    pattern: str,
    scope: str = "client",
    client_id: str = "138",
    status: str = "active",
) -> Rule:
    canonical = normalize(pattern)
    return Rule(
        scope=scope,
        client_id=client_id if scope == "client" else None,
        pattern_canonical=canonical,
        pattern_simhash=simhash(canonical),
        action=LiteralInstructionAction(natural_language=pattern),
        status=status,
    )


# ---------------------------------------------------------------------------
# Caso 1: exact match
# ---------------------------------------------------------------------------

def test_lookup_exact_match_cliente(tmp_db):
    rule = _make_rule("factura a y b", client_id="138")
    insert_rule(rule, tmp_db)

    result = lookup("138", "armar factura a y b", tmp_db)

    assert result.match_type == "exact"
    assert result.match_score == 1.0
    assert result.rule is not None
    assert result.rule.id == rule.id


def test_lookup_exact_match_global(tmp_db):
    rule = _make_rule("50/50", scope="global")
    insert_rule(rule, tmp_db)

    result = lookup("cualquier_cliente", "hacer 50/50", tmp_db)

    assert result.match_type == "exact"
    assert result.rule.scope == "global"


def test_lookup_cliente_tiene_prioridad_sobre_global(tmp_db):
    global_rule = _make_rule("50/50", scope="global")
    client_rule = _make_rule("50/50", scope="client", client_id="138")
    insert_rule(global_rule, tmp_db)
    insert_rule(client_rule, tmp_db)

    result = lookup("138", "50/50", tmp_db)

    assert result.rule.scope == "client"
    assert result.rule.id == client_rule.id


# ---------------------------------------------------------------------------
# Caso 2: SimHash match
# ---------------------------------------------------------------------------

def test_lookup_simhash_match(tmp_db):
    # Insertamos la regla con el patrón base
    rule = _make_rule("factura a y b", client_id="138")
    insert_rule(rule, tmp_db)

    # Buscamos con una variante que normaliza diferente pero es semánticamente igual
    result = lookup("138", "hacer factura A y B", tmp_db)

    # Puede ser exact (si normalizan igual) o simhash (si hay leve diferencia)
    assert result.match_type in ("exact", "simhash")
    assert result.rule is not None


def test_lookup_simhash_ignora_shadow(tmp_db):
    # Una regla shadow NO debe ser retornada aunque esté cerca por SimHash
    rule = _make_rule("factura a y b", status="shadow")
    insert_rule(rule, tmp_db)

    result = lookup("138", "factura a y b", tmp_db)

    # Shadow → no match (el agente debe preguntar)
    assert result.match_type == "none"
    assert result.rule is None


# ---------------------------------------------------------------------------
# Caso 3: no match
# ---------------------------------------------------------------------------

def test_lookup_no_match_db_vacia(tmp_db):
    result = lookup("138", "observacion completamente desconocida xyz", tmp_db)

    assert result.match_type == "none"
    assert result.match_score == 0.0
    assert result.rule is None


def test_lookup_no_match_regla_deprecated(tmp_db):
    rule = _make_rule("50/50", status="deprecated")
    insert_rule(rule, tmp_db)

    result = lookup("138", "50/50", tmp_db)

    assert result.match_type == "none"


# ---------------------------------------------------------------------------
# Hit buffer: verificar que se incrementa el hit_count
# ---------------------------------------------------------------------------

def test_hit_count_se_incrementa(tmp_db):
    rule = _make_rule("50/50", client_id="138")
    insert_rule(rule, tmp_db)

    lookup("138", "50/50", tmp_db)
    flush_hit_buffer(tmp_db)

    from second_brain.db import get_connection
    with get_connection(tmp_db) as conn:
        row = conn.execute("SELECT hit_count FROM rules WHERE id=?", (rule.id,)).fetchone()
    assert row["hit_count"] == 1


# ---------------------------------------------------------------------------
# Benchmark de performance: p99 < 5ms con 10.000 reglas
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_lookup_performance_10k_rules(tmp_db):
    """p99 del lookup sobre 10.000 reglas activas debe ser < 5ms."""
    # Poblar con 10.000 reglas de distintos clientes y patrones
    from second_brain.db import get_connection

    batch_size = 500
    total = 10_000
    now = datetime.now(UTC).isoformat()

    for batch_start in range(0, total, batch_size):
        rows = []
        for i in range(batch_start, min(batch_start + batch_size, total)):
            rule_id = str(uuid.uuid4())
            canonical = f"observacion patron numero {i}"
            h = to_db_int(simhash(canonical))
            rows.append((
                rule_id,
                "client",
                f"cliente_{i % 100}",
                canonical,
                h,
                '{"type": "literal_instruction", "natural_language": "instruccion"}',
                1.0, 0, now, None, now, "active",
            ))
        with get_connection(tmp_db) as conn:
            conn.executemany(
                """INSERT INTO rules
                   (id, scope, client_id, pattern_canonical, pattern_simhash,
                    action_json, confidence, hit_count, created_at,
                    last_used_at, last_modified_at, status)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )

    # Warm-up: cargar el índice y calentar el cache de SQLite antes de medir
    for w in range(20):
        lookup(f"cliente_{w % 100}", f"warmup {w}", tmp_db)

    # Medir 200 lookups (mezcla de miss y hit)
    latencies = []
    for i in range(200):
        # Alterna entre queries que matchean y queries que no
        if i % 2 == 0:
            query = f"observacion patron numero {i % total}"
        else:
            query = f"query sin match {i}"

        start = time.perf_counter()
        lookup(f"cliente_{i % 100}", query, tmp_db)
        latencies.append((time.perf_counter() - start) * 1000)  # ms

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p99 = latencies[int(len(latencies) * 0.99)]

    print(f"\nBenchmark lookup 10k reglas — p50={p50:.2f}ms  p99={p99:.2f}ms")

    assert p99 < 5.0, f"p99={p99:.2f}ms excede el límite de 5ms"
