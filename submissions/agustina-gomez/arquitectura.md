# Arquitectura del MVP

Este documento describe el sistema de memoria que se inserta entre el agente de WhatsApp
existente (el que ya parsea imágenes y valida transferencias) y los sistemas internos a los
que alimenta. La apuesta es que el agente aprenda, una vez, qué hacer con las observaciones
ambiguas de cada cliente, y no vuelva a preguntar lo mismo.

---

## 1. El perfil del cliente

La unidad de memoria es el cliente. Cada cliente recurrente tiene un perfil con dos tipos de
memoria distintos:

**Quirks (operaciones aprendidas):** observación a acción ejecutable.
**Diccionario de entidades (resoluciones aprendidas):** mención a identificador interno.

Son tipos distintos de aprendizaje. Un quirk enseña *qué hacer*. Una entrada del diccionario
enseña *cómo se llaman las cosas en el mundo de este cliente*. Una observación real puede
requerir las dos: "transferencia de Banco del Chaco, hacer 50/50" necesita primero resolver
"Banco del Chaco" a un identificador interno, y después aplicar el split.

El perfil vive en Postgres como fuente de verdad operacional, y se proyecta a un archivo
markdown en el vault de Obsidian para lectura y auditoría humana. Forma del perfil:

```markdown
---
client_id: cliente-001
razon_social_primaria: "Distribuidora del Norte SA"
default_action: { op: assign_razon_social, params: { razon_social_id: rs-001 } }
updated_at: 2026-05-12
---

# Distribuidora del Norte SA

## Diccionario de entidades

| Mención del cliente   | Tipo      | ID interno | Confirmaciones |
|-----------------------|-----------|------------|----------------|
| "banco del chaco"     | bank      | BCH-01     | 34             |
| "el de Pilar"         | warehouse | PIL-001    | 5              |

## Quirks aprendidos

### "factura A y B" / "50/50" / "mitad mitad"
- Acción: `split_invoice(types=[A, B], ratios=[0.5, 0.5])`
- Confirmaciones: 47 aplicaciones, 0 correcciones
- Triggers conocidos: "factura a y b", "50/50", "mitad mitad", "una a y una b"

## Reglas globales que aplican a este cliente
- [[regla-global-IVA-exento]]
```

El runtime necesita queries rápidas, y parsear markdown por cada comprobante es frágil.
Postgres ejecuta, Obsidian audita.

---

## 2. La Action DSL

Una observación ambigua se traduce a un programa de operaciones tomadas de un vocabulario
fijo. El LLM elige qué operación aplicar; no inventa operaciones nuevas.

Para el MVP, el vocabulario es chico y cubre los casos observados:

| Operación              | Qué hace                                                  |
|------------------------|-----------------------------------------------------------|
| `resolve_entity`       | Mapea una mención del cliente a un ID interno             |
| `assign_razon_social`  | Asigna el comprobante a una razón social específica       |
| `partition_amount`     | Divide el monto en N partes con ratios indicados          |
| `set_invoice_type`     | Define el tipo de factura (A/B/C/E/M) para una partición  |
| `link_to_receipt`      | Asocia el comprobante con otro existente                  |
| `hold_for_review`      | Marca explícitamente para revisión humana                 |

Las operaciones se componen. "Factura A y B en 50/50" se traduce a `partition_amount` seguido
de dos `set_invoice_type` sobre cada parte.

Cada quirk lleva un campo opcional `when` con uno de tres predicados cerrados: `entity == X`
(donde X es un ID resuelto por `resolve_entity`), `amount > Y` o `amount < Y`, o
`date_in [start, end]`. Resuelve el caso típico de condicionales que aparecen en la práctica:
"50/50 normal, pero 60/40 si viene del depósito Pilar" se compila a dos quirks con el mismo
trigger, distinguidos por `when entity == depósito-pilar`. Más predicados que esos tres se
rechazan.

El vocabulario es chico y cerrado a propósito: el LLM puede equivocarse de operación o de
parámetros (ambos verificables), pero no puede inventar una que no exista. En un dominio donde
los errores se ven en facturas mal emitidas o pedidos mal ruteados, eso es lo que querés.
`resolve_entity` parece una sola primitiva pero cubre toda la superficie de normalización:
bancos, productos, depósitos, listas de precios.

---

## 3. Pipeline de resolución

Cuando llega un comprobante con observación, el sistema corre una cascada. Cada paso es más
costoso que el anterior; el sistema se detiene en el primero que resuelve.

1. **Cargar el perfil del cliente.** Una query a Postgres, sub-milisegundo. Si el cliente no
   existe, se crea un perfil mínimo desde los datos del comprobante.
2. **Resolver entidades mencionadas.** Lookup en el diccionario del cliente sobre la
   observación normalizada. Si hay menciones conocidas, se sustituyen por sus IDs internos
   antes de buscar la operación. Si una mención no está en el diccionario, no bloquea: se
   sigue con la observación tal cual y el miss se loguea.
3. **Match exacto en quirks del cliente.** Buscar la observación normalizada en los triggers
   conocidos del perfil. B-tree, sub-100ms. Si hay hit, ejecutar la acción, log, done.
4. **Match exacto en reglas globales.** Igual al paso anterior, sobre la tabla de triggers
   globales. Antes de aplicar, verificar que el cliente no tenga una excepción registrada.
5. **Match semántico.** Si el match exacto falla, lo mismo en semántico, primero el cliente y
   después globales, con pgvector y HNSW particionado por scope.
6. **LLM como último recurso.** Input: la observación, los top-K quirks del cliente filtrados
   por relevancia semántica al input (con el mismo pgvector de la cascada, scope cliente), la
   DSL con schemas y algunos ejemplos por similitud. El LLM nunca ve el perfil entero: la cota
   de tokens del prompt es dura y no depende de cuántos quirks acumuló el cliente con el
   tiempo. Output estructurado: la operación propuesta, un `confidence` y una pregunta
   clarificatoria si la confianza es baja.

Yo lo armo así: cuando el candidato sale por vía semántica o LLM, nunca se aplica solo. Se
genera una pregunta de confirmación al humano y, si confirma, el trigger nuevo se agrega al
quirk existente o se registra como quirk nuevo.

**Latencias esperadas:** sub-100ms en pasos exactos (el caso estacionario), sub-segundo en
semántico, segundos en LLM (solo aparece en miss).

---

## 4. Aprendizaje

Una sola llamada al LLM por respuesta humana, no por mensaje. La llamada recibe la observación
original, la respuesta del humano (texto libre o sí/no de un quick-reply), los top-K quirks
del cliente filtrados por relevancia al input, y la DSL con schemas. Devuelve JSON estructurado:

```json
{
  "operation": {
    "op": "split_invoice",
    "params": { "types": ["A", "B"], "ratios": [0.5, 0.5] }
  },
  "matched_quirk_id": null,
  "is_new_quirk": true,
  "alternative_phrasings": ["factura a y b", "50/50", "mitad mitad"],
  "scope_suggestion": "client" | "candidate_global",
  "confidence": 0.92
}
```

Con eso, el sistema actualiza el perfil: si la operación ya existía como quirk, agrega los
nuevos triggers; si es nueva, registra el quirk; si `scope_suggestion = "candidate_global"`,
queda anotado como candidato a promoción (revisado más adelante). Si `confidence < 0.7`, el
quirk entra como `pending_validation` y no aplica automáticamente la próxima vez sin
confirmación humana. El campo `confidence` gobierna ese pase a pendiente, no es decorativo.

---

## 5. Promoción a global

Cuando varios clientes acumulan el mismo quirk independientemente, hay señal de que la regla
debería ser global. Un job periódico identifica candidatos: misma operación canónica registrada
en cinco o más clientes distintos, con triggers que overlapean y sin correcciones recientes.

La promoción a global siempre requiere aprobación humana. Decidir que una regla aplica a todos
los clientes tiene consecuencias operativas reales: un falso positivo genera errores
silenciosos en clientes que no se quejaron pero quedaron mal procesados. El sistema propone
con evidencia, el humano aprueba, y la aprobación escribe a Postgres y regenera el vault.

---

## 6. Schema esencial

El runtime usa cuatro tablas principales: `client_quirks` y `quirk_triggers` para las
operaciones aprendidas por cliente (con `when_predicate JSONB` opcional, ver §2),
`client_entities` para el diccionario de entidades, y `global_rules` para las reglas
promocionadas. Más tablas auxiliares para triggers globales, excepciones por cliente,
embeddings con pgvector, y auditoría de aplicaciones (qué quirk corrió, qué path de
resolución, si fue corregida después).

<details>
<summary>Schema SQL e índices críticos</summary>

```sql
-- Quirks (operaciones por cliente)
client_quirks(id PK, client_id, operation JSONB, when_predicate JSONB NULL,
              status, confirmations, corrections, last_used_at)
              -- status: active | pending_validation | under_review | archived
quirk_triggers(id PK, quirk_id FK, normalized_trigger, original_trigger)

-- Entidades por cliente (diccionario de resolución)
client_entities(id PK, client_id, domain, mention_normalized, internal_id,
                confirmations, status, last_used_at)
                -- status: active | archived

-- Reglas globales
global_rules(id PK, operation JSONB, status, approved_by, approved_at)
```

**Índices críticos:** B-tree sobre `quirk_triggers(normalized_trigger)` y
`client_entities(client_id, mention_normalized)` para el caso caliente; HNSW sobre
`trigger_embeddings` con metadata-filtering por scope para el semántico (no un índice
físico por cliente, ver `decisiones.md §6`).

</details>

---

## 7. Integración con el agente existente

Dos endpoints: `resolve_observation(client_id, observation, context)` devuelve el programa DSL
y un flag de si requiere confirmación; `record_human_response(conversation_id, response)`
dispara el aprendizaje. El estado de conversación (qué respuesta corresponde a qué pregunta)
vive en el agente host, no acá. Eso mantiene el contrato simple y deja la puerta abierta para
otros canales si Galo los agrega.

---

## 8. Observabilidad

Tres métricas dicen si el sistema funciona:

- **Hit rate:** porcentaje de comprobantes resueltos en match exacto, sin LLM. Sube con el
  tiempo, objetivo 80%+ a las 12 semanas.
- **Correction rate:** porcentaje de aplicaciones automáticas corregidas después. Baja con el
  tiempo, objetivo menor al 2%. Se mide por quirk con ventana móvil y se computa solo después
  de un mínimo de aplicaciones, para no desactivar quirks recién aprendidos por una sola
  corrección. Si un quirk supera el 20% sostenido, se desactiva y se notifica al equipo.
  Importante: mientras un quirk está en `under_review` (entre la primera corrección y la
  próxima aclaración humana), los comprobantes que peguen ese quirk no disparan re-asks; caen
  a `hold_for_review` y esperan. Un cliente con alta frecuencia más un quirk en revisión
  podría bombardear al operador con 50 preguntas/día si no se hace así. Hold explícito, ping
  único por quirk pendiente.
- **Question rate per quirk:** un quirk maduro que sigue generando preguntas tiene un
  problema de normalización; un cliente maduro que sigue recibiendo preguntas tiene el perfil
  incompleto.

Más un dashboard por cliente con los quirks aprendidos y cuándo: lo que el equipo operativo de
Galo mira todos los días.

---

## 9. Cómo se mide el éxito

|           | Hit rate | Correction rate | Question rate |
|-----------|----------|-----------------|---------------|
| Mes 1     | ≥ 40%    | ≤ 5%            | ≤ 8/día       |
| Mes 3     | ≥ 70%    | ≤ 3%            | ≤ 3/día       |
| Mes 6     | ≥ 85%    | ≤ 2%            | ≤ 1/día       |

Si en mes 3 estamos por debajo del 50% de hit rate, hay que auditar los miss. O son clientes
nuevos (esperable y se resuelve con el tiempo) o son observaciones recurrentes que no se
compilaron a quirk, y ahí la normalización de triggers está fallando o el extractor no está
agarrando bien.

Si la correction rate supera 5% sostenido, el threshold de auto-apply (0.88) está bajo. Subirlo
a 0.92 y aumentar la ventana mínima de aplicaciones antes de marcar un quirk como confiable.
