#!/usr/bin/env python3
"""Wrapper para correr el watcher del vault de Obsidian desde la línea de comandos.

Uso:
  uv run python scripts/watch_vault.py
  uv run python scripts/watch_vault.py --vault /ruta/al/vault --interval 15
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

from second_brain.db import get_db_path
from second_brain.obsidian_writer import get_vault_path
from second_brain.watcher import watch_vault


def main() -> None:
    parser = argparse.ArgumentParser(description="Watcher del vault de Obsidian")
    parser.add_argument(
        "--vault",
        type=Path,
        default=None,
        help="Path al vault (default: obsidian_vault/ junto a la DB)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=30.0,
        help="Segundos entre scans (default: 30)",
    )
    args = parser.parse_args()

    db_path = get_db_path()
    vault_path = args.vault or get_vault_path(db_path)

    print(f"Vault watcher iniciado")
    print(f"  Vault:    {vault_path}")
    print(f"  DB:       {db_path}")
    print(f"  Interval: {args.interval:.0f}s")
    print(f"  Ctrl+C para detener\n")

    try:
        watch_vault(vault_path, db_path, interval=args.interval)
    except KeyboardInterrupt:
        print("\nWatcher detenido.")


if __name__ == "__main__":
    main()
