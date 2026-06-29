"""
Strategy intake queue report.

Usage:
    python scripts/strategy_intake_report.py
    python scripts/strategy_intake_report.py --pending
    python scripts/strategy_intake_report.py --id intake-001
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

QUEUE_PATH = Path(__file__).resolve().parent.parent / "research" / "strategy_intake" / "strategy_queue.json"


def load(path: Path = QUEUE_PATH) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def print_summary(items: list[dict]) -> None:
    pending = [i for i in items if i.get("decision") == "pending"]
    candidates = [i for i in items if i.get("decision") == "paper_candidate"]
    rejected = [i for i in items if i.get("decision") == "rejected"]

    print(f"\n{'='*62}")
    print("Strategy Intake Queue")
    print(f"{'='*62}")
    print(f"Total: {len(items)} | Pending: {len(pending)} | Candidates: {len(candidates)} | Rejected: {len(rejected)}\n")

    status_order = ["pending", "paper_candidate", "rejected"]
    for decision in status_order:
        group = [i for i in items if i.get("decision") == decision]
        if not group:
            continue
        label = {"pending": "PENDING", "paper_candidate": "CANDIDATE", "rejected": "REJECTED"}[decision]
        print(f"-- {label} ------------------------------------------")
        for item in group:
            print(f"  [{item['id']}] {item['strategy_name']} ({item['market']}, {item['timeframe']})")
            print(f"    Source: {item['source_platform']} | Pine: {item['pine_status']} | Python: {item['python_status']} | Backtest: {item['backtest_status']}")
            print(f"    Next: {item['next_action'][:80]}{'...' if len(item['next_action']) > 80 else ''}")
            if item.get("rejection_reasons"):
                print(f"    Rejected: {'; '.join(item['rejection_reasons'][:2])}")
            print()


def print_detail(item: dict) -> None:
    print(f"\n{'='*62}")
    print(f"[{item['id']}] {item['strategy_name']}")
    print(f"{'='*62}")
    for field in ["source_platform", "source_url", "trader", "market", "timeframe"]:
        print(f"  {field}: {item.get(field, 'N/A')}")
    print()
    print(f"Entry:  {item.get('entry_rules', '')}")
    print(f"Stop:   {item.get('stop_loss_rules', '')}")
    print(f"Exit:   {item.get('exit_rules', '')}")
    print(f"Size:   {item.get('position_sizing', '')}")
    print()
    if item.get("ambiguities"):
        print("Ambiguities:")
        for a in item["ambiguities"]:
            print(f"  ? {a}")
    print()
    print(f"Status: Pine={item.get('pine_status')} | Python={item.get('python_status')} | Backtest={item.get('backtest_status')} | Decision={item.get('decision')}")
    print(f"Next:   {item.get('next_action', '')}")
    if item.get("notes"):
        print(f"Notes:  {item.get('notes', '')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pending", action="store_true", help="Show only pending items")
    parser.add_argument("--id", help="Show detail for one item by ID")
    args = parser.parse_args()

    items = load()
    if not items:
        print(f"No items found at {QUEUE_PATH}")
        return 0

    if args.id:
        match = next((i for i in items if i["id"] == args.id), None)
        if match:
            print_detail(match)
        else:
            print(f"ID not found: {args.id}")
        return 0

    if args.pending:
        items = [i for i in items if i.get("decision") == "pending"]

    print_summary(items)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
