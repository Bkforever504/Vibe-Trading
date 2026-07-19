#!/usr/bin/env python3
"""Grouped Alpaca options dashboard.

Read-only report for tracked option groups. It does not submit, cancel, or
modify orders. The report combines durable trade state with broker-position
reconciliation so Kenny can see grouped P&L, exit distance, DTE, and risk flags
without reading raw OCC legs.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import options_position_reconciler
from strategies import options_state

VIBE_HOME = Path(os.path.expanduser("~")) / ".vibe-trading"
ENV_FILE = ROOT / "agent" / ".env"
DEFAULT_STATE_FILE = VIBE_HOME / "options-trades.json"
DEFAULT_CONCENTRATION = VIBE_HOME / "reports" / "portfolio-concentration.json"
DEFAULT_OUTPUT = VIBE_HOME / "reports" / "options-grouped-dashboard.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _parse_expiry(value: Any) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _basis(trade: dict[str, Any]) -> tuple[float, str]:
    qty = max(1, _safe_int(trade.get("qty"), 1))
    credit = _safe_float(trade.get("net_credit")) * 100 * qty
    if credit > 0:
        return credit, "credit"
    max_risk = _safe_float(trade.get("max_risk_per_contract")) * qty
    return max_risk, "max_risk"


def _pnl_pct(pnl: float | None, basis: float) -> float | None:
    if pnl is None or basis <= 0:
        return None
    return pnl / basis


def _distance_to_threshold(pnl_pct: float | None, threshold: float | None) -> float | None:
    if pnl_pct is None or threshold is None:
        return None
    return threshold - pnl_pct


def _broker_book(report: dict[str, Any]) -> dict[str, int]:
    rec = report.get("reconciliation") if isinstance(report.get("reconciliation"), dict) else {}
    raw = rec.get("broker_book") if isinstance(rec.get("broker_book"), dict) else {}
    return {str(symbol): _safe_int(qty) for symbol, qty in raw.items()}


def _position_pnl_by_symbol(report: dict[str, Any]) -> dict[str, float]:
    rows = report.get("broker_positions")
    if not isinstance(rows, list):
        return {}
    out: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "")
        if symbol:
            out[symbol] = _safe_float(row.get("unrealized_pl"), 0.0)
    return out


def _group_pnl(trade: dict[str, Any], pnl_by_symbol: dict[str, float]) -> float | None:
    legs = [str(symbol) for symbol in trade.get("legs") or []]
    if not legs or any(symbol not in pnl_by_symbol for symbol in legs):
        return None
    return round(sum(pnl_by_symbol[symbol] for symbol in legs), 2)


def _known_leg_pnl(legs: list[str], pnl_by_symbol: dict[str, float]) -> float | None:
    known = [pnl_by_symbol[symbol] for symbol in legs if symbol in pnl_by_symbol]
    if not known:
        return None
    return round(sum(known), 2)


def _group_status(trade: dict[str, Any], group_states: dict[str, Any]) -> dict[str, Any]:
    key = str(trade.get("id") or trade.get("label") or "?")
    state = group_states.get(key)
    return state if isinstance(state, dict) else {}


def build_dashboard(
    *,
    state_file: Path = DEFAULT_STATE_FILE,
    positions_file: Path = DEFAULT_CONCENTRATION,
    allow_live: bool = True,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    load_dotenv(dotenv_path=ENV_FILE, override=False)
    generated_at = generated_at or datetime.now(timezone.utc)
    state = _read_json(state_file)
    trades = state.get("trades") if isinstance(state, dict) else []
    if not isinstance(trades, list):
        trades = []

    reconcile_report = options_position_reconciler.build_report(
        state_file,
        positions_file,
        allow_live=allow_live,
    )
    rec = reconcile_report.get("reconciliation", {})
    group_states = rec.get("group_states") if isinstance(rec.get("group_states"), dict) else {}
    broker_book = _broker_book(reconcile_report)
    pnl_by_symbol = _position_pnl_by_symbol(reconcile_report)

    groups: list[dict[str, Any]] = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        status = str(trade.get("status") or "")
        if status not in {"open", "closing", "exit_pending", "partially_closed", "manual_review"}:
            continue

        basis, basis_type = _basis(trade)
        pnl = _group_pnl(trade, pnl_by_symbol)
        pnl_pct = _pnl_pct(pnl, basis)
        profit_target = _safe_float(trade.get("profit_close_pct"), 0.5)
        stop_loss = _safe_float(trade.get("stop_loss_pct"), -1.0)
        expiry = _parse_expiry(trade.get("expiry"))
        dte = (expiry - generated_at.date()).days if expiry else None
        legs = [str(symbol) for symbol in trade.get("legs") or []]
        state_info = _group_status(trade, group_states)
        present_legs = state_info.get("legs_present") if isinstance(state_info.get("legs_present"), list) else []
        missing_legs = state_info.get("legs_missing") if isinstance(state_info.get("legs_missing"), list) else []
        netted_legs = state_info.get("legs_netted") if isinstance(state_info.get("legs_netted"), list) else []

        flags: list[str] = []
        if state_info.get("state") in {"manual_review", "partially_closed"}:
            flags.append(str(state_info.get("state")))
        if missing_legs:
            flags.append("missing_legs")
        if netted_legs:
            flags.append("netted_legs")
        if pnl_pct is not None and pnl_pct <= stop_loss:
            flags.append("stop_threshold_reached")
        if pnl_pct is not None and pnl_pct >= profit_target:
            flags.append("profit_target_reached")
        if dte is not None and dte <= 2:
            flags.append("expiry_near")
        pnl_attribution = "complete" if pnl is not None else "unattributable"
        if pnl is None and (missing_legs or netted_legs):
            pnl_attribution = "blocked_by_missing_or_netted_legs"

        groups.append({
            "id": trade.get("id"),
            "label": trade.get("label"),
            "strategy": trade.get("strategy"),
            "underlying": trade.get("underlying") or options_state.occ_underlying(legs[0]) if legs else None,
            "status": status,
            "reconciliation_state": state_info.get("state", "unknown"),
            "qty": _safe_int(trade.get("qty"), 1),
            "legs": legs,
            "present_legs": present_legs,
            "missing_legs": missing_legs,
            "netted_legs": netted_legs,
            "broker_qty_by_leg": {symbol: broker_book.get(symbol, 0) for symbol in legs},
            "basis": round(basis, 2),
            "basis_type": basis_type,
            "net_credit": _safe_float(trade.get("net_credit")),
            "group_unrealized_pnl": pnl,
            "known_leg_unrealized_pnl": _known_leg_pnl(legs, pnl_by_symbol),
            "pnl_attribution": pnl_attribution,
            "group_unrealized_pnl_pct": round(pnl_pct, 4) if pnl_pct is not None else None,
            "profit_target_pct": profit_target,
            "stop_loss_pct": stop_loss,
            "distance_to_profit_target_pct": round(_distance_to_threshold(pnl_pct, profit_target), 4)
            if _distance_to_threshold(pnl_pct, profit_target) is not None else None,
            "distance_to_stop_loss_pct": round(_distance_to_threshold(stop_loss, pnl_pct), 4)
            if pnl_pct is not None else None,
            "expiry": str(expiry) if expiry else None,
            "dte": dte,
            "candidate_confidence": trade.get("candidate_confidence"),
            "flags": flags,
        })

    total_pnl = sum(_safe_float(row.get("group_unrealized_pnl")) for row in groups if row.get("group_unrealized_pnl") is not None)
    total_broker_option_pnl = round(sum(pnl_by_symbol.values()), 2)
    review_groups = [row for row in groups if row["flags"] or row["reconciliation_state"] not in {"open", "unknown"}]
    status = "review_required" if rec.get("entries_allowed") is False or review_groups else "ok"

    return {
        "provider": "options_grouped_dashboard",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": generated_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "state_file": str(state_file),
        "position_source": reconcile_report.get("position_source"),
        "reconciliation_status": rec.get("status"),
        "entries_allowed": rec.get("entries_allowed"),
        "status": status,
        "summary": {
            "open_groups": len(groups),
            "review_groups": len(review_groups),
            "total_group_unrealized_pnl": round(total_pnl, 2),
            "total_broker_option_unrealized_pnl": total_broker_option_pnl,
            "unattributable_group_pnl_count": sum(1 for row in groups if row.get("pnl_attribution") != "complete"),
            "broker_option_legs": len(broker_book),
        },
        "groups": groups,
        "reconciliation_findings": rec.get("findings") or [],
    }


def write_dashboard(report: dict[str, Any], output: Path = DEFAULT_OUTPUT) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return output


def print_dashboard(report: dict[str, Any]) -> None:
    print("Options Grouped Dashboard | read-only")
    print("=" * 80)
    print(
        f"status={report['status']} reconciliation={report['reconciliation_status']} "
        f"entries_allowed={report['entries_allowed']}"
    )
    summary = report["summary"]
    print(
        f"open_groups={summary['open_groups']} review_groups={summary['review_groups']} "
        f"group_unrealized_pnl=${summary['total_group_unrealized_pnl']:+.2f} "
        f"broker_option_pnl=${summary['total_broker_option_unrealized_pnl']:+.2f}"
    )
    for row in report["groups"]:
        pnl = row["group_unrealized_pnl"]
        pnl_pct = row["group_unrealized_pnl_pct"]
        pnl_text = "-" if pnl is None else f"${pnl:+.2f}"
        pct_text = "-" if pnl_pct is None else f"{pnl_pct:+.1%}"
        flags = ",".join(row["flags"]) if row["flags"] else "none"
        print(
            f"- {row['label'] or row['id']} | {row['status']} / {row['reconciliation_state']} | "
            f"basis=${row['basis']:.2f} {row['basis_type']} | P&L={pnl_text} ({pct_text}) | "
            f"attrib={row['pnl_attribution']} | DTE={row['dte']} | flags={flags}"
        )
    print(f"JSON: {DEFAULT_OUTPUT}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--positions-file", type=Path, default=DEFAULT_CONCENTRATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-live", action="store_true", help="skip live Alpaca read")
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args(argv)

    report = build_dashboard(
        state_file=args.state_file,
        positions_file=args.positions_file,
        allow_live=not args.no_live,
    )
    write_dashboard(report, args.output)
    if args.do_print:
        print_dashboard(report)
    else:
        print(f"Options grouped dashboard written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
