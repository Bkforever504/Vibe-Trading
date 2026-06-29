"""
Read-only overlap report: Williams %R QQQ vs RSI-2 QQQ (shadow log comparison).

Reads accumulated forward-test logs and reports whether Williams %R adds
independent signal value beyond RSI-2, or whether they are correlated.

Logs compared:
  data/williams_r_shadow_log.jsonl  -- primary_setup tracks QQQ WR(2)
  data/rsi2_shadow_log.jsonl        -- primary_setup tracks QQQ RSI(2)

Usage:
    python scripts/williams_r_rsi2_overlap_report.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WR_LOG = ROOT / "data" / "williams_r_shadow_log.jsonl"
RSI2_LOG = ROOT / "data" / "rsi2_shadow_log.jsonl"

MINIMUM_ROWS_FOR_ANALYSIS = 5


def _load_log(path: Path) -> dict[str, dict]:
    """Return {date: entry} from a JSONL log. Skips malformed lines."""
    if not path.exists():
        return {}
    result: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("date"):
            result[row["date"]] = row
    return result


def _in_position(entry: dict, setup_key: str = "primary_setup") -> bool:
    return bool(entry.get(setup_key, {}).get("in_position", False))


def _action(entry: dict, setup_key: str = "primary_setup") -> str:
    return str(entry.get(setup_key, {}).get("action", "unknown"))


def analyze(
    wr_log: dict[str, dict],
    rsi2_log: dict[str, dict],
) -> dict:
    shared_dates = sorted(set(wr_log) & set(rsi2_log))
    wr_only_dates = sorted(set(wr_log) - set(rsi2_log))
    rsi2_only_dates = sorted(set(rsi2_log) - set(wr_log))

    both_in: list[str] = []
    only_wr_in: list[str] = []
    only_rsi2_in: list[str] = []
    both_flat: list[str] = []

    for d in shared_dates:
        wr_in = _in_position(wr_log[d])
        rsi2_in = _in_position(rsi2_log[d])
        if wr_in and rsi2_in:
            both_in.append(d)
        elif wr_in:
            only_wr_in.append(d)
        elif rsi2_in:
            only_rsi2_in.append(d)
        else:
            both_flat.append(d)

    wr_entry_dates = [d for d in wr_log if _action(wr_log[d]) == "enter_long"]
    rsi2_entry_dates = [d for d in rsi2_log if _action(rsi2_log[d]) == "enter_long"]

    # Among WR entries, how many overlap with RSI-2 in-position?
    wr_entries_with_rsi2_active = [
        d for d in wr_entry_dates if d in rsi2_log and _in_position(rsi2_log[d])
    ]
    # Among RSI-2 entries, how many overlap with WR in-position?
    rsi2_entries_with_wr_active = [
        d for d in rsi2_entry_dates if d in wr_log and _in_position(wr_log[d])
    ]

    union = len(both_in) + len(only_wr_in) + len(only_rsi2_in)
    jaccard = len(both_in) / union if union > 0 else 0.0
    pct_wr_entries_with_rsi2 = (
        len(wr_entries_with_rsi2_active) / len(wr_entry_dates) * 100
        if wr_entry_dates else 0.0
    )

    return {
        "shared_dates": len(shared_dates),
        "wr_only_dates": len(wr_only_dates),
        "rsi2_only_dates": len(rsi2_only_dates),
        "both_in": both_in,
        "only_wr_in": only_wr_in,
        "only_rsi2_in": only_rsi2_in,
        "both_flat": both_flat,
        "wr_entry_dates": wr_entry_dates,
        "rsi2_entry_dates": rsi2_entry_dates,
        "wr_entries_with_rsi2_active": wr_entries_with_rsi2_active,
        "rsi2_entries_with_wr_active": rsi2_entries_with_wr_active,
        "jaccard": jaccard,
        "pct_wr_entries_with_rsi2_active": pct_wr_entries_with_rsi2,
    }


def _interpret(jaccard: float) -> str:
    if jaccard >= 0.70:
        return "HIGH -- strategies likely redundant"
    if jaccard >= 0.40:
        return "MODERATE -- partial redundancy, monitor live"
    return "LOW -- WR appears to add independent value"


def print_report(
    wr_log: dict[str, dict],
    rsi2_log: dict[str, dict],
    result: dict,
) -> None:
    print("\n" + "=" * 66)
    print("Williams %R vs RSI-2 | Shadow Log Overlap Report")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 66)

    print(f"\nLogs loaded:")
    print(f"  Williams %R entries: {len(wr_log)}")
    print(f"  RSI-2 entries:       {len(rsi2_log)}")
    print(f"  Shared dates:        {result['shared_dates']}")

    if result["shared_dates"] < MINIMUM_ROWS_FOR_ANALYSIS:
        remaining = MINIMUM_ROWS_FOR_ANALYSIS - result["shared_dates"]
        print(f"\n  [LOG BUILDING] Need {remaining} more shared log rows for meaningful analysis.")
        print(f"  Overlap stats below are preliminary.\n")

    print("\nIN-POSITION BREAKDOWN (shared dates):")
    print(f"  Both in trade:   {len(result['both_in'])} days  {result['both_in'] or ''}")
    print(f"  Only WR in:      {len(result['only_wr_in'])} days  {result['only_wr_in'] or ''}")
    print(f"  Only RSI-2 in:   {len(result['only_rsi2_in'])} days  {result['only_rsi2_in'] or ''}")
    print(f"  Both flat:       {len(result['both_flat'])} days")

    print("\nENTRY SIGNAL BREAKDOWN:")
    print(f"  WR entry signals:   {len(result['wr_entry_dates'])}  {result['wr_entry_dates'] or ''}")
    print(f"  RSI-2 entry signals:{len(result['rsi2_entry_dates'])}  {result['rsi2_entry_dates'] or ''}")
    print(f"  WR entries where RSI-2 also active: {len(result['wr_entries_with_rsi2_active'])}")
    print(f"  RSI-2 entries where WR also active: {len(result['rsi2_entries_with_wr_active'])}")

    print(f"\nOVERLAP SCORE:")
    print(f"  Jaccard (shared days): {result['jaccard']:.3f}")
    if result["shared_dates"] < MINIMUM_ROWS_FOR_ANALYSIS:
        print("  Interpretation:        LOG BUILDING -- not enough shared rows")
    else:
        print(f"  Interpretation:        {_interpret(result['jaccard'])}")
    pct = result["pct_wr_entries_with_rsi2_active"]
    print(f"  WR entry overlap with RSI-2: {pct:.1f}%")

    print("\nDECISION:")
    j = result["jaccard"]
    if result["shared_dates"] < MINIMUM_ROWS_FOR_ANALYSIS:
        print("  Keep logging. Do not infer independence or redundancy yet.")
        print("  Need more shared Williams %R and RSI-2 rows before making a strategy decision.")
    elif j >= 0.70:
        print("  Williams %R does NOT add independent value over RSI-2.")
        print("  Consider using WR only as a confirmation layer, not a standalone logger.")
    elif j >= 0.40:
        print("  Williams %R has partial overlap with RSI-2.")
        print("  Continue logging. Re-evaluate when 30+ shared rows available.")
    else:
        print("  Williams %R fires independently of RSI-2.")
        print("  Both loggers are tracking distinct oversold events. Continue accumulating.")
    print()


def main() -> int:
    wr_log = _load_log(WR_LOG)
    rsi2_log = _load_log(RSI2_LOG)
    result = analyze(wr_log, rsi2_log)
    print_report(wr_log, rsi2_log, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
