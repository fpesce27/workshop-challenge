# Ejemplos — Extracción de Memorias

## Caso 1: Memoria claramente global

**Situación:**
```
Comprobante: obs: "armar factura A y B"
Agente pregunta: ¿Qué significa "armar factura A y B"?
Usuario responde: "significa emitir una factura A por el 50% 
                  y una B por el resto del monto"
```

**Decisión del Consolidador:** GLOBAL

**Razonamiento:** La respuesta define un concepto sin mencionar nada específico del cliente. Cualquier cliente que use la misma frase recibirá el mismo tratamiento.

**Memoria generada:**
```yaml
---
tipo: global
concepto: factura_a_y_b
confianza: 0.70
visto: 1
accion: "emitir factura A por 50% y factura B por el 50% restante"
ultima_vez: 2026-05-14
---
Concepto aprendido el 2026-05-14 de la respuesta directa del usuario.
Pendiente de confirmación con más observaciones.
```

---

## Caso 2: Memoria claramente por cliente

**Situación:**
```
Comprobante de López: obs: "dos razones sociales"
Agente pregunta: ¿A qué razón social corresponde este comprobante?
Usuario responde: "López Distribuciones cuando el monto es mayor a 
                  $500.000, López Hnos cuando es menor"
```

**Decisión del Consolidador:** CLIENTE

**Razonamiento:** La respuesta menciona nombres propios específicos y una regla que solo aplica a ese cliente.

**Memoria generada:**
```yaml
---
tipo: cliente
scope: lopez_001
concepto: seleccion_razon_social
confianza: 0.85
visto: 1
regla: "monto > 500000 → López Distribuciones | monto <= 500000 → López Hnos"
ultima_vez: 2026-05-14
---
Quirk específico de López. No aplicar a otros clientes.
```

---

## Caso 3: Ambigüedad — guardar en ambos con confianza baja

**Situación:**
```
Comprobante: obs: "hacer 50/50"
Agente pregunta: ¿Qué significa "hacer 50/50"?
Usuario responde: "dividir el monto en dos partes iguales 
                  y emitir una factura por cada una"
```

**Decisión del Consolidador:** AMBOS

**Razonamiento:** Suena a un concepto global (dividir en partes iguales) pero podría ser que solo este cliente lo pida así. Confianza baja en ambos hasta que el Sueño tenga más datos.

**Memorias generadas:**
```yaml
# /global/conceptos/hacer_50_50.md
---
tipo: global
concepto: hacer_50_50
confianza: 0.50   ← bajo, solo 1 observación
visto: 1
accion: "dividir monto en dos partes iguales, una factura por cada parte"
pendiente_confirmacion: true
---
```

```yaml
# /clientes/garcia_022/quirks.md (entrada adicional)
---
concepto: hacer_50_50
confianza: 0.50
origen: primera_vez
---
```

**Después del Sueño**, si 5 clientes más usan la misma frase:
- La memoria global sube a confianza 0.85
- Se elimina la entrada por cliente
- El concepto queda promovido a global definitivamente

---

## Caso 4: Contradicción — el sistema aprende que no es global

**Situación:**
```
[Semana 1] García responde: "50/50 significa dos facturas iguales"
[Semana 3] Martínez responde: "50/50 para nosotros es 30% en efectivo 
            y 70% transferencia, no tiene que ver con facturas"
```

**Acción del Sueño:**
- Detecta que "50/50" tiene dos interpretaciones distintas
- Baja la confianza del concepto global a 0.3
- Crea dos entradas por cliente con sus definiciones propias
- Marca el concepto como **ambiguo** — el agente debe preguntar hasta tener más contexto del cliente específico

```yaml
# /global/conceptos/hacer_50_50.md
---
tipo: global
concepto: hacer_50_50
confianza: 0.30
ambiguo: true
nota: "Interpretaciones contradictorias entre clientes. Preguntar al cliente nuevo."
interpretaciones:
  - clientes: [garcia_022, otros_5]
    accion: "dos facturas iguales"
  - clientes: [martinez_088]
    accion: "30% efectivo / 70% transferencia"
---
```

---

## Caso 5: Múltiples razones sociales — quirk puro de cliente

**Situación:**
```
Comprobante de Rodríguez: obs: "para la de Morón"
Agente pregunta: ¿A qué se refiere "la de Morón"?
Usuario responde: "tengo dos empresas, Rodríguez Logística 
                  (Morón) y Rodríguez Servicios (Palermo). 
                  Cuando digo 'la de Morón' es Rodríguez Logística."
```

**Decisión:** CLIENTE — es un alias personal que no aplica a nadie más.

**Memoria generada:**
```yaml
---
tipo: cliente
scope: rodriguez_034
concepto: alias_moron
confianza: 0.95
razon_social: "Rodríguez Logística S.R.L."
alias: ["la de Morón", "Morón", "la logística"]
ultima_vez: 2026-05-14
---
```

**La próxima vez:**
```
Comprobante de Rodríguez: obs: "para la de Morón"
Pre-inyector inyecta: 
  "la de Morón = Rodríguez Logística S.R.L. (no preguntes)"
Agente: procesa directamente sin preguntar.
```
