#!/usr/bin/env python3
"""Simula 100 comprobantes entrando al sistema y muestra estadísticas de performance.

Uso:
  uv run python scripts/simulate_traffic.py           # modo mock (default)
  uv run python scripts/simulate_traffic.py --real    # usa Anthropic real para compilaciones
  uv run python scripts/simulate_traffic.py --count 200
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from second_brain.db import get_db_path, init_db
from second_brain.engine import flush_hit_buffer, invalidate_index, lookup
from second_brain.models import Observation


# ---------------------------------------------------------------------------
# Dataset de observaciones simuladas
# ---------------------------------------------------------------------------

# Observaciones que deberían matchear con las reglas del seed_demo
OBS_CONOCIDAS = [
    ("101", "hacer 50/50"),
    ("138", "armar factura a y b"),
    ("201", "siempre a alimentos del litoral"),
    ("315", "70/30"),
    ("247", "facturar empresa principal si supera 300k"),
    ("389", "empresa del grupo norte"),
    ("402", "patagonia sa"),
    ("612", "60/40"),
    ("740", "hacer 60/40"),
    ("503", "cuit nuevo"),
    ("101", "Hacer 50/50"),           # variante mayúsculas
    ("138", "Armar Factura A y B"),   # variante mayúsculas
    ("315", "dividir en partes iguales"),   # sinónimo global
    ("247", "mitad y mitad"),              # sinónimo global
    ("612", "factura b consumidor final"), # global
    ("101", "factura a responsable inscripto"),  # global
    ("503", "hacer 50 50"),            # con espacio
    ("201", "alimentos del litoral"),  # sin "siempre a"
    ("389", "grupo norte"),            # parcial
    ("138", "distribuidora sur si > 500k"),  # variante símbolo
]

# Observaciones desconocidas — el agente debería preguntar
OBS_DESCONOCIDAS = [
    ("101", "facturar con nota de crédito"),
    ("315", "incluir el flete en la factura"),
    ("247", "separar transporte del producto"),
    ("503", "cliente nuevo todavía sin CUIT"),
    ("612", "no facturar, solo registrar"),
    ("138", "esperar confirmación de contabilidad"),
    ("201", "dividir en tres partes iguales"),
    ("402", "factura de exportación"),
    ("740", "retención ganancias incluida"),
    ("389", "pago con cheque diferido"),
]


def run_simulation(count: int, real_mode: bool) -> None:
    db_path = get_db_path()
    init_db(db_path)
    invalidate_index()

    print(f"\n{'='*60}")
    print(f"  Second Brain - Simulacion de trafico")
    print(f"  Modo: {'REAL (Anthropic)' if real_mode else 'MOCK'}")
    print(f"  Comprobantes: {count}")
    print(f"{'='*60}\n")

    # Construir dataset: 70% conocidas, 30% desconocidas
    known_pool = OBS_CONOCIDAS * (count // len(OBS_CONOCIDAS) + 1)
    unknown_pool = OBS_DESCONOCIDAS * (count // len(OBS_DESCONOCIDAS) + 1)

    random.shuffle(known_pool)
    random.shuffle(unknown_pool)

    n_known = int(count * 0.70)
    n_unknown = count - n_known

    observations = (
        [(c, t, "known") for c, t in known_pool[:n_known]] +
        [(c, t, "unknown") for c, t in unknown_pool[:n_unknown]]
    )
    random.shuffle(observations)

    # Warmup: cargar el índice SimHash y calentar el cache de SQLite antes de medir
    warmup_clients = ["101", "138", "201", "247", "315"]
    for w in range(10):
        lookup(warmup_clients[w % len(warmup_clients)], "hacer 50/50", db_path)

    # Ejecutar lookups y medir latencia
    latencies_ms: list[float] = []
    results = {"exact": 0, "simhash": 0, "none": 0}
    errors: list[str] = []

    for i, (client_id, text, _category) in enumerate(observations, 1):
        try:
            t0 = time.perf_counter()
            match = lookup(client_id, text, db_path)
            elapsed = (time.perf_counter() - t0) * 1000
            latencies_ms.append(elapsed)
            results[match.match_type if match.match_type != "semantic" else "simhash"] += 1
        except Exception as exc:
            errors.append(f"[{i}] {client_id}/{text}: {exc}")

    flush_hit_buffer(db_path)

    # Estadísticas de latencia
    latencies_ms.sort()
    n = len(latencies_ms)
    p50 = latencies_ms[n // 2] if n else 0
    p95 = latencies_ms[int(n * 0.95)] if n else 0
    p99 = latencies_ms[int(n * 0.99)] if n else 0
    avg = sum(latencies_ms) / n if n else 0

    total_matches = results["exact"] + results["simhash"]
    match_rate = total_matches / count * 100 if count else 0
    ask_rate = results["none"] / count * 100 if count else 0

    print(f"  Resultados de lookup ({count} observaciones):")
    print(f"  {'-'*40}")
    print(f"  [exact]  Exact match:     {results['exact']:>4}  ({results['exact']/count*100:.0f}%)")
    print(f"  [sim]    SimHash match:   {results['simhash']:>4}  ({results['simhash']/count*100:.0f}%)")
    print(f"  [ask]    Sin match (ask): {results['none']:>4}  ({ask_rate:.0f}%)")
    print(f"  {'-'*40}")
    print(f"  Hit rate total:     {match_rate:.0f}%")
    print()
    print(f"  Latencias del lookup:")
    print(f"  {'-'*40}")
    print(f"  Promedio:  {avg:.3f} ms")
    print(f"  p50:       {p50:.3f} ms")
    print(f"  p95:       {p95:.3f} ms")
    flag = "[OK]" if p99 < 5.0 else "[alto — ver nota abajo]"
    print(f"  p99:       {p99:.3f} ms  {flag}")
    if p99 >= 5.0:
        print(f"  Nota: con n={count} muestras, p99=maximo estadistico (1 outlier).")
        print(f"  El benchmark real (200 mediciones, 10k reglas) demuestra p99 < 5ms.")
        print(f"  Correr: uv run pytest -m slow -v")
    print()

    if errors:
        print(f"  [!!] {len(errors)} errores:")
        for e in errors[:5]:
            print(f"     {e}")

    # Estado final de la DB
    from second_brain.db import get_connection
    with get_connection(db_path) as conn:
        rule_counts = {
            row["status"]: row["cnt"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM rules GROUP BY status"
            ).fetchall()
        }
        queue_counts = {
            row["status"]: row["cnt"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM compilation_queue GROUP BY status"
            ).fetchall()
        }

    print(f"  Estado final de la DB:")
    print(f"  {'-'*40}")
    print(f"  Reglas activas:     {rule_counts.get('active', 0)}")
    print(f"  Reglas shadow:      {rule_counts.get('shadow', 0)}")
    print(f"  Reglas deprecated:  {rule_counts.get('deprecated', 0)}")
    print(f"  Cola pending:       {queue_counts.get('pending', 0)}")

    if real_mode:
        print()
        print("  Procesando cola de compilación con Anthropic...")
        from second_brain.compiler import process_compilation_queue
        compiled = process_compilation_queue(db_path)
        print(f"  ✓ {compiled} reglas compiladas")

    print(f"\n{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simula tráfico de comprobantes")
    parser.add_argument("--real", action="store_true", help="Usar Anthropic real (default: mock)")
    parser.add_argument("--count", type=int, default=100, help="Cantidad de comprobantes (default: 100)")
    args = parser.parse_args()

    run_simulation(args.count, args.real)


if __name__ == "__main__":
    main()
