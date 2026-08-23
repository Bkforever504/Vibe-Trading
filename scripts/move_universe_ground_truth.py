#!/usr/bin/env python3
"""Freeze the session's causal, liquid move denominator for detection audits.

The output is accountability evidence only.  It cannot place orders or promote
strategies, and every admitted move retains its data/proxy limitations.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
VIBE_HOME = Path.home() / ".vibe-trading"
RADAR_REPORT = VIBE_HOME / "reports" / "intraday-opportunity-radar.json"
RADAR_LOG = ROOT / "data" / "intraday_opportunity_radar_log.jsonl"
MOVE_GROUND_TRUTH_SPEC = ROOT / "research" / "MOVE_GROUND_TRUTH_SPEC_2026-08-20.md"
MIN_PRICE = 1.0
MIN_ABS_MOVE_PCT = 2.0
MIN_AVERAGE_DOLLAR_VOLUME = 20_000_000.0
TOP_N = 20


def ground_truth_spec_status(path: Path = MOVE_GROUND_TRUTH_SPEC) -> dict[str, Any]:
    """Fail closed until Kenny explicitly freezes and approves the denominator spec."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        text = ""
    normalized = {
        line.replace("**", "").replace("__", "").strip().lower()
        for line in text.splitlines()
    }
    approved = "status: frozen" in normalized and "kenny approval: approved" in normalized
    return {
        "path": path.as_posix(),
        "status": "approved_frozen" if approved else "pending_kenny_signoff",
        "approved": approved,
        "required_markers": ["Status: frozen", "Kenny Approval: approved"],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def build_placeholder_ground_truth(
    radar: dict[str, Any], *, spec_path: Path = MOVE_GROUND_TRUTH_SPEC
) -> dict[str, Any]:
    """Return an explicit, non-metric placeholder; never imply an approved denominator."""
    session_date = str(radar.get("date") or radar.get("generated_at") or "")[:10]
    status = ground_truth_spec_status(spec_path)
    return {
        "schema_version": 1,
        "provider": "move_universe_ground_truth",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": session_date,
        "ground_truth_status": status["status"],
        "metrics_qualified": False,
        "spec": status,
        "definition": None,
        "moves": [],
        "excluded": [],
        "summary": {"movers_seen": 0, "admitted": 0, "excluded": 0, "missing_liquidity": 0},
        "warnings": [
            "Placeholder only: pattern coverage metrics are not qualified until Kenny approves the frozen MOVE ground-truth spec.",
            "TODO(Kenny): approve research/MOVE_GROUND_TRUTH_SPEC_2026-08-20.md with the required frozen approval markers.",
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for raw in lines:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _timestamp(row: dict[str, Any]) -> str | None:
    value = row.get("as_of_et") or row.get("generated_at")
    return str(value) if value else None


def _candidate_index(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = [
        row
        for key in ("ranked_candidates", "filtered_candidates")
        for row in report.get(key) or []
        if isinstance(row, dict) and row.get("symbol")
    ]
    return {str(row["symbol"]).upper(): row for row in rows}


def build_ground_truth(
    radar: dict[str, Any],
    history: Iterable[dict[str, Any]] = (),
    *,
    liquidity_by_symbol: dict[str, float] | None = None,
    top_n: int = TOP_N,
) -> dict[str, Any]:
    session_date = str(radar.get("date") or radar.get("generated_at") or "")[:10]
    candidates = _candidate_index(radar)
    liquidity = {str(key).upper(): float(value) for key, value in (liquidity_by_symbol or {}).items() if _number(value) is not None}
    first_move_at: dict[str, str] = {}
    for snapshot in sorted(
        (row for row in history if str(row.get("date") or "")[:10] == session_date),
        key=lambda row: _timestamp(row) or "",
    ):
        stamp = _timestamp(snapshot)
        for mover in snapshot.get("market_movers") or []:
            if not isinstance(mover, dict) or not stamp:
                continue
            change = _number(mover.get("percent_change"))
            if change is not None and abs(change) >= 1.0:
                first_move_at.setdefault(str(mover.get("symbol") or "").upper(), stamp)

    admitted: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    movers = sorted(
        (row for row in radar.get("market_movers") or [] if isinstance(row, dict)),
        key=lambda row: abs(_number(row.get("percent_change")) or 0.0),
        reverse=True,
    )
    for mover in movers:
        symbol = str(mover.get("symbol") or "").upper()
        change = _number(mover.get("percent_change"))
        price = _number(mover.get("price"))
        candidate = candidates.get(symbol, {})
        average_dollar = liquidity.get(symbol)
        if average_dollar is None:
            average_dollar = _number(candidate.get("avg_dollar_volume_20d"))
        reasons: list[str] = []
        if not symbol:
            reasons.append("missing_symbol")
        if price is None or price < MIN_PRICE:
            reasons.append("price_below_minimum_or_missing")
        if change is None or abs(change) < MIN_ABS_MOVE_PCT:
            reasons.append("move_below_minimum_or_missing")
        if average_dollar is None:
            reasons.append("average_dollar_volume_missing")
        elif average_dollar < MIN_AVERAGE_DOLLAR_VOLUME:
            reasons.append("average_dollar_volume_below_minimum")
        if mover.get("halted") is True or candidate.get("halted") is True:
            reasons.append("halt_flagged")
        row = {
            "move_id": f"{session_date}:{symbol}",
            "date": session_date,
            "symbol": symbol,
            "direction": "bullish" if (change or 0.0) > 0 else "bearish",
            "move_pct": round(change, 4) if change is not None else None,
            "final_price": round(price, 4) if price is not None else None,
            "move_start_at": first_move_at.get(symbol),
            "average_dollar_volume_20d": round(average_dollar, 2) if average_dollar is not None else None,
            "session_dollar_volume": _number(candidate.get("current_session_dollar_volume")),
            "catalyst_available": bool(candidate.get("catalyst_available")),
            "catalyst_headlines": list(candidate.get("catalyst_headlines") or [])[:3],
            "halt_status": "flagged" if "halt_flagged" in reasons else "not_flagged_by_radar_proxy",
            "eligibility": "admitted" if not reasons else "excluded",
            "exclusion_reasons": reasons,
            "source_labels": ["alpaca_market_movers", "alpaca_daily_liquidity", "intraday_radar_history"],
            "execution_enabled": False,
            "can_submit_orders": False,
        }
        (admitted if not reasons else excluded).append(row)
    admitted = admitted[: max(1, int(top_n))]
    return {
        "schema_version": 1,
        "provider": "move_universe_ground_truth",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "date": session_date,
        "ground_truth_status": "approved_frozen_legacy_proxy_unqualified",
        "metrics_qualified": False,
        "definition": {
            "minimum_price": MIN_PRICE,
            "minimum_abs_move_pct": MIN_ABS_MOVE_PCT,
            "minimum_average_dollar_volume_20d": MIN_AVERAGE_DOLLAR_VOLUME,
            "top_n": int(top_n),
            "halt_policy": "exclude_explicit_halt_flags; otherwise label radar no-halt proxy",
            "implementation_status": "legacy_market_mover_proxy_does_not_implement_frozen_atr_retention_r_multiple_or_instrument_timeframe_contract",
        },
        "moves": admitted,
        "excluded": excluded,
        "summary": {
            "movers_seen": len(movers),
            "admitted": len(admitted),
            "excluded": len(excluded),
            "missing_liquidity": sum("average_dollar_volume_missing" in row["exclusion_reasons"] for row in excluded),
        },
        "warnings": [
            "Ground truth is a causal move-audit denominator, not a trade recommendation.",
            "No-halt status is a labeled radar proxy unless an explicit halt flag is present.",
            "Coverage metrics are fail-closed: this legacy radar-derived proxy is not the independent frozen MOVE denominator.",
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def load_ground_truth(
    radar: dict[str, Any],
    history: Iterable[dict[str, Any]] = (),
    *,
    liquidity_by_symbol: dict[str, float] | None = None,
    top_n: int = TOP_N,
    spec_path: Path = MOVE_GROUND_TRUTH_SPEC,
) -> dict[str, Any]:
    """Load the placeholder today and automatically activate after explicit approval."""
    status = ground_truth_spec_status(spec_path)
    if not status["approved"]:
        return build_placeholder_ground_truth(radar, spec_path=spec_path)
    report = build_ground_truth(
        radar,
        history,
        liquidity_by_symbol=liquidity_by_symbol,
        top_n=top_n,
    )
    report["spec"] = status
    return report


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radar-report", type=Path, default=RADAR_REPORT)
    parser.add_argument("--radar-log", type=Path, default=RADAR_LOG)
    parser.add_argument("--spec", type=Path, default=MOVE_GROUND_TRUTH_SPEC)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--top-n", type=int, default=TOP_N)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    radar = _read_json(args.radar_report)
    spec_status = ground_truth_spec_status(args.spec)
    mover_symbols = [str(row.get("symbol") or "").upper() for row in radar.get("market_movers") or [] if isinstance(row, dict)]
    liquidity: dict[str, float] = {}
    if spec_status["approved"] and mover_symbols:
        try:
            if str(ROOT) not in sys.path:
                sys.path.insert(0, str(ROOT))
            from scripts.premarket_opportunity_radar import fetch_daily_liquidity

            liquidity, _ = fetch_daily_liquidity(
                mover_symbols, datetime.now(ZoneInfo("America/New_York"))
            )
        except Exception:
            liquidity = {}
    report = load_ground_truth(
        radar,
        _read_jsonl(args.radar_log),
        liquidity_by_symbol=liquidity,
        top_n=args.top_n,
        spec_path=args.spec,
    )
    output = args.output_dir / f"move_ground_truth_{report['date'].replace('-', '')}.json"
    _atomic_json(output, report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"ground_truth date={report['date']} status={report['ground_truth_status']} "
            f"admitted={report['summary']['admitted']} excluded={report['summary']['excluded']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
