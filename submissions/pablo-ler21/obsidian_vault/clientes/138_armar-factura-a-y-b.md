---
rule_id: a1b2c3d4-e5f6-7890-abcd-ef1234567890
scope: client
client_id: "138"
status: active
approved: true
hit_count: 47
confidence: 1.0
created_at: "2026-04-01T10:23:15+00:00"
last_used_at: "2026-05-14T09:11:02+00:00"
simhash: 7823645901234567890
action:
  type: split_invoice
  type_a_pct: 50
  type_b_pct: 50
tags:
  - second-brain
---

# ✅ Regla: `factura a y b`

**Scope:** cliente — cliente `138`
**Status:** active

## Observación original

> armar factura A y B

## Respuesta del operador

"Factura tipo A para Distribuidora Sur SA y tipo B para Sur Logística SRL. Siempre mitad y mitad."

## Regla compilada

Dividir la factura en dos partes: **50%** tipo A y **50%** tipo B.

## Cuándo se aplica

Cuando un comprobante del cliente `138` tenga una observación similar a `armar factura A y B`.

**Usos registrados:** 47  
**Confianza:** 100%
