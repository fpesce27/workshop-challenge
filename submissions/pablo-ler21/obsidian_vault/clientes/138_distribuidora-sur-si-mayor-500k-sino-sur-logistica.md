---
rule_id: 2a7ca015-198b-44e7-ad6d-420c176faeaa
scope: client
client_id: 138
status: active
approved: true
hit_count: 19
confidence: 1.0
created_at: "2026-04-04T20:36:21.752260+00:00"
last_used_at: "2026-05-15T18:36:21.752268+00:00"
simhash: 5191715955218868292
action:
  type: multi_tax_id
  default_cuit: 30-98765432-1
  conditions:
  - field: amount
    operator: gt
    value: 500000.0
  condition_cuit: 20-12345678-9
tags:
  - second-brain
---
# ✅ Regla: `distribuidora sur si mayor 500k sino sur logistica`

**Scope:** cliente — cliente `138`
**Status:** active

## Observación original

> distribuidora sur si mayor 500k sino sur logistica

## Respuesta del operador

Respuesta del operador (demo)

## Regla compilada

Elegir razón social según el monto: si amount > 500000.0 usar CUIT `20-12345678-9`, si no usar CUIT `30-98765432-1` (default).

## Cuándo se aplica

Cuando un comprobante de `138` tenga una observación similar a `distribuidora sur si mayor 500k sino sur logistica`.

**Usos registrados:** 19  
**Confianza:** 100%
