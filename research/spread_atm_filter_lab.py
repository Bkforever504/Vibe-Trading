#!/usr/bin/env python3
"""Options 1 + 3: Spread-tightness and ATM-proximity filter lab.

Hypothesis: the flip bot's negative executable expectancy is caused by wide
bid-ask spreads on cheap OTM options. If we restrict to tight-spread and/or
higher-premium (more ATM) entries, does executable ask-to-bid expectancy turn
positive?

Filters tested (preregistered):
  Spread gates:
    spread_le_3c   : spread_cents <= 3  (p50 of corpus)
    spread_le_5c   : spread_cents <= 5  (p61)
    spread_le_8c   : spread_cents <= 8  (p75)
    spread_le_10c  : spread_cents <= 10 (p81)
  ATM-proxy gates (entry_price_est as ATM proxy — higher = closer to ATM):
    entry_ge_50c   : entry >= $0.50
    entry_ge_100c  : entry >= $1.00
    entry_ge_200c  : entry >= $2.00
  Combined:
    spread3_entry50  : spread <= 3c AND entry >= $0.50
    spread5_entry100 : spread <= 5c AND entry >= $1.00
  Baseline:
    baseline         : all lifecycles (control)

Executable return = (exit_selection_bid - entry_selection_ask) / entry_selection_ask * 100
Fee proxy: 1.5% per trade (round-trip friction).

Read-only. No execution. No config mutation. No promotion authority.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_CANDIDATES_PATH = ROOT / "data" / "flip_shadow_candidates_log.jsonl"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "spread_atm_filter_lab_results.json"
DEFAULT_FEE_PCT = 1.5
MIN_SAMPLES_REVIEW = 30
MIN_DATES_REVIEW = 20


@dataclass(frozen=True)
class SpreadLife:
    lifecycle_id: str
    date: str
    symbol: str
    spread_cents: float
    entry_ask: float          # what you actually pay (selection_ask at entry)
    entry_price_est: float    # mid-based estimate
    exit_bid: float           # what you actually receive (selection_bid at exit)
    executable_return_pct: float   # (exit_bid - entry_ask) / entry_ask * 100
    midpoint_return_pct: float     # return_pct_at_mark from log (mid-based)


def _num(v: Any) -> float | None:
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def load_lifecycles(path: Path) -> list[SpreadLife]:
    if not path.exists():
        return []
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        lid = row.get("lifecycle_id")
        if isinstance(lid, str) and lid:
            groups[lid].append(row)

    out: list[SpreadLife] = []
    for lid, rows in groups.items():
        rows.sort(key=lambda r: str(r.get("scanned_at") or ""))
        entry_rows = [r for r in rows if r.get("event_type") == "shadow_entry"]
        exit_rows = [r for r in rows if r.get("event_type") == "shadow_exit"]
        if not entry_rows or not exit_rows:
            continue
        entry = entry_rows[0]
        exit_ = exit_rows[-1]

        sc = _num(entry.get("spread_cents"))
        e_ask = _num(entry.get("selection_ask"))
        e_est = _num(entry.get("entry_price_est"))
        x_bid = _num(exit_.get("selection_bid"))
        mid_ret = _num(exit_.get("return_pct_at_mark"))

        if sc is None or e_ask is None or e_ask <= 0 or x_bid is None:
            continue
        if e_est is None:
            e_est = e_ask

        exec_ret = (x_bid - e_ask) / e_ask * 100.0
        if mid_ret is None:
            mid_ret = exec_ret  # fallback

        out.append(SpreadLife(
            lifecycle_id=lid,
            date=str(entry.get("date") or ""),
            symbol=str(entry.get("symbol") or ""),
            spread_cents=sc,
            entry_ask=e_ask,
            entry_price_est=e_est,
            exit_bid=x_bid,
            executable_return_pct=round(exec_ret, 4),
            midpoint_return_pct=round(mid_ret, 4),
        ))
    return out


def _cohort(returns: list[float], fee_pct: float, label: str, dates: set) -> dict[str, Any]:
    n = len(returns)
    if n == 0:
        return {"label": label, "n": 0, "unique_dates": 0}
    adj = [r - fee_pct for r in returns]
    adj2 = [r - fee_pct * 2 for r in returns]
    wins = [r for r in adj if r > 0]
    losses = [r for r in adj if r <= 0]
    pf = round(sum(wins) / abs(sum(losses)), 3) if losses else float("inf")
    remove_n = max(1, int(n * 0.05))
    top5_adj = [r - fee_pct for r in sorted(returns)[:-remove_n]]
    top5_exp = round(sum(top5_adj) / len(top5_adj), 3) if top5_adj else None
    failed = []
    if n < MIN_SAMPLES_REVIEW:
        failed.append(f"insufficient_samples_{n}/{MIN_SAMPLES_REVIEW}")
    if len(dates) < MIN_DATES_REVIEW:
        failed.append(f"insufficient_dates_{len(dates)}/{MIN_DATES_REVIEW}")
    if (sum(adj) / n) <= 0:
        failed.append("post_fee_expectancy_not_positive")
    if (sum(adj2) / n) <= 0:
        failed.append("doubled_cost_expectancy_not_positive")
    if top5_exp is not None and top5_exp <= 0:
        failed.append("top5_removed_expectancy_not_positive")
    return {
        "label": label,
        "n": n,
        "unique_dates": len(dates),
        "post_fee_expectancy_pct": round(sum(adj) / n, 3),
        "doubled_cost_expectancy_pct": round(sum(adj2) / n, 3),
        "top5_removed_expectancy_pct": top5_exp,
        "win_rate": round(len(wins) / n, 3),
        "profit_factor": pf,
        "mean_winner_pct": round(sum(wins) / len(wins), 3) if wins else None,
        "mean_loser_pct": round(sum(losses) / len(losses), 3) if losses else None,
        "review_gate": {"passed": len(failed) == 0, "failed_checks": failed},
    }


FILTER_DEFS: list[tuple[str, Any]] = [
    ("baseline",          lambda l: True),
    ("spread_le_3c",      lambda l: l.spread_cents <= 3),
    ("spread_le_5c",      lambda l: l.spread_cents <= 5),
    ("spread_le_8c",      lambda l: l.spread_cents <= 8),
    ("spread_le_10c",     lambda l: l.spread_cents <= 10),
    ("entry_ge_50c",      lambda l: l.entry_ask >= 0.50),
    ("entry_ge_100c",     lambda l: l.entry_ask >= 1.00),
    ("entry_ge_200c",     lambda l: l.entry_ask >= 2.00),
    ("spread3_entry50",   lambda l: l.spread_cents <= 3 and l.entry_ask >= 0.50),
    ("spread5_entry100",  lambda l: l.spread_cents <= 5 and l.entry_ask >= 1.00),
]


def build_report(
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    fee_pct: float = DEFAULT_FEE_PCT,
) -> dict[str, Any]:
    lives = load_lifecycles(candidates_path)
    results = []
    for name, fn in FILTER_DEFS:
        subset = [l for l in lives if fn(l)]
        exec_returns = [l.executable_return_pct for l in subset]
        mid_returns = [l.midpoint_return_pct for l in subset]
        dates = {l.date for l in subset if l.date}
        exec_stats = _cohort(exec_returns, fee_pct, f"{name}_exec", dates)
        mid_stats = _cohort(mid_returns, fee_pct, f"{name}_mid", dates)
        results.append({
            "filter": name,
            "n": len(subset),
            "unique_dates": len(dates),
            "executable": exec_stats,
            "midpoint_diagnostic": mid_stats,
        })
    results.sort(
        key=lambda r: r["executable"].get("post_fee_expectancy_pct", -999),
        reverse=True,
    )
    return {
        "provider": "spread_atm_filter_lab",
        "mode": "read_only_executable_replay",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "execution_enabled": False,
        "can_submit_orders": False,
        "automatic_parameter_changes": False,
        "promotion_authority": "shadow_challenger_only",
        "candidates_path": str(candidates_path),
        "total_lifecycles": len(lives),
        "all_unique_dates": len({l.date for l in lives if l.date}),
        "fee_pct_per_trade": fee_pct,
        "filters_ranked": results,
        "notes": (
            "executable_return = (exit_selection_bid - entry_selection_ask) / entry_selection_ask. "
            "midpoint_diagnostic uses return_pct_at_mark (mid-based, not executable). "
            "entry_ask >= X is an ATM proximity proxy — higher premium = closer to ATM."
        ),
    }


def write_report(report: dict[str, Any], out_path: Path = DEFAULT_OUTPUT_PATH) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, out_path)


def _summary(report: dict[str, Any]) -> str:
    lines = [
        f"total={report['total_lifecycles']} dates={report['all_unique_dates']} fee={report['fee_pct_per_trade']}%",
        "",
        f"{'filter':<20} {'n':>5} {'dates':>6} {'exec%':>8} {'2x%':>8} {'top5-%':>8} {'wr':>6} {'pf':>6} {'gate'}",
        "-" * 90,
    ]
    for r in report["filters_ranked"]:
        e = r["executable"]
        g = e.get("review_gate", {})
        gate_str = "PASS" if g.get("passed") else f"FAIL({len(g.get('failed_checks', []))})"
        pf = e.get("profit_factor", 0)
        lines.append(
            f"{r['filter']:<20} {r['n']:>5} {r['unique_dates']:>6} "
            f"{e.get('post_fee_expectancy_pct', 0):>8.2f} "
            f"{e.get('doubled_cost_expectancy_pct', 0):>8.2f} "
            f"{e.get('top5_removed_expectancy_pct') or 0:>8.2f} "
            f"{e.get('win_rate', 0):>6.2%} "
            f"{pf if pf != float('inf') else 99.0:>6.2f} "
            f"{gate_str}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--fee-pct", type=float, default=DEFAULT_FEE_PCT)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(candidates_path=args.candidates, fee_pct=args.fee_pct)
    write_report(report, args.out)
    if args.do_print:
        print(_summary(report))
        print(f"\nreport: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
