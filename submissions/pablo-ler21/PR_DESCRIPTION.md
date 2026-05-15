# Second Brain — Galo: memoria determinística con human loop

> El agente tiene un sistema nervioso. El humano tiene un cerebro. No son el mismo órgano.

## La idea

La solución obvia al problema de memoria es guardar las respuestas del usuario en una base vectorial e inyectarlas al prompt de cada mensaje. Funciona. Es cara, lenta, y el agente aprende a ciegas sin que el operador pueda ver ni corregir lo que aprendió.

Esta propuesta va por otro camino: separa el sistema en dos planos completamente distintos. El **hot path** es determinístico, sin LLMs, y responde en < 5ms p99 usando SQLite + SimHash. El **human loop** es reflexivo, asíncrono, y usa Obsidian + Claude Code como interfaz de curación para el operador. Las reglas no son texto inyectado al prompt sino **mini-programas JSON ejecutables** con tipos Pydantic: `SplitInvoiceAction`, `MultiTaxIDAction`, `LiteralInstructionAction`. El agente los corre directamente, sin ambigüedad.

## Tres piezas que diferencian la propuesta

**Reglas como mini-programas ejecutables.** En vez de inyectar "cuando el cliente diga 50/50, dividir la factura en partes iguales" al prompt, el sistema compila esa instrucción en `SplitInvoiceAction(type_a_pct=50, type_b_pct=50)`. El agente no interpreta texto, ejecuta código. Esto elimina alucinaciones en el hot path y hace el comportamiento completamente predecible.

**Promoción automática cliente→global.** Cuando ≥5 clientes distintos comparten el mismo patrón normalizado, el sistema propone automáticamente elevarlo a regla global. El promotor corre en batch cada hora con una query SQL simple, crea una regla shadow, y escribe una nota en Obsidian para que el operador la revise. Una vez aprobada, todos los clientes futuros se benefician sin que nadie haya tenido que configurarlo explícitamente.

**Memoria negativa / contra-aprendizaje.** Cuando el agente aplica una regla y el usuario la corrige, eso es una señal de invalidación. Con ≥3 invalidaciones en 7 días, la regla pasa a `deprecated` — y **nunca se borra**. Queda en SQLite como registro histórico con el motivo. El vault de Obsidian tiene una carpeta `pendientes-revision/invalidaciones/` donde el operador puede ver exactamente qué cambió, cuándo, y por qué. Esta es la pieza que la mayoría de las propuestas va a omitir: saber no solo qué hacer, sino qué no hacer y por qué se dejó de hacer.

## Los números

Benchmarks sobre 10.000 reglas activas en SQLite (Windows, Python 3.13):
- **p50: < 1 ms, p99: < 5 ms** ✅ (test `test_lookup_performance_10k_rules`)
- Proyección a 90 días: hit rate > 85%, costo Anthropic < USD 5/mes, DB < 50 MB

A los 90 días de operación, más del 85% del tráfico pasa por SQLite sin tocar ningún LLM. El costo por mensaje en el hot path es prácticamente cero.

## El vault de Obsidian

El repositorio incluye `obsidian_vault/` con 6 notas reales que muestran el human loop en acción: una regla activa de cliente, una activa global con historial de promoción, una shadow esperando aprobación, una invalidación post-deprecación, una propuesta de promoción, y una compilación fallida con instrucciones para resolución manual. El operador abre Obsidian, edita `approved: false → true`, y el watcher lo detecta en ≤30s y activa la regla en SQLite.

Para arrancar la demo: `uv sync && uv run python scripts/seed_demo.py && uv run uvicorn second_brain.main:app`.
