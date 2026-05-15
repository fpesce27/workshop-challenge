# PLAN DE PROYECTO — Second Brain Challenge (Galo)

> Documento de trabajo para Claude Code.
> Leelo entero antes de tocar una sola línea de código.
> Ejecutá las fases en orden. No salgas de una fase hasta que cumplas el criterio de "hecho".
> Al final de cada fase: commit semántico siguiendo el formato definido en la Fase 0.

---

## 0. Contexto y filosofía del proyecto

### El problema (resumen ejecutivo)

Galo (https://soygalo.com) tiene un agente de WhatsApp que procesa comprobantes de transferencia bancaria de clientes B2B del rubro alimentos. El agente ya extrae datos de la imagen y los valida. El problema **NO** es ese.

El problema es el **campo de observaciones del comprobante**, donde aparecen instrucciones ambiguas o idiosincráticas:

- `"armar factura A y B"`
- `"hacer 50/50"`
- `"facturar a Distribuidora Sur si > 500k, si no a Sur Logística"`
- múltiples razones sociales en la misma nota

Estas peculiaridades tienen **doble dimensión**:

- **Por cliente**: el cliente X siempre factura mitad A / mitad B; el cliente Y elige razón social según monto.
- **Globales**: hay conceptos que el agente no entendía y que, una vez aclarados, aplican a varios clientes.

La primera vez que el agente ve algo raro, **pregunta**. Cuando el usuario responde, el agente debe:

1. Usar esa respuesta para procesar **ese** comprobante.
2. **Aprender** de la respuesta.
3. La próxima vez que llegue la misma observación (o equivalente), **no volver a preguntar**.

### Restricciones operativas

- **Tráfico**: 1 comprobante/minuto sostenido, con picos de concurrencia (ej: lunes a la mañana entran 100 en una hora).
- **Escala**: pensar en 30, 60, 90 días. Decenas de miles a millones de memorias acumuladas.
- **Contexto del agente**: limitado. No se pueden inyectar todas las memorias siempre.
- **Costos**: una solución "tres Claude Opus en paralelo por mensaje" funciona pero funde la cuenta.

### Criterios de evaluación del challenge

1. **Realismo**: ¿se lleva a producción sin fundirse? Costos, latencia, infra.
2. **Creatividad**: la solución obvia (vector DB + inyección al prompt) es aburrida. Buscan ideas no convencionales.
3. **Escalabilidad**: ¿sigue funcionando con 1k, 100k, 1M memorias? ¿Cómo decidís qué traer?

### La filosofía de esta propuesta

> **El agente tiene un sistema nervioso. El humano tiene un cerebro. No son el mismo órgano.**

La mayoría de las propuestas van a ser una de dos cosas:

- **(A) Vector DB + RAG + prompt injection**: la solución obvia que el README explícitamente vetó.
- **(B) "Uso Obsidian para todo"**: ingenua, no escala, Obsidian no es una base de datos concurrente.

**Esta propuesta es distinta**: separa el **hot path determinístico** (donde el agente decide en milisegundos sin tocar un LLM) del **human loop reflexivo** (donde un operador humano cura y enseña, usando Obsidian y Claude Code como su "second brain").

Hay además tres piezas que diferencian esta propuesta y que **deben estar explícitas en la implementación y el documento final**:

1. **Reglas como mini-programas ejecutables**, no como texto que se inyecta al prompt.
2. **Promoción automática cliente → global** cuando una regla idiosincrática aparece en N clientes distintos.
3. **Memoria negativa / contra-aprendizaje**: el sistema sabe explícitamente *qué reglas ya no aplican* y por qué. Esto es lo que la mayoría va a olvidar.

---

## Stack obligatorio

- **Python 3.11+**
- **FastAPI** (API HTTP)
- **Pydantic v2** (modelos)
- **SQLite** (almacenamiento principal, con WAL mode habilitado para concurrencia)
- **Anthropic SDK** (`anthropic`) con **Claude Haiku** (`claude-haiku-4-5-20251001`) para compilación de reglas y embedding semántico ligero. No usar Opus ni Sonnet acá: la compilación es una tarea estructurada barata.
- **uv** para gestión del proyecto y dependencias (Pablo ya lo usa).
- **pytest** para los tests de la lógica del motor de reglas.

**No incluir**: vector DB, Redis, Postgres, Docker, Ollama, modelos locales. Si te tienta agregar algo de eso, parate y volvé a leer este documento.

---

## Estructura final esperada del repo

```
second-brain-galo/
├── README.md                      ← Documento principal del PR
├── ARCHITECTURE.md                ← Documento de arquitectura con diagramas Mermaid
├── PR_DESCRIPTION.md              ← Texto del PR listo para pegar
├── pyproject.toml                 ← uv project file
├── .gitignore
├── src/
│   └── second_brain/
│       ├── __init__.py
│       ├── main.py                ← FastAPI app
│       ├── models.py              ← Pydantic models (Rule, Observation, etc.)
│       ├── engine.py              ← Motor de reglas (lookup hot path)
│       ├── normalizer.py          ← Normalización + SimHash de observaciones
│       ├── compiler.py            ← Compilación asíncrona de respuestas → reglas
│       ├── promoter.py            ← Promoción cliente → global
│       ├── invalidator.py         ← Memoria negativa / contra-aprendizaje
│       ├── obsidian_writer.py     ← Escritura del vault Markdown
│       └── db.py                  ← Setup de SQLite + migraciones
├── tests/
│   ├── test_engine.py
│   ├── test_normalizer.py
│   ├── test_compiler.py
│   └── test_promotion.py
├── obsidian_vault/                ← Vault de ejemplo (committeado, con notas reales)
│   ├── _index.md
│   ├── clientes/
│   │   └── 138_distribuidora-sur.md
│   ├── globales/
│   │   └── armar-factura-a-y-b.md
│   └── pendientes-revision/
│       └── ejemplo-quirk-nuevo.md
└── scripts/
    ├── seed_demo.py               ← Pobla la DB con un escenario de demo
    └── simulate_traffic.py        ← Simula 100 comprobantes para mostrar el sistema
```

---

## Convenciones de commits

Formato: `tipo(scope): descripción corta en inglés`

Tipos permitidos: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`.

Al final de cada fase, hacé **un commit con el resumen de esa fase** (no commits sueltos por archivo). Ejemplo: `feat(engine): implement rule lookup with SimHash matching`.

Después de la Fase 6 (PR), hacé `git log --oneline` y pegalo en el output final para que Pablo lo revise.

---

# FASE 1 — Scaffold y modelos

**Objetivo**: tener el proyecto inicializado, el esquema de datos definido, y SQLite configurada con WAL.

## Tareas

1. Inicializar el proyecto con `uv init` y agregar dependencias: `fastapi`, `uvicorn[standard]`, `pydantic`, `anthropic`, `pytest`, `pyyaml`.
2. Crear la estructura de carpetas completa según el esquema de arriba (vacías o con `__init__.py` donde corresponda).
3. Definir en `models.py` los Pydantic models:
   - `Rule`: representa una regla compilada. Campos: `id` (UUID), `scope` (Literal["client", "global"]), `client_id` (Optional[str]), `pattern_canonical` (str, la observación normalizada), `pattern_simhash` (int 64-bit), `action` (dict, el "mini-programa" ejecutable), `confidence` (float), `hit_count` (int), `created_at`, `last_used_at`, `last_modified_at`, `status` (Literal["active", "shadow", "deprecated", "archived"]).
   - `Observation`: input crudo. Campos: `client_id` (str), `text` (str), `comprobante_id` (str), `timestamp`.
   - `RuleMatch`: resultado de una búsqueda. Campos: `rule` (Optional[Rule]), `match_type` (Literal["exact", "simhash", "semantic", "none"]), `match_score` (float).
   - `CompilationRequest`: para el job async. Campos: `observation` (Observation), `user_response` (str), `original_rule_id` (Optional[str], si era una corrección).
4. En `db.py`, crear el esquema SQLite con:
   - Tabla `rules` con índices en `(scope, client_id)`, `pattern_simhash`, `status`, `last_used_at`.
   - Tabla `compilation_queue` (cola persistente para los jobs async).
   - Tabla `invalidations` (historial de reglas que se desactivaron y por qué — esto es central para la memoria negativa).
   - Habilitar `PRAGMA journal_mode=WAL` y `PRAGMA synchronous=NORMAL`.
   - Función `init_db()` que crea todo si no existe.

## Criterio de "hecho"

- `uv run python -c "from second_brain.db import init_db; init_db()"` corre sin errores y crea `second_brain.db`.
- `uv run pytest` corre (puede no haber tests aún, pero el comando no debe fallar).
- Commit: `feat(scaffold): initialize project structure and data models`.

---

# FASE 2 — Normalizador y motor de reglas (hot path)

**Objetivo**: que dada una observación, el sistema responda en `< 5ms` si hay una regla aplicable. Sin LLMs, sin red, sin nada lento.

## Tareas

1. En `normalizer.py`:
   - Función `normalize(text: str) -> str`: lowercase, sacar acentos, colapsar espacios, sacar puntuación no semántica, sinónimos hardcodeados básicos (`mitad` → `50/50`, `partir` → `split`, `dividir` → `split`).
   - Función `simhash(text_normalized: str) -> int`: SimHash de 64 bits sobre n-gramas de palabras (n=2). Implementación propia, sin libs externas (es ~30 líneas).
   - Función `hamming_distance(a: int, b: int) -> int`: para comparar SimHashes.

2. En `engine.py`, función central `lookup(client_id: str, observation_text: str) -> RuleMatch`:
   - **Paso 1 (exact match)**: normalizar la observación, buscar en `rules` por `(scope='client' AND client_id=X AND pattern_canonical=norm)` OR `(scope='global' AND pattern_canonical=norm)`. Si hay match, retornar `RuleMatch(rule=..., match_type='exact', match_score=1.0)`.
   - **Paso 2 (SimHash match)**: calcular SimHash de la observación. Buscar reglas con SimHash a distancia de Hamming ≤ 3 (umbral inicial; parametrizable). Priorizar scope cliente sobre global. Si hay match, retornar con `match_type='simhash'`.
   - **Paso 3 (no match)**: retornar `RuleMatch(rule=None, match_type='none', match_score=0.0)`.
   - **Importante**: las reglas con `status != 'active'` se ignoran en el lookup. Las `shadow` se loguean pero no se ejecutan (para A/B testing de reglas nuevas).

3. Cuando hay un hit, **incrementar `hit_count` y actualizar `last_used_at`** de forma async (no bloqueante: usar un buffer en memoria que se flushea cada N segundos o cada M hits). Esto evita un write por cada request.

## Criterio de "hecho"

- Tests en `test_normalizer.py` que verifican: `normalize("50/50") == normalize("Hacer 50/50")` (después de quitar el verbo), `simhash("armar factura a y b") ≈ simhash("hacer factura A y B")` (distancia Hamming pequeña).
- Tests en `test_engine.py` que verifican los 3 casos de lookup con una DB de prueba.
- Benchmark: `lookup` sobre una DB con 10.000 reglas tarda `< 5ms` p99. Incluir el benchmark como test (`test_engine_perf.py`).
- Commit: `feat(engine): implement hot-path rule lookup with normalizer and simhash`.

---

# FASE 3 — Compilador asíncrono (cold path)

**Objetivo**: cuando el agente pregunta y el usuario responde, compilar esa respuesta a una regla ejecutable usando Claude Haiku, e insertarla en SQLite.

## Tareas

1. En `compiler.py`:
   - Función `compile_rule(observation: Observation, user_response: str) -> Rule`:
     - Llama a Claude Haiku con un system prompt que define el formato de "regla ejecutable" (un JSON con `action_type` enum + parámetros).
     - El system prompt debe incluir 3-4 few-shot examples con casos reales del dominio Galo (facturas A/B, split de razones sociales, condicionales por monto).
     - Retorna un `Rule` con `status='shadow'` por default (las reglas nuevas no se activan hasta que pasan validación).
   - Función `enqueue_compilation(req: CompilationRequest)`: inserta en `compilation_queue` con `status='pending'`.
   - Worker `process_compilation_queue()`: corre en background (asyncio task o thread), procesa la cola FIFO.

2. **Auto-promoción shadow → active**: una regla `shadow` se promueve a `active` cuando:
   - Llega un comprobante con la misma observación.
   - El usuario humano confirma con un "sí, hacé eso" (el agente puede preguntar "la última vez me dijiste X, ¿procedo igual?").
   - Después de 3 confirmaciones consecutivas, pasa a `active` sin preguntar.
   - Esto es importante para mostrar: el sistema **no aprende a ciegas**, valida.

3. El `action` JSON debe seguir un schema estricto. Definí en `models.py` un `Action` union type con al menos estos casos:
   - `SplitInvoiceAction(type_a_pct: int, type_b_pct: int)`
   - `MultiTaxIDAction(default_cuit: str, conditions: list[Condition])` donde `Condition` puede ser por monto, fecha, etc.
   - `LiteralInstructionAction(natural_language: str)` — fallback para casos que no se pudieron estructurar; estos son los que más necesitan revisión humana.

## Criterio de "hecho"

- Test en `test_compiler.py`: dado un mock de respuesta de Anthropic, `compile_rule` retorna un `Rule` válido con el `action` parseado correctamente.
- Test de integración: enqueue + process retira un job de la cola y deja una regla `shadow` en `rules`.
- Manejo de errores: si Anthropic falla, el job vuelve a la cola con `retry_count` incrementado. Después de 3 retries, queda en `status='failed'` y se escribe una nota en `pendientes-revision/`.
- Commit: `feat(compiler): implement async rule compilation with Claude Haiku and shadow-to-active validation`.

---

# FASE 4 — Promoción cliente → global y memoria negativa

**Objetivo**: implementar las dos piezas creativas que diferencian la propuesta. Esta fase es la que va a ganar el challenge si está bien hecha.

## Tareas

1. **Promotor (`promoter.py`)**:
   - Función `evaluate_promotion(rule: Rule) -> Optional[Rule]`: si una regla de scope `client` tiene reglas "hermanas" (mismo `pattern_canonical` o SimHash cercano) en N≥5 clientes distintos, propone una regla global derivada.
   - La propuesta no se aplica automáticamente: crea una regla global con `status='shadow'` y escribe una nota en `pendientes-revision/promociones/` con el detalle (qué clientes la tienen, ejemplos de uso, recomendación).
   - El operador humano abre Obsidian, lee, y aprueba (cambia un campo `approved: true` en el frontmatter de la nota; un watcher lo detecta y promueve a `active` global).
   - Correr `evaluate_promotion` por lote, no por mensaje: una vez por hora vía un job programado.

2. **Invalidador (`invalidator.py`) — esta es la pieza más original**:
   - Cuando el agente ejecuta una regla `active` y el usuario corrige ("no, esta vez es 70/30, no 50/50"), eso es una **señal de invalidación**.
   - Función `register_invalidation(rule_id: str, observation: Observation, user_correction: str)`:
     - Inserta en `invalidations` con la razón.
     - Si la regla recibe ≥3 invalidaciones en una ventana de 7 días, su `status` pasa a `deprecated` y se compila una nueva regla con la información corregida.
     - **La regla vieja NO se borra**: queda con `status='deprecated'` para auditoría. Esto es lo que la mayoría de los participantes va a omitir.
   - Las invalidaciones también disparan una nota en Obsidian (`pendientes-revision/invalidaciones/`) para que el humano vea que algo cambió en el comportamiento del cliente.

## Criterio de "hecho"

- Test en `test_promotion.py`: seedear 5 clientes con la misma regla "split 50/50", correr el promoter, verificar que se creó la regla global shadow.
- Test de invalidación: registrar 3 invalidaciones, verificar que la regla pasa a `deprecated` y que hay una nueva regla compilada.
- Test de "no falsos positivos": una regla con 4 clientes (no 5) no se promueve.
- Commit: `feat(memory): implement client-to-global promotion and negative-memory invalidation`.

---

# FASE 5 — Capa Obsidian (Human Loop)

**Objetivo**: que el operador humano pueda ver, auditar y corregir lo que el agente aprende, usando Obsidian + Claude Code como su "second brain".

## Tareas

1. En `obsidian_writer.py`:
   - Función `write_rule_note(rule: Rule, observation: Observation, user_response: str)`:
     - Decide la carpeta destino según `rule.scope` y `rule.status`:
       - `clientes/{client_id}_{slug}.md` para reglas de cliente activas.
       - `globales/{slug}.md` para reglas globales activas.
       - `pendientes-revision/{slug}-{rule_id}.md` para shadow, failed, invalidaciones.
     - Escribe Markdown con frontmatter YAML que incluye **todos** los campos relevantes: `rule_id`, `scope`, `client_id`, `status`, `hit_count`, `confidence`, `created_at`, `last_used_at`, `simhash`, `action` (JSON), y un tag `#pendiente-revision` cuando aplica.
     - El cuerpo de la nota es legible: observación original, respuesta del usuario, regla compilada explicada en lenguaje natural, ejemplos de cuándo se aplica.

2. **Watcher de cambios en el vault** (`obsidian_writer.py` también):
   - Función `watch_vault(vault_path: Path)`: usa polling cada 30s sobre los `mtime` de los archivos (no usar inotify para simplicidad y portabilidad).
   - Cuando detecta que una nota cambió:
     - Parsea el frontmatter.
     - Si `approved: true` apareció, promueve la regla `shadow` → `active`.
     - Si el campo `action` fue editado a mano, valida que sea JSON parseable y actualiza la regla en SQLite.
     - Si el `scope` cambió (ej: el humano movió la nota de `clientes/` a `globales/`), actualiza la regla.
   - **Loggear cada cambio**: el humano debe poder ver "esto se cambió porque vos editaste el archivo X a las HH:MM".

3. **Slash commands sugeridos para Claude Code** (documentarlos en el README, no hace falta implementarlos como código — son comandos para que Pablo use Claude Code dentro del vault):
   - `/auditar-cliente {client_id}`: Claude lee todas las notas del cliente, detecta contradicciones, propone consolidaciones.
   - `/proponer-global {nota.md}`: Claude evalúa si una regla específica debería ser global y arma el PR de promoción.
   - `/detectar-drift {client_id}`: Claude compara reglas viejas vs comportamiento reciente del cliente y alerta de cambios.

## Criterio de "hecho"

- Una regla compilada genera una nota Markdown válida (parsea sin errores con `yaml.safe_load` sobre el frontmatter).
- Editar manualmente una nota y poner `approved: true` hace que la regla pase a `active` (test de integración con el watcher en mock).
- El vault de ejemplo (`obsidian_vault/`) tiene **al menos 6 notas reales** mostrando distintos casos: una regla activa de cliente, una activa global, una shadow esperando aprobación, una deprecated post-invalidación, una propuesta de promoción, y un quirk failed que necesita revisión humana.
- Commit: `feat(obsidian): implement human-loop vault writer and watcher`.

---

# FASE 6 — API, demo y entregables del PR

**Objetivo**: tener una API que funcione, un script de demo que muestre el sistema en acción, y todos los documentos del PR listos.

## Tareas

1. En `main.py`, exponer endpoints FastAPI:
   - `POST /observations`: recibe `{client_id, text, comprobante_id}`. Devuelve `{action: "execute", rule_id: "...", action_details: {...}}` si hay regla, o `{action: "ask", question: "¿Qué significa X?"}` si no.
   - `POST /observations/{observation_id}/response`: recibe la respuesta del usuario. Encola la compilación y devuelve `{status: "learning", will_apply_next_time: true}`.
   - `POST /observations/{observation_id}/invalidate`: marca una ejecución como incorrecta y dispara el flujo de invalidación.
   - `GET /rules`: lista paginada de reglas, con filtros por scope, client_id, status.
   - `GET /stats`: estadísticas del sistema (total de reglas, hit rate, % de preguntas por día, top 10 clientes por reglas).

2. `scripts/seed_demo.py`: pobla la DB con un escenario realista:
   - 10 clientes simulados.
   - 30 reglas pre-existentes (mix de globales y por cliente).
   - 5 invalidaciones históricas.
   - El vault de Obsidian queda con notas reales correspondientes.

3. `scripts/simulate_traffic.py`: simula 100 comprobantes entrando al sistema, mostrando en consola:
   - Cuántos matchearon exact, cuántos simhash, cuántos preguntaron.
   - Latencia p50, p95, p99 del lookup.
   - Estado final de la DB y el vault.

4. Documentos finales:

   - **`README.md`**: explica qué es esto, cómo se corre (`uv sync && uv run python scripts/seed_demo.py && uv run uvicorn second_brain.main:app`), y los slash commands de Claude Code para usar el vault.

   - **`ARCHITECTURE.md`**: documento principal de la propuesta. Debe incluir:
     - Resumen ejecutivo (3 párrafos).
     - **Diagrama Mermaid de arquitectura** mostrando: comprobante entrante → engine lookup (hot path, <5ms) → bifurcación ejecutar/preguntar → loop async de compilación → escritura SQLite + Obsidian → human loop separado. Indicar tiempos en cada arista.
     - **Diagrama Mermaid de decisión** del agente al recibir una observación (flowchart).
     - **Pseudocódigo** de `procesar_observacion(client_id, observacion)` mostrando lookup → ejecución o pregunta → enqueue async.
     - **Ejemplo de nota Obsidian** generada para "armar factura A y B" del cliente 138, con frontmatter completo.
     - **Tabla de benchmark teórico** comparando: solución obvia (Vector DB + prompt injection) vs esta propuesta. Filas: latencia lectura, costo por mensaje, escalabilidad a 1M, curación humana, alineación con workshop.
     - **Sección "¿Qué pasa a los 90 días?"** describiendo el comportamiento con 50k+ reglas (hit rate esperado, % de tráfico que evita el LLM, costo proyectado, tamaño del vault).
     - **Sección "Trade-offs honestos"**: dónde esta arquitectura podría fallar (ej: si los quirks son extremadamente verbosos, el SimHash pierde precisión; si los clientes cambian de criterio muy seguido, la memoria negativa genera ruido).

   - **`PR_DESCRIPTION.md`**: 3-4 párrafos pensados como descripción del Pull Request. Debe:
     - Resumir la idea en una línea ("El agente tiene un sistema nervioso, el humano tiene un cerebro").
     - Explicar la separación hot path / human loop.
     - Justificar contra los 3 pilares (realismo, creatividad, escalabilidad) con números concretos del benchmark.
     - Cerrar con una invitación a revisar el vault de Obsidian incluido en el repo como demostración del human loop.

## Criterio de "hecho"

- `uv run uvicorn second_brain.main:app` levanta la API y los endpoints responden.
- `uv run python scripts/simulate_traffic.py` corre end-to-end y muestra estadísticas.
- Los tres documentos (`README.md`, `ARCHITECTURE.md`, `PR_DESCRIPTION.md`) están completos, sin TODOs ni placeholders.
- Los diagramas Mermaid renderizan correctamente (probalos en https://mermaid.live antes de cerrar la fase).
- `git log --oneline` muestra commits limpios, uno por fase.
- Commit final: `docs(pr): finalize README, architecture document, and PR description`.

---

# Fase 7 — Auto-revisión final (NO SALTEAR)

Antes de declarar terminado, Claude Code debe correr esta checklist y reportar cada punto:

1. ¿La propuesta diferencia claramente "lo que va al hot path" de "lo que va al human loop"? Si un evaluador lee 30 segundos del README, ¿le queda claro?
2. ¿Las tres piezas creativas (reglas como mini-programas, promoción automática, memoria negativa) están **explícitas** en el documento de arquitectura, con su propio subtítulo?
3. ¿Los números del benchmark son defendibles? Por ejemplo: si decís "latencia <5ms", ¿el test lo demuestra?
4. ¿La sección de trade-offs honestos existe? El jurado valora la honestidad técnica.
5. ¿El vault de Obsidian tiene notas reales que un humano podría leer y entender, o son placeholders genéricos?
6. ¿El stack se mantuvo dentro de lo permitido (FastAPI + Pydantic + SQLite + Anthropic SDK + uv + pytest)? Si agregaste algo más, justificalo o sacalo.
7. ¿Hay algún componente que en realidad no aporta y solo agrega complejidad? Si lo hay, sacalo. La elegancia de la propuesta es parte de la creatividad.

Si algún punto falla, **volvé a la fase correspondiente y arreglalo antes de cerrar**.

Reportá el resultado de cada punto al final.

---

## Notas finales para Claude Code

- **Pablo escribe los comentarios del código en español** y los nombres de funciones/variables en inglés. Mantené esa convención.
- **Los commits van en inglés**.
- **Los documentos (README, ARCHITECTURE, PR_DESCRIPTION) van en español rioplatense informal** (tuteo, no "ustedeo"). Pablo es argentino y los evaluadores también.
- Si en algún punto tenés dudas reales (no aparentes — duda genuina sobre el diseño), **parate y preguntá** antes de seguir. No inventes.
- Cuando termines todo, dejame `git log --oneline` y un resumen de cuántas líneas de código, tests y documentación produjiste.
