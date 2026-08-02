"""Baixa o histórico 2022-2026 (Jolpica, com cache em data/raw/) e monta
data/f1.db.

Uso:
    python scripts/build_db.py
    python scripts/build_db.py --seasons 2022 2023
"""
import argparse
import sys
from pathlib import Path


from src.data.db import build_db          # noqa: E402
from src.data.f1_provider import F1Provider  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", nargs="+", type=int,
                    default=[2022, 2023, 2024, 2025, 2026])
    ap.add_argument("--offline", action="store_true",
                    help="só cache local — falha em vez de ir à rede")
    args = ap.parse_args()
    stats = build_db(F1Provider(offline=args.offline), args.seasons)
    print(f"f1.db: {stats['races']} corridas, {stats['results']} resultados "
          f"({stats['path']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
