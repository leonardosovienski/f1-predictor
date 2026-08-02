from __future__ import annotations

import argparse
from datetime import UTC, datetime

from .config import ROOT
from .contracts import PredictionRequest
from .services import F1Plugin


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="f1-predictor")
    sub = parser.add_subparsers(dest="command", required=True)
    health = sub.add_parser("health")
    health.add_argument("--offline", action="store_true")
    predict = sub.add_parser("predict")
    predict.add_argument("--circuit", required=True)
    predict.add_argument("--weather", default="dry", choices=("dry", "wet"))
    args = parser.parse_args(argv)
    plugin = F1Plugin(ROOT)
    if args.command == "health":
        if args.offline:
            plugin.provider.offline = True
        print(plugin.health().model_dump_json(indent=2))
    else:
        now = datetime.now(UTC)
        result = plugin.predict(
            PredictionRequest(circuit=args.circuit, weather=args.weather, predicted_at=now, data_as_of=now)
        )
        print(result.model_dump_json(indent=2))
    return 0
