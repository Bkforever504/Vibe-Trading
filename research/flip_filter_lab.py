#!/usr/bin/env python3
"""Entry-universe filter comparison lab for flip bot shadow lifecycles.

Tests whether filtering the ENTRY UNIVERSE by symbol type, entry time bucket,
or first-mark momentum improves post-fee expectancy vs. the unfiltered baseline.

Filters tested (preregistered, not tuned post-hoc):
  - baseline          : all resolved lifecycles
  - etf_only          : SPY / QQQ / IWM only
  - single_stock_only : exclude SPY / QQQ / IWM
  - orb_09_30_only    : lifecycle_id time bucket == '09:30'
  - not_09_30         : all other time buckets
  - first_mark_green  : first shadow_mark return > 0 (momentum confirmation)
  - first_mark_red    : first shadow_mark return <= 0
  - stock_09_30       : single-stock AND 09:30 bucket (combined)
  - green_09_30       : first mark green AND 09:30 bucket (combined)

NOTE: first_mark_green / first_mark_red and the combined filters are
diagnostic only — they require knowing the first mark AFTER entry, so they
cannot be used as pure entry filters. They test whether momentum confirmation
is predictive and whether an early-exit rule could help.

Read-only. No execution. No config mutation. No promotion.
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
DEFAULT_OUTPUT_PATH = ROOT / "data" / "flip_filter_lab_results.json"
DEFAULT_FEE_PCT = 1.5
MIN_SAMPLES_REVIEW = 30
MIN_DATES_REVIEW = 20
ETF_SYMBOLS = {"SPY", "QQQ", "IWM"}


@dataclass(frozen=True)
class FilteredLife:
    lifecycle_id: str
    date: str
    symbol: str
    time_bucket: str          # 5th segment of lifecycle_id, e.g. '09:30'
    is_etf: bool
    realized_return_pct: float  # exit return_pct_at_mark (bid-based vs entry)
    first_mark_return_pct: float | None  # first shadow_mark return, None if no marks


def _num(v: Any) -> float | None:
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def load_lifecycles(path: Path) -> list[FilteredLife]:
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

    out: list[FilteredLife] = []
    for lid, rows in groups.items():
        rows.sort(key=lambda r: str(r.get("scanned_at") or ""))
        entry_rows = [r for r in rows if r.get("event_type") == "shadow_entry"]
        exit_rows = [r for r in rows if r.get("event_type") == "shadow_exit"]
        if not entry_rows or not exit_rows:
            continue
        entry = entry_rows[0]
        exit_ = exit_rows[-1]

        ret = _num(exit_.get("return_pct_at_mark"))
        if ret is None:
            # fallback: compute from entry_price_est vs exit bid
            ep = _num(entry.get("entry_price_est")) or _num(entry.get("selection_bid"))
            xb = _num(exit_.get("selection_bid")) or _num(exit_.get("mark_price"))
            if ep and xb and ep > 0:
                ret = (xb - ep) / ep * 100.0
        if ret is None:
            continue

        parts = lid.split("|")
        time_bucket = parts[4] if len(parts) >= 5 else "unknown"
        symbol = str(entry.get("symbol") or "")

        # Future first-mark gates can close on the first observation, so the
        # first post-entry observation may be a shadow_exit rather than a mark.
        mark_rows = [
            r for r in rows
            if (
                r.get("event_type") == "shadow_mark"
                or (
                    r.get("event_type") == "shadow_exit"
                    and r.get("mark_reason") == "first_mark_momentum_not_confirmed"
                )
            )
            and r is not entry
        ]
        first_mark_ret: float | None = None
        if mark_rows:
            fm = mark_rows[0]
            fmr = _num(fm.get("return_pct_at_mark"))
            if fmr is None:
                ep = _num(entry.get("entry_price_est")) or _num(entry.get("selection_bid"))
                fb = _num(fm.get("selection_bid")) or _num(fm.get("mark_price"))
                if ep and fb and ep > 0:
                    fmr = (fb - ep) / ep * 100.0
            first_mark_ret = fmr

        out.append(FilteredLife(
            lifecycle_id=lid,
            date=str(entry.get("date") or ""),
            symbol=symbol,
            time_bucket=time_bucket,
            is_etf=symbol in ETF_SYMBOLS,
            realized_return_pct=round(ret, 4),
            first_mark_return_pct=round(first_mark_ret, 4) if first_mark_ret is not None else None,
        ))
    return out


def _cohort_stats(returns: list[float], fee_pct: float, label: str) -> dict[str, Any]:
    n = len(returns)
    if n == 0:
        return {"n": 0, "label": label}
    adj = [r - fee_pct for r in returns]
    adj2 = [r - fee_pct * 2 for r in returns]
    wins = [r for r in adj if r > 0]
    losses = [r for r in adj if r <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = round(gross_profit / gross_loss, 3) if gross_loss > 0 else float("inf")

    sorted_r = sorted(returns)
    remove_n = max(1, int(n * 0.05))
    top5_removed = sorted_r[:-remove_n]
    top5_adj = [r - fee_pct for r in top5_removed]
    top5_exp = round(sum(top5_adj) / len(top5_adj), 3) if top5_adj else None

    return {
        "label": label,
        "n": n,
        "post_fee_expectancy_pct": round(sum(adj) / n, 3),
        "doubled_cost_expectancy_pct": round(sum(adj2) / n, 3),
        "top5_removed_expectancy_pct": top5_exp,
        "win_rate": round(sum(1 for r in adj if r > 0) / n, 3),
        "profit_factor": pf,
        "mean_winner_pct": round(sum(wins) / len(wins), 3) if wins else None,
        "mean_loser_pct": round(sum(losses) / len(losses), 3) if losses else None,
    }


def review_gate(stats: dict[str, Any], unique_dates: int) -> dict[str, Any]:
    failed = []
    if stats.get("n", 0) < MIN_SAMPLES_REVIEW:
        failed.append(f"insufficient_samples_{stats.get('n')}/{MIN_SAMPLES_REVIEW}")
    if unique_dates < MIN_DATES_REVIEW:
        failed.append(f"insufficient_dates_{unique_dates}/{MIN_DATES_REVIEW}")
    if (stats.get("post_fee_expectancy_pct") or -999) <= 0:
        failed.append("post_fee_expectancy_not_positive")
    if (stats.get("doubled_cost_expectancy_pct") or -999) <= 0:
        failed.append("doubled_cost_expectancy_not_positive")
    if (stats.get("top5_removed_expectancy_pct") or -999) <= 0:
        failed.append("top5_removed_expectancy_not_positive")
    return {"passed": len(failed) == 0, "failed_checks": failed}


FILTER_DEFS: list[tuple[str, Any]] = [
    ("baseline",         lambda l: True),
    ("etf_only",         lambda l: l.is_etf),
    ("single_stock_only", lambda l: not l.is_etf),
    ("orb_09_30_only",   lambda l: l.time_bucket == "09:30"),
    ("not_09_30",        lambda l: l.time_bucket != "09:30"),
    ("first_mark_green", lambda l: l.first_mark_return_pct is not None and l.first_mark_return_pct > 0),
    ("first_mark_red",   lambda l: l.first_mark_return_pct is not None and l.first_mark_return_pct <= 0),
    ("stock_09_30",      lambda l: not l.is_etf and l.time_bucket == "09:30"),
    ("green_09_30",      lambda l: l.time_bucket == "09:30" and l.first_mark_return_pct is not None and l.first_mark_return_pct > 0),
]


def build_report(
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    fee_pct: float = DEFAULT_FEE_PCT,
) -> dict[str, Any]:
    lives = load_lifecycles(candidates_path)
    results = []
    for name, fn in FILTER_DEFS:
        subset = [l for l in lives if fn(l)]
        returns = [l.realized_return_pct for l in subset]
        dates = {l.date for l in subset if l.date}
        stats = _cohort_stats(returns, fee_pct, name)
        gate = review_gate(stats, len(dates))
        symbols_in = sorted({l.symbol for l in subset})
        time_buckets = sorted({l.time_bucket for l in subset})
        results.append({
            "filter": name,
            "n": len(subset),
            "unique_dates": len(dates),
            "symbols": symbols_in,
            "time_buckets": time_buckets,
            "stats": stats,
            "review_gate": gate,
        })

    # sort by post_fee_expectancy descending
    results.sort(key=lambda r: r["stats"].get("post_fee_expectancy_pct", -999), reverse=True)

    return {
        "provider": "flip_filter_lab",
        "mode": "read_only_filter_comparison",
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
            "first_mark_green/red and combined green_09_30 filters require post-entry "
            "information — diagnostic only, not a pure entry filter. "
            "Practical application: early-exit rule if not green by mark 1."
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
        f"{'filter':<22} {'n':>5} {'dates':>6} {'exp%':>7} {'2x':>7} {'top5-':>7} {'wr':>6} {'pf':>6} {'gate'}",
        "-" * 82,
    ]
    for r in report["filters_ranked"]:
        s = r["stats"]
        g = r["review_gate"]
        gate_str = "PASS" if g["passed"] else f"FAIL({len(g['failed_checks'])})"
        lines.append(
            f"{r['filter']:<22} {r['n']:>5} {r['unique_dates']:>6} "
            f"{s.get('post_fee_expectancy_pct', 0):>7.2f} "
            f"{s.get('doubled_cost_expectancy_pct', 0):>7.2f} "
            f"{s.get('top5_removed_expectancy_pct', 0) if s.get('top5_removed_expectancy_pct') is not None else 0:>7.2f} "
            f"{s.get('win_rate', 0):>6.2%} "
            f"{s.get('profit_factor', 0) if s.get('profit_factor') != float('inf') else 99.0:>6.2f} "
            f"{gate_str}"
        )
    lines.append("")
    lines.append("NOTE: first_mark_green/green_09_30 require post-entry info — diagnostic only.")
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
