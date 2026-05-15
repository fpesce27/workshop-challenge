# Ejemplos — Recuperación de Memorias

## Flujo completo de recuperación

```
Comprobante llega
      ↓
Identificar cliente (número WhatsApp / CBU / CUIT)
      ↓
Leer observación del comprobante
      ↓
┌─────────────────────────────────────┐
│         PASO 1: Índice RAM          │
│                                     │
│  ¿Hay entrada para este cliente     │
│  + esta observación?                │
│                                     │
│  Sí → Hit → ir a INYECCIÓN         │
│  No → ir a PASO 2                  │
└─────────────────────────────────────┘
      ↓ miss
┌─────────────────────────────────────┐
│    PASO 2: Búsqueda en /global/     │
│                                     │
│  FTS sobre conceptos globales       │
│  ¿La observación matchea algo?      │
│                                     │
│  Sí → Hit parcial → ir a INYECCIÓN │
│  No → ir a PASO 3                  │
└─────────────────────────────────────┘
      ↓ miss
┌─────────────────────────────────────┐
│      PASO 3: El agente pregunta     │
│                                     │
│  Respuesta → Consolidador           │
│  Consolidador → Obsidian + Índice  │
└─────────────────────────────────────┘
```

---

## Ejemplo 1: Hit completo en Índice RAM

**Contexto:** López (cliente conocido) manda comprobante con obs: "la grande A y B"

```
[08:03:12] Comprobante recibido - López - obs: "la grande A y B"
[08:03:12] Índice RAM consultado - cliente: lopez_001 + obs: "la grande A y B"
[08:03:12] HIT → alias "la grande" = López Distribuciones S.A.
[08:03:12] HIT → "A y B" = factura A por monto mayor + factura B por el resto
[08:03:12] Pre-inyector construye contexto:

  CONTEXTO (78 tokens):
  Cliente: López Distribuciones (lopez_001)
  Razón social: López Distribuciones S.A. ("la grande")
  Instrucción: emitir factura A por monto mayor + factura B por el resto
  No preguntes. Procesá directamente.

[08:03:12] Contexto inyectado al agente
[08:03:13] Agente responde: "✅ Procesado. Factura A $7.300 + Factura B $2.700"
[08:03:13] Consolidador: no hubo preguntas, refuerza confianza en índice
```

**Costo LLM:** $0 (solo lectura de índice)
**Tokens usados:** ~78 de contexto + tokens propios del agente

---

## Ejemplo 2: Hit parcial — concepto global, cliente nuevo

**Contexto:** Primer comprobante de Rodríguez (cliente nuevo) con obs: "armar factura A y B"

```
[09:15:44] Comprobante recibido - Rodríguez - obs: "armar factura A y B"
[09:15:44] Índice RAM - cliente: rodriguez_nuevo → sin entradas
[09:15:44] Índice RAM - global: "factura_a_y_b" → HIT (confianza 0.97)
[09:15:44] Pre-inyector construye contexto:

  CONTEXTO (52 tokens):
  [GLOBAL] "armar factura A y B" = emitir factura A 50% + factura B 50%
  Cliente nuevo: no hay preferencias específicas registradas.
  Procesá con el estándar global.

[09:15:44] Contexto inyectado al agente
[09:15:45] Agente responde: "✅ Procesado. Factura A $5.000 + Factura B $5.000"
[09:15:45] Consolidador: crea entrada para rodriguez_nuevo
           quirk inicial: "usa factura_a_y_b estándar" (confianza 0.6)
```

**Costo LLM:** $0 (concepto global ya conocido)
**Beneficio:** El agente no preguntó a pesar de ser un cliente nuevo

---

## Ejemplo 3: Miss completo — el agente pregunta y aprende

**Contexto:** Primer comprobante de Fernández con obs: "obs: poner en cuenta corriente"

```
[10:22:07] Comprobante recibido - Fernández - obs: "poner en cuenta corriente"
[10:22:07] Índice RAM - cliente: fernandez_nuevo → sin entradas
[10:22:07] Índice RAM - global: "cuenta corriente" → sin entradas
[10:22:07] FTS en /global/: "cuenta corriente" → sin match relevante
[10:22:07] Pre-inyector: no hay contexto disponible
[10:22:07] Agente pregunta:
           "¿Qué significa 'poner en cuenta corriente' en este contexto?"

[10:22:45] Usuario responde:
           "significa que en vez de cobrar ahora lo acumulo en su cuenta
            corriente para cobrar todo junto a fin de mes"

[10:22:45] Consolidador activado
[10:22:45] LLM evalúa: ¿global o cliente?
           → Respuesta: GLOBAL (define un proceso contable general)
[10:22:46] Memoria creada en /global/conceptos/cuenta_corriente.md
           confianza: 0.70, visto: 1
[10:22:46] Índice RAM actualizado

--- Próxima vez ---

[10:45:12] Comprobante de García - obs: "cc"
[10:45:12] FTS: "cc" no matchea directamente
[10:45:12] Agente pregunta: "¿'cc' significa cuenta corriente?"
[10:45:18] Usuario: "sí"
[10:45:18] Consolidador: agrega "cc" como alias de cuenta_corriente
           confianza sube a 0.80

--- Al mes siguiente ---

[10:22:07] Comprobante de cualquier cliente - obs: "cuenta corriente"
[10:22:07] Índice RAM: HIT global (confianza 0.94, visto 12 veces)
[10:22:07] Agente NO pregunta. Ya sabe.
```

---

## Ejemplo 4: Contradicción entre memoria y realidad

**Contexto:** El sistema aprendió que "factura A y B" es 50/50. Pero Pérez responde diferente.

```
[14:33:01] Comprobante de Pérez - obs: "factura A y B"
[14:33:01] HIT global: "factura_a_y_b" (confianza 0.97)
[14:33:01] Agente procesa: Factura A $5.000 + Factura B $5.000
[14:33:01] Pérez responde: "No, para nosotros A y B es
           70% a la razón social nueva y 30% a la vieja"

[14:33:01] Consolidador detecta contradicción:
           → Crea quirk por cliente: perez_055 tiene variante propia
           → Memoria global NO se modifica (34 clientes la usan correctamente)
           → Crea nota en perez_055/quirks.md:
              "factura A y B: 70% RS nueva / 30% RS vieja (difiere del estándar)"
           → Índice RAM actualizado para perez_055

--- Próxima vez con Pérez ---

[15:10:22] Comprobante de Pérez - obs: "factura A y B"
[15:10:22] HIT cliente perez_055 (tiene quirk propio)
[15:10:22] Agente aplica regla de Pérez, no el estándar global
[15:10:22] Sin preguntas.
```

---

## Comparación de tokens: antes vs después

| Escenario | Sin Cerebro | Con Cerebro | Ahorro |
|---|---|---|---|
| Cliente conocido, obs conocida | ~300 tokens (pregunta + respuesta) | ~80 tokens (contexto) | **73%** |
| Cliente nuevo, obs global conocida | ~300 tokens | ~52 tokens | **83%** |
| Cliente nuevo, obs desconocida | ~300 tokens | ~300 tokens (aprende) | 0% — pero solo pasa 1 vez |
| Después del aprendizaje | ~300 tokens | ~52 tokens | **83%** |
