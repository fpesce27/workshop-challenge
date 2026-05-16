---
rule_id: b2c3d4e5-f6a7-8901-bcde-f12345678901
scope: global
client_id: null
status: active
approved: true
hit_count: 312
confidence: 1.0
created_at: "2026-03-15T08:00:00+00:00"
last_used_at: "2026-05-14T18:45:30+00:00"
simhash: 4512367890123456789
action:
  type: split_invoice
  type_a_pct: 50
  type_b_pct: 50
tags:
  - second-brain
  - global
---

# ✅ Regla: `50/50`

**Scope:** global
**Status:** active

## Observación original

> hacer 50/50

## Respuesta del operador

"Partir la factura en dos partes iguales. Aplica a cualquier cliente."

## Regla compilada

Dividir la factura en dos partes: **50%** tipo A y **50%** tipo B.

## Cuándo se aplica

Cuando cualquier comprobante tenga una observación similar a `hacer 50/50`, `mitad y mitad`, `dividir en partes iguales`, etc. (el normalizador colapsa todas esas variantes a `50/50`).

**Usos registrados:** 312  
**Confianza:** 100%

---

> Esta regla fue **promovida de cliente a global** el 2026-03-15 después de detectarse en 8 clientes distintos con el mismo patrón. Ver nota de promoción en `pendientes-revision/promociones/`.
