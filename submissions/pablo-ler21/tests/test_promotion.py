"""Tests del promotor cliente→global y del invalidador (memoria negativa)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from second_brain.db import get_connection, init_db, insert_rule, update_rule_status
from second_brain.invalidator import (
    INVALIDATION_THRESHOLD,
    INVALIDATION_WINDOW_DAYS,
    register_invalidation,
)
from second_brain.models import LiteralInstructionAction, Observation, Rule, SplitInvoiceAction
from second_brain.normalizer import normalize, simhash
from second_brain.promoter import PROMOTION_THRESHOLD, run_promotion_scan


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path: Path):
    from second_brain.db import close_read_connection
    from second_brain.engine import _simhash_index
    db_path = tmp_path / "test.db"
    init_db(db_path)
    yield db_path
    close_read_connection(db_path)
    _simhash_index.invalidate()


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


def _make_client_rule(client_id: str, pattern: str = "hacer 50/50") -> Rule:
    canonical = normalize(pattern)
    return Rule(
        scope="client",
        client_id=client_id,
        pattern_canonical=canonical,
        pattern_simhash=simhash(canonical),
        action=SplitInvoiceAction(type_a_pct=50, type_b_pct=50),
        status="active",
    )


def _obs(rule: Rule) -> Observation:
    return Observation(
        client_id=rule.client_id,
        text=rule.pattern_canonical,
        comprobante_id="CMP001",
    )


# ---------------------------------------------------------------------------
# Promotor: promoción cliente → global
# ---------------------------------------------------------------------------

def test_promotion_creates_global_shadow_rule(tmp_db, tmp_vault):
    """Con ≥5 clientes compartiendo el mismo patrón, se crea una regla global shadow."""
    for i in range(PROMOTION_THRESHOLD):
        insert_rule(_make_client_rule(f"cliente_{i}"), tmp_db)

    created = run_promotion_scan(tmp_db, tmp_vault)

    assert len(created) == 1
    assert created[0].scope == "global"
    assert created[0].status == "shadow"
    assert created[0].client_id is None


def test_promotion_pattern_matches(tmp_db, tmp_vault):
    """La regla global creada comparte el pattern_canonical con las de cliente."""
    canonical = normalize("hacer 50/50")
    for i in range(PROMOTION_THRESHOLD):
        insert_rule(_make_client_rule(f"c_{i}"), tmp_db)

    created = run_promotion_scan(tmp_db, tmp_vault)

    assert created[0].pattern_canonical == canonical


def test_no_promotion_below_threshold(tmp_db, tmp_vault):
    """Con menos de 5 clientes no se debe crear ninguna regla global."""
    for i in range(PROMOTION_THRESHOLD - 1):
        insert_rule(_make_client_rule(f"c_{i}"), tmp_db)

    created = run_promotion_scan(tmp_db, tmp_vault)

    assert created == []


def test_promotion_not_duplicated(tmp_db, tmp_vault):
    """Si ya existe una regla global para ese patrón, no se crea otra."""
    for i in range(PROMOTION_THRESHOLD):
        insert_rule(_make_client_rule(f"c_{i}"), tmp_db)

    # Primer scan: crea la global
    first = run_promotion_scan(tmp_db, tmp_vault)
    assert len(first) == 1

    # Segundo scan: no debe crear duplicado
    second = run_promotion_scan(tmp_db, tmp_vault)
    assert second == []


def test_promotion_writes_obsidian_note(tmp_db, tmp_vault):
    """El scan debe escribir una nota en pendientes-revision/promociones/."""
    for i in range(PROMOTION_THRESHOLD):
        insert_rule(_make_client_rule(f"c_{i}"), tmp_db)

    run_promotion_scan(tmp_db, tmp_vault)

    notes = list((tmp_vault / "pendientes-revision" / "promociones").glob("*.md"))
    assert len(notes) == 1
    note_text = notes[0].read_text(encoding="utf-8")
    assert "approved: false" in note_text


def test_promotion_ignores_shadow_and_deprecated_rules(tmp_db, tmp_vault):
    """Solo reglas active deben contar para el umbral de promoción."""
    for i in range(PROMOTION_THRESHOLD - 1):
        insert_rule(_make_client_rule(f"c_{i}"), tmp_db)

    # Agregar una más pero con status shadow — no debe contar
    shadow = _make_client_rule("c_shadow")
    shadow = shadow.model_copy(update={"status": "shadow"})
    insert_rule(shadow, tmp_db)

    created = run_promotion_scan(tmp_db, tmp_vault)
    assert created == []


# ---------------------------------------------------------------------------
# Invalidador: memoria negativa
# ---------------------------------------------------------------------------

def test_register_invalidation_inserts_record(tmp_db, tmp_vault):
    """Cada invalidación queda en la tabla invalidations."""
    rule = _make_client_rule("c1")
    insert_rule(rule, tmp_db)

    obs = _obs(rule)
    register_invalidation(rule.id, obs, "en realidad es 70/30", tmp_db, tmp_vault)

    with get_connection(tmp_db) as conn:
        rows = conn.execute(
            "SELECT * FROM invalidations WHERE rule_id=?", (rule.id,)
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["user_correction"] == "en realidad es 70/30"


def test_register_invalidation_no_deprecation_below_threshold(tmp_db, tmp_vault):
    """Con menos de INVALIDATION_THRESHOLD invalidaciones, la regla sigue activa."""
    rule = _make_client_rule("c1")
    insert_rule(rule, tmp_db)
    obs = _obs(rule)

    for _ in range(INVALIDATION_THRESHOLD - 1):
        deprecated = register_invalidation(rule.id, obs, "70/30", tmp_db, tmp_vault)
        assert deprecated is False

    with get_connection(tmp_db) as conn:
        row = conn.execute("SELECT status FROM rules WHERE id=?", (rule.id,)).fetchone()

    assert row["status"] == "active"


def test_register_invalidation_deprecates_at_threshold(tmp_db, tmp_vault):
    """Al alcanzar el umbral, la regla pasa a 'deprecated'."""
    rule = _make_client_rule("c1")
    insert_rule(rule, tmp_db)
    obs = _obs(rule)

    for _ in range(INVALIDATION_THRESHOLD - 1):
        register_invalidation(rule.id, obs, "70/30", tmp_db, tmp_vault)

    deprecated = register_invalidation(rule.id, obs, "70/30", tmp_db, tmp_vault)
    assert deprecated is True

    with get_connection(tmp_db) as conn:
        row = conn.execute("SELECT status FROM rules WHERE id=?", (rule.id,)).fetchone()

    assert row["status"] == "deprecated"


def test_register_invalidation_creates_new_shadow_rule(tmp_db, tmp_vault):
    """Al deprecar una regla se crea una nueva regla shadow con la corrección."""
    rule = _make_client_rule("c1")
    insert_rule(rule, tmp_db)
    obs = _obs(rule)

    for _ in range(INVALIDATION_THRESHOLD):
        register_invalidation(rule.id, obs, "en realidad es 70/30", tmp_db, tmp_vault)

    with get_connection(tmp_db) as conn:
        new_rules = conn.execute(
            "SELECT * FROM rules WHERE client_id='c1' AND status='shadow'"
        ).fetchall()

    assert len(new_rules) == 1
    # La acción de la nueva regla debe contener la corrección
    import json
    action = json.loads(new_rules[0]["action_json"])
    assert "70/30" in action.get("natural_language", "")


def test_register_invalidation_writes_obsidian_note(tmp_db, tmp_vault):
    """Al deprecar se escribe una nota de auditoría en pendientes-revision/invalidaciones/."""
    rule = _make_client_rule("c1")
    insert_rule(rule, tmp_db)
    obs = _obs(rule)

    for _ in range(INVALIDATION_THRESHOLD):
        register_invalidation(rule.id, obs, "70/30", tmp_db, tmp_vault)

    notes = list((tmp_vault / "pendientes-revision" / "invalidaciones").glob("*.md"))
    assert len(notes) == 1
    note_text = notes[0].read_text(encoding="utf-8")
    assert rule.id[:8] in note_text


def test_old_invalidations_outside_window_dont_count(tmp_db, tmp_vault):
    """Invalidaciones fuera de la ventana de 7 días no cuentan para el umbral."""
    rule = _make_client_rule("c1")
    insert_rule(rule, tmp_db)
    obs = _obs(rule)

    # Insertar invalidaciones viejas directamente en la DB (fuera de la ventana)
    old_date = (datetime.now(UTC) - timedelta(days=INVALIDATION_WINDOW_DAYS + 1)).isoformat()
    with get_connection(tmp_db) as conn:
        for i in range(INVALIDATION_THRESHOLD):
            conn.execute(
                """INSERT INTO invalidations
                   (id, rule_id, client_id, comprobante_id, observation_text, user_correction, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"old-inv-{i}",
                    rule.id,
                    obs.client_id,
                    obs.comprobante_id,
                    obs.text,
                    "correccion vieja",
                    old_date,
                ),
            )

    # Una sola invalidación reciente no debe disparar la deprecación
    deprecated = register_invalidation(rule.id, obs, "correccion nueva", tmp_db, tmp_vault)
    assert deprecated is False

    with get_connection(tmp_db) as conn:
        row = conn.execute("SELECT status FROM rules WHERE id=?", (rule.id,)).fetchone()
    assert row["status"] == "active"
