#!/usr/bin/env python3
"""CLI for the forward-only assisted-shadow decision desk."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.assisted_shadow_desk import (
    DEFAULT_JOURNAL,
    create_packet,
    load_states,
    packet_summary,
    record_decision,
    resolve_outcome,
)


def _candidate_from_args(args: argparse.Namespace) -> dict:
    return {
        "symbol": args.symbol,
        "strategy": args.strategy,
        "side": args.side,
        "entry": args.entry,
        "stop": args.stop,
        "target": args.target,
        "quantity": 1,
        "point_value": args.point_value,
        "estimated_round_trip_cost": args.cost,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "context": {"source": args.source},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Human approve/skip decisions for shadow candidates only")
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--symbol", required=True)
    create.add_argument("--strategy", required=True)
    create.add_argument("--side", choices=("buy", "sell"), required=True)
    create.add_argument("--entry", type=float, required=True)
    create.add_argument("--stop", type=float, required=True)
    create.add_argument("--target", type=float, required=True)
    create.add_argument("--point-value", type=float, default=1.0)
    create.add_argument("--cost", type=float, default=0.0)
    create.add_argument("--source", default="manual_alert")
    create.add_argument("--decision-window", type=int, default=90)

    sub.add_parser("list")
    show = sub.add_parser("show")
    show.add_argument("packet_id")
    for name in ("approve", "skip"):
        decision = sub.add_parser(name)
        decision.add_argument("packet_id")
        decision.add_argument("--digest")
    resolve = sub.add_parser("resolve")
    resolve.add_argument("packet_id")
    resolve.add_argument("--exit-price", type=float, required=True)

    args = parser.parse_args()
    if args.command == "create":
        result = create_packet(
            _candidate_from_args(args),
            journal=args.journal,
            decision_window_seconds=args.decision_window,
        )
    elif args.command == "list":
        result = [packet_summary(state) for state in load_states(args.journal).values()]
    elif args.command == "show":
        state = load_states(args.journal)[args.packet_id]
        result = packet_summary(state)
    elif args.command in {"approve", "skip"}:
        result = record_decision(
            args.packet_id,
            args.command,
            journal=args.journal,
            expected_candidate_digest=args.digest,
        )
    else:
        result = resolve_outcome(args.packet_id, exit_price=args.exit_price, journal=args.journal)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
