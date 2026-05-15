# Stack Técnico — Decisiones de Diseño

## Stack completo

| Componente | Tecnología elegida | Alternativa posible |
|---|---|---|
| Canal | WhatsApp Business API | Telegram, cualquier webhook |
| Índice rápido | SQLite en RAM | Redis, diccionario Python |
| Fuente de verdad | Obsidian + Local REST API | Cualquier vector DB |
| Formato de memoria | Markdown + Frontmatter YAML | JSON puro |
| Búsqueda | FTS sobre Obsidian | pgvector, Chroma, Pinecone |
| Orquestación | Python | Node.js |
| LLM | API genérica (Claude / GPT-4o / Gemini) | Cualquiera |
| Sueño | Cron job (crontab / APScheduler) | Celery beat, Airflow |

---

## Decisiones clave

### ¿Por qué SQLite en RAM como índice?

El sistema recibe 1 comprobante por minuto. Si cada mensaje hace una consulta I/O a Obsidian, la latencia acumula. SQLite en RAM resuelve esto con consultas en microsegundos.

El tradeoff es que el índice se pierde si el proceso cae — pero se reconstruye desde Obsidian en el arranque. Es un índice derivado, no la fuente de verdad.

```python
import sqlite3

# Al iniciar
conn = sqlite3.connect(":memory:")
conn.execute("""
    CREATE TABLE memorias (
        clave TEXT,
        tipo TEXT,  -- 'global' | 'cliente'
        scope TEXT, -- id_cliente | 'todos'
        path TEXT,
        confianza REAL
    )
""")
# Poblar desde Obsidian al arrancar
```

### ¿Por qué Obsidian y no una vector DB?

Dos razones:

1. **Auditabilidad**: el equipo humano puede abrir Obsidian y ver exactamente qué aprendió el sistema, corregirlo, y entender por qué el agente tomó una decisión.

2. **El grafo es la inteligencia**: los links entre notas representan relaciones semánticas que ninguna DB tabular captura. Un concepto global linked a 23 clientes es evidencia de su universalidad.

Si el volumen supera los límites de FTS (~100K memorias), Obsidian se reemplaza por pgvector o Chroma sin cambiar la arquitectura — solo cambia la capa de storage.

### ¿Por qué un LLM genérico barato?

El Consolidador hace una sola llamada LLM por respuesta del usuario — y es una pregunta binaria simple (global/cliente). Gemini Flash o Claude Haiku cuestan fracciones de centavo por llamada.

El Pre-inyector **no llama al LLM** — solo lee el índice y construye el contexto. Costo: 0.

El Sueño llama al LLM una vez por noche en batch — no en tiempo real.

### ¿Por qué el Sueño en lugar de procesar en tiempo real?

Comprimir 50 memorias en 1 requiere razonamiento sobre el conjunto — no sobre un mensaje individual. Hacerlo en tiempo real sería caro e innecesario. El Sueño corre cuando el tráfico es bajo y el índice se reconstruye después.

---

## Costos estimados

| Operación | Frecuencia | Costo LLM |
|---|---|---|
| Pre-inyector | 1 por mensaje | $0 (solo lectura) |
| Consolidador — clasificar | Solo cuando el agente preguntó | ~$0.001 por llamada |
| Sueño | 1 vez por noche | ~$0.01-0.10 según volumen |

Con 2.000 clientes activos y ~10% de mensajes ambiguos:
- ~200 llamadas al Consolidador por día → ~$0.20/día
- 1 ejecución del Sueño → ~$0.05/día
- **Total: ~$0.25/día para toda la infraestructura de memoria**

---

## Camino de migración si escala

```
Fase 1 (0-10K memorias):
SQLite RAM + Obsidian + FTS
→ Sin cambios de arquitectura

Fase 2 (10K-1M memorias):
SQLite RAM + Obsidian + pgvector para búsqueda semántica
→ Solo cambia la capa de búsqueda

Fase 3 (1M+ memorias):
Redis como índice + vector DB distribuida
→ Obsidian queda como capa de auditoría humana solamente
```

La arquitectura en capas permite escalar cada componente independientemente.
