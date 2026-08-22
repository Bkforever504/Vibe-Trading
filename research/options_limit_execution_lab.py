#!/usr/bin/env python3
"""Entry-side execution economics on shadow-directional lifecycles.

Reads `data/flip_shadow_candidates_log.jsonl`. For each entered lifecycle,
compares four preregistered entry-fill policies:

  - aggressive_ask     : marketable at ask (assumed always filled at entry mark)
  - patient_mid        : limit at midpoint, fills only if next mark's ask <= mid
  - patient_bid        : limit at bid, fills only if next mark's ask <= bid
  - concession_1tick   : limit at (bid + 1 penny), same fill rule against ask

For each policy, reports: fill rate, mean realized return over trade horizon,
opportunity cost of non-fills (assumed 0 realized on missed trades), net
expectancy including friction, and adverse-selection proxy (return over the
first 15 minutes post-fill).

Read-only. Coarse 5-minute mark cadence limits precision vs. sub-second labs.
Never enables execution. Never mutates production config.
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
DEFAULT_OUTPUT_PATH = ROOT / "data" / "options_limit_execution_lab_results.json"
DEFAULT_FEE_PER_TRADE_PCT = 1.5


@dataclass(frozen=True)
class EntryMark:
    ts: str
    bid: float
    ask: float
    mid: float


@dataclass(frozen=True)
class LifecycleE:
    lifecycle_id: str
    date: str
    symbol: str
    day_type: str
    entry: EntryMark
    marks: tuple[EntryMark, ...]        # forward marks after entry
    realized_bid_return_pct: float      # final bid return using entry ask baseline
    horizon_15m_return_pct: float | None
    horizon_60m_return_pct: float | None


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def load_lifecycles(path: Path) -> list[LifecycleE]:
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

    out: list[LifecycleE] = []
    for lid, rows in groups.items():
        rows.sort(key=lambda r: str(r.get("scanned_at") or ""))
        entry_rows = [r for r in rows if r.get("event_type") == "shadow_entry"]
        exit_rows = [r for r in rows if r.get("event_type") == "shadow_exit"]
        if not entry_rows or not exit_rows:
            continue
        entry = entry_rows[0]
        e_bid = _num(entry.get("selection_bid"))
        e_ask = _num(entry.get("selection_ask"))
        if e_bid is None or e_ask is None or e_ask <= 0:
            continue
        e_mid = (e_bid + e_ask) / 2.0
        entry_mark = EntryMark(ts=str(entry.get("scanned_at") or ""), bid=e_bid, ask=e_ask, mid=e_mid)
        entry_dt = _parse_ts(entry_mark.ts)
        if entry_dt is None:
            continue

        forward: list[EntryMark] = []
        h15 = None
        h60 = None
        for row in rows:
            if row is entry:
                continue
            ts = str(row.get("scanned_at") or "")
            dt = _parse_ts(ts)
            if dt is None or dt <= entry_dt:
                continue
            bid = _num(row.get("selection_bid"))
            ask = _num(row.get("selection_ask"))
            if bid is None or ask is None:
                continue
            forward.append(EntryMark(ts=ts, bid=bid, ask=ask, mid=(bid + ask) / 2.0))
            elapsed_min = (dt - entry_dt).total_seconds() / 60.0
            if h15 is None and elapsed_min >= 15.0:
                h15 = (bid - e_ask) / e_ask * 100.0
            if h60 is None and elapsed_min >= 60.0:
                h60 = (bid - e_ask) / e_ask * 100.0
        if not forward:
            continue
        final_bid = forward[-1].bid
        realized = (final_bid - e_ask) / e_ask * 100.0
        out.append(LifecycleE(
            lifecycle_id=lid,
            date=str(entry.get("date") or ""),
            symbol=str(entry.get("symbol") or ""),
            day_type=str(entry.get("day_type") or "unknown"),
            entry=entry_mark,
            marks=tuple(forward),
            realized_bid_return_pct=round(realized, 4),
            horizon_15m_return_pct=round(h15, 4) if h15 is not None else None,
            horizon_60m_return_pct=round(h60, 4) if h60 is not None else None,
        ))
    return out


def _try_passive_fill(life: LifecycleE, limit_price: float, max_wait_marks: int = 3) -> bool:
    """Filled if any forward mark's ASK <= limit_price within wait window."""
    for m in life.marks[:max_wait_marks]:
        if m.ask <= limit_price:
            return True
    return False


def _policy_aggressive_ask(life: LifecycleE) -> tuple[bool, float, float]:
    """Marketable at ask: always fills. Fill price = entry ask. Return uses realized."""
    return True, life.entry.ask, life.realized_bid_return_pct


def _policy_patient(
    life: LifecycleE, limit_price: float, max_wait_marks: int = 3
) -> tuple[bool, float, float]:
    """Passive limit. Fill only if ask crosses down to limit. Return recomputed from lower fill price."""
    if not _try_passive_fill(life, limit_price, max_wait_marks):
        return False, 0.0, 0.0
    final_bid = life.marks[-1].bid
    ret = (final_bid - limit_price) / limit_price * 100.0
    return True, limit_price, round(ret, 4)


POLICIES = {
    "aggressive_ask":  lambda l: _policy_aggressive_ask(l),
    "patient_mid":     lambda l: _policy_patient(l, l.entry.mid),
    "patient_bid":     lambda l: _policy_patient(l, l.entry.bid),
    "concession_1c":   lambda l: _policy_patient(l, round(l.entry.bid + 0.01, 2)),
}


def _cohort(returns: list[float], fee_pct: float, fills: int, attempts: int) -> dict[str, Any]:
    fill_rate = round(fills / attempts, 4) if attempts else 0.0
    if not returns:
        return {"attempts": attempts, "fills": 0, "fill_rate": fill_rate,
                "expectancy_per_attempt_pct": 0.0, "expectancy_per_fill_pct": None}
    adjusted = [r - fee_pct for r in returns]
    per_fill = round(sum(adjusted) / len(adjusted), 3)
    # per attempt: missed trades contribute 0 realized (opportunity cost is the
    # signed value of missed executions, which we can't confirm without the
    # counterfactual entry, so we report both).
    per_attempt = round(sum(adjusted) / attempts, 3) if attempts else 0.0
    return {
        "attempts": attempts,
        "fills": fills,
        "fill_rate": fill_rate,
        "expectancy_per_fill_pct": per_fill,
        "expectancy_per_attempt_pct": per_attempt,
    }


def evaluate_policy(name: str, fn, lives: list[LifecycleE], fee_pct: float) -> dict[str, Any]:
    returns = []
    fills = 0
    for l in lives:
        filled, _, ret = fn(l)
        if filled:
            fills += 1
            returns.append(ret)
    base = _cohort(returns, fee_pct=0.0, fills=fills, attempts=len(lives))
    with_fee = _cohort(returns, fee_pct=fee_pct, fills=fills, attempts=len(lives))
    doubled = _cohort(returns, fee_pct=fee_pct * 2.0, fills=fills, attempts=len(lives))
    # opportunity cost proxy: if we assume missed trades would have filled at ask,
    # they would have contributed realized_bid_return_pct - fee_pct
    missed_hypothetical = []
    for l in lives:
        filled, _, _ = fn(l)
        if not filled:
            missed_hypothetical.append(l.realized_bid_return_pct - fee_pct)
    missed_mean = round(sum(missed_hypothetical) / len(missed_hypothetical), 3) if missed_hypothetical else 0.0
    return {
        "policy": name,
        "pre_fee": base,
        "post_fee": with_fee,
        "doubled_cost": doubled,
        "missed_trade_hypothetical_return_pct_mean": missed_mean,
        "missed_trade_count": len(missed_hypothetical),
    }


def _adverse_selection(lives: list[LifecycleE]) -> dict[str, Any]:
    h15 = [l.horizon_15m_return_pct for l in lives if l.horizon_15m_return_pct is not None]
    h60 = [l.horizon_60m_return_pct for l in lives if l.horizon_60m_return_pct is not None]
    def _stats(xs):
        if not xs: return None
        return {
            "n": len(xs),
            "mean_pct": round(sum(xs)/len(xs), 3),
            "median_pct": round(sorted(xs)[len(xs)//2], 3),
            "pct_negative": round(sum(1 for x in xs if x < 0)/len(xs), 3),
        }
    return {"15m_bid_return_vs_entry_ask": _stats(h15), "60m_bid_return_vs_entry_ask": _stats(h60)}


def _spread_distribution(lives: list[LifecycleE]) -> dict[str, Any]:
    spreads_pct = []
    for l in lives:
        if l.entry.mid > 0:
            spreads_pct.append((l.entry.ask - l.entry.bid) / l.entry.mid * 100.0)
    if not spreads_pct:
        return {"n": 0}
    spreads_pct.sort()
    def pct(p): return round(spreads_pct[max(0, int(len(spreads_pct) * p) - 1)], 2)
    return {
        "n": len(spreads_pct),
        "mean_pct": round(sum(spreads_pct)/len(spreads_pct), 2),
        "p50": pct(0.50), "p75": pct(0.75), "p90": pct(0.90), "p99": pct(0.99),
    }


def build_report(
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    fee_pct: float = DEFAULT_FEE_PER_TRADE_PCT,
) -> dict[str, Any]:
    lives = load_lifecycles(candidates_path)
    policy_rows = [evaluate_policy(name, fn, lives, fee_pct) for name, fn in POLICIES.items()]
    policy_rows.sort(
        key=lambda r: r["post_fee"].get("expectancy_per_attempt_pct", 0), reverse=True
    )
    return {
        "provider": "options_limit_execution_lab",
        "mode": "read_only_5m_cadence_replay",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "execution_enabled": False,
        "can_submit_orders": False,
        "automatic_parameter_changes": False,
        "candidates_path": str(candidates_path),
        "total_lifecycles": len(lives),
        "unique_dates": len({l.date for l in lives if l.date}),
        "fee_pct_per_trade": fee_pct,
        "adverse_selection": _adverse_selection(lives),
        "entry_spread_pct_distribution": _spread_distribution(lives),
        "policies_ranked": policy_rows,
        "notes": (
            "5-minute mark cadence gives coarse fill inference. Missed-trade "
            "hypothetical return assumes ask fill; true opportunity cost may be "
            "smaller due to selection bias in when passive limits would sit."
        ),
        "promotion_authority": "shadow_challenger_only",
    }


def write_report(report: dict[str, Any], out_path: Path = DEFAULT_OUTPUT_PATH) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, out_path)


def _summary(report: dict[str, Any]) -> str:
    lines = [
        f"lifecycles={report['total_lifecycles']} dates={report['unique_dates']} "
        f"fee={report['fee_pct_per_trade']}%",
        f"spread_dist: {report['entry_spread_pct_distribution']}",
        f"adverse_15m: {report['adverse_selection'].get('15m_bid_return_vs_entry_ask')}",
        f"adverse_60m: {report['adverse_selection'].get('60m_bid_return_vs_entry_ask')}",
        "",
        f"{'policy':<18} {'fills':>6} {'rate':>7} {'exp/fill%':>10} {'exp/att%':>10} {'2×cost':>8} {'missed_avg%':>12}",
        "-" * 78,
    ]
    for r in report["policies_ranked"]:
        pf = r["post_fee"]
        dc = r["doubled_cost"]
        lines.append(
            f"{r['policy']:<18} {pf['fills']:>6} {pf['fill_rate']:>7.2%} "
            f"{pf.get('expectancy_per_fill_pct',0):>10.2f} "
            f"{pf.get('expectancy_per_attempt_pct',0):>10.2f} "
            f"{dc.get('expectancy_per_attempt_pct',0):>8.2f} "
            f"{r['missed_trade_hypothetical_return_pct_mean']:>12.2f}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES_PATH)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--fee-pct", type=float, default=DEFAULT_FEE_PER_TRADE_PCT)
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
