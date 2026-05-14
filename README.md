# Second Brain · Workshop Challenge

Auspiciado por **[Galo](https://soygalo.com)** · Organizado por **Martín Pullitaro y Nicolas Silva**

Este repo es donde los participantes del workshop **Second Brain** mandan sus soluciones al challenge. Cualquiera puede abrir un Pull Request con su propuesta.

---

## El contexto

Hay un chatbot ya existente que vive en un número de WhatsApp. Una persona le reenvía a ese número, **uno por minuto**, comprobantes de transferencia bancaria de sus clientes. Son compras recurrentes: por ejemplo, un lunes pueden llegar 100 comprobantes de 100 clientes distintos, y el lunes siguiente vuelven a aparecer esos mismos 100 clientes con su comprobante correspondiente.

El agente actual hace bien casi todo el trabajo:

- Analiza la imagen del comprobante.
- Extrae los datos (monto, CBU, CUIT, etc.).
- Ejecuta una tool con esos datos y corre sus validaciones.

**El problema no es ese.** El problema son los comprobantes que vienen con información extra o ambigua en el campo de observaciones / notas, por ejemplo:

- `armar factura A y B`
- `hacer 50/50`
- múltiples razones sociales en la misma nota
- otros casos no previstos

**Las peculiaridades no siempre son universales.** "Armar factura A y B" puede ser un requisito puntual de un cliente y no aplicar a otros. La memoria tiene una doble dimensión:

- **Por cliente** — quirks específicos de cada cliente recurrente (este cliente siempre factura mitad A / mitad B, este otro tiene dos razones sociales y elige según el monto, etc.).
- **Global** — conceptos generales que el agente no entendía y que, una vez aclarados, pueden aplicar a varios clientes.

Tu solución tiene que pensar cuándo una respuesta es genérica y cuándo es específica de un cliente.

Para esos casos el agente **tiene que preguntar** la primera vez:

> "¿Qué significa 'armar factura A y B'?"

Cuando el usuario responde, el agente debería:

1. Usar esa respuesta para procesar **ese** comprobante.
2. **Aprender** de la respuesta.
3. La próxima vez que llegue un comprobante con la misma observación (o equivalente), **no volver a preguntar**: ya sabe qué hacer.

---

## Lo que tenés que resolver

El foco del challenge **no** es construir el agente entero. Damos por sentado que la parte de análisis de imagen, extracción de datos y validación ya está resuelta.

**Lo que tenés que diseñar es el sistema de memoria/aprendizaje:**

1. **Extracción** — ¿Cómo extraés insights/memorias útiles a partir de las respuestas del usuario?
2. **Almacenamiento** — ¿Dónde y cómo las guardás?
3. **Recuperación** — ¿Cómo las traés en el momento justo para que el agente no vuelva a preguntar?

---

## Restricciones a tener en cuenta

- **Tráfico**: llega un comprobante por minuto. Hay alta concurrencia.
- **Escala temporal**: pensá la solución para 30, 60, 90 días. ¿Qué pasa cuando hay miles, decenas de miles o millones de memorias acumuladas?
- **Contexto**: el contexto del agente se llena rápido. **No** es el problema central del challenge, pero tu solución no puede ignorarlo — no podés "inyectar todas las memorias siempre".

---

## Criterios de evaluación

Tres pilares, con peso parejo:

### 1. Realismo
¿Se puede llevar a producción sin fundirse? Una solución del estilo "tres agentes Claude Opus 4.7 en paralelo extrayendo memorias para cada mensaje" resuelve el problema, pero te funde la cuenta. Pensá en costos, latencia, infra.

### 2. Creatividad
La solución obvia es "guardo memorias en una DB y las inyecto al prompt". Funciona, pero es aburrida. Acá buscamos ideas distintas, enfoques no convencionales, arquitecturas que no se nos hubieran ocurrido.

### 3. Escalabilidad
¿Tu solución sigue funcionando con 1.000 memorias? ¿Con 100.000? ¿Con 1M? ¿Cómo decidís qué memorias traer? ¿Cómo evitás que el costo crezca lineal con el tráfico?

---

## Cómo participar

1. Forkeá este repo.
2. Armá tu solución. **Formato libre**: puede ser código, diagramas, un documento explicando la arquitectura, una mezcla, lo que vos quieras.
3. Abrí un Pull Request a este repo con tu propuesta.
4. En la descripción del PR contá brevemente cuál fue tu enfoque y cómo se evalúa contra los tres pilares.

> **No hace falta código funcional.** Una propuesta de arquitectura bien argumentada vale tanto como una implementación.

---

## Reglas

- Podés mandar más de un PR si tenés varias ideas distintas, pero **mantenelos en PRs separados**.
- Tocá solo los archivos de tu propia submission. Los PRs que modifiquen el README, configuración del repo o submissions ajenas no se consideran.
- Plagio = descalificación.

---

## Fechas

- **Deadline**: viernes **15 de mayo de 2026, 23:59 ART** (UTC-3).
- Los PRs abiertos después de esa hora no se consideran.

---

## Premio

El ganador se lleva una **cuenta de Claude (USD 20)**.

---

## Dudas

Abrí un **[Issue](../../issues)** en este repo. Es el canal oficial para preguntas durante el challenge.

---

## Créditos

- **Workshop**: Second Brain
- **Auspiciante**: [Galo](https://soygalo.com)
- **Organizadores**: Martín Pullitaro y Nicolas Silva
