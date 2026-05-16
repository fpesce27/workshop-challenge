# Second Brain — Galo

> El agente tiene un sistema nervioso. El humano tiene un cerebro. No son el mismo órgano.

Sistema de memoria determinístico para el agente de WhatsApp de Galo. Aprende de las respuestas del operador, ejecuta reglas compiladas en < 5ms, y le da al operador humano un vault de Obsidian para ver y corregir lo que el agente aprendió.

---

## Instalación rápida

```bash
# Clonar e instalar
uv sync

# Poblar la DB con datos de demo (10 clientes, 21 reglas, 5 invalidaciones)
uv run python scripts/seed_demo.py

# Levantar la API
uv run uvicorn second_brain.main:app --reload
```

La API queda en `http://localhost:8000`. Docs en `http://localhost:8000/docs`.

### Simular tráfico

```bash
# 100 comprobantes en modo mock (sin llamadas a Anthropic)
uv run python scripts/simulate_traffic.py

# Con Anthropic real (requiere ANTHROPIC_API_KEY)
uv run python scripts/simulate_traffic.py --real

# Cantidad personalizada
uv run python scripts/simulate_traffic.py --count 500
```

### Correr tests

```bash
uv run pytest                    # suite completa (74 tests)
uv run pytest -m slow            # incluye benchmark de performance
```

### Watcher del vault (opcional)

```bash
# Arrancar manualmente
uv run python scripts/watch_vault.py

# O activar en la API (detecta cambios en Obsidian automáticamente)
ENABLE_WATCHER=1 uv run uvicorn second_brain.main:app
```

---

## Endpoints

| Método | Path | Descripción |
|--------|------|-------------|
| `POST` | `/observations` | Recibe una observación: responde con `execute` o `ask` |
| `POST` | `/observations/{id}/response` | Respuesta del usuario → encola compilación |
| `POST` | `/observations/{id}/invalidate` | Marca una ejecución como incorrecta |
| `GET`  | `/rules` | Lista reglas (filtros: scope, client_id, status) |
| `GET`  | `/stats` | Estadísticas del sistema |
| `POST` | `/admin/promotion-scan` | Dispara scan de promoción cliente→global |

### Ejemplo: observación conocida

```bash
curl -X POST http://localhost:8000/observations \
  -H "Content-Type: application/json" \
  -d '{"client_id": "138", "text": "hacer 50/50", "comprobante_id": "CMP-001"}'
```

```json
{
  "observation_id": "a1b2c3...",
  "action": "execute",
  "rule_id": "...",
  "match_type": "exact",
  "match_score": 1.0,
  "action_details": {"type": "split_invoice", "type_a_pct": 50, "type_b_pct": 50}
}
```

### Ejemplo: observación desconocida → el agente pregunta

```bash
curl -X POST http://localhost:8000/observations \
  -H "Content-Type: application/json" \
  -d '{"client_id": "138", "text": "empresa del grupo", "comprobante_id": "CMP-002"}'
```

```json
{
  "observation_id": "d4e5f6...",
  "action": "ask",
  "question": "¿Qué significa \"empresa del grupo\"? ¿Cómo lo proceso?"
}
```

### Responder y aprender

```bash
curl -X POST http://localhost:8000/observations/d4e5f6.../response \
  -H "Content-Type: application/json" \
  -d '{"user_response": "Facturar a Alimentos del Sur SA, CUIT 30-11111111-1"}'
```

```json
{"status": "learning", "compilation_job_id": "...", "will_apply_next_time": true}
```

---

## Slash commands en Obsidian (Claude Code)

Desde Claude Code dentro del vault `obsidian_vault/`:

```
/auditar-cliente 138
```
Lee todas las notas del cliente 138, detecta contradicciones o reglas que podrían consolidarse, y propone cambios.

```
/proponer-global pendientes-revision/distribuidora-sur-condicional-a1b2c3d4.md
```
Evalúa si una regla de cliente debería elevarse a global y arma el texto del PR de promoción.

```
/detectar-drift 138
```
Compara las reglas activas del cliente 138 con las invalidaciones recientes y alerta si el comportamiento del cliente parece haber cambiado.

---

## Variables de entorno

| Variable | Default | Descripción |
|----------|---------|-------------|
| `SECOND_BRAIN_DB` | `second_brain.db` | Path a la base de datos SQLite |
| `OBSIDIAN_VAULT_PATH` | `obsidian_vault/` | Path al vault |
| `ANTHROPIC_API_KEY` | — | Requerida para compilación de reglas (Claude Haiku) |
| `ENABLE_WATCHER` | `0` | `1` para activar el vault watcher en startup de la API |

---

## Estructura del proyecto

```
src/second_brain/
├── models.py          → Modelos Pydantic (Rule, Observation, Action types)
├── db.py              → SQLite + WAL, helpers de serialización
├── normalizer.py      → Normalización de texto + SimHash 64-bit
├── engine.py          → Lookup determinístico < 5ms (hot path)
├── compiler.py        → Compilación async con Claude Haiku (cold path)
├── promoter.py        → Promoción automática cliente→global
├── invalidator.py     → Memoria negativa / contra-aprendizaje
├── obsidian_writer.py → Escritura de notas en el vault
├── watcher.py         → Watcher de cambios en el vault
└── main.py            → API FastAPI
```

Ver `ARCHITECTURE.md` para la explicación completa de la arquitectura.
