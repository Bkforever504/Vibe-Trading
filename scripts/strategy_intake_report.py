#!/usr/bin/env python3
"""Generate the research-only strategy intake queue report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.strategy_intake import QUEUE_FILE, REPORT_FILE, run_report


def _print_summary(items: list[dict]) -> None:
    stage_counts: dict[str, int] = {}
    for item in items:
        stage = str(item.get("stage") or "unknown")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    print("\n" + "=" * 72)
    print("Strategy Intake Factory")
    print("=" * 72)
    print(f"Total: {len(items)} | " + " | ".join(f"{stage}: {count}" for stage, count in sorted(stage_counts.items())))
    print()

    for item in items:
        print(f"[{item.get('id')}] {item.get('strategy_name')} ({item.get('market')}, {item.get('timeframe')})")
        print(
            "  "
            f"Stage: {item.get('stage')} | Score: {item.get('readiness_score')} | "
            f"Pine: {item.get('pine_status')} | Python: {item.get('python_status')} | Backtest: {item.get('backtest_status')}"
        )
        blockers = item.get("blockers") if isinstance(item.get("blockers"), list) else []
        if blockers:
            print(f"  Blockers: {'; '.join(str(blocker) for blocker in blockers[:3])}")
        print(f"  Next: {item.get('next_action')}")
        print()


def _print_detail(item: dict) -> None:
    print("\n" + "=" * 72)
    print(f"[{item.get('id')}] {item.get('strategy_name')}")
    print("=" * 72)
    for field in ("source_platform", "source_url", "trader", "market", "timeframe", "stage", "readiness_score"):
        print(f"{field}: {item.get(field)}")
    print()
    blockers = item.get("blockers") if isinstance(item.get("blockers"), list) else []
    strengths = item.get("strengths") if isinstance(item.get("strengths"), list) else []
    print("Blockers:")
    for blocker in blockers or ["none"]:
        print(f"  - {blocker}")
    print("Strengths:")
    for strength in strengths or ["none"]:
        print(f"  - {strength}")
    print()
    print(f"Next action: {item.get('next_action')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate strategy intake queue report.")
    parser.add_argument("--queue", type=Path, default=QUEUE_FILE, help="Strategy queue JSON file.")
    parser.add_argument("--out", type=Path, default=REPORT_FILE, help="Report output path.")
    parser.add_argument("--id", help="Show detail for one intake item after scoring.")
    parser.add_argument("--pending", action="store_true", help="Show only non-rejected items.")
    parser.add_argument("--print", action="store_true", help="Print report JSON.")
    args = parser.parse_args(argv)

    report = run_report(queue_path=args.queue, out=args.out)
    if args.print:
        print(json.dumps(report, indent=2))
    else:
        items = report["items"]
        if args.pending:
            items = [item for item in items if item.get("stage") != "rejected"]
        if args.id:
            match = next((item for item in report["items"] if item.get("id") == args.id), None)
            if not match:
                print(f"ID not found: {args.id}")
                return 1
            _print_detail(match)
        else:
            _print_summary(items)
        print(f"Strategy intake report written to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
