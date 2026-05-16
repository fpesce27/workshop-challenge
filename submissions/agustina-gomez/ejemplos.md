# Ejemplos end-to-end

Tres walkthroughs concretos que muestran cómo el sistema procesa comprobantes en distintos
puntos de su madurez, más un wireframe de la UI de revisión.

---

## Caso A. Cliente nuevo: entidad + operación en una observación

**Contexto:** primer comprobante de este cliente. La observación mezcla una mención de entidad
con una instrucción operativa: el caso que muestra los dos tipos de memoria del perfil.

**Comprobante entrante:**
```
client_id: cliente-042
observation: "transferencia del Chaco, hacer 50/50"
```

**Lo que hace el sistema:**

```
[Paso 1] Cargar perfil cliente-042 → crear perfil mínimo
[Paso 2] Resolver entidades → "del chaco" no está en el diccionario del cliente
         La observación no se enriquece; se sigue con el original
[Paso 3] Match exacto en quirks del cliente → no hay match
[Paso 4-6] no hay match
[Paso 7] LLM
         Input: observación + perfil vacío + DSL
         Output: {
           operation: [
             { op: resolve_entity, domain: bank, raw: "del chaco" },
             { op: split_invoice, params: { types: [A, B], ratios: [0.5, 0.5] } }
           ],
           confidence: 0.62,
           clarifying_question: "Detecté 'del chaco' como banco no registrado para este
                                 cliente. ¿A qué cuenta corresponde? ¿Confirmo split A/B 50/50?"
         }
```

Confidence < 0.75: el bot pregunta abierto. Si hubiera sido ≥ 0.75 (operación sin entidad
desconocida), habría propuesto con quick-reply **[Sí] [No, aclarame]** en lugar de preguntar.

> **Bot:** Detecté "del chaco" como mención de banco para este cliente nuevo. ¿A qué cuenta
> corresponde? Y para el comprobante: ¿confirmo dividir en mitad factura A y mitad factura B?

**Respuesta humana:**
> Es Banco del Chaco, BCH-01. Sí, 50/50.

**Aprendizaje (1 LLM call extrae dos memorias del mismo turno):**

```json
{
  "entity": {
    "domain": "bank",
    "mention": "del chaco",
    "alternative_phrasings": ["banco del chaco", "del chaco", "chaco"],
    "internal_id": "BCH-01"
  },
  "quirk": {
    "operation": {
      "op": "split_invoice",
      "params": { "types": ["A", "B"], "ratios": [0.5, 0.5] }
    },
    "alternative_phrasings": ["50/50", "mitad mitad", "una a y una b"],
    "scope_suggestion": "candidate_global"
  },
  "confidence": 0.91
}
```

El perfil suma dos entradas: una en el diccionario de entidades, otra en quirks. La próxima
vez que llegue "del Chaco" para este cliente se resuelve a BCH-01 sin preguntar. La próxima
vez que llegue "50/50" para este cliente, se aplica sin preguntar.

Como `scope_suggestion = "candidate_global"` para el quirk de partición, se registra en
`promotion_candidates` para revisión semanal (ver Caso C).

**Costo:** 2 LLM calls Sonnet (~$0.01).

---

## Caso B. Corrección post-aplicación

**Contexto:** dos semanas después del Caso A. El sistema aplicó automáticamente split 50/50
sobre un comprobante de cliente-042, pero ese comprobante puntual debía ser 60/40 porque
incluía un pago adicional fuera de la división habitual.

El operador entra a la aplicación desde el panel de revisión y la marca como incorrecta, con
una nota:

> "Era 60/40 esta vez porque sumaron el pedido del depósito de Pilar."

El sistema dispara un LLM call para extraer la operación correcta y actualiza:

```
quirk-xyz.status = 'under_review'
rule_applications.was_corrected = true
rule_applications.correction_reason = "incluía pago de depósito Pilar, debía ser 60/40"
```

La próxima vez que llegue una observación "50/50" para este cliente, el sistema no la aplica
automáticamente: pregunta de nuevo. El operador puede confirmar (el quirk vuelve a activo) o
aclarar (el quirk se reemplaza o se extiende).

Si la tasa de corrección de este quirk supera 20% en los próximos comprobantes, se desactiva
automáticamente y se notifica al equipo.

---

## Caso C. Promoción a global

**Contexto:** un mes después del go-live. Cinco clientes distintos acumularon
independientemente quirks que se traducen a la misma operación canónica: `set_invoice_type(M)`
ante variantes de "monotributo", "soy monotributista", "fact. M", "factura M".

**Batch semanal de detección:**

```
Candidato detectado:
  operation_signature: hash(set_invoice_type{type: M})
  clientes involucrados: cliente-012, cliente-034, cliente-051, cliente-067, cliente-088
  triggers consolidados: ["monotributo", "monotributista", "fact m", "factura m"]
  conflictos detectados: ninguno
  correcciones en los últimos 14 días: 0
```

El batch genera dos cosas:

1. Un archivo en `vault/pendientes-revision/2026-06-15-promocion-monotributo.md` con la
   propuesta legible, lista de clientes, triggers consolidados, evidencia.
2. Un ítem en la UI de revisión con botones [Aprobar como global] / [Rechazar].

El operador con rol `engineer` lee el archivo en Obsidian (navegando backlinks a los cinco
perfiles de cliente para entender el contexto), vuelve a la UI y aprueba. La aprobación
inserta la regla y sus triggers en Postgres y mueve el archivo de `pendientes/` a
`reglas-globales/`. Los cinco quirks locales se marcan como `superseded_by_global` con link a
la nueva regla. No se borran: quedan como historia.

A partir de ahora, una observación "monotributo" en cualquier cliente (excepto los que tengan
excepción registrada) dispara la regla global sin tocar el LLM.

---

## Wireframe de la UI de revisión

La UI delgada que mencionamos en `decisiones.md` (Sección 4.3). Es la interfaz operativa para
los aprobadores que no usan git. El flujo de git/PR sigue existiendo por debajo, generado por
la UI.

### Detalle de un pendiente (promoción a global)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ← Volver                                                                    │
│                                                                              │
│  Promoción a global: set_invoice_type(M)                                     │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                              │
│  Operación canónica propuesta:                                               │
│    set_invoice_type(type: M)                                                 │
│                                                                              │
│  Triggers consolidados:                                                      │
│    • "monotributo"      (visto en 4 clientes)                                │
│    • "monotributista"   (visto en 3 clientes)                                │
│    • "fact m"           (visto en 2 clientes)                                │
│    • "factura m"        (visto en 5 clientes)                                │
│                                                                              │
│  Clientes involucrados:                                                      │
│    • cliente-012 (Distribuidora Tucumán)        ver perfil ↗                 │
│    • cliente-034 (Mayorista Sur)                ver perfil ↗                 │
│    • cliente-051 (Almacenes del Litoral)        ver perfil ↗                 │
│    • cliente-067 (Importadora Patagonia)        ver perfil ↗                 │
│    • cliente-088 (Distribuidora Norte)          ver perfil ↗                 │
│                                                                              │
│  Conflictos detectados: ninguno                                              │
│  Correcciones en los últimos 14 días: 0                                      │
│                                                                              │
│  ─────────────────────────────────────────────────────────────────────────  │
│  Justificación (opcional):                                                   │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ Patrón consistente entre 5 clientes monotributistas. Sin ambigüedad. │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  Esta acción requiere: ✓ engineer    ☐ contable-lead (esperando)             │
│                                                                              │
│              [ Aprobar como global ]    [ Rechazar ]    [ Cancelar ]         │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

Notas sobre la UI:
- Cuando el operador aprueba, la UI escribe a Postgres directamente (no a Obsidian); el job
  de regeneración actualiza el vault después.
- "Esta acción requiere" se calcula desde la configuración de blast radius (ver
  `decisiones.md` Sección 4.4). Si el aprobador no tiene el rol necesario, el botón aparece
  deshabilitado con la razón visible.
- Cada perfil de cliente tiene un link al markdown en Obsidian para revisión contextual.
  La idea: leer contexto en Obsidian, ejecutar acciones desde la UI.
