# Ejemplos — Almacenamiento en Obsidian

## Estructura completa del vault

```
obsidian-vault/
│
├── global/
│   ├── conceptos/
│   │   ├── factura_a_y_b.md
│   │   ├── hacer_50_50.md
│   │   └── armar_factura_mixta.md
│   └── patrones/
│       └── ambiguedades_comunes.md
│
├── clientes/
│   ├── lopez_001/
│   │   ├── quirks.md
│   │   └── historial.md
│   ├── garcia_022/
│   │   ├── quirks.md
│   │   └── historial.md
│   └── rodriguez_034/
│       ├── quirks.md
│       └── historial.md
│
└── insights/
    └── eurekas/
        ├── facturacion_mixta_combo.md
        └── zona_sur_julio.md
```

---

## Ejemplo: nota de concepto global

**Archivo:** `/global/conceptos/factura_a_y_b.md`

```markdown
---
tipo: global
concepto: factura_a_y_b
confianza: 0.97
visto: 34
primera_vez: 2026-01-15
ultima_vez: 2026-05-14
accion: "emitir factura A por 50% y factura B por el 50% restante del monto total"
---

# Factura A y B

Cuando una observación de comprobante dice "armar factura A y B" o variantes,
se deben emitir dos facturas por partes iguales del monto.

## Variantes reconocidas
- "armar factura A y B"
- "factura A más B"
- "A y B"
- "dos facturas"

## Clientes que usan este concepto
- [[clientes/lopez_001/quirks]] — con variante: A siempre por el monto mayor
- [[clientes/garcia_022/quirks]]
- [[clientes/martinez_088/quirks]]
- 31 clientes más

## Excepciones
- [[clientes/lopez_001/quirks]] tiene una regla propia que sobreescribe el 50/50 estándar.
```

---

## Ejemplo: nota de quirks por cliente

**Archivo:** `/clientes/lopez_001/quirks.md`

```markdown
---
cliente_id: lopez_001
nombre: López Distribuciones
ultima_actualizacion: 2026-05-14
---

# Quirks — López Distribuciones

## Razones sociales
- Monto > $500.000 → **López Distribuciones S.A.** (CUIT: 30-12345678-9)
- Monto ≤ $500.000 → **López Hnos. S.R.L.** (CUIT: 30-98765432-1)

## Facturación
- Usa [[global/conceptos/factura_a_y_b]] PERO con variante propia:
  la factura A siempre debe ser por el monto mayor (no necesariamente 50%)

## Aliases reconocidos
- "la grande" → López Distribuciones S.A.
- "la chica" → López Hnos. S.R.L.
- "Morón" → López Distribuciones S.A. (tiene depósito en Morón)

## Notas operativas
- Siempre pide remito por duplicado
- No acepta facturas electrónicas para López Hnos.
```

---

## Ejemplo: nota de Eureka

**Archivo:** `/insights/eurekas/facturacion_mixta_combo.md`

```markdown
---
tipo: eureka
confianza: 0.82
clientes_involucrados: 23
descubierto: 2026-04-10
ultima_confirmacion: 2026-05-13
---

# Eureka: Facturación mixta — combo frecuente

## Patrón detectado
Los clientes que usan [[global/conceptos/factura_a_y_b]] también
piden [[global/conceptos/hacer_50_50]] en el 78% de los casos.

## Clientes con este combo
[[clientes/lopez_001/quirks]]
[[clientes/garcia_022/quirks]]
[[clientes/rodriguez_034/quirks]]
... y 20 más

## Acción sugerida
Cuando llegue un comprobante con "factura A y B", preguntar proactivamente
si también aplica "50/50" o si ya está incluido en la instrucción.

## Resultado esperado
Reducir una vuelta de preguntas en clientes nuevos que usan ambos conceptos.
```

---

## Ejemplo: historial comprimido por cliente

**Archivo:** `/clientes/garcia_022/historial.md`

```markdown
---
cliente_id: garcia_022
periodo: 2026-01 a 2026-05
interacciones_totales: 87
preguntas_del_agente: 3
preguntas_evitadas: 84
---

# Historial comprimido — García Distribuciones

## Aprendizaje cronológico

**Enero 2026** — Primera interacción
- Agente preguntó sobre "50/50" → aprendió concepto global
- Agente preguntó sobre razón social → aprendió quirk: siempre García S.A.

**Febrero 2026** — Sin preguntas
- 22 comprobantes procesados sin fricción
- Concepto "50/50" aplicado correctamente en todos

**Marzo 2026** — Nueva situación
- Agente preguntó sobre "obs: urgente" → aprendió: urgente = enviar
  confirmación por email además del WhatsApp

**Abril-Mayo 2026** — Sin preguntas
- 41 comprobantes procesados sin fricción
- Sistema completamente calibrado para este cliente
```
