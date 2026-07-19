#!/usr/bin/env python3
"""View shadow-only prop signals from the local JSONL journal.

Read-only. Does not submit orders or modify the journal.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_JOURNAL = Path(os.path.expanduser(r"~\.vibe-trading\shadow-ai-signals.jsonl"))


@dataclass(frozen=True)
class SignalRow:
    created_at: str
    symbol: str
    strategy: str
    side: str
    entry: float | None
    stop: float | None
    target: float | None
    confidence: float
    outcome: str
    pnl: float | None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_shadow_signals(journal: Path = DEFAULT_JOURNAL) -> list[dict[str, Any]]:
    if not journal.exists():
        return []

    signals: list[dict[str, Any]] = []
    outcomes_by_signal_id: dict[str, dict[str, Any]] = {}
    with journal.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") == "outcome" and record.get("signal_id"):
                outcomes_by_signal_id[str(record["signal_id"])] = record
            elif (record.get("mode") == "shadow_only"
                    and record.get("executable") is False):
                signals.append(record)

    joined: list[dict[str, Any]] = []
    for signal in signals:
        row = dict(signal)
        outcome = outcomes_by_signal_id.get(str(signal.get("created_at", "")))
        if outcome:
            row["_outcome_record"] = outcome
        joined.append(row)
    return joined


def to_row(record: dict[str, Any]) -> SignalRow:
    context = record.get("context") if isinstance(record.get("context"), dict) else {}
    outcome_record = record.get("_outcome_record") if isinstance(record.get("_outcome_record"), dict) else {}
    outcome_value = outcome_record.get("outcome") or context.get("outcome") or record.get("outcome") or "open"
    pnl_value = outcome_record.get("pnl") if outcome_record else (context.get("pnl") or record.get("pnl"))
    return SignalRow(
        created_at=str(record.get("created_at", "")),
        symbol=str(record.get("symbol", "")),
        strategy=str(record.get("strategy", "")),
        side=str(record.get("proposed_action", "")),
        entry=_safe_float(context.get("entry")),
        stop=_safe_float(context.get("stop")),
        target=_safe_float(context.get("target")),
        confidence=float(record.get("confidence") or 0.0),
        outcome=str(outcome_value),
        pnl=_safe_float(pnl_value),
    )


def _money(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _price(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def print_table(rows: list[SignalRow], *, limit: int) -> None:
    shown = rows[-limit:] if limit > 0 else rows
    if not shown:
        print("No shadow signals found.")
        print(f"Journal: {DEFAULT_JOURNAL}")
        return

    print(f"{'Created':<22} {'Sym':<5} {'Strategy':<20} {'Side':<5} {'Entry':>9} {'Stop':>9} {'Target':>9} {'Conf':>6} {'Outcome':<14} {'PnL':>9}")
    print("-" * 125)
    for row in shown:
        print(
            f"{row.created_at[:22]:<22} {row.symbol:<5} {row.strategy[:20]:<20} {row.side:<5} "
            f"{_price(row.entry):>9} {_price(row.stop):>9} {_price(row.target):>9} "
            f"{row.confidence:>6.2f} {row.outcome[:14]:<14} {_money(row.pnl):>9}"
        )


def print_summary(rows: list[SignalRow]) -> None:
    if not rows:
        return
    by_strategy = Counter(row.strategy for row in rows)
    by_outcome = Counter(row.outcome for row in rows)
    closed = [row for row in rows if row.outcome not in {"open", "pending", ""}]
    wins = [row for row in closed if (row.pnl or 0.0) > 0]
    total_pnl = sum(row.pnl or 0.0 for row in closed)
    win_rate = len(wins) / len(closed) if closed else 0.0

    print()
    print("Summary")
    print(f"  Signals: {len(rows)}")
    print(f"  Strategies: {dict(by_strategy)}")
    print(f"  Outcomes: {dict(by_outcome)}")
    print(f"  Closed forward-test signals: {len(closed)}")
    print(f"  Forward-test win rate: {win_rate:.1%}")
    print(f"  Forward-test P&L: {total_pnl:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="View shadow-only signal journal")
    parser.add_argument("--journal", type=Path, default=DEFAULT_JOURNAL)
    parser.add_argument("--strategy", default=None)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    records = load_shadow_signals(args.journal)
    rows = [to_row(r) for r in records]
    if args.strategy:
        rows = [row for row in rows if row.strategy == args.strategy]

    if args.json:
        print(json.dumps([row.__dict__ for row in rows], indent=2))
        return

    print_table(rows, limit=args.limit)
    print_summary(rows)


if __name__ == "__main__":
    main()
