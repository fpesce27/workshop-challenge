"""Smoke tests de los modelos Pydantic — Fase 1."""

from second_brain.models import (
    CompilationRequest,
    LiteralInstructionAction,
    MultiTaxIDAction,
    Observation,
    Rule,
    RuleMatch,
    SplitInvoiceAction,
)


def test_split_invoice_action_valida():
    action = SplitInvoiceAction(type_a_pct=50, type_b_pct=50)
    assert action.type == "split_invoice"


def test_split_invoice_action_invalida():
    import pytest
    with pytest.raises(ValueError):
        SplitInvoiceAction(type_a_pct=60, type_b_pct=60)


def test_rule_defaults():
    action = LiteralInstructionAction(natural_language="hacer factura A")
    rule = Rule(
        scope="client",
        client_id="138",
        pattern_canonical="hacer factura a",
        pattern_simhash=12345,
        action=action,
    )
    assert rule.status == "shadow"
    assert rule.hit_count == 0
    assert rule.id  # UUID generado automáticamente


def test_rule_match_default():
    match = RuleMatch()
    assert match.match_type == "none"
    assert match.match_score == 0.0
    assert match.rule is None


def test_observation_timestamp_autogenerado():
    obs = Observation(client_id="138", text="hacer 50/50", comprobante_id="comp-001")
    assert obs.timestamp is not None


def test_compilation_request():
    obs = Observation(client_id="138", text="armar factura A y B", comprobante_id="comp-002")
    req = CompilationRequest(observation=obs, user_response="50% factura A, 50% factura B")
    assert req.retry_count == 0
    assert req.original_rule_id is None
