# Compiled Intelligence

**Submission de [@Agusting22](https://github.com/Agusting22) — Workshop Challenge Galo · Second Brain**

Un sistema de memoria que **compila** las respuestas del operador en reglas ejecutables determinísticas, en vez de almacenarlas como texto para que un LLM las interprete cada vez.

---

## El insight central

El bot ya extrae datos del comprobante. Lo que falla es interpretar las observaciones ambiguas ("armar factura A y B", "50/50", múltiples razones sociales). Hoy el bot **le pregunta al cliente** y como los clientes son recurrentes, **preguntarle dos veces lo mismo rompe la relación comercial**. La memoria no es una optimización: es un requerimiento de negocio.

La solución habitual sería RAG: guardar las aclaraciones como texto, buscar por embedding, inyectar al prompt, dejar que el LLM las interprete cada vez. Funciona, pero el costo crece linealmente con el tráfico y nunca se vuelve más barato.

**Compiled Intelligence invierte esa lógica:** cuando el operador aclara una observación, esa aclaración se compila en una **regla estructurada** con trigger + acción. La próxima vez que aparece esa observación (o una equivalente), un **lookup determinístico en Postgres** resuelve el caso en milisegundos, sin tokens, sin LLM.

El LLM solo aparece en dos momentos: durante el aprendizaje (compilar la respuesta del operador en regla, asíncrono) y cuando llega una observación genuinamente nueva sin match en la cascada.

A los 90 días, >95% de los comprobantes se resuelven con lookup, costo cercano a $0 por comprobante.

---

## Cómo se evalúa contra los tres pilares

### Realismo
- **Stack estándar y barato**: Postgres + pgvector + pg_trgm. Supabase Pro a USD 25/mes alcanza para 10K clientes. Sin servicios exóticos.
- **Costo proyectado**: ~USD 35/mes a régimen para 100 clientes; ~USD 250/mes para 100K clientes (escala sublinealmente porque el LLM se usa menos a medida que hay más reglas).
- **Tolerancia a fallos**: si la API del LLM cae, el ~95% del sistema sigue operando con reglas determinísticas. Sólo se degrada el aprendizaje y los casos nuevos.
- **Auditabilidad**: cada acción ejecutada tiene una regla trazable con origen (qué interacción la creó), historial de uso y confianza. Crítico para una distribuidora que delega facturación a terceros.

### Creatividad
- **No es RAG.** No guardamos texto para reinterpretar — compilamos texto en código ejecutable.
- **Curva de costo invertida**: a más uso, más barato por unidad. El LLM se usa para enseñar al sistema, no para operarlo.
- **Doble dimensión client/global resuelta con un `ORDER BY` simple**: per-client wins, global como fallback. Promoción automática de per-client a global cuando 3+ clientes coinciden.
- **Cascada de 3 niveles ordenada por costo creciente**: exact (hash) → fuzzy (trigramas pg_trgm) → semantic (embeddings pgvector). Cada nivel cubre un tipo distinto de variación (tipográfica, semántica) sin pagar el costo del siguiente.

### Escalabilidad
- **Postgres maneja millones de reglas** con índices apropiados: B-tree para hash, GIN para trigramas, IVFFlat para vectores. Particionable por CUIT si crece más de 10M de filas.
- **El % de LLM decrece con el tiempo**: más reglas compiladas = más matches determinísticos. El componente caro se usa cada vez menos.
- **Asincronía**: el Learning Pipeline corre en background. El flujo principal nunca espera al LLM si no hace falta.
- **Client DNA acotado**: cada cliente tiene un resumen de ~200-500 tokens (no un log creciente), recompilado on-change.

---

## Qué hay en esta carpeta

| Archivo | Qué es |
|---------|--------|
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | El documento completo. Decisiones, trade-offs, flujo end-to-end, edge cases, costos a escala, por qué no es RAG. |
| [`schema.sql`](./schema.sql) | Schema Postgres con pg_trgm + pgvector. Tablas, índices, funciones de matching. |
| [`types.ts`](./types.ts) | Tipos compartidos: `Rule`, `ClientDNA`, `Action`, action_types. |
| [`rules-engine.ts`](./rules-engine.ts) | Cascada de 3 niveles (exact → fuzzy → semantic) con prioridad per-client. |
| [`learning-pipeline.ts`](./learning-pipeline.ts) | Pipeline asíncrono: clasifica scope, extrae regla, compila, persiste, actualiza Client DNA. |
| [`flow.mmd`](./flow.mmd) | Diagrama Mermaid del flujo completo de un comprobante. |

> El código TypeScript es **ilustrativo**: tipado y completo, pero no instalable (sin `package.json`). Muestra el approach, no es un sistema corriendo. El schema SQL es ejecutable tal cual sobre un Postgres con pg_trgm y pgvector habilitados.

---

## En una línea

> *"Si el conocimiento no cambia, no debería re-interpretarse. Compilalo una vez y ejecutalo siempre."*
