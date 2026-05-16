---
tipo: compilation-failed
job_id: a7b8c9d0-e1f2-3456-abcd-567890123456
created_at: "2026-05-14T16:45:00+00:00"
retry_count: 3
estado: fallido
---

# Error de compilación — revisión manual requerida

**Observación:** empresa del grupo
**Cliente:** 503
**Comprobante:** CMP-2026-05-1089
**Respuesta del operador:** "según qué mes, depende del cierre contable, a veces es una a veces la otra, fijate con contabilidad"

**Error:** La respuesta del operador no tiene suficiente información estructurada para compilar una regla ejecutable. Se reintentó 3 veces con el mismo resultado.

## ¿Qué hacer?

1. Contactar al cliente 503 para obtener una respuesta más precisa.
2. Una vez que tengas la regla clara, podés cargarla manualmente editando el frontmatter:

```yaml
action:
  type: literal_instruction
  natural_language: "Descripción clara de qué hacer"
```

O si es una condición estructurada:

```yaml
action:
  type: multi_tax_id
  default_cuit: XX-XXXXXXXX-X
  conditions:
  - field: amount
    operator: gt
    value: 0
  condition_cuit: XX-XXXXXXXX-X
```

3. Una vez editado, reencolar manualmente el job o crear la regla directamente desde la API.

## Contexto

Este es un caso donde la respuesta del operador es demasiado ambigua para estructurar ("depende del cierre contable"). El sistema registró la observación pero no pudo aprender de ella. Es una señal de que el proceso de consulta al usuario necesita más contexto para este cliente.
