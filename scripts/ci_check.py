"""CI minima local do f1-predictor — 3 barreiras (Fase 0).

  1. pytest — a suite inteira tem que passar.
  2. Encoding — qualquer .ps1 do repo precisa ser ASCII puro (licao do wc).
  3. Parse dos arquivos criticos — config.yaml valido, drivers_f1.json com
     22 pilotos / 11 equipes, circuits_f1.json com 22 rodadas, .env.example
     presente, e smoke do serving: predict --circuit Monza --json com o
     ranking completo e P(win) somando ~1.

Uso:
    python scripts/ci_check.py            # tudo
    python scripts/ci_check.py --fast     # pula o pytest
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
failures: list[str] = []


def check_pytest() -> None:
    print("[1/3] pytest (suite completa)...")
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                       cwd=ROOT, capture_output=True, text=True)
    tail = (r.stdout or "").strip().splitlines()[-1:] or ["(sem saida)"]
    print(f"      {tail[0]}")
    if r.returncode != 0:
        failures.append(f"pytest falhou (exit {r.returncode}) — rode: python -m pytest tests/")


def check_ps1_ascii() -> None:
    print("[2/3] encoding de scripts .ps1 (ASCII puro)...")
    ps1 = [p for p in ROOT.rglob("*.ps1")
           if ".venv" not in p.parts and ".git" not in p.parts]
    for p in ps1:
        try:
            p.read_bytes().decode("ascii")
        except UnicodeDecodeError as e:
            failures.append(f"{p.relative_to(ROOT)}: nao-ASCII no byte {e.start}")
    print(f"      {len(ps1)} arquivo(s) .ps1 verificados")


def check_critical_files() -> None:
    print("[3/3] parse dos arquivos criticos + smoke do serving...")
    try:
        import yaml
        cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        for key in ("sport", "season", "k_factor_base", "k_factor_rookie",
                    "drivers_file", "circuits_file"):
            if key not in cfg:
                failures.append(f"config.yaml sem a chave obrigatoria '{key}'")
    except Exception as e:
        failures.append(f"config.yaml ilegivel: {e}")

    try:
        drivers = json.loads((ROOT / "data" / "drivers_f1.json")
                             .read_text(encoding="utf-8"))["drivers"]
        if len(drivers) != 22 or len({d["team"] for d in drivers}) != 11:
            failures.append(f"drivers_f1.json: esperava 22 pilotos/11 equipes, "
                            f"achei {len(drivers)}/{len({d['team'] for d in drivers})}")
    except Exception as e:
        failures.append(f"drivers_f1.json ilegivel: {e}")

    try:
        circuits = json.loads((ROOT / "data" / "circuits_f1.json")
                              .read_text(encoding="utf-8"))["circuits"]
        if len(circuits) != 22:
            failures.append(f"circuits_f1.json: esperava 22 rodadas, achei {len(circuits)}")
    except Exception as e:
        failures.append(f"circuits_f1.json ilegivel: {e}")

    if not (ROOT / ".env.example").exists():
        failures.append(".env.example ausente")

    env = dict(os.environ)
    tmp = Path(tempfile.gettempdir())
    env["PREDICTIONS_LOG_PATH"] = str(tmp / "f1_ci_smoke_pred.jsonl")
    env["PREDICTOR_EVENTS_PATH"] = str(tmp / "f1_ci_smoke_events.jsonl")
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "src.predict",
                        "--circuit", "Monza", "--weather", "dry", "--json"],
                       cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    if r.returncode != 0:
        failures.append(f"predict --json saiu com exit {r.returncode}: "
                        f"{(r.stderr or '')[-200:]}")
    else:
        try:
            out = json.loads(r.stdout)
            soma = sum(v["win"] for v in out["ranking"].values())
            if not 0.99 <= soma <= 1.01:
                failures.append(f"soma P(win) = {soma:.4f} (esperado ~1)")
            fav = next(iter(out["ranking"]))
            print(f"      smoke: {len(out['ranking'])} pilotos | favorito "
                  f"{fav} {out['ranking'][fav]['win']:.1%}")
        except (ValueError, KeyError) as e:
            failures.append(f"predict --json nao produziu o dict esperado ({e})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="pula o pytest")
    args = ap.parse_args()

    if not args.fast:
        check_pytest()
    else:
        print("[1/3] pytest PULADO (--fast)")
    check_ps1_ascii()
    check_critical_files()

    print()
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        print(f"\nCI: {len(failures)} falha(s) — commit bloqueado.")
        return 1
    print("CI: todas as barreiras verdes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
