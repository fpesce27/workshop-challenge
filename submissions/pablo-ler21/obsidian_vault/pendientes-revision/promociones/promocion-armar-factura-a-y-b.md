---
tipo: promocion-global
rule_id: f6a7b8c9-d0e1-2345-fabc-456789012345
pattern: "factura a y b"
client_count: 7
created_at: "2026-05-10T09:00:00+00:00"
approved: false
---

# Propuesta de promoción global: `factura a y b`

El patrón aparece en **7 clientes distintos**. Se propone elevar a regla global (scope=global, status=shadow).

## Clientes que la tienen

- 112 (Frigorífico del Norte SRL)
- 138 (Distribuidora Sur SA)
- 201 (Alimentos del Litoral)
- 247 (Comercial Belgrano)
- 315 (Frigorífico Central SA)
- 389 (Distribuidora Norte SRL)
- 402 (Alimentos Patagonia)

## Acción propuesta

Dividir la factura en dos partes: **50%** tipo A y **50%** tipo B.

## Análisis

Todos los clientes responden exactamente igual a esta observación. No hay variación en los parámetros. Es un concepto global del sistema de facturación que el agente desconocía.

## Para aprobar

Cambiar `approved: false` por `approved: true` en el frontmatter. El watcher lo detectará y promoverá la regla global a `active`.

Si el agente ya tiene reglas de cliente para este patrón, seguirán funcionando (la regla de cliente siempre tiene prioridad sobre la global).
