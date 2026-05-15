# Second Brain — Vault de Galo

Este vault es la interfaz humana del sistema. Acá el operador puede ver, auditar y corregir lo que el agente aprende.

## Estructura

```
clientes/          → Reglas activas por cliente
globales/          → Reglas activas que aplican a todos
pendientes-revision/
  ├── promociones/ → Propuestas de elevación a global (requieren aprobación)
  ├── invalidaciones/ → Reglas deprecadas y su historial
  └── *.md         → Reglas shadow nuevas y compilaciones fallidas
```

## Cómo usar

### Aprobar una regla nueva (shadow → active)
1. Abrí la nota en `pendientes-revision/`
2. Revisá que la acción sea correcta
3. Cambiá `approved: false` → `approved: true` en el frontmatter
4. El watcher lo detecta en ≤30s y activa la regla

### Corregir una acción a mano
1. Editá el campo `action:` en el frontmatter
2. Guardá — el watcher valida el JSON y actualiza SQLite

### Aprobar una promoción global
1. Abrí la nota en `pendientes-revision/promociones/`
2. Verificá que los clientes listados tengan el mismo comportamiento
3. Cambiá `approved: false` → `approved: true`

---

## Slash commands (Claude Code)

Desde Claude Code dentro de este vault:

- `/auditar-cliente {client_id}` — lee todas las notas del cliente, detecta contradicciones, propone consolidaciones
- `/proponer-global {nota.md}` — evalúa si una regla de cliente debería ser global
- `/detectar-drift {client_id}` — compara reglas históricas vs comportamiento reciente y alerta de cambios

---

## Estado actual

| Tipo | Cantidad |
|------|---------|
| Reglas activas de cliente | — |
| Reglas activas globales | — |
| Pendientes de revisión | — |
| Deprecadas | — |

> Ejecutá `uv run python scripts/seed_demo.py` para poblar el vault con datos de demo.
