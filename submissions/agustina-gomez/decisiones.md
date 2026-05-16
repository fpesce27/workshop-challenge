# Decisiones, alternativas descartadas y horizontes de evolución

Este documento acompaña a `arquitectura.md`. Acá viven las alternativas que descarté, los
lugares donde me aparto de la lectura literal del enunciado (con razón explícita), y la
evolución del sistema más allá del MVP.

---

## 1. Alternativas descartadas

### 1.1 RAG naive sobre observaciones

**Lo obvio:** embeddear cada observación, guardar en una vector DB, recuperar las más
similares y meterlas al prompt cuando llega un comprobante. Es lo que el 80% de las
submissions va a hacer.

**Por qué no:** recupera strings parecidos, no acciones verificables, y que dos observaciones
se parezcan semánticamente no garantiza que disparen la misma acción para el mismo cliente.
Mete contexto pesado al prompt en cada comprobante, los costos crecen y con el tiempo aparecen
el "context rot" y "lost in the middle". No tiene mecanismo de corrección: una memoria mala
persiste hasta que alguien la borre, y mientras tanto contamina los retrievals porque sigue
siendo similar. Y no distingue cliente de global, lo que genera errores silenciosos cuando una
memoria global no debería serlo.

### 1.2 Obsidian como fuente de verdad operacional

**La alternativa creativa:** que el vault de Obsidian sea la base de datos. Un watcher
sincroniza markdown → SQL. Suena alineado con el espíritu del workshop ("frenar en el nivel 4").

**Por qué no:** pone al componente más frágil del sistema (parser de markdown con secciones
anidadas, listas heterogéneas y frontmatter) en el path crítico de cualquier aprendizaje
persistido. Parsear markdown estructurado a SQL normalizado transaccionalmente es escribir un
mini-ORM, frágil y caro de mantener. Y si el watcher falla o queda atrás, el sistema empieza
a aplicar reglas sobre un perfil obsoleto sin saberlo.

### 1.3 Inferencia automática de scope (cliente vs global)

Sería tentador que el sistema decida solo cuándo una regla aprendida con un cliente debería
promocionarse a global: "si en N clientes apareció el mismo trigger con la misma operación,
conviértelo en global".

**Por qué no:** un falso positivo (regla global que no debía serlo) genera errores silenciosos
en clientes que no la pidieron. En dominio operativo B2B ese tipo de error es invisible al
sistema (el afectado puede no quejarse) y caro de revertir (los pedidos ya se procesaron mal).

**Lo que hacemos:** el sistema propone candidatos a global con evidencia (N clientes, triggers
consolidados, conflictos detectados), y un humano aprueba. Una decisión con esas consecuencias
necesita autoridad humana, no inferencia.

---

## 2. Contradicciones al espíritu del enunciado

Dos puntos donde me aparto de la lectura literal del enunciado, con razones.

### 2.1 "Second Brain" para el agente, no para el operador

El segundo cerebro útil acá es del agente sobre sus clientes, no del operador humano. El humano
lee y audita ese segundo cerebro en Obsidian: navega backlinks, ve la historia de aprendizajes
y correcciones, edita con fricción intencional cuando hace falta. Pero la operación corre sobre
Postgres.

### 2.2 Frenar en el nivel 4, la lectura honesta

Luciano recomendó frenar en el nivel 4 (Obsidian) salvo que el caso lo justifique. Esta
solución usa pgvector, que en su clasificación está en el nivel 5. La justificación no pasa
por la complejidad del problema sino por algo más concreto: hay dos consumidores de la
memoria con necesidades incompatibles. El humano la consume como nivel 4, con un vault de
Obsidian para navegar, auditar y editar con fricción intencional. La máquina la consume como
lookup estructurado, con B-tree y pgvector para resolver sub-100ms por comprobante. Mezclar
los dos usos en una misma capa rompe a alguno.

Agregar pgvector tampoco es "subir al nivel 5 del RAG naive". El nivel 5 de Luciano implica
chunking + embeddings de documentos con retrieval semántico general. Acá los embeddings
indexan triggers normalizados de longitud fija, sin chunking, sin retrieval de documentos
arbitrarios, y la búsqueda está particionada por cliente.

---

## 3. Bootstrap histórico (Fase -1)

El sistema no debería arrancar en frío. Si la primera semana después del go-live hace 30
preguntas por día al operador que reenvía comprobantes, ese operador apaga el sistema antes
de la semana 2.

**El bootstrap:** un job batch toma el historial de los últimos 90 días, agrupa por cliente,
y corre una pasada de LLM por cliente con ≥10 comprobantes para extraer quirks y resoluciones
de entidades. Output: perfiles pre-poblados para los 50-100 clientes que cubren el grueso del
tráfico. Esos perfiles se revisan manualmente con el equipo operativo antes de activar.

**Costo:** muy bajo (~US$1 en LLM para el mining, más horas-persona de revisión). **Impacto:**
el warm-up esperado pasa de "30 preguntas por día durante 3 semanas" a "3-5 preguntas por día
durante la primera semana". La diferencia entre que el operador siga reenviando comprobantes
la semana siguiente o que apague el sistema.

Si Galo no tiene registro estructurado de los 90 días (solo imágenes), hay un paso previo:
correr el pipeline OCR + extracción existente sobre el histórico. Suma costo y tiempo, pero
sigue siendo barato comparado con el costo de un go-live fallido.

---

## 4. Horizontes de evolución (qué hay después del MVP)

El MVP entrega la cascada, los dos tipos de memoria por cliente, el flujo de correcciones y
la promoción humana a global. Lo siguiente está identificado y fuera de scope del primer
entregable.

### 4.1 DSL en dos niveles cuando crezca

El MVP usa 6-8 operaciones planas. Cuando el dominio se expande, la arquitectura correcta es
separar la DSL en dos niveles: una decena de **primitivas** atómicas mapeables 1:1 al sistema
downstream (ingeniería + dominio), y **composiciones** declaradas en YAML versionado
(configuración, no código). El LLM en runtime arma programas combinando composiciones del
catálogo; el catálogo es lo que un ingeniero o un operador con criterio contable extiende, no
el modelo en el momento.

Cuando esa DSL evoluciona y un cambio rompe compatibilidad (por ejemplo, `partition_amount`
se divide en `partition_by_ratio` y `partition_by_fixed`), hay miles de quirks aprendidos
referenciando la operación vieja. El patrón: versionado semántico, runtime que soporta
múltiples versiones a la vez, migrador mecánico para los casos no ambiguos, cola humana para
los ambiguos, y un período de doble lectura donde cada resolución se evalúa con ambas
versiones y se loguean divergencias. Cada quirk se guarda con su `dsl_version`.

### 4.2 Operación sin git: UI delgada y políticas por blast radius

El MVP usa PR + CI para edits humanas, suficiente para ingenieros y operadores técnicos. Para
operadores que no van a aprender git hay que construir una UI delgada: panel web que lista
clientes, muestra el perfil renderizado, y permite acciones tipadas ("agregar quirk", "marcar
pending_validation como aprobado"). Detrás de escena crea un PR con el diff y la
justificación; otro operador lo revisa con un botón "aprobar" desde la misma UI. 2-3 sprints
para la versión usable.

Una vez que esa UI existe, la política de aprobación tiene que diferenciar por impacto:
cambios a reglas globales o a la DSL requieren un approver con rol `engineer`; cambios a un
quirk puntual alcanzan con dos operadores contables. Esto se fuerza por configuración
(CODEOWNERS + branch protection).

### 4.3 Más allá: qué nivel saltar y cuándo

Más allá de ~1.000.000 de quirks (probablemente año 5+), HNSW de pgvector puede no escalar
bien con tantas particiones por cliente: migración a Qdrant o Weaviate con namespaces nativos.
El shape de los datos no cambia, es una migración de runtime. **Graph RAG** podría tener
sentido si las relaciones entre entidades (cliente, razón social, banco, regla, comprobante)
se volvieran densas y centrales; hoy el perfil del cliente captura suficiente. **Agentic RAG /
multimodal** tiene sentido si Galo decide procesar audios largos o imágenes no estructuradas
más a fondo; hoy el agente parsea bien las imágenes y el audio no es parte del problema. Si
en algún momento el dominio lo justifica, la arquitectura permite incorporar esas capas sin
reescribir el sistema base.

---

## 5. Tradeoffs honestos del MVP

Los límites de esta solución, nombrados:

1. **La DSL es el bottleneck de expresividad.** Un caso que no encaja en una composición
   existente no se aprende solo: alguien tiene que extender el DSL. En B2B operativo esto es
   feature (el LLM no inventa operaciones que no existen), pero hay que decirlo.

2. **La calibración de thresholds requiere datos reales.** Los valores iniciales (0.88 para
   match vectorial, 0.75 para confidence del LLM) son conservadores. El sistema mide
   precision y correction rate por estrato de cliente y los ajusta con observabilidad.

3. **El warm-up es agresivo sin el bootstrap.** Por eso la Fase -1 no es opcional.

4. **El flujo de PR para edits humanas no es para todo el mundo.** Por eso la UI custom está
   en el roadmap inmediato, no en el horizonte lejano.

5. **El batch de promoción a global es semanal en producción madura.** Una regla que debería
   ser global puede tardar 1-2 semanas en serlo. Aceptable: el costo de duplicación
   per-cliente es bajo; el costo de una global errónea es alto.

6. **Los condicionales del MVP cubren tres formas, no más.** El `when` opcional (ver
   `arquitectura.md §2`) acepta `entity == X`, `amount > Y` o `amount < Y`, y
   `date_in [start, end]`. Cubre el caso del depósito Pilar y la mayoría de los condicionales
   que aparecen en B2B. Lo que no entra en esos tres se queda como `hold_for_review` hasta que
   alguien lo separe a mano, o requiere extender la DSL. El espacio de predicados también es
   cerrado por diseño: el LLM no inventa lógica.

---

## 6. Escalabilidad: detalle de archivado

Las tres decisiones que sostienen la promesa de escalabilidad (top-K al LLM, particionamiento
por cohorte del vector index, hold_for_review para no DDoSear al operador) están argumentadas
en la sección "Por qué cumple los 3 criterios" del README. Lo que agrego acá es el archivado,
que no aparece ahí.

**El archivado es parte del runtime, no un proyecto futuro.** A 1M de clientes con churn
natural del 20-30% anual, asumir crecimiento infinito rompe la promesa. Tres reglas: un quirk
sin uso en 6 meses y con menos de 3 confirmaciones pasa a `status: archived` y sale del index
activo, pero sigue en tabla para auditoría; una entrada del diccionario de entidades sin uso en
6 meses pasa a `archived` y la próxima aparición dispara pregunta en vez de asumir; un perfil
sin comprobantes en 12 meses pasa a inactivo, y si el cliente reaparece el siguiente
comprobante rehidrata el perfil en background antes de procesar. Nada se borra: el archivado
es reversible. El peor caso (rehidratar un perfil que tendría que haber quedado activo) cuesta
una llamada al LLM extra, no un error de procesamiento.

---

## 7. Costos modelados con hipótesis

El README dice US$5 a US$80/mes. Esa horquilla cubre los escenarios realistas. Las hipótesis
abajo, para que se vea de dónde salen los números y qué pasa fuera del rango.

| Escenario | Hit rate | Cache | LLM calls/mes | Costo aprox |
|---|---|---|---|---|
| Estado maduro (12+ semanas) | 90-95% | 80%+ | ~2-3k | US$10-25 |
| Esperado entre 4 y 12 semanas | 80-90% | 50% | ~5-8k | US$30-60 |
| Sin Fase -1, semanas 1-3 | 50-70% | 0% inicial | ~15-20k | US$150-220 |

Supuestos comunes: 43k comprobantes/mes (1 por minuto, 24/7), Sonnet con prompt caching de
Anthropic activado, embeddings ~US$3-5/mes. Cada miss puede disparar dos LLM calls (una en el
paso 6 de la cascada, otra en el extractor del aprendizaje), así que "LLM calls/mes" cuenta
ambas. La diferencia entre la segunda fila y la tercera es lo que ahorra el bootstrap
histórico: arrancar con perfiles pre-poblados saca al sistema de la zona cara desde el día uno.

El piso real con cache caliente y hit rate alto puede bajar a US$5-10/mes. El techo defendible
del rango "US$80" del README asume estado intermedio, no peor caso. Si el peor caso pasa más
de dos semanas, hay algo mal con la Fase -1 o con la cohorte de clientes que se está
incorporando, y se ve enseguida en el `hit rate` (que es una de las tres métricas que
arquitectura.md §8 vigila).
