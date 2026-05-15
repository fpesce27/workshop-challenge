# Compiled Intelligence: arquitectura completa

> Documento de arquitectura para el sistema de memoria del agente de comprobantes de [Galo](https://soygalo.com).
> Submission al [Workshop Challenge](https://github.com/fpesce27/workshop-challenge) por [@Agusting22](https://github.com/Agusting22).

---

## Tabla de contenidos

1. [El problema real](#1-el-problema-real)
2. [La idea: compilar en vez de interpretar](#2-la-idea-compilar-en-vez-de-interpretar)
3. [Los cuatro componentes](#3-los-cuatro-componentes)
4. [Flujo end-to-end de un comprobante](#4-flujo-end-to-end-de-un-comprobante)
5. [Per-client vs global: la doble dimensión](#5-per-client-vs-global-la-doble-dimensi%C3%B3n)
6. [Edge cases y manejo de errores](#6-edge-cases-y-manejo-de-errores)
7. [Costos a escala](#7-costos-a-escala)
8. [Escalabilidad técnica](#8-escalabilidad-t%C3%A9cnica)
9. [Por qué no es RAG](#9-por-qu%C3%A9-no-es-rag)
10. [Decisiones y trade-offs](#10-decisiones-y-trade-offs)

---

## 1. El problema real

El agente actual de Galo procesa correctamente la mecánica de los comprobantes: extrae monto, CBU, CUIT, banco, y ejecuta validaciones. **El problema aparece en el campo de observaciones cuando el cliente escribe instrucciones ambiguas**:

- `armar factura A y B` — el cliente quiere dos facturas pero no dice en qué proporción.
- `hacer 50/50` — ¿dividir el monto? ¿el tipo de factura? ¿entre razones sociales? depende del cliente.
- múltiples razones sociales en la misma nota.
- `sumar IVA aparte` — instrucción fiscal que puede ser de un cliente o general.

El bot actual, ante cualquier ambigüedad, **le pregunta al cliente**. Y acá empieza el problema real:

> Los clientes son **recurrentes** y operan compras semanales o diarias con Galo. Preguntarle a un cliente recurrente "¿qué quisiste decir con 50/50?" **una vez** es aceptable. Preguntárselo cada semana es ofensivo y rompe la relación comercial. El sistema **no puede preguntar dos veces lo mismo al mismo cliente**.

Esto convierte el problema de memoria en **un requerimiento de negocio**, no en una optimización de costo o latencia. La memoria es lo que hace viable el producto.

### Tres fallas encadenadas hoy

1. **Sin memoria persistente** — la conversación con el operador se pierde. La próxima vez el bot vuelve a no saber.
2. **Contexto saturado** — si se intenta inyectar historial conversacional al prompt, se llena de ruido.
3. **Sin distinción client/global** — el sistema no diferencia un quirk de un cliente de un concepto universal.

### Contexto que ya tiene Galo (y que el sistema puede explotar)

Cuando llega un comprobante, Galo **ya sabe**:
- Quién es el cliente (CUIT, razones sociales, banco habitual).
- Qué pidió (historial de pedidos previos).
- Patrones de comportamiento: montos típicos, frecuencia, productos.

Esto significa que el sistema de memoria no arranca vacío: puede pre-popular el perfil de cada cliente con datos existentes y aprender desde ahí.

### Lo que Galo NO hace (y por qué importa)

Galo **no factura** ni hace logística — eso lo maneja el ERP de cada empresa contratante. La "acción" final del sistema es **transmitir una instrucción estructurada al sistema externo**, no ejecutar una operación contable. Esto simplifica el modelo: las acciones son mensajes pasables a un ERP, no operaciones críticas en sí mismas. El error es recuperable porque hay otro sistema downstream que las consume y valida.

---

## 2. La idea: compilar en vez de interpretar

La analogía técnica que guía toda la arquitectura es la diferencia entre **un intérprete y un compilador**.

Un intérprete lee código fuente cada vez que necesita ejecutarlo, lo analiza, decide qué hacer. Es flexible pero lento — repite el mismo trabajo en cada ejecución. Un compilador transforma el código fuente **una sola vez** en instrucciones ejecutables. Después, esas instrucciones corren directamente, sin volver a analizar el fuente.

Los sistemas de memoria basados en RAG son intérpretes: almacenan texto, lo buscan con embeddings, lo inyectan al prompt, y el LLM lo interpreta cada vez que aparece la misma observación. Funciona, pero el costo crece linealmente con el uso.

**Compiled Intelligence es un compilador**: cuando el operador explica qué hacer con una observación, esa respuesta se compila **una vez** en una regla estructurada (trigger + acción + metadata). La próxima vez que aparece esa observación (o una equivalente), la regla se ejecuta directamente. Sin embedding-search, sin prompt, sin LLM.

El LLM queda reservado para dos momentos:

1. **Aprendizaje**: compilar la respuesta del operador en regla (asíncrono, fuera del path crítico).
2. **Casos genuinamente nuevos**: cuando la cascada determinística falla y existe un Client DNA, intentar inferir antes de escalar al operador.

Todo lo demás es determinístico.

---

## 3. Los cuatro componentes

### 3.1 Rules Engine — cascada de matching

Primera línea de procesamiento. Recibe `(cuit, observacion)` y devuelve `Rule | null`. Funciona como un lookup en tres niveles **ordenados de más barato a más caro**. Se corta en el primer match.

**Nivel 1 — Exact match (hash).** Se normaliza la observación (lowercase, sin tildes, sin espacios duplicados, sin puntuación redundante) y se calcula un hash SHA-1. Lookup contra índice B-tree sobre `normalized_trigger_hash`. **O(log n), <1ms, costo USD 0.**

> Cubre el caso "el cliente escribe exactamente lo mismo que ya vimos antes" — el más común a régimen.

**Nivel 2 — Fuzzy match (trigramas).** Si no hay exact match, se usa `pg_trgm` de Postgres para buscar por similitud de trigramas con umbral 0.3. Captura variaciones tipográficas: `fact. A y B`, `factura tipo A + B`, `factura A & B` todas matchean contra `armar factura a y b`. Índice GIN. **<5ms, costo USD 0.**

> Cubre el caso "lo escribió distinto pero quiso decir lo mismo".

**Nivel 3 — Semantic match (embeddings).** Si los dos anteriores fallan, se genera embedding de la observación con `text-embedding-3-small` (USD 0.00002/1K tokens) y se busca con similitud coseno >= 0.82 contra embeddings almacenados usando pgvector + IVFFlat. **~100ms, ~USD 0.0001.**

> Cubre el caso "dijo algo completamente distinto pero semánticamente equivalente": "dividir en dos partes iguales" → matchea "50/50".

**Prioridad per-client.** En los tres niveles, las reglas con `client_cuit` igual al del comprobante tienen prioridad sobre las globales (`client_cuit IS NULL`). Se implementa con `ORDER BY client_cuit NULLS LAST` — las per-client aparecen primero, las globales son fallback. Si un cliente tiene su propia regla de "50/50", se aplica esa; si no, la global.

**Estructura de una regla** (ver [`schema.sql`](./schema.sql) y [`types.ts`](./types.ts)):

```typescript
type Rule = {
  id: string;
  client_cuit: string | null;       // null = global
  trigger_text: string;              // texto original
  trigger_normalized: string;        // normalizado
  trigger_hash: string;              // sha1 del normalizado
  trigger_embedding: number[];       // vector(1536)
  action: Action;                    // tipo + params
  confidence: number;                // 0..1
  times_used: number;
  source_interaction_id: string;     // trazabilidad
  created_at: Date;
  active: boolean;
};
```

### 3.2 Client DNA — perfil estructurado por cliente

Un registro **compacto** (no creciente) que representa todo lo que el sistema sabe del cliente. **No es un log** — es una foto compilada del estado actual, diseñada para caber en un prompt sin saturar contexto.

Campos clave:

- **`quirks_digest`** — resumen en lenguaje natural de las reglas activas del cliente, generado por el Learning Pipeline. Ej: *"Siempre factura 50/50 entre tipo A y B. Tiene dos razones sociales: ABC SRL para montos >100.000, XYZ SA para el resto. Los viernes pide IVA como línea separada."* Tope: ~150 tokens. Se recompila cuando hay ≥3 reglas nuevas o cuando una existente cambia.
- **`razones_sociales`** — JSON con las entidades legales del cliente y reglas de selección (por monto, por banco, default).
- **`bank_patterns`** — bancos habituales del cliente. Anomalías (un comprobante de un banco inusual) se loguean.
- **`stats`** — total de comprobantes, tasa de resolución automática, último visto.

Tamaño total acotado: **~200-500 tokens por cliente**, independientemente de cuántos comprobantes haya procesado. La información granular vive en las reglas; el DNA es un resumen ejecutivo para que el LLM tenga contexto cuando lo necesita.

### 3.3 LLM — Haiku como modelo principal, de último recurso

El LLM **no opera el sistema**: enseña al sistema. Solo aparece en dos escenarios:

**Escenario A — Inferencia con DNA.** El Rules Engine no encontró match pero el cliente tiene `quirks_digest` no vacío. Se llama a Haiku con un prompt mínimo: observación + digest + lista cerrada de `action_types`. Si Haiku infiere una acción con alta certeza, se ejecuta y se envía al Learning Pipeline para compilar como regla. ~1-2s, ~USD 0.003.

**Escenario B — Escalación al operador.** Ni el Rules Engine ni la inferencia funcionaron. Se le pregunta al **operador humano** (no al cliente — el cliente nunca vuelve a ser molestado por lo mismo). La pregunta incluye nombre del cliente, monto, observación, y el quirks_digest si existe (para que el operador tenga contexto sin tener que recordar de memoria). Su respuesta se usa para procesar el comprobante actual y se manda al Learning Pipeline.

**Por qué Haiku.** Las tareas son acotadas (clasificación binaria, extracción a JSON, inferencia con contexto chico). No requieren razonamiento de Sonnet u Opus. Haiku es ~20x más barato que Sonnet y latencia significativamente menor.

### 3.4 Learning Pipeline — compilador asíncrono

Transforma respuestas humanas desestructuradas en reglas ejecutables. **Asíncrono** — corre después de que el comprobante ya fue procesado, sin agregar latencia al flujo principal.

Seis pasos (detalle en [`learning-pipeline.ts`](./learning-pipeline.ts)):

1. **Clasificar scope (per-client vs global).** Heurísticas primero ("este cliente", "él siempre" → per-client; "en general", "siempre que diga X" → global). Si no es concluyente, una llamada a Haiku con prompt binario (~USD 0.0003).
2. **Extraer regla.** Haiku devuelve JSON con `action_type` (de un conjunto cerrado), `action_params`, y un `confidence`. Si no mapea a ningún `action_type` conocido, se usa `custom_instruction` con texto libre. ~USD 0.0005.
3. **Compilar.** Normalizar trigger, generar hash, generar embedding, asignar metadata.
4. **Verificar conflictos.** Si existe una regla con mismo trigger y misma acción, se hace merge (incrementa `times_used`). Si existe con acción distinta, **se marca para revisión** — el sistema no auto-resuelve conflictos porque la consecuencia (transmitir instrucción incorrecta al ERP) es costosa. Conflictos global↔per-client no son conflictos: per-client siempre gana.
5. **Persistir.** INSERT en Postgres con todos los índices actualizados.
6. **Actualizar Client DNA.** Recompilar `quirks_digest` si acumuló ≥3 reglas nuevas. Una llamada a Haiku (~USD 0.001), unas pocas veces por semana por cliente.

Costo total del pipeline por aprendizaje: ~USD 0.001-0.002. A 10 aprendizajes nuevos por día (decreciente con el tiempo), USD 0.01-0.02/día. Despreciable.

---

## 4. Flujo end-to-end de un comprobante

Ver [`flow.mmd`](./flow.mmd) para el diagrama. Resumen narrativo:

**Momento 0.** Llega imagen del comprobante por WhatsApp. **(Galo existente)**

**Momento 1.** El agente actual extrae datos estructurados: monto, CBU, CUIT, banco, observación. **(Galo existente, fuera de alcance)**

**Momento 2.** Lookup del cliente por CUIT en `client_dna`. Si no existe, se crea perfil vacío con los datos del comprobante. Operación O(1).

**Momento 3.** Si la observación está vacía o es texto plano sin instrucciones (heurística: solo números, referencias a facturas), se procesa normal sin tocar el sistema de memoria. Si requiere interpretación (verbos imperativos, sustantivos de dominio, patrones numéricos ambiguos), entra al Rules Engine.

**Momento 4 — Rules Engine.** Cascada:
- Exact match (hash) filtrando por `client_cuit` → si hay, ejecutar.
- Fuzzy (pg_trgm) → si hay, ejecutar.
- Semantic (pgvector) → si hay, ejecutar.

Las tres queries priorizan `client_cuit` específico sobre `NULL` (global) con `ORDER BY client_cuit NULLS LAST`.

**Momento 5a — Inferencia con DNA** (solo si la cascada falló y el cliente tiene `quirks_digest`). Llamada a Haiku con observación + digest. Si Haiku infiere con confianza, ejecutar y mandar al Learning Pipeline.

**Momento 5b — Escalación al operador** (si todo lo anterior falló). Mensaje al operador con contexto mínimo. Respuesta del operador → procesar comprobante + Learning Pipeline.

**Momento 6 — Ejecutar acción.** Transmitir la instrucción estructurada al ERP downstream de la empresa contratante (fuera de alcance de este componente).

**Momento 7 — Actualizar stats** del Client DNA (`total_receipts++`, `last_seen`, `resolution_rate`).

**Momento 8 — Learning Pipeline (async).** Si hubo intervención de LLM o operador, compilar la regla en background. El usuario y el cliente ya recibieron respuesta — el pipeline no agrega latencia.

---

## 5. Per-client vs global: la doble dimensión

Cuando el operador explica qué significa "50/50", el sistema necesita decidir si esa explicación aplica solo a ese cliente o es universal. Clasificar mal tiene consecuencias:

- **Per-client guardada como global** → se aplica a otros clientes incorrectamente.
- **Global guardada como per-client** → el sistema "reaprende" el mismo concepto cliente por cliente, pierde eficiencia.

### Mecanismo

**Clasificación inicial** (Learning Pipeline, paso 1). Heurísticas + Haiku. Si hay dudas, **default a per-client** — el peor caso es redundancia (compilás N veces lo mismo), no error (aplicás regla de A al cliente B).

**Promoción automática a global.** Si 3+ clientes distintos tienen reglas per-client con el mismo trigger normalizado y la misma acción, se crea automáticamente una regla global. Las per-client siguen vivas como overrides; la global sirve de fallback para clientes nuevos.

**Override de global.** Si un cliente tiene observación con regla global pero el operador dice "para este es diferente", se crea regla per-client. La prioridad del Rules Engine (per-client primero) resuelve el resto.

**Degradación de global.** Si una regla global se overridea por per-client en >50% de los clientes que la usan, se marca para revisión humana. No se elimina automáticamente — puede seguir siendo útil como default para clientes nuevos.

---

## 6. Edge cases y manejo de errores

### 6.1 Cliente escribe distinto pero quiere lo mismo

Captura natural de la cascada:
- Misma frase con typo → exact (después de normalizar).
- Misma frase con variación tipográfica grande → fuzzy.
- Misma intención con palabras distintas → semantic.

Es exactamente el caso de uso para el que se diseñó la cascada.

### 6.2 Observación completamente nueva

Cliente manda "distribuir 30/40/30 entre las tres sucursales". Ninguna regla matchea, no hay patrón similar, DNA no ayuda. **Escala al operador una vez.** El operador responde, el pipeline compila la regla. Si después aparece en 3+ clientes, promueve a global. Si es un quirk del cliente, queda per-client. **Pasa una sola vez** — la segunda vez ya hay regla.

### 6.3 El operador explica con conversación contextual

> "Ah sí, llamé al cliente ayer y me dijo que a partir de ahora factura A y B en proporción 60/40."

El Learning Pipeline (paso 2) usa Haiku para extraer "factura A y B en proporción 60/40" y descartar el contexto conversacional. Por eso la extracción no es regex — el lenguaje natural del operador es impredecible.

### 6.4 Cambio de patrón del cliente en el tiempo

Cliente que durante 6 meses pidió "50/50" un día dice "ahora todo factura A". La regla per-client vieja se desactiva (soft delete con `active = false`), se crea una nueva. El `quirks_digest` se recompila.

Historial de reglas desactivadas se mantiene para auditoría. Pero no participan del matching — no consumen recursos en queries.

### 6.5 LLM API caído

Si la API de Anthropic cae, el Rules Engine sigue funcionando: ~95% de los comprobantes se resuelven con lookups determinísticos. Solo se degradan:
- Casos genuinamente nuevos (no hay regla) → se encola la pregunta al operador.
- Compilación de reglas nuevas → la queue del Learning Pipeline acumula tareas, se procesan cuando vuelve la API.

Comparado con RAG: ahí un outage del LLM detiene todo, porque cada query depende del modelo.

### 6.6 Concurrencia: dos comprobantes del mismo cliente al mismo tiempo

Update del Client DNA usa `UPDATE ... SET total_receipts = total_receipts + 1` (idempotente, sin locks). Si dos reglas se compilan en paralelo para el mismo trigger, el constraint de unicidad sobre `(client_cuit, trigger_hash)` resuelve la carrera: una gana, la otra hace merge.

---

## 7. Costos a escala

Con la asunción de **~1000 comprobantes/día** (según el contexto que tiene Galo hoy):

### Costo por comprobante según escenario

| Escenario | % a día 90 | Costo | Latencia |
|-----------|-----------|-------|----------|
| Exact match | ~70-80% | USD 0 | <1ms |
| Fuzzy match | ~10-15% | USD 0 | <5ms |
| Semantic match | ~5-8% | USD 0.0001 | ~100ms |
| LLM con DNA | ~3-5% | USD 0.003 | ~1-2s |
| Escalación humana | ~1-2% | USD 0.002 (pipeline) | Humano |

### Costo diario proyectado (1000 comprobantes/día)

| Período | % sin LLM | Costo IA/día | Horas operador evitadas/día |
|---------|-----------|--------------|------------------------------|
| Semana 1 | ~20% | ~USD 2.50 | Bajo (aprendiendo) |
| Semana 4 | ~75% | ~USD 0.70 | ~2 horas |
| Semana 8 | ~90% | ~USD 0.30 | ~3 horas |
| Semana 12 | ~95%+ | ~USD 0.15 | ~3.5 horas |

### Costo total mensual a régimen

| Componente | Costo |
|-----------|-------|
| Supabase Pro (Postgres + pgvector incluido) | USD 25 |
| Anthropic (Haiku, ~95% lookups) | USD 5-10 |
| OpenAI embeddings (~5% de comprobantes) | USD 1 |
| **Total** | **~USD 31-36/mes** |

### Escalabilidad sublineal

| Escala | Reglas en DB | Postgres | LLM/mes | Total/mes |
|--------|--------------|----------|---------|-----------|
| 100 clientes | ~500 | USD 25 | USD 6-10 | ~USD 35 |
| 1K clientes | ~5K | USD 25 | USD 15-30 | ~USD 55 |
| 10K clientes | ~50K | USD 75 | USD 30-60 | ~USD 135 |
| 100K clientes | ~500K | USD 150 | USD 50-100 | ~USD 250 |
| 1M clientes | ~5M | USD 300 | USD 80-150 | ~USD 450 |

> Pasar de 100 a 1M de clientes (10.000x) multiplica el costo por ~13x. La razón: a más clientes, más reglas, mayor cobertura de la cascada determinística, menos LLM por comprobante.

---

## 8. Escalabilidad técnica

### La tabla de reglas a escala

Con 1M de clientes y ~5 reglas promedio, `rules` tiene ~5M filas. Postgres maneja esto sin problemas con los índices apropiados:

- **B-tree sobre `(normalized_trigger_hash, client_cuit)`** → exact match en O(log n). Microsegundos.
- **GIN sobre trigramas** → fuzzy en <5ms para queries puntuales.
- **IVFFlat sobre embeddings** → semantic en <100ms con `lists` tuneado a ~sqrt(5M) ≈ 2200.

Si la tabla crece más allá de 10M filas, particionar por `client_cuit` (partitioning declarativo nativo). Cada partición indexa solo un subconjunto.

### Concurrencia

A 1 comprobante/minuto (escenario base) la concurrencia es trivial. A 100/min (100x más tráfico), Postgres lo maneja sin estrés — son lecturas mayoritariamente, con escrituras esporádicas del Learning Pipeline.

### Queue del Learning Pipeline

Asíncrono, tolera latencia. `pgboss` o una tabla con `status` + worker pollando es suficiente hasta escalas grandes. Migrable a Redis/SQS sin cambiar la lógica.

---

## 9. Por qué no es RAG

La diferencia no es cosmética. RAG y Compiled Intelligence resuelven el mismo problema con filosofías opuestas:

**RAG dice:** "Guardo todo como texto, y cada vez que necesito algo, busco lo más relevante y le pido al LLM que lo interprete." Retrieval + interpretación. El LLM es el cerebro; la DB es la memoria.

**Compiled Intelligence dice:** "Convierto todo en reglas ejecutables, y cada vez que necesito algo, ejecuto la regla directamente." Compilación + ejecución. La DB es el cerebro; el LLM es un compilador que se usa para aprender y después se apaga.

| Dimensión | RAG | Compiled Intelligence |
|-----------|-----|----------------------|
| Costo a escala | Lineal (cada query = LLM call) | Tiende a 0 (cada query = DB lookup) |
| Latencia | 500ms - 2s | 1-100ms (95% de casos) |
| Determinismo | No (LLM puede variar) | Sí (misma regla = mismo output) |
| Auditabilidad | Difícil | Total (regla trazable hasta la interacción que la creó) |
| Tolerancia a fallos | LLM down = todo down | LLM down = 95% sigue operando |
| Recompilación con cambios | No aplica (siempre re-interpreta) | Cambio de regla = recompilación explícita y trazable |

**El punto de auditabilidad importa especialmente** para Galo: la empresa contratante puede reclamar "esto se procesó mal". Compiled Intelligence puede mostrar exactamente qué regla se aplicó, cuándo se creó, de qué interacción operador-bot salió, cuántas veces se usó sin corrección, y qué confidence tenía.

---

## 10. Decisiones y trade-offs

### Por qué Postgres y no una vector DB dedicada (Pinecone, Weaviate)

Postgres con pgvector cubre **todo** lo que necesitamos: relacional + full-text + trigramas + vectores en un solo sistema. Una vector DB dedicada requeriría sincronizar dos sistemas, agrega latencia de red y complejidad operativa. Para 1M de vectores, pgvector escala perfectamente.

### Por qué Haiku y no Sonnet u Opus

Las tareas que el LLM resuelve son acotadas (clasificación binaria, extracción a JSON con schema cerrado, inferencia con contexto chico). Sonnet u Opus serían over-engineering: 20-60x más caros, latencia mayor, sin beneficio medible. Si en algún caso Haiku resulta insuficiente, se puede subir solo ese path específico.

### Por qué confidence en vez de "regla absoluta"

El operador (asumimos) responde correctamente, pero las **reglas pueden volverse obsoletas** (el cliente cambia su preferencia, el contexto cambia). Confidence permite:
- Detectar reglas inestables (mucho rebote en la confidence) → marcar para revisión.
- Distinguir reglas freshly compiled (sin track record) de reglas probadas.
- Tener un umbral para acción autónoma vs. confirmación.

### Por qué un conjunto cerrado de `action_types` (con escape hatch a `custom_instruction`)

Schema cerrado para los casos comunes (`split_invoice`, `assign_razon_social`, etc.) → validable, transmitible a un ERP sin ambigüedad, testable. Escape hatch (`custom_instruction` con texto libre) → cubrir el long tail sin bloquear el sistema cuando aparece algo nuevo.

### Por qué Mermaid para diagramas

Mermaid se renderiza nativamente en GitHub. No requiere imágenes externas que se pueden perder. Es texto, se versiona como código.

---

## Apéndice: lo que queda por definir con el equipo de Galo

1. **Catálogo final de `action_types`** — qué instrucciones estructuradas espera el ERP downstream. Definible en una sesión con el área contable.
2. **Mecanismo de feedback del operador** — proactivo ("esa regla está mal") o reactivo (solo cuando corrige una acción).
3. **Umbral de acción autónoma** — propusimos 0.75, validable según tolerancia a errores.
4. **Integración exacta con el bot actual** — ¿API, webhook, middleware? Esto define el punto de entrada del Rules Engine.
5. **Modelo de embeddings final** — text-embedding-3-small (USD 0.00002/1K, gestionado) vs. all-MiniLM-L6-v2 (self-hosted, gratis pero ops overhead).
