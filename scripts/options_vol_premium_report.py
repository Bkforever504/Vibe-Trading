#!/usr/bin/env python3
"""Research-only maturity-matched options volatility-premium instrumentation."""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Optional

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = ROOT / "data" / "options_shadow_twin_log.jsonl"
DEFAULT_REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "options-vol-premium.json"
METHOD_VERSION = "maturity_matched_vol_premium_v1"


def _number(value: Any) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def dte_bucket(dte: int) -> str:
    if dte <= 7:
        return "0-7"
    if dte <= 14:
        return "8-14"
    if dte <= 30:
        return "15-30"
    if dte <= 45:
        return "31-45"
    return "46+"


def ewma_realized_vol_pct(closes: Iterable[float], decay: float = 0.94) -> Optional[float]:
    prices = [float(value) for value in closes if _number(value) is not None and float(value) > 0]
    if len(prices) < 31 or not 0.0 < decay < 1.0:
        return None
    returns = [math.log(current / previous) for previous, current in zip(prices, prices[1:])]
    seed = returns[:20]
    variance = sum(value * value for value in seed) / len(seed)
    for value in returns[20:]:
        variance = decay * variance + (1.0 - decay) * value * value
    forecast = math.sqrt(max(0.0, variance) * 252.0) * 100.0
    return forecast if math.isfinite(forecast) and forecast > 0 else None


def _normalized_iv_pct(value: Any) -> Optional[float]:
    iv = _number(value)
    if iv is None or iv <= 0:
        return None
    return iv * 100.0 if iv <= 5.0 else iv


def _atm_iv_pct(chain_legs: Iterable[dict[str, Any]], expiry: str) -> tuple[Optional[float], list[str]]:
    by_right: dict[str, tuple[float, float, str]] = {}
    for leg in chain_legs:
        if str(leg.get("expiry") or "") != expiry:
            continue
        iv = _normalized_iv_pct(leg.get("implied_volatility"))
        delta = _number(leg.get("delta"))
        right = str(leg.get("right") or "").upper()
        if iv is None or delta is None or right not in {"C", "P"}:
            continue
        distance = abs(abs(delta) - 0.50)
        current = by_right.get(right)
        if current is None or distance < current[0]:
            by_right[right] = (distance, iv, str(leg.get("symbol") or ""))
    values = [row[1] for row in by_right.values()]
    symbols = [row[2] for row in by_right.values()]
    return (mean(values), symbols) if values else (None, [])


def capture_entry_snapshot(
    *,
    symbol: str,
    expiry: date,
    selected_legs: Iterable[dict[str, Any]],
    chain_legs: Iterable[dict[str, Any]],
    vix_at_entry: Any = None,
    as_of: Optional[date] = None,
    closes: Optional[Iterable[float]] = None,
    macro_events: Optional[Iterable[dict[str, Any]]] = None,
    macro_coverage_end: Optional[date] = None,
    earnings_dates: Optional[Iterable[date]] = None,
) -> dict[str, Any]:
    """Freeze entry inputs. Missing inputs stay explicit and never affect execution."""
    as_of = as_of or date.today()
    dte = max(0, (expiry - as_of).days)
    expiry_text = expiry.isoformat()
    atm_iv, atm_symbols = _atm_iv_pct(chain_legs, expiry_text)
    result: dict[str, Any] = {
        "method_version": METHOD_VERSION,
        "authority": "shadow_research_only",
        "as_of_date": as_of.isoformat(),
        "expiry": expiry_text,
        "dte_calendar_days": dte,
        "dte_bucket": dte_bucket(dte),
        "atm_iv_annualized_pct": round(atm_iv, 4) if atm_iv is not None else None,
        "atm_iv_source": "alpaca_chain_nearest_abs_delta_0.50_same_expiry",
        "atm_iv_contracts": atm_symbols,
        "rv_forecast_annualized_pct": None,
        "rv_forecast_model": "ewma_close_to_close_decay_0.94_annualized_252",
        "spread_friction_vol_pct": None,
        "spread_friction_method": "proxy_sum_leg_bid_ask_width_over_spot_annualized_sqrt252_over_dte",
        "gross_vol_premium_pct": None,
        "net_vol_premium_ex_event_pct": None,
        "event_risk_premium_pct": None,
        "net_vol_premium_after_event_pct": None,
        "vix_at_entry": _number(vix_at_entry),
        "macro_events_within_horizon": [],
        "fomc_within_horizon": None,
        "earnings_within_horizon": None,
        "event_data_complete": False,
        "gate_changed": False,
    }
    if atm_iv is None:
        result["status"] = "atm_iv_unavailable"
        return result

    price_values = [float(value) for value in (closes or []) if _number(value) is not None and float(value) > 0]
    rv = ewma_realized_vol_pct(price_values)
    spot = price_values[-1] if price_values else None
    result["rv_forecast_annualized_pct"] = round(rv, 4) if rv is not None else None
    result["underlying_close_at_capture"] = round(spot, 4) if spot is not None else None

    widths = []
    for leg in selected_legs:
        bid, ask = _number(leg.get("bid")), _number(leg.get("ask"))
        ratio = int(_number(leg.get("ratio_qty")) or 1)
        if bid is not None and ask is not None and 0 <= bid <= ask:
            widths.append((ask - bid) * ratio)
    friction = None
    if spot and widths and dte > 0:
        friction = sum(widths) / spot * math.sqrt(252.0 / dte) * 100.0
        result["spread_friction_vol_pct"] = round(friction, 4)

    events = []
    if macro_events is not None:
        parsed_macro_dates = []
        for event in macro_events:
            try:
                event_date = date.fromisoformat(str(event.get("date")))
            except (TypeError, ValueError):
                continue
            parsed_macro_dates.append(event_date)
            if as_of <= event_date <= expiry:
                events.append({"date": event_date.isoformat(), "name": str(event.get("name") or "unknown"), "impact": str(event.get("impact") or "unknown")})
        result["macro_events_within_horizon"] = events
        coverage_end = macro_coverage_end or (max(parsed_macro_dates) if parsed_macro_dates else None)
        result["macro_calendar_coverage_end"] = coverage_end.isoformat() if coverage_end else None
        result["macro_event_data_complete"] = coverage_end is not None and coverage_end >= expiry
        if result["macro_event_data_complete"]:
            result["fomc_within_horizon"] = any("fomc" in row["name"].lower() for row in events)
    if earnings_dates is not None:
        normalized_earnings = [value for value in earnings_dates if isinstance(value, date)]
        result["earnings_within_horizon"] = any(as_of <= value <= expiry for value in normalized_earnings)
    result["event_flags_available"] = (
        result["fomc_within_horizon"] is not None
        and result["earnings_within_horizon"] is not None
    )
    result["event_data_complete"] = (
        result.get("macro_event_data_complete") is True
        and result["event_flags_available"] is True
    )

    if rv is not None:
        gross = atm_iv - rv
        result["gross_vol_premium_pct"] = round(gross, 4)
        if friction is not None:
            result["net_vol_premium_ex_event_pct"] = round(gross - friction, 4)
    result["status"] = "complete_ex_event" if rv is not None and friction is not None else "incomplete"
    return result


def _quantile(values: list[float], fraction: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower, upper = math.floor(index), math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _tercile(value: Optional[float], low: Optional[float], high: Optional[float]) -> str:
    if value is None or low is None or high is None:
        return "unknown"
    if value <= low:
        return "low"
    if value <= high:
        return "middle"
    return "high"


def build_report(records: Iterable[dict[str, Any]], now: Optional[datetime] = None) -> dict[str, Any]:
    rows = list(records)
    outcomes = {str(row.get("candidate_id")): row for row in rows if row.get("type") == "outcome"}
    candidates = [row for row in rows if row.get("type") == "candidate"]
    vix_values = [value for value in (_number((row.get("volatility_edge") or {}).get("vix_at_entry")) for row in candidates) if value is not None]
    low_cut, high_cut = _quantile(vix_values, 1 / 3), _quantile(vix_values, 2 / 3)
    evidence_rows = []
    for candidate in candidates:
        edge = candidate.get("volatility_edge") if isinstance(candidate.get("volatility_edge"), dict) else {}
        outcome = outcomes.get(str(candidate.get("candidate_id")))
        vix = _number(edge.get("vix_at_entry"))
        evidence_rows.append({
            "candidate_id": candidate.get("candidate_id"), "created_at": candidate.get("created_at"),
            "strategy": candidate.get("strategy"), "dte_bucket": edge.get("dte_bucket"),
            "dte_calendar_days": edge.get("dte_calendar_days"), "atm_iv_annualized_pct": edge.get("atm_iv_annualized_pct"),
            "rv_forecast_annualized_pct": edge.get("rv_forecast_annualized_pct"), "spread_friction_vol_pct": edge.get("spread_friction_vol_pct"),
            "gross_vol_premium_pct": edge.get("gross_vol_premium_pct"), "net_vol_premium_ex_event_pct": edge.get("net_vol_premium_ex_event_pct"),
            "event_risk_premium_pct": edge.get("event_risk_premium_pct"), "net_vol_premium_after_event_pct": edge.get("net_vol_premium_after_event_pct"),
            "event_data_complete": edge.get("event_data_complete") is True, "vix_at_entry": vix,
            "vix_sample_tercile": _tercile(vix, low_cut, high_cut), "outcome": outcome.get("reason") if outcome else None,
            "win": outcome.get("win") if outcome else None, "pnl_before_fees": outcome.get("pnl_before_fees") if outcome else None,
        })

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in evidence_rows:
        key = (str(row.get("strategy") or "unknown"), str(row.get("dte_bucket") or "unknown"), str(row.get("vix_sample_tercile") or "unknown"))
        grouped.setdefault(key, []).append(row)
    cohorts = []
    for (strategy, bucket, regime), cohort_rows in sorted(grouped.items()):
        resolved = [row for row in cohort_rows if row.get("win") is not None]
        premiums = [float(row["net_vol_premium_ex_event_pct"]) for row in cohort_rows if _number(row.get("net_vol_premium_ex_event_pct")) is not None]
        wins = sum(1 for row in resolved if row.get("win") is True)
        cohorts.append({
            "strategy": strategy, "dte_bucket": bucket, "vix_sample_tercile": regime,
            "candidate_count": len(cohort_rows), "resolved_count": len(resolved),
            "mean_net_vol_premium_ex_event_pct": round(mean(premiums), 4) if premiums else None,
            "win_rate": round(wins / len(resolved), 4) if resolved else None,
            "status": "researchable" if len(resolved) >= 30 else "insufficient_resolved_n",
        })
    instrumented = sum(1 for row in evidence_rows if row.get("atm_iv_annualized_pct") is not None)
    return {
        "provider": "options_vol_premium_report", "generated_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "method_version": METHOD_VERSION, "mode": "forward_only_shadow_research", "execution_enabled": False, "can_submit_orders": False,
        "candidate_count": len(candidates), "instrumented_candidate_count": instrumented, "resolved_count": len(outcomes),
        "vix_sample_tercile_boundaries": {"low_max": low_cut, "middle_max": high_cut}, "cohorts": cohorts, "rows": evidence_rows,
        "warnings": [
            "VIX terciles are descriptive sample terciles and can move as candidates accumulate.",
            "Event-adjusted premium remains unavailable until complete point-in-time event coverage and an event-premium model are frozen.",
            "No cohort is researchable before 30 resolved outcomes; this report cannot change entry gates or sizing.",
        ],
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-path", type=Path, default=DEFAULT_LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(_read_jsonl(args.log_path))
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
