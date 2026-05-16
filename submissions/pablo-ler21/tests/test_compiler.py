"""Tests del compilador asíncrono — todas las llamadas a Anthropic son mock."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from second_brain.compiler import (
    CONFIRMATIONS_NEEDED,
    MAX_RETRIES,
    compile_rule,
    confirm_shadow_rule,
    enqueue_compilation,
    process_compilation_queue,
)
from second_brain.db import get_connection, init_db
from second_brain.models import (
    CompilationRequest,
    LiteralInstructionAction,
    MultiTaxIDAction,
    Observation,
    SplitInvoiceAction,
)


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


def _obs(text: str = "hacer 50/50", client_id: str = "138") -> Observation:
    return Observation(client_id=client_id, text=text, comprobante_id="CMP001")


def _mock_client(json_str: str) -> MagicMock:
    """Crea un mock del cliente Anthropic que devuelve json_str como respuesta."""
    msg = MagicMock()
    msg.content = [MagicMock(text=json_str)]
    client = MagicMock()
    client.messages.create.return_value = msg
    return client


# ---------------------------------------------------------------------------
# compile_rule — tipos de action
# ---------------------------------------------------------------------------

def test_compile_rule_split_invoice():
    client = _mock_client('{"type": "split_invoice", "type_a_pct": 50, "type_b_pct": 50}')
    rule = compile_rule(_obs("hacer 50/50"), "mitad y mitad", client)

    assert isinstance(rule.action, SplitInvoiceAction)
    assert rule.action.type_a_pct == 50
    assert rule.action.type_b_pct == 50


def test_compile_rule_split_invoice_70_30():
    client = _mock_client('{"type": "split_invoice", "type_a_pct": 70, "type_b_pct": 30}')
    rule = compile_rule(_obs("70/30"), "70% factura A, 30% factura B", client)

    assert isinstance(rule.action, SplitInvoiceAction)
    assert rule.action.type_a_pct == 70
    assert rule.action.type_b_pct == 30


def test_compile_rule_multi_tax_id():
    json_str = (
        '{"type": "multi_tax_id", "default_cuit": "30-99999999-9", '
        '"conditions": [{"field": "amount", "operator": "gt", "value": 500000}], '
        '"condition_cuit": "20-11111111-1"}'
    )
    client = _mock_client(json_str)
    rule = compile_rule(
        _obs("facturar a Distribuidora Sur si mayor a 500k"),
        "CUIT 20-11111111-1 si supera 500k, sino 30-99999999-9",
        client,
    )

    assert isinstance(rule.action, MultiTaxIDAction)
    assert rule.action.default_cuit == "30-99999999-9"
    assert rule.action.condition_cuit == "20-11111111-1"
    assert len(rule.action.conditions) == 1
    assert rule.action.conditions[0].value == 500000


def test_compile_rule_literal_instruction():
    client = _mock_client(
        '{"type": "literal_instruction", "natural_language": "Usar siempre Empresa XYZ SA"}'
    )
    rule = compile_rule(_obs("siempre a XYZ"), "Empresa XYZ SA", client)

    assert isinstance(rule.action, LiteralInstructionAction)
    assert "XYZ" in rule.action.natural_language


def test_compile_rule_status_is_shadow():
    client = _mock_client('{"type": "split_invoice", "type_a_pct": 50, "type_b_pct": 50}')
    rule = compile_rule(_obs(), "mitad y mitad", client)

    assert rule.status == "shadow"


def test_compile_rule_scope_is_client():
    client = _mock_client('{"type": "split_invoice", "type_a_pct": 50, "type_b_pct": 50}')
    rule = compile_rule(_obs(client_id="999"), "mitad y mitad", client)

    assert rule.scope == "client"
    assert rule.client_id == "999"


def test_compile_rule_strips_backtick_wrapping():
    """Claude a veces envuelve el JSON en bloques de código — debe ignorar los backticks."""
    wrapped = "```json\n{\"type\": \"split_invoice\", \"type_a_pct\": 50, \"type_b_pct\": 50}\n```"
    client = _mock_client(wrapped)
    rule = compile_rule(_obs(), "mitad y mitad", client)

    assert isinstance(rule.action, SplitInvoiceAction)


def test_compile_rule_unknown_type_falls_back_to_literal():
    """Un tipo desconocido no debe romper — fallback a LiteralInstructionAction."""
    client = _mock_client('{"type": "unknown_action", "foo": "bar"}')
    rule = compile_rule(_obs("algo raro"), "hacé lo que puedas", client)

    assert isinstance(rule.action, LiteralInstructionAction)


# ---------------------------------------------------------------------------
# enqueue_compilation
# ---------------------------------------------------------------------------

def test_enqueue_inserts_pending_job(tmp_db):
    req = CompilationRequest(observation=_obs(), user_response="mitad y mitad")
    enqueue_compilation(req, tmp_db)

    with get_connection(tmp_db) as conn:
        row = conn.execute(
            "SELECT * FROM compilation_queue WHERE id=?", (req.id,)
        ).fetchone()

    assert row is not None
    assert row["status"] == "pending"
    assert row["user_response"] == "mitad y mitad"
    assert row["retry_count"] == 0


# ---------------------------------------------------------------------------
# process_compilation_queue — integración enqueue + process
# ---------------------------------------------------------------------------

def test_process_queue_creates_shadow_rule(tmp_db, tmp_vault):
    req = CompilationRequest(observation=_obs(), user_response="mitad y mitad")
    enqueue_compilation(req, tmp_db)

    client = _mock_client('{"type": "split_invoice", "type_a_pct": 50, "type_b_pct": 50}')
    count = process_compilation_queue(tmp_db, client, tmp_vault)

    assert count == 1

    with get_connection(tmp_db) as conn:
        job = conn.execute(
            "SELECT status FROM compilation_queue WHERE id=?", (req.id,)
        ).fetchone()
        rules = conn.execute(
            "SELECT * FROM rules WHERE client_id='138' AND status='shadow'"
        ).fetchall()

    assert job["status"] == "done"
    assert len(rules) == 1


def test_process_queue_empty_returns_zero(tmp_db, tmp_vault):
    client = _mock_client('{"type": "split_invoice", "type_a_pct": 50, "type_b_pct": 50}')
    count = process_compilation_queue(tmp_db, client, tmp_vault)
    assert count == 0


# ---------------------------------------------------------------------------
# Manejo de errores y reintentos
# ---------------------------------------------------------------------------

def test_process_queue_retries_on_error(tmp_db, tmp_vault):
    req = CompilationRequest(observation=_obs(), user_response="mitad y mitad")
    enqueue_compilation(req, tmp_db)

    bad_client = MagicMock()
    bad_client.messages.create.side_effect = RuntimeError("API error simulado")

    process_compilation_queue(tmp_db, bad_client, tmp_vault)

    with get_connection(tmp_db) as conn:
        job = conn.execute(
            "SELECT status, retry_count FROM compilation_queue WHERE id=?", (req.id,)
        ).fetchone()

    assert job["status"] == "pending"
    assert job["retry_count"] == 1


def test_process_queue_marks_failed_after_max_retries(tmp_db, tmp_vault):
    req = CompilationRequest(observation=_obs(), user_response="mitad y mitad")
    enqueue_compilation(req, tmp_db)

    bad_client = MagicMock()
    bad_client.messages.create.side_effect = RuntimeError("API error simulado")

    for _ in range(MAX_RETRIES):
        process_compilation_queue(tmp_db, bad_client, tmp_vault)

    with get_connection(tmp_db) as conn:
        job = conn.execute(
            "SELECT status, retry_count FROM compilation_queue WHERE id=?", (req.id,)
        ).fetchone()

    assert job["status"] == "failed"
    assert job["retry_count"] == MAX_RETRIES

    # Debe haber una nota en pendientes-revision/
    notes = list((tmp_vault / "pendientes-revision").glob("compilation-failed-*.md"))
    assert len(notes) == 1
    note_text = notes[0].read_text(encoding="utf-8")
    assert "hacer 50/50" in note_text


# ---------------------------------------------------------------------------
# confirm_shadow_rule — promoción shadow → active
# ---------------------------------------------------------------------------

@pytest.fixture
def shadow_rule_id(tmp_db):
    """Inserta una regla shadow y retorna su ID."""
    from second_brain.db import insert_rule
    from second_brain.models import Rule
    from second_brain.normalizer import normalize, simhash

    canonical = normalize("hacer 50/50")
    rule = Rule(
        scope="client",
        client_id="138",
        pattern_canonical=canonical,
        pattern_simhash=simhash(canonical),
        action=SplitInvoiceAction(type_a_pct=50, type_b_pct=50),
        status="shadow",
    )
    insert_rule(rule, tmp_db)
    return rule.id


def test_confirm_not_promoted_below_threshold(shadow_rule_id, tmp_db):
    for _ in range(CONFIRMATIONS_NEEDED - 1):
        promoted = confirm_shadow_rule(shadow_rule_id, tmp_db)
        assert promoted is False

    with get_connection(tmp_db) as conn:
        row = conn.execute(
            "SELECT status FROM rules WHERE id=?", (shadow_rule_id,)
        ).fetchone()

    assert row["status"] == "shadow"


def test_confirm_promotes_at_threshold(shadow_rule_id, tmp_db):
    for _ in range(CONFIRMATIONS_NEEDED - 1):
        confirm_shadow_rule(shadow_rule_id, tmp_db)

    promoted = confirm_shadow_rule(shadow_rule_id, tmp_db)

    assert promoted is True

    with get_connection(tmp_db) as conn:
        row = conn.execute(
            "SELECT status FROM rules WHERE id=?", (shadow_rule_id,)
        ).fetchone()

    assert row["status"] == "active"


def test_confirm_ignores_active_rule(tmp_db):
    """Una regla ya activa no debe ser afectada por confirm_shadow_rule."""
    from second_brain.db import insert_rule, update_rule_status
    from second_brain.models import Rule
    from second_brain.normalizer import normalize, simhash

    canonical = normalize("hacer 50/50")
    rule = Rule(
        scope="client",
        client_id="138",
        pattern_canonical=canonical,
        pattern_simhash=simhash(canonical),
        action=SplitInvoiceAction(type_a_pct=50, type_b_pct=50),
        status="shadow",
    )
    insert_rule(rule, tmp_db)
    update_rule_status(rule.id, "active", tmp_db)

    result = confirm_shadow_rule(rule.id, tmp_db)
    assert result is False

    with get_connection(tmp_db) as conn:
        row = conn.execute(
            "SELECT status FROM rules WHERE id=?", (rule.id,)
        ).fetchone()
    assert row["status"] == "active"
