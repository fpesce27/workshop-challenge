---
rule_id: c3d4e5f6-a7b8-9012-cdef-123456789012
scope: client
client_id: "247"
status: shadow
approved: false
hit_count: 0
confidence: 1.0
created_at: "2026-05-14T14:30:00+00:00"
last_used_at: null
simhash: 9034512678901234567
action:
  type: multi_tax_id
  default_cuit: 30-98765432-1
  conditions:
  - field: amount
    operator: gt
    value: 500000
  condition_cuit: 20-12345678-9
tags:
  - second-brain
  - pendiente-revision
---

# 🔵 Regla: `facturar distribuidora sur si mayor 500k`

**Scope:** cliente — cliente `247`
**Status:** shadow (esperando validación)

## Observación original

> facturar a Distribuidora Sur si mayor a 500k, sino a Sur Logística

## Respuesta del operador

"Si el monto supera 500.000 pesos, usar CUIT 20-12345678-9 (Distribuidora Sur SA). Si no, usar CUIT 30-98765432-1 (Sur Logística SRL)."

## Regla compilada

Elegir razón social según el monto: si amount > 500000 usar CUIT `20-12345678-9`, si no usar CUIT `30-98765432-1` (default).

## Cuándo se aplica

Cuando un comprobante del cliente `247` tenga una observación similar a `facturar a Distribuidora Sur si mayor a 500k`.

**Usos registrados:** 0  
**Confianza:** 100%

---

> 🔵 **Pendiente de validación** — Esta es la primera vez que el agente vio esta observación. Cambiar `approved: false` a `approved: true` en el frontmatter para activar esta regla.
