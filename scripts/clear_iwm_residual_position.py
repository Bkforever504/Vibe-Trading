#!/usr/bin/env python3
"""Guarded IWM residual option position clearance.

Dry-run is the default. The script only submits a broker close after an
explicit --execute plus confirmation phrase. It exists for the July 2026 IWM
residual incident where Alpaca still reported a long IWM260807C00315000 leg
after the durable trade group had been manually cleared.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies import options_state

VIBE_HOME = Path.home() / ".vibe-trading"
ENV_FILE = ROOT / "agent" / ".env"
DEFAULT_RECONCILIATION = VIBE_HOME / "reports" / "options-position-reconciliation.json"
DEFAULT_OUTPUT = VIBE_HOME / "reports" / "iwm-residual-clearance.json"
FALLBACK_OUTPUT = ROOT / "data" / "iwm-residual-clearance.json"
DEFAULT_SYMBOL = "IWM260807C00315000"
DEFAULT_EXPECTED_QTY = 2
CONFIRMATION_PHRASE = f"CLOSE {DEFAULT_SYMBOL}"


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> Path | None:
    temp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}-{datetime.now(timezone.utc).timestamp()}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, path)
        return path
    except OSError as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        payload.setdefault("warnings", []).append(f"Primary audit path unavailable: {exc}")
        for fallback in (FALLBACK_OUTPUT, Path(tempfile.gettempdir()) / "iwm-residual-clearance.json"):
            fallback_temp = fallback.with_suffix(
                fallback.suffix + f".tmp-{os.getpid()}-{datetime.now(timezone.utc).timestamp()}"
            )
            try:
                fallback.parent.mkdir(parents=True, exist_ok=True)
                fallback_temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                os.replace(fallback_temp, fallback)
                return fallback
            except OSError as fallback_exc:
                payload.setdefault("warnings", []).append(f"Audit fallback unavailable: {fallback_exc}")
                try:
                    fallback_temp.unlink(missing_ok=True)
                except OSError:
                    pass
        return None


def _position_from_reconciliation(path: Path, symbol: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    data = _load_json(path)
    source = {
        "provider": str(path),
        "mode": "cached_reconciliation_report",
        "available": isinstance(data, dict),
    }
    if not isinstance(data, dict):
        return None, source
    for pos in data.get("broker_positions") or []:
        if isinstance(pos, dict) and str(pos.get("symbol") or "").upper() == symbol:
            source["position_source"] = data.get("position_source")
            return pos, source
    source["position_source"] = data.get("position_source")
    return None, source


def _live_position(symbol: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        return None, {"provider": "alpaca", "available": False, "reason": "missing_credentials"}
    try:
        from alpaca.trading.client import TradingClient

        paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
        client = TradingClient(key, secret, paper=paper)
        pos = client.get_open_position(symbol)
    except Exception as exc:
        return None, {"provider": "alpaca", "available": False, "reason": str(exc)[:240]}
    return {
        "symbol": str(getattr(pos, "symbol", symbol)),
        "qty": float(getattr(pos, "qty", 0) or 0),
        "avg_entry_price": float(getattr(pos, "avg_entry_price", 0) or 0),
        "current_price": float(getattr(pos, "current_price", 0) or 0),
        "market_value": float(getattr(pos, "market_value", 0) or 0),
        "unrealized_pl": float(getattr(pos, "unrealized_pl", 0) or 0),
        "unrealized_plpc": float(getattr(pos, "unrealized_plpc", 0) or 0),
    }, {"provider": "alpaca_live_trading_client", "available": True, "paper": os.getenv("ALPACA_PAPER", "true")}


def _validate_position(position: dict[str, Any] | None, symbol: str, expected_qty: int) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if not options_state.OCC_RE.match(symbol):
        issues.append(f"{symbol} is not an OCC option symbol")
    if not position:
        issues.append(f"{symbol} is not present in broker positions")
        return False, issues
    try:
        qty = float(position.get("qty") or 0)
    except (TypeError, ValueError):
        issues.append(f"{symbol} quantity is unreadable")
        return False, issues
    if qty <= 0:
        issues.append(f"{symbol} is not a long residual; qty={qty}")
    if abs(qty - expected_qty) > 1e-9:
        issues.append(f"{symbol} qty mismatch; expected {expected_qty}, saw {qty}")
    return not issues, issues


def build_clearance_plan(
    *,
    symbol: str = DEFAULT_SYMBOL,
    expected_qty: int = DEFAULT_EXPECTED_QTY,
    reconciliation_path: Path = DEFAULT_RECONCILIATION,
    use_live: bool = False,
) -> dict[str, Any]:
    symbol = symbol.upper()
    if use_live:
        position, source = _live_position(symbol)
    else:
        position, source = _position_from_reconciliation(reconciliation_path, symbol)
    valid, issues = _validate_position(position, symbol, expected_qty)
    return {
        "provider": "iwm_residual_clearance",
        "generated_at": _utc_now_text(),
        "mode": "dry_run_plan",
        "execution_enabled": False,
        "can_submit_orders": False,
        "target": {
            "symbol": symbol,
            "expected_qty": expected_qty,
            "expected_direction": "long",
        },
        "position_source": source,
        "observed_position": position,
        "clearance_ready": valid,
        "issues": issues,
        "planned_broker_action": {
            "action": "close_position",
            "symbol": symbol,
            "qty": expected_qty,
            "effect": "sell_to_close long residual option contracts",
            "submitter": "alpaca.trading.client.TradingClient.close_position",
        } if valid else None,
        "approval_required": True,
        "confirmation_phrase": CONFIRMATION_PHRASE,
    }


def execute_clearance(symbol: str, expected_qty: int) -> dict[str, Any]:
    position, source = _live_position(symbol)
    valid, issues = _validate_position(position, symbol, expected_qty)
    if not valid:
        return {
            "submitted": False,
            "position_source": source,
            "observed_position": position,
            "issues": issues,
        }
    from alpaca.trading.client import TradingClient

    key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
    client = TradingClient(key, secret, paper=paper)
    try:
        response = client.close_position(symbol)
    except Exception as exc:
        return {
            "submitted": False,
            "position_source": source,
            "observed_position": position,
            "issues": [f"broker close_position failed: {str(exc)[:240]}"],
        }
    return {
        "submitted": True,
        "position_source": source,
        "observed_position": position,
        "broker_response": str(response),
    }


def _print_plan(plan: dict[str, Any]) -> None:
    print("IWM Residual Clearance")
    print(f"  generated_at : {plan.get('generated_at')}")
    print(f"  target       : {plan['target']['symbol']} qty={plan['target']['expected_qty']}")
    print(f"  ready        : {plan.get('clearance_ready')}")
    if plan.get("observed_position"):
        pos = plan["observed_position"]
        print(
            "  observed     : "
            f"qty={pos.get('qty')} current={pos.get('current_price')} "
            f"mv={pos.get('market_value')} upl={pos.get('unrealized_pl')}"
        )
    for issue in plan.get("issues") or []:
        print(f"  ISSUE        : {issue}")
    if plan.get("planned_broker_action"):
        action = plan["planned_broker_action"]
        print(f"  DRY RUN      : {action['action']} {action['symbol']} qty={action['qty']}")
        print(f"  approval     : rerun with --execute --confirm \"{plan['confirmation_phrase']}\"")


def main(argv: list[str] | None = None) -> int:
    load_dotenv(dotenv_path=ENV_FILE, override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--expected-qty", type=int, default=DEFAULT_EXPECTED_QTY)
    parser.add_argument("--reconciliation", type=Path, default=DEFAULT_RECONCILIATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--live-read", action="store_true", help="read the current broker position live")
    parser.add_argument("--execute", action="store_true", help="submit the guarded close_position call")
    parser.add_argument("--confirm", default="", help=f"required phrase: {CONFIRMATION_PHRASE}")
    parser.add_argument("--print", dest="do_print", action="store_true")
    args = parser.parse_args(argv)

    symbol = args.symbol.upper()
    plan = build_clearance_plan(
        symbol=symbol,
        expected_qty=args.expected_qty,
        reconciliation_path=args.reconciliation,
        use_live=args.live_read,
    )

    if args.execute:
        required_phrase = f"CLOSE {symbol}"
        if args.confirm != required_phrase:
            plan["execution_attempt"] = {
                "submitted": False,
                "reason": f"confirmation phrase must be exactly {required_phrase!r}",
            }
            written = _write_json(args.output, plan)
            plan["audit_path"] = str(written) if written else None
            if args.do_print:
                _print_plan(plan)
            return 2
        result = execute_clearance(symbol, args.expected_qty)
        plan["mode"] = "execution_attempt"
        plan["execution_enabled"] = True
        plan["can_submit_orders"] = True
        plan["execution_attempt"] = result
    written = _write_json(args.output, plan)
    plan["audit_path"] = str(written) if written else None
    if args.do_print:
        _print_plan(plan)
        if plan.get("execution_attempt"):
            print(f"  execution    : {plan['execution_attempt']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
