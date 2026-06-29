"""
Read-only overlap report: QQQ/GLD rotation vs Momentum Rotation (shadow log comparison).

Reads accumulated forward-test logs and reports whether QQQ/GLD rotation
agrees with or conflicts with the existing multi-asset momentum rotation holdings.

Logs compared:
  data/qqq_gld_shadow_log.jsonl   -- selected: "QQQ" or "GLD"
  data/momentum_shadow_log.jsonl  -- holdings: list of top-2 assets

Usage:
    python scripts/qqq_gld_momentum_overlap_report.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QQQ_GLD_LOG = ROOT / "data" / "qqq_gld_shadow_log.jsonl"
MOMENTUM_LOG = ROOT / "data" / "momentum_shadow_log.jsonl"

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


def _qqq_gld_selected(entry: dict) -> str:
    return str(entry.get("selected", "unknown"))


def _momentum_holdings(entry: dict) -> list[str]:
    return list(entry.get("holdings", []))


def _nearest_momentum_date(target: str, momentum_dates: list[str]) -> str | None:
    """Find the most recent momentum log date on or before target date."""
    eligible = [d for d in momentum_dates if d <= target]
    return max(eligible) if eligible else None


def analyze(
    qqq_gld_log: dict[str, dict],
    momentum_log: dict[str, dict],
) -> dict:
    momentum_dates = sorted(momentum_log)

    rows: list[dict] = []
    for date in sorted(qqq_gld_log):
        qqq_gld_entry = qqq_gld_log[date]
        selected = _qqq_gld_selected(qqq_gld_entry)

        mom_date = _nearest_momentum_date(date, momentum_dates)
        mom_holdings: list[str] = []
        if mom_date:
            mom_holdings = _momentum_holdings(momentum_log[mom_date])

        agree = selected in mom_holdings
        rows.append({
            "date": date,
            "qqq_gld_selected": selected,
            "momentum_holdings": mom_holdings,
            "momentum_date": mom_date,
            "agree": agree,
        })

    matched_rows = [r for r in rows if r["momentum_date"] is not None]
    unmatched_rows = [r for r in rows if r["momentum_date"] is None]

    # Breakdowns use only rows with a comparable momentum log date.
    both_qqq = [r for r in matched_rows if r["qqq_gld_selected"] == "QQQ" and "QQQ" in r["momentum_holdings"]]
    qqq_gld_qqq_only = [r for r in matched_rows if r["qqq_gld_selected"] == "QQQ" and "QQQ" not in r["momentum_holdings"]]
    both_gld = [r for r in matched_rows if r["qqq_gld_selected"] == "GLD" and "GLD" in r["momentum_holdings"]]
    qqq_gld_gld_only = [r for r in matched_rows if r["qqq_gld_selected"] == "GLD" and "GLD" not in r["momentum_holdings"]]

    total_shared = len(matched_rows)
    total_agree = len(both_qqq) + len(both_gld)
    total_diverge = len(qqq_gld_qqq_only) + len(qqq_gld_gld_only)
    pct_agree = total_agree / total_shared * 100 if total_shared > 0 else 0.0

    qqq_gld_qqq_weeks = [r for r in matched_rows if r["qqq_gld_selected"] == "QQQ"]
    jaccard_num = len(both_qqq)
    jaccard_den = len(qqq_gld_qqq_weeks) + sum(1 for r in matched_rows if "QQQ" in r["momentum_holdings"]) - jaccard_num
    jaccard = jaccard_num / jaccard_den if jaccard_den > 0 else 0.0

    return {
        "rows": rows,
        "matched_rows": matched_rows,
        "unmatched_rows": unmatched_rows,
        "total_shared": total_shared,
        "total_agree": total_agree,
        "total_diverge": total_diverge,
        "pct_agree": pct_agree,
        "both_qqq": both_qqq,
        "qqq_gld_qqq_only": qqq_gld_qqq_only,
        "both_gld": both_gld,
        "qqq_gld_gld_only": qqq_gld_gld_only,
        "jaccard_qqq": jaccard,
    }


def _interpret(pct_agree: float) -> str:
    if pct_agree >= 70:
        return "HIGH AGREEMENT -- strategies may be redundant"
    if pct_agree >= 40:
        return "MODERATE AGREEMENT -- partial overlap, monitor"
    return "LOW AGREEMENT -- QQQ/GLD appears to add independent signals"


def print_report(
    qqq_gld_log: dict[str, dict],
    momentum_log: dict[str, dict],
    result: dict,
) -> None:
    print("\n" + "=" * 66)
    print("QQQ/GLD Rotation vs Momentum Rotation | Overlap Report")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 66)

    print(f"\nLogs loaded:")
    print(f"  QQQ/GLD log entries:  {len(qqq_gld_log)}")
    print(f"  Momentum log entries: {len(momentum_log)}")
    print(f"  Matched rows:         {result['total_shared']}")
    print(f"  Unmatched QQQ/GLD:    {len(result['unmatched_rows'])}")

    if result["total_shared"] < MINIMUM_ROWS_FOR_ANALYSIS:
        remaining = MINIMUM_ROWS_FOR_ANALYSIS - result["total_shared"]
        print(f"\n  [LOG BUILDING] Need {remaining} more matched rows for meaningful analysis.")
        print(f"  Stats below are preliminary.\n")

    print("\nDAILY BREAKDOWN:")
    for r in result["rows"]:
        mom_str = ", ".join(r["momentum_holdings"]) if r["momentum_holdings"] else "none"
        agree_str = "NO MATCH" if r["momentum_date"] is None else ("AGREE" if r["agree"] else "DIVERGE")
        print(f"  {r['date']}: QQQ/GLD={r['qqq_gld_selected']}  Momentum=[{mom_str}] ({r.get('momentum_date', '?')})  -> {agree_str}")

    print("\nSUMMARY:")
    print(f"  Total agree (selected in momentum):  {result['total_agree']}")
    print(f"  Total diverge:                       {result['total_diverge']}")
    print(f"  Agreement rate:                      {result['pct_agree']:.1f}%")
    print()
    print(f"  Both pick QQQ:             {len(result['both_qqq'])} rows")
    print(f"  QQQ/GLD=QQQ, Mom excludes: {len(result['qqq_gld_qqq_only'])} rows")
    print(f"  Both include GLD:          {len(result['both_gld'])} rows")
    print(f"  QQQ/GLD=GLD, Mom excludes: {len(result['qqq_gld_gld_only'])} rows")
    print(f"  Jaccard (QQQ selection):   {result['jaccard_qqq']:.3f}")

    print(f"\nOVERLAP INTERPRETATION:")
    if result["total_shared"] < MINIMUM_ROWS_FOR_ANALYSIS:
        print("  LOG BUILDING -- not enough matched rows for interpretation")
    else:
        print(f"  {_interpret(result['pct_agree'])}")

    print("\nDECISION:")
    pct = result["pct_agree"]
    if result["total_shared"] < MINIMUM_ROWS_FOR_ANALYSIS:
        print("  Keep logging. Do not infer independence or redundancy yet.")
        print("  Need matched QQQ/GLD and momentum rows before making a strategy decision.")
    elif pct >= 70:
        print("  QQQ/GLD rotation largely agrees with Momentum Rotation.")
        print("  Running both may double QQQ exposure without diversification benefit.")
        print("  Re-evaluate after 30+ log rows; consider merging into one rotation system.")
    elif pct >= 40:
        print("  Partial overlap. Monitor divergence periods -- they may reveal different regime sensitivity.")
        print("  Continue logging. Position sizing should account for potential concurrent QQQ exposure.")
    else:
        print("  QQQ/GLD rotation and Momentum Rotation diverge frequently.")
        print("  The two strategies respond to different lookback windows (40d vs 252d).")
        print("  Independent signals confirmed. Both loggers worth continuing.")
    print()


def main() -> int:
    qqq_gld_log = _load_log(QQQ_GLD_LOG)
    momentum_log = _load_log(MOMENTUM_LOG)
    result = analyze(qqq_gld_log, momentum_log)
    print_report(qqq_gld_log, momentum_log, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
