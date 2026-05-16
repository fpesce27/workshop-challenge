"""Tests del vault writer y watcher de Obsidian."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import yaml

from second_brain.db import get_connection, init_db, insert_rule, update_rule_status
from second_brain.models import Observation, Rule, SplitInvoiceAction
from second_brain.normalizer import normalize, simhash
from second_brain.obsidian_writer import write_rule_note
from second_brain.watcher import parse_frontmatter, process_vault_changes


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


def _shadow_rule(client_id: str = "138", pattern: str = "hacer 50/50") -> Rule:
    canonical = normalize(pattern)
    return Rule(
        scope="client",
        client_id=client_id,
        pattern_canonical=canonical,
        pattern_simhash=simhash(canonical),
        action=SplitInvoiceAction(type_a_pct=50, type_b_pct=50),
        status="shadow",
    )


def _obs(rule: Rule) -> Observation:
    return Observation(
        client_id=rule.client_id,
        text="hacer 50/50",
        comprobante_id="CMP001",
    )


# ---------------------------------------------------------------------------
# write_rule_note — estructura y validez del Markdown
# ---------------------------------------------------------------------------

def test_write_rule_note_returns_path(tmp_vault):
    rule = _shadow_rule()
    obs = _obs(rule)
    path = write_rule_note(rule, obs, "mitad y mitad", tmp_vault)

    assert path.exists()
    assert path.suffix == ".md"


def test_write_rule_note_frontmatter_is_valid_yaml(tmp_vault):
    rule = _shadow_rule()
    obs = _obs(rule)
    path = write_rule_note(rule, obs, "mitad y mitad", tmp_vault)

    content = path.read_text(encoding="utf-8")
    fm = parse_frontmatter(content)

    assert fm is not None
    # Verificar con yaml.safe_load directamente también
    parts = content.split("---", 2)
    parsed = yaml.safe_load(parts[1])
    assert parsed is not None


def test_write_rule_note_frontmatter_fields(tmp_vault):
    rule = _shadow_rule()
    obs = _obs(rule)
    path = write_rule_note(rule, obs, "mitad y mitad", tmp_vault)

    content = path.read_text(encoding="utf-8")
    fm = parse_frontmatter(content)

    assert fm["rule_id"] == rule.id
    assert fm["scope"] == "client"
    assert str(fm["client_id"]) == "138"
    assert fm["status"] == "shadow"
    assert fm["approved"] is False
    assert "action" in fm


def test_write_active_rule_goes_to_clientes_folder(tmp_vault):
    rule = _shadow_rule()
    rule = rule.model_copy(update={"status": "active"})
    obs = _obs(rule)
    path = write_rule_note(rule, obs, "mitad y mitad", tmp_vault)

    assert "clientes" in str(path)


def test_write_active_global_rule_goes_to_globales_folder(tmp_vault):
    canonical = normalize("hacer 50/50")
    rule = Rule(
        scope="global",
        client_id=None,
        pattern_canonical=canonical,
        pattern_simhash=simhash(canonical),
        action=SplitInvoiceAction(type_a_pct=50, type_b_pct=50),
        status="active",
    )
    obs = Observation(client_id="cualquiera", text="hacer 50/50", comprobante_id="CMP001")
    path = write_rule_note(rule, obs, "mitad y mitad", tmp_vault)

    assert "globales" in str(path)


def test_write_shadow_rule_goes_to_pendientes(tmp_vault):
    rule = _shadow_rule()
    obs = _obs(rule)
    path = write_rule_note(rule, obs, "mitad y mitad", tmp_vault)

    assert "pendientes-revision" in str(path)


def test_write_rule_note_contains_observation_text(tmp_vault):
    rule = _shadow_rule()
    obs = _obs(rule)
    path = write_rule_note(rule, obs, "mitad y mitad", tmp_vault)

    content = path.read_text(encoding="utf-8")
    assert "hacer 50/50" in content
    assert "mitad y mitad" in content


# ---------------------------------------------------------------------------
# watcher — parse_frontmatter
# ---------------------------------------------------------------------------

def test_parse_frontmatter_valid():
    content = "---\nrule_id: abc123\nstatus: shadow\napproved: false\n---\n\n# Body"
    fm = parse_frontmatter(content)
    assert fm["rule_id"] == "abc123"
    assert fm["approved"] is False


def test_parse_frontmatter_no_yaml_returns_none():
    content = "# Just a markdown file with no frontmatter"
    fm = parse_frontmatter(content)
    assert fm is None


def test_parse_frontmatter_invalid_yaml_returns_none():
    content = "---\n: invalid: yaml: [\n---\n"
    fm = parse_frontmatter(content)
    assert fm is None


# ---------------------------------------------------------------------------
# process_vault_changes — integración watcher + DB
# ---------------------------------------------------------------------------

def test_process_vault_changes_promotes_on_approved_true(tmp_db, tmp_vault):
    """Cuando una nota pasa a approved: true, la regla shadow se promueve a active."""
    rule = _shadow_rule()
    insert_rule(rule, tmp_db)

    # Escribir la nota con approved: false
    obs = _obs(rule)
    note_path = write_rule_note(rule, obs, "mitad y mitad", tmp_vault)

    # Inicializar estado del watcher
    state = process_vault_changes(tmp_vault, tmp_db)

    # Simular que el operador edita la nota y pone approved: true
    content = note_path.read_text(encoding="utf-8")
    content = content.replace("approved: false", "approved: true")
    note_path.write_text(content, encoding="utf-8")

    # Esperar un tick para que mtime sea diferente (en algunos sistemas es necesario)
    time.sleep(0.05)

    # Segundo scan: debe detectar el cambio y promover la regla
    process_vault_changes(tmp_vault, tmp_db, state)

    with get_connection(tmp_db) as conn:
        row = conn.execute(
            "SELECT status FROM rules WHERE id=?", (rule.id,)
        ).fetchone()

    assert row["status"] == "active"


def test_process_vault_changes_ignores_already_active(tmp_db, tmp_vault):
    """Una nota con approved: true sobre una regla ya activa no genera error."""
    rule = _shadow_rule()
    insert_rule(rule, tmp_db)
    update_rule_status(rule.id, "active", tmp_db)

    obs = _obs(rule)
    note_path = write_rule_note(rule, obs, "mitad y mitad", tmp_vault)

    content = note_path.read_text(encoding="utf-8")
    content = content.replace("approved: false", "approved: true")
    note_path.write_text(content, encoding="utf-8")

    # No debe lanzar excepción
    process_vault_changes(tmp_vault, tmp_db)

    with get_connection(tmp_db) as conn:
        row = conn.execute(
            "SELECT status FROM rules WHERE id=?", (rule.id,)
        ).fetchone()
    assert row["status"] == "active"
