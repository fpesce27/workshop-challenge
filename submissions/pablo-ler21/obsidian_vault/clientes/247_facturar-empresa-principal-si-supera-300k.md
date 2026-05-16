---
rule_id: 7e0fa2ce-8432-4f8f-bd2d-6ab5813276b5
scope: client
client_id: 247
status: active
approved: true
hit_count: 11
confidence: 1.0
created_at: "2026-04-06T20:36:21.764017+00:00"
last_used_at: "2026-05-15T18:36:21.764026+00:00"
simhash: 8671652329241585563
action:
  type: multi_tax_id
  default_cuit: 30-11223344-5
  conditions:
  - field: amount
    operator: gt
    value: 300000.0
  condition_cuit: 20-55667788-9
tags:
  - second-brain
---
# ✅ Regla: `facturar empresa principal si supera 300k`

**Scope:** cliente — cliente `247`
**Status:** active

## Observación original

> facturar empresa principal si supera 300k

## Respuesta del operador

Respuesta del operador (demo)

## Regla compilada

Elegir razón social según el monto: si amount > 300000.0 usar CUIT `20-55667788-9`, si no usar CUIT `30-11223344-5` (default).

## Cuándo se aplica

Cuando un comprobante de `247` tenga una observación similar a `facturar empresa principal si supera 300k`.

**Usos registrados:** 11  
**Confianza:** 100%
