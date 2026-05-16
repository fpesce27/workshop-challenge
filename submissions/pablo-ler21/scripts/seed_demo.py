#!/usr/bin/env python3
"""Pobla la DB con un escenario realista de demo.

Crea:
  - 10 clientes simulados
  - 30 reglas activas (mix de globales y por cliente)
  - 5 invalidaciones históricas
  - Notas Obsidian correspondientes
"""

from __future__ import annotations

import sys
from pathlib import Path

# Agregar src/ al path para poder importar second_brain
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from datetime import UTC, datetime, timedelta
import uuid

from second_brain.db import get_connection, get_db_path, init_db, insert_rule
from second_brain.models import (
    Condition,
    LiteralInstructionAction,
    MultiTaxIDAction,
    Observation,
    Rule,
    SplitInvoiceAction,
)
from second_brain.normalizer import normalize, simhash
from second_brain.obsidian_writer import get_vault_path, write_rule_note


# ---------------------------------------------------------------------------
# Datos de demo
# ---------------------------------------------------------------------------

CLIENTES = [
    {"id": "101", "nombre": "Frigorífico del Norte SRL"},
    {"id": "138", "nombre": "Distribuidora Sur SA"},
    {"id": "201", "nombre": "Alimentos del Litoral SRL"},
    {"id": "247", "nombre": "Comercial Belgrano SA"},
    {"id": "315", "nombre": "Frigorífico Central SA"},
    {"id": "389", "nombre": "Distribuidora Norte SRL"},
    {"id": "402", "nombre": "Alimentos Patagonia SA"},
    {"id": "503", "nombre": "Carnes del Sur SRL"},
    {"id": "612", "nombre": "Importadora Centro SA"},
    {"id": "740", "nombre": "Mayorista del Litoral SRL"},
]

# Reglas globales — aplican a todos los clientes
REGLAS_GLOBALES = [
    {
        "pattern": "hacer 50/50",
        "action": SplitInvoiceAction(type_a_pct=50, type_b_pct=50),
        "hit_count": 312,
    },
    {
        "pattern": "armar factura a y b",
        "action": SplitInvoiceAction(type_a_pct=50, type_b_pct=50),
        "hit_count": 87,
    },
    {
        "pattern": "dividir en partes iguales",
        "action": SplitInvoiceAction(type_a_pct=50, type_b_pct=50),
        "hit_count": 43,
    },
]

# Reglas por cliente — idiosincrasias específicas
REGLAS_CLIENTE = [
    # Clientes que usan 70/30
    {"client_id": "101", "pattern": "70/30", "action": SplitInvoiceAction(type_a_pct=70, type_b_pct=30), "hit_count": 28},
    {"client_id": "315", "pattern": "70/30", "action": SplitInvoiceAction(type_a_pct=70, type_b_pct=30), "hit_count": 15},
    # Clientes con razón social condicional por monto
    {
        "client_id": "138",
        "pattern": "distribuidora sur si mayor 500k sino sur logistica",
        "action": MultiTaxIDAction(
            default_cuit="30-98765432-1",
            conditions=[Condition(field="amount", operator="gt", value=500000)],
            condition_cuit="20-12345678-9",
        ),
        "hit_count": 19,
    },
    {
        "client_id": "247",
        "pattern": "facturar empresa principal si supera 300k",
        "action": MultiTaxIDAction(
            default_cuit="30-11223344-5",
            conditions=[Condition(field="amount", operator="gt", value=300000)],
            condition_cuit="20-55667788-9",
        ),
        "hit_count": 11,
    },
    # Instrucciones literales
    {"client_id": "201", "pattern": "siempre a alimentos del litoral", "action": LiteralInstructionAction(natural_language="Facturar siempre a Alimentos del Litoral SRL, CUIT 30-22334455-6"), "hit_count": 55},
    {"client_id": "389", "pattern": "empresa del grupo norte", "action": LiteralInstructionAction(natural_language="Usar razón social Distribuidora Norte SRL, CUIT 30-44556677-8"), "hit_count": 33},
    {"client_id": "402", "pattern": "patagonia sa", "action": LiteralInstructionAction(natural_language="Facturar a Alimentos Patagonia SA, CUIT 30-66778899-0"), "hit_count": 22},
    {"client_id": "503", "pattern": "cuit nuevo", "action": LiteralInstructionAction(natural_language="Usar CUIT actualizado 30-99887766-5 (cambió en 2025)"), "hit_count": 8},
    # 60/40 específico de algunos clientes
    {"client_id": "612", "pattern": "60/40", "action": SplitInvoiceAction(type_a_pct=60, type_b_pct=40), "hit_count": 17},
    {"client_id": "740", "pattern": "60/40", "action": SplitInvoiceAction(type_a_pct=60, type_b_pct=40), "hit_count": 9},
    # Más variantes de clientes
    {"client_id": "101", "pattern": "siempre tipo a", "action": LiteralInstructionAction(natural_language="Emitir todo en factura tipo A, sin dividir"), "hit_count": 41},
    {"client_id": "138", "pattern": "factura electronica b", "action": LiteralInstructionAction(natural_language="Emitir factura electrónica tipo B, contribuyente inscripto"), "hit_count": 67},
    {"client_id": "315", "pattern": "dos facturas distintas", "action": SplitInvoiceAction(type_a_pct=50, type_b_pct=50), "hit_count": 24},
    {"client_id": "247", "pattern": "solo tipo b", "action": LiteralInstructionAction(natural_language="Solo factura tipo B, consumidor final"), "hit_count": 13},
    {"client_id": "503", "pattern": "tercio y dos tercios", "action": LiteralInstructionAction(natural_language="Dividir: 33% factura A, 67% factura B"), "hit_count": 5},
    # Globales adicionales
    {"client_id": None, "pattern": "mitad tipo a mitad tipo b", "action": SplitInvoiceAction(type_a_pct=50, type_b_pct=50), "hit_count": 29, "scope": "global"},
    {"client_id": None, "pattern": "factura b consumidor final", "action": LiteralInstructionAction(natural_language="Emitir como factura B a consumidor final"), "hit_count": 156, "scope": "global"},
    {"client_id": None, "pattern": "factura a responsable inscripto", "action": LiteralInstructionAction(natural_language="Emitir como factura A a responsable inscripto"), "hit_count": 203, "scope": "global"},
]


def _make_rule(
    pattern: str,
    action,
    scope: str = "client",
    client_id: str = None,
    hit_count: int = 0,
    days_ago: int = 30,
) -> Rule:
    canonical = normalize(pattern)
    created = datetime.now(UTC) - timedelta(days=days_ago)
    last_used = datetime.now(UTC) - timedelta(hours=2) if hit_count > 0 else None
    return Rule(
        scope=scope,
        client_id=client_id,
        pattern_canonical=canonical,
        pattern_simhash=simhash(canonical),
        action=action,
        hit_count=hit_count,
        created_at=created,
        last_used_at=last_used,
        status="active",
    )


def seed_rules(db_path: Path, vault_path: Path) -> list[Rule]:
    rules: list[Rule] = []

    # Globales explícitas
    for i, g in enumerate(REGLAS_GLOBALES):
        rule = _make_rule(g["pattern"], g["action"], scope="global", hit_count=g["hit_count"], days_ago=60 - i * 5)
        insert_rule(rule, db_path)
        obs = Observation(client_id="cualquier_cliente", text=g["pattern"], comprobante_id=f"DEMO-G{i:03d}")
        write_rule_note(rule, obs, "Respuesta del operador (demo)", vault_path)
        rules.append(rule)

    # Por cliente
    for i, rc in enumerate(REGLAS_CLIENTE):
        scope = rc.get("scope", "client")
        rule = _make_rule(
            rc["pattern"], rc["action"],
            scope=scope,
            client_id=rc.get("client_id"),
            hit_count=rc["hit_count"],
            days_ago=max(1, 45 - i * 2),
        )
        insert_rule(rule, db_path)
        client_id = rc.get("client_id") or "global"
        obs = Observation(client_id=client_id, text=rc["pattern"], comprobante_id=f"DEMO-C{i:03d}")
        write_rule_note(rule, obs, "Respuesta del operador (demo)", vault_path)
        rules.append(rule)

    return rules


def seed_invalidations(db_path: Path, rules: list[Rule]) -> None:
    """Inserta 5 invalidaciones históricas para mostrar memoria negativa."""
    client_rules = [r for r in rules if r.scope == "client" and r.status == "active"]
    if len(client_rules) < 5:
        return

    invalidation_data = [
        (client_rules[0], "Era 70/30 antes, ahora cambiaron a 60/40"),
        (client_rules[1], "La razón social cambió, ahora es Sur Distribuciones SA"),
        (client_rules[2], "Solo aplica los lunes, el resto de los días es normal"),
        (client_rules[3], "El cliente confirmó que ya no quiere dividir, todo tipo A"),
        (client_rules[4], "CUIT incorrecto, el correcto es 30-12121212-1"),
    ]

    now = datetime.now(UTC)
    with get_connection(db_path) as conn:
        for idx, (rule, correction) in enumerate(invalidation_data):
            inv_date = (now - timedelta(days=idx + 1)).isoformat()
            conn.execute(
                """INSERT INTO invalidations
                   (id, rule_id, client_id, comprobante_id, observation_text, user_correction, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    rule.id,
                    rule.client_id or "global",
                    f"DEMO-INV{idx:03d}",
                    rule.pattern_canonical,
                    correction,
                    inv_date,
                ),
            )
    print(f"  [ok] {len(invalidation_data)} invalidaciones historicas insertadas")


def main() -> None:
    db_path = get_db_path()
    vault_path = get_vault_path(db_path)

    print(f"Iniciando seed en: {db_path}")
    print(f"Vault: {vault_path}\n")

    init_db(db_path)

    # Limpiar datos existentes para demo limpia
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM invalidations")
        conn.execute("DELETE FROM compilation_queue")
        conn.execute("DELETE FROM rules")
    print("  [ok] DB limpiada")

    rules = seed_rules(db_path, vault_path)
    print(f"  [ok] {len(rules)} reglas insertadas ({sum(1 for r in rules if r.scope == 'global')} globales, {sum(1 for r in rules if r.scope == 'client')} de cliente)")

    seed_invalidations(db_path, rules)

    with get_connection(db_path) as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM rules").fetchone()["c"]
        active = conn.execute("SELECT COUNT(*) AS c FROM rules WHERE status='active'").fetchone()["c"]

    print(f"\n[LISTO] Demo lista: {total} reglas totales, {active} activas")
    print(f"        Vault: {vault_path}")
    print("\nPara levantar la API:")
    print("  uv run uvicorn second_brain.main:app --reload")


if __name__ == "__main__":
    main()
