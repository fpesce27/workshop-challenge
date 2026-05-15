# 🧠 Cerebro Agéntico

> *"La primera vez pregunta. La segunda vez duda. La tercera vez anticipa."*

**Propuesta para el Second Brain Workshop Challenge · Auspiciado por [Galo](https://soygalo.com) + Obsidian**

---

## El problema en una línea

El agente sabe procesar comprobantes. Lo que no sabe es qué significa lo que le escriben — y cuando no sabe, pregunta. Siempre lo mismo. A la misma persona.

```
Usuario: [comprobante] obs: "armar factura A y B"
Agente:  ¿Qué significa "armar factura A y B"?
Usuario: significa emitir una A por el 50% y una B por el resto
--- lunes siguiente ---
Usuario: [comprobante] obs: "armar factura A y B"
Agente:  ¿Qué significa "armar factura A y B"?   ← nunca aprendió
```

---

## La solución: tres capas de memoria

No proponemos un agente nuevo. Proponemos una **capa de memoria externa** que el agente existente no sabe que existe — solo recibe contexto enriquecido antes de procesar cada mensaje.

```
Comprobante entra
      ↓
[ÍNDICE RAM] → consulta en microsegundos
      ↓ hit/miss
[PRE-INYECTOR] → inyecta contexto al agente
      ↓
[AGENTE EXISTENTE] → responde sin preguntar
      ↓
[CONSOLIDADOR] → aprende de cada interacción
      ↓
[OBSIDIAN] → fuente de verdad auditable
      ↓ (cron nocturno)
[EL SUEÑO] → comprime + promueve + descubre
```

---

## Arquitectura

Ver [`docs/arquitectura.md`](docs/arquitectura.md) para la explicación completa.

Ver [`diagrams/`](diagrams/) para los diagramas de flujo y stack.

---

## Las tres preguntas del challenge

### 1. Extracción — ¿Cómo extraés insights útiles?

Cuando el agente pregunta y el usuario responde, el **Consolidador** evalúa:

**¿Es memoria global o por cliente?**

| Tipo | Descripción | Dónde se guarda |
|---|---|---|
| **Global** | Aplica a cualquier cliente | `/global/conceptos/` |
| **Por cliente** | Quirk específico de uno | `/clientes/{id}/quirks.md` |

El LLM evalúa la respuesta y decide. Si hay ambigüedad, guarda en ambos con score de confianza bajo y el Sueño lo resuelve con más contexto.

Ver [`examples/extraccion.md`](examples/extraccion.md) para casos concretos.

---

### 2. Almacenamiento — ¿Dónde y cómo lo guardás?

Tres capas con roles distintos:

#### Capa 1 — Índice Rápido (RAM)
- SQLite en memoria o JSON estructurado
- Consulta en **microsegundos** por cada mensaje entrante
- Contiene punteros a memorias relevantes, no las memorias completas
- Se reconstruye desde Obsidian al iniciar el sistema
- **Resuelve la concurrencia** de 1 mensaje/minuto sin fricción

#### Capa 2 — Obsidian (fuente de verdad)
```
/global/
  conceptos/        ← términos aprendidos para todos los clientes
  patrones/         ← comportamientos generales

/clientes/
  {id_cliente}/
    quirks.md       ← peculiaridades específicas
    historial.md    ← resumen comprimido de interacciones

/insights/
  eurekas/          ← patrones cruzados descubiertos por el Sueño
```

Formato de cada memoria:
```yaml
---
tipo: global | cliente
scope: {id_cliente} | todos
concepto: factura_a_y_b
confianza: 0.95
visto: 14
ultima_vez: 2026-05-14
accion: "emitir factura A por 50% y B por el resto"
---
```

El **grafo de links de Obsidian** conecta conceptos globales con los clientes que los usan — como neuronas. Esto permite al Sueño detectar cuándo un quirk de un cliente es en realidad un patrón global.

#### Capa 3 — El Sueño (background)
Cron nocturno. Tres tareas:
1. **Comprimir** — 50 memorias de lo mismo → 1 memoria con confianza alta
2. **Promover** — Si 10 clientes tienen el mismo quirk → es global
3. **Descubrir** — Cruza patrones, genera Eurekas

Ver [`examples/almacenamiento.md`](examples/almacenamiento.md) para estructura completa.

---

### 3. Recuperación — ¿Cómo traés la memoria en el momento justo?

El Pre-inyector tiene tres pasos en orden de costo:

```
Paso 1: Consulta el Índice RAM
→ ¿Hay memoria para este cliente + esta observación?
→ Hit → inyecta y listo. Costo: microsegundos.

Paso 2: Si miss → busca en /global/ por FTS
→ ¿La observación matchea algo aprendido?
→ Costo: bajo, solo sobre memorias globales consolidadas.

Paso 3: Si nada → el agente pregunta
→ La respuesta entra al Consolidador
→ El ciclo continúa.
```

**¿Qué se inyecta exactamente?**

No todo. Solo lo relevante para el comprobante que llegó.

```
Comprobante con obs: "armar factura A y B"

Pre-inyector inyecta:
→ [global] "factura A y B = 50% cada tipo"
→ [cliente] "López: siempre A por el monto mayor"
→ [instrucción] "no preguntes, procesá directamente"

Tokens inyectados:   ~80
Tokens de repregunta: ~300
Ahorro:              ~73%
```

Ver [`examples/recuperacion.md`](examples/recuperacion.md) para flujos completos.

---

## Cómo escala

| Volumen | Comportamiento |
|---|---|
| 0 – 1.000 | Índice RAM + Obsidian. Sin fricción. |
| 1.000 – 100.000 | Sueño comprime activamente. Índice liviano. |
| 100.000 – 1M | Memorias por cluster de clientes. Solo carga el relevante. |
| 1M+ | Mayoría resuelve con memoria global. **Costo baja con el tiempo, no sube.** |

El costo no crece lineal porque el Sueño convierte muchas memorias específicas en pocas memorias generales.

---

## Stack técnico

| Componente | Tecnología |
|---|---|
| Canal | WhatsApp Business API |
| Índice rápido | SQLite en RAM / JSON en memoria |
| Fuente de verdad | Obsidian + Local REST API |
| Formato de memoria | Markdown + Frontmatter YAML |
| Búsqueda | FTS sobre Obsidian |
| Orquestación | Python |
| LLM | API genérica — Claude / GPT-4o / Gemini |
| Sueño | Cron job nocturno |

Ver [`docs/stack.md`](docs/stack.md) para decisiones de diseño.

---

## Evaluación contra los tres pilares

### ✅ Realismo
- El agente existente **no se modifica**
- El LLM solo se invoca cuando hay ambigüedad real — no por cada mensaje
- El Índice RAM resuelve concurrencia sin latencia
- El Sueño corre fuera de horario pico — **0 costo en tiempo real**
- Stack simple: Python + SQLite + Obsidian + cualquier LLM barato

### ✅ Creatividad
- Obsidian como red neuronal auditable — el grafo de links es la memoria viva
- Distinción global/cliente resuelta semánticamente, no con reglas hardcodeadas
- El Sueño inspirado en cómo el cerebro consolida memoria durante el descanso
- Índice RAM como capa de velocidad separada de la persistencia

### ✅ Escalabilidad
- Tres capas con roles distintos evitan cuellos de botella únicos
- Promoción de memorias cliente → global aplana el sistema con el tiempo
- Recuperación selectiva — nunca se inyecta todo, siempre solo lo relevante
- Obsidian reemplazable por vector DB si el volumen lo requiere, sin cambiar la arquitectura

---

## Estructura del repositorio

```
/
├── README.md                  ← esta propuesta
├── docs/
│   ├── arquitectura.md        ← explicación detallada de cada componente
│   └── stack.md               ← decisiones técnicas y alternativas
├── diagrams/
│   ├── flujo_completo.html    ← diagrama interactivo del flujo
│   └── stack_tecnico.html     ← diagrama de stack y herramientas
└── examples/
    ├── extraccion.md          ← casos de extracción global vs cliente
    ├── almacenamiento.md      ← estructura de Obsidian con ejemplos reales
    └── recuperacion.md        ← flujos de recuperación paso a paso
```

---

> El Cerebro no hace al agente más inteligente.  
> Le da memoria.  
> Y con memoria, el agente deja de preguntar lo que ya sabe.
