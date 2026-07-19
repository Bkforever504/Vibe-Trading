#!/usr/bin/env python3
"""Read-only options broker/state reconciler.

Compares durable options trade state (options-trades.json) against broker
option positions using signed per-contract quantities, explains residuals
with closed trades that are still open at the broker, classifies every group
through the reconciliation state machine, and emits a repair PLAN that
requires Kenny's explicit approval. It never places, modifies, or cancels
orders and never rewrites trade state.

Position sources, in order of preference:
1. Live Alpaca positions (read-only GET /v2/positions) when credentials exist
   and --no-live is not passed.
2. The latest portfolio-concentration.json report (labeled with its age).

Usage:
    python scripts/options_position_reconciler.py --print
    python scripts/options_position_reconciler.py --state-file X --positions-file Y --output Z
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies import options_state

VIBE_HOME = Path(os.path.expanduser("~")) / ".vibe-trading"
DEFAULT_STATE_FILE = VIBE_HOME / "options-trades.json"
DEFAULT_CONCENTRATION = VIBE_HOME / "reports" / "portfolio-concentration.json"
DEFAULT_OUTPUT = VIBE_HOME / "reports" / "options-position-reconciliation.json"
ENV_FILE = ROOT / "agent" / ".env"


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _live_broker_positions() -> tuple[list[dict], dict] | None:
    """Fetch live option positions read-only. Returns (positions, source) or None."""
    key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        return None
    base = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    try:
        import requests

        resp = requests.get(
            f"{base}/v2/positions",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception:
        return None
    positions = [
        {
            "symbol": str(p.get("symbol")),
            "qty": float(p.get("qty") or 0),
            "unrealized_pl": float(p.get("unrealized_pl") or 0),
            "unrealized_plpc": float(p.get("unrealized_plpc") or 0),
            "current_price": float(p.get("current_price") or 0),
            "avg_entry_price": float(p.get("avg_entry_price") or 0),
            "market_value": float(p.get("market_value") or 0),
        }
        for p in raw
        if isinstance(p, dict) and str(p.get("asset_class", "")).endswith("option")
    ]
    return positions, {"provider": "alpaca_live_read_only", "as_of": _utc_now_text(), "stale_seconds": 0}


def _report_broker_positions(concentration_path: Path) -> tuple[list[dict], dict] | None:
    data = _load_json(concentration_path)
    if not isinstance(data, dict):
        return None
    conc = data.get("concentration") or {}
    raw = conc.get("positions")
    if not isinstance(raw, list):
        return None
    positions = [
        {"symbol": str(p.get("symbol")), "qty": float(p.get("qty") or 0)}
        for p in raw
        if isinstance(p, dict) and options_state.OCC_RE.match(str(p.get("symbol") or ""))
    ]
    as_of = str(data.get("timestamp") or data.get("date") or "")
    stale_seconds = None
    try:
        as_of_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        stale_seconds = max(0, int((datetime.now(timezone.utc) - as_of_dt).total_seconds()))
    except ValueError:
        pass
    return positions, {
        "provider": str(concentration_path),
        "as_of": as_of,
        "stale_seconds": stale_seconds,
    }


def _build_repair_plan(reconciliation: dict) -> dict:
    """Translate findings into explicit, human-approved repair options.

    Every step is a proposal. Nothing here is executed by any code path.
    """
    steps: list[dict] = []
    closed_open = reconciliation.get("closed_groups_still_open") or []
    group_states = reconciliation.get("group_states") or {}

    for trade_id in closed_open:
        info = group_states.get(trade_id, {})
        steps.append({
            "action": "restore_group_to_manual_review",
            "trade_id": trade_id,
            "label": info.get("label"),
            "detail": (
                "Durable state marks this group closed but its legs are still "
                "open at the broker. Option A (recommended): edit "
                "options-trades.json to set status='open' plus "
                "needs_manual_review=true so monitoring resumes and exits can "
                "manage it. Option B: manually close its remaining broker legs "
                "as a grouped close. Either action requires Kenny's approval."
            ),
            "requires_kenny_approval": True,
        })

    netted = reconciliation.get("netted_symbols") or []
    if netted:
        steps.append({
            "action": "acknowledge_netted_legs",
            "symbols": netted,
            "detail": (
                "These OCC contracts are held long by one group and short by "
                "another, so the broker nets them to zero or a reduced "
                "quantity. Per-symbol position checks cannot confirm them. "
                "After restoring the closed group(s) above, the signed books "
                "reconcile exactly; no broker order is needed for these legs."
            ),
            "requires_kenny_approval": True,
        })

    unexplained = reconciliation.get("unexplained_residual") or {}
    if unexplained:
        steps.append({
            "action": "investigate_unexplained_residual",
            "symbols": sorted(unexplained),
            "detail": (
                "Broker holdings that no tracked or recently-closed group "
                "explains. Inspect Alpaca order history manually before any "
                "action."
            ),
            "requires_kenny_approval": True,
        })

    if not steps:
        steps.append({
            "action": "none",
            "detail": "Durable state and broker positions reconcile exactly.",
            "requires_kenny_approval": False,
        })
    return {
        "requires_kenny_approval": any(s.get("requires_kenny_approval") for s in steps),
        "steps": steps,
    }


def build_report(state_file: Path, positions_file: Path, allow_live: bool = True) -> dict:
    state = _load_json(state_file)
    trades = state.get("trades") if isinstance(state, dict) else None
    if not isinstance(trades, list):
        trades = []

    source_result = _live_broker_positions() if allow_live else None
    if source_result is None:
        source_result = _report_broker_positions(positions_file)
    if source_result is None:
        positions, source = [], {
            "provider": "unavailable",
            "as_of": None,
            "stale_seconds": None,
            "error": "no live credentials and no readable concentration report",
        }
        reconciliation = {
            "status": "unknown",
            "entries_allowed": False,
            "findings": ["broker position source unavailable; failing closed"],
        }
    else:
        positions, source = source_result
        reconciliation = options_state.reconcile(trades, positions)

    return {
        "provider": "options_position_reconciler",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": _utc_now_text(),
        "state_file": str(state_file),
        "position_source": source,
        "broker_positions": positions,
        "reconciliation": reconciliation,
        "proposed_repair_plan": _build_repair_plan(reconciliation),
    }


def _print_report(report: dict) -> None:
    rec = report.get("reconciliation", {})
    src = report.get("position_source", {})
    print("Options Position Reconciler (read-only)")
    print(f"  generated_at : {report.get('generated_at')}")
    print(f"  source       : {src.get('provider')} (as_of={src.get('as_of')}, stale_s={src.get('stale_seconds')})")
    print(f"  status       : {rec.get('status')}  entries_allowed={rec.get('entries_allowed')}")
    for finding in rec.get("findings", []) or []:
        print(f"  FINDING      : {finding}")
    for tid, info in (rec.get("group_states") or {}).items():
        print(
            f"  group {tid[:20]:<20} state={info.get('state'):<26} "
            f"present={len(info.get('legs_present') or [])} "
            f"missing={len(info.get('legs_missing') or [])} "
            f"netted={len(info.get('legs_netted') or [])}"
        )
    plan = report.get("proposed_repair_plan", {})
    print(f"  repair plan  : {len(plan.get('steps') or [])} step(s), "
          f"requires_kenny_approval={plan.get('requires_kenny_approval')}")
    for step in plan.get("steps") or []:
        print(f"    - {step.get('action')}: {step.get('detail')}")


def main(argv: list[str] | None = None) -> int:
    # Match the bot entry points so the documented CLI can use live read-only
    # broker truth without requiring credentials in the parent shell.
    load_dotenv(dotenv_path=ENV_FILE, override=False)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--positions-file", type=Path, default=DEFAULT_CONCENTRATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-live", action="store_true", help="skip live broker read")
    parser.add_argument("--print", dest="do_print", action="store_true")
    args = parser.parse_args(argv)

    report = build_report(args.state_file, args.positions_file, allow_live=not args.no_live)
    options_state.atomic_save_json(args.output, report)
    if args.do_print:
        _print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
