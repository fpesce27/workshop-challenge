# Arquitectura — Cerebro Agéntico

## Visión general

El Cerebro Agéntico es una capa externa al agente existente. No lo reemplaza ni lo modifica. Le habla como si fuera un usuario más — el agente solo ve que recibe contexto adicional antes de procesar cada mensaje.

```
┌─────────────────────────────────────────────┐
│           CEREBRO AGÉNTICO                  │
│                                             │
│  ┌──────────┐  ┌─────────────┐  ┌────────┐ │
│  │  Índice  │  │Pre-inyector │  │Consoli-│ │
│  │   RAM    │←→│             │  │dador   │ │
│  └──────────┘  └─────────────┘  └────────┘ │
│        ↕               ↕            ↕       │
│  ┌─────────────────────────────────────┐    │
│  │           OBSIDIAN                  │    │
│  │  /global/  /clientes/  /insights/   │    │
│  └─────────────────────────────────────┘    │
│                    ↕                        │
│  ┌─────────────────────────────────────┐    │
│  │         EL SUEÑO (cron)             │    │
│  └─────────────────────────────────────┘    │
└─────────────────────────────────────────────┘
         ↓ contexto inyectado
┌─────────────────────────────────────────────┐
│         AGENTE EXISTENTE (GALO)             │
└─────────────────────────────────────────────┘
```

---

## Componente 1 — Índice Rápido

**Problema que resuelve:** 1 comprobante por minuto = alta concurrencia. No podés hacer una consulta a Obsidian por cada mensaje sin latencia.

**Cómo funciona:**
- SQLite en RAM o JSON estructurado en memoria
- Al iniciar el sistema, se construye desde Obsidian
- Cada entrada es un puntero liviano: `{clave_semántica} → {path_en_obsidian}`
- Consulta en microsegundos, sin I/O

**Estructura del índice:**
```json
{
  "global": {
    "factura_a_y_b": "global/conceptos/factura_a_y_b.md",
    "hacer_50_50": "global/conceptos/hacer_50_50.md"
  },
  "clientes": {
    "lopez_001": {
      "quirks": ["factura_mitad_a", "dos_razones_sociales"],
      "path": "clientes/lopez_001/"
    }
  }
}
```

**Cuándo se actualiza:**
- Después de cada ejecución del Sueño
- Inmediatamente cuando el Consolidador escribe una memoria nueva

---

## Componente 2 — Pre-inyector

**Problema que resuelve:** El agente no tiene contexto del cliente ni de los términos ambiguos.

**Flujo de decisión:**
```
1. Identificar cliente por número de WhatsApp / CBU / CUIT
2. Leer observación del comprobante
3. Consultar Índice RAM por cliente + observación
   → Hit global: traer concepto global
   → Hit cliente: traer quirk específico
   → Miss: buscar en Obsidian por FTS
   → Nada: dejar que el agente pregunte
4. Construir prompt de contexto (~80 tokens máximo)
5. Inyectar al agente
```

**Prompt de inyección (ejemplo):**
```
[CONTEXTO DEL CLIENTE]
Cliente: López Distribuciones (ID: 001)
Razón social habitual: López Hnos. S.A.
Banco habitual: Galicia

[MEMORIAS ACTIVAS]
- "factura A y B" = emitir factura A por 50% y B por el resto (confianza: 0.95)
- Este cliente siempre quiere la factura A por el monto mayor (confianza: 0.88)

[INSTRUCCIÓN]
No preguntes. Procesá directamente con esta información.
```

---

## Componente 3 — Consolidador

**Problema que resuelve:** Aprender de cada respuesta del usuario sin sobrecargar el sistema.

**Se activa cuando:** El agente hizo una pregunta y el usuario respondió.

**Decisión central — global vs cliente:**

```python
# Pseudocódigo de la decisión
def clasificar_memoria(pregunta, respuesta, id_cliente):
    prompt = f"""
    El agente preguntó: {pregunta}
    El usuario respondió: {respuesta}
    
    ¿Esta respuesta aplica a:
    A) Cualquier cliente que use esta misma frase → GLOBAL
    B) Solo a este cliente específico → CLIENTE
    C) Ambos con confianza diferente → AMBOS
    
    Responde solo: GLOBAL | CLIENTE | AMBOS
    """
    decision = llm(prompt)  # llamada barata, prompt pequeño
    return decision
```

**Qué escribe en Obsidian:**
```yaml
---
tipo: global
concepto: factura_a_y_b
confianza: 0.7          # bajo porque es primera vez
visto: 1
origen: respuesta_usuario
ultima_vez: 2026-05-14
accion: "emitir factura A por 50% y B por el resto"
---

Aprendido de la respuesta del usuario el 2026-05-14.
Pendiente de confirmación por el Sueño.
```

---

## Componente 4 — Obsidian

**Problema que resuelve:** Persistencia, auditabilidad y conexión entre conceptos.

**Por qué Obsidian y no una DB:**
- El grafo de links conecta conceptos globales con clientes que los usan
- Es auditable por humanos — el equipo puede ver y corregir lo que aprendió el sistema
- El formato Markdown + YAML es legible por LLMs directamente
- Reemplazable por vector DB si el volumen supera los límites de FTS

**Estructura de links:**
```
factura_a_y_b.md
  [[lopez_001]]     ← lo usa López
  [[garcia_045]]    ← lo usa García
  [[patrones/facturacion_mixta]]  ← concepto relacionado
```

Cuando el Sueño ve que 10 clientes usan el mismo concepto, los links se convierten en evidencia de que es realmente global.

---

## Componente 5 — El Sueño

**Problema que resuelve:** Escala. Sin compresión, las memorias crecen sin límite.

**Cuándo corre:** Cron nocturno, fuera de horario pico. 0 costo en tiempo real.

**Tarea 1 — Comprimir:**
```
Antes: 50 entradas de "factura A y B para López"
       con confianza 0.7 cada una

Después: 1 entrada con confianza 0.97
         visto: 50
         primera_vez: 2026-01-10
         ultima_vez: 2026-05-14
```

**Tarea 2 — Promover de cliente a global:**
```
Si /clientes/lopez/factura_a_y_b (confianza 0.95)
+  /clientes/garcia/factura_a_y_b (confianza 0.91)
+  /clientes/martinez/factura_a_y_b (confianza 0.88)
+  7 clientes más con el mismo concepto

→ Crear /global/conceptos/factura_a_y_b.md (confianza 0.93)
→ Mantener los quirks individuales si difieren
→ Actualizar Índice RAM
```

**Tarea 3 — Descubrir Eurekas:**
```
Patrón detectado: 23 clientes que usan "factura A y B"
también piden "hacer 50/50" en el mismo período.

Eureka: son conceptos relacionados. 
Cuando llegue uno, preguntar si también aplica el otro.
→ Escribir en /insights/eurekas/facturacion_mixta_combo.md
```

---

## Flujo completo — ejemplo real

```
[08:03] Comprobante de López
        obs: "armar factura A y B"
        ↓
[08:03] Índice RAM: hit global "factura_a_y_b" + hit cliente "lopez_001"
        ↓
[08:03] Pre-inyector construye contexto (82 tokens)
        ↓
[08:03] Agente procesa SIN preguntar
        responde: "Procesado. Factura A $5.000 + Factura B $5.000"
        ↓
[08:03] Consolidador: sesión sin preguntas → nada nuevo que aprender
        ↓
[03:00] Sueño: refuerza confianza de "factura_a_y_b" para López
               visto: 15 → confianza: 0.99
```

```
[08:47] Comprobante de Rodríguez (cliente nuevo)
        obs: "armar factura A y B"
        ↓
[08:47] Índice RAM: hit global "factura_a_y_b" / miss cliente nuevo
        ↓
[08:47] Pre-inyector: inyecta solo el concepto global (45 tokens)
        ↓
[08:47] Agente procesa SIN preguntar (aprendió de López)
        ↓
[08:47] Consolidador: crea quirk para Rodríguez con confianza inicial 0.6
        ↓
[03:00] Sueño: Rodríguez se suma a la lista de clientes con "factura A y B"
               El concepto global se refuerza
```
