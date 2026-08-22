#!/usr/bin/env python3
"""Run the governed learning pipeline once for each newly closed Flip trade."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path(os.getenv("VIBE_TRADING_HOME", Path.home() / ".vibe-trading"))
DEFAULT_TRADES_PATH = VIBE_HOME / "flip-trades.json"
DEFAULT_STATE_PATH = VIBE_HOME / "reports" / "post-trade-learning-state.json"
DEFAULT_REPORT_PATH = VIBE_HOME / "reports" / "post-trade-learning-cycle.json"

PRE_LEARNING_DATED_STEPS = (
    "closed_trade_postmortem.py",
    "daily_outcome_reviewer.py",
    "flip_bot_learning_report.py",
)
GLOBAL_STEPS = ("self_learning_edge_loop.py",)
POST_LEARNING_DATED_STEPS = ("loop_closure_report.py",)
DATED_STEPS = PRE_LEARNING_DATED_STEPS + POST_LEARNING_DATED_STEPS


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _trade_id(trade: dict[str, Any]) -> str:
    stable = trade.get("id") or trade.get("alpaca_order_id")
    if stable:
        return str(stable)
    fields = (
        trade.get("symbol"), trade.get("option_symbol"), trade.get("entry_at"),
        trade.get("exit_at"), trade.get("entry_price"), trade.get("exit_price"),
    )
    return "|".join("" if value is None else str(value) for value in fields)


def _exit_day(trade: dict[str, Any]) -> str:
    value = trade.get("exit_date") or trade.get("exit_at") or date.today().isoformat()
    return str(value)[:10]


def _closed_trades(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path, [])
    if isinstance(payload, dict):
        payload = payload.get("trades", [])
    if not isinstance(payload, list):
        return []
    return [
        row for row in payload
        if isinstance(row, dict) and str(row.get("status", "")).lower() == "closed"
    ]


def _command(step: str, day: str | None = None) -> list[str]:
    command = [sys.executable, str(ROOT / "scripts" / step)]
    if day is not None:
        command.extend(["--date", day])
    return command


def run_cycle(
    trades_path: Path = DEFAULT_TRADES_PATH,
    state_path: Path = DEFAULT_STATE_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    current_day: date | None = None,
) -> tuple[dict[str, Any], int]:
    state = _read_json(state_path, {})
    processed = {str(value) for value in state.get("processed_trade_ids", [])}
    trades = _closed_trades(trades_path)
    bootstrapped = not state_path.exists()
    today = current_day or date.today()
    if bootstrapped:
        processed.update(_trade_id(trade) for trade in trades if _exit_day(trade) < today.isoformat())
    new_trades = [trade for trade in trades if _trade_id(trade) not in processed]
    days = sorted({_exit_day(trade) for trade in new_trades})

    executions: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    if new_trades:
        for day in days:
            for step in PRE_LEARNING_DATED_STEPS:
                command = _command(step, day)
                result = runner(command, cwd=ROOT, capture_output=True, text=True, check=False)
                row = {"step": step, "date": day, "returncode": int(result.returncode)}
                executions.append(row)
                if result.returncode:
                    failures.append({**row, "stderr_tail": (result.stderr or "")[-1000:]})
        for step in GLOBAL_STEPS:
            command = _command(step)
            result = runner(command, cwd=ROOT, capture_output=True, text=True, check=False)
            row = {"step": step, "date": None, "returncode": int(result.returncode)}
            executions.append(row)
            if result.returncode:
                failures.append({**row, "stderr_tail": (result.stderr or "")[-1000:]})
        for day in days:
            for step in POST_LEARNING_DATED_STEPS:
                command = _command(step, day)
                result = runner(command, cwd=ROOT, capture_output=True, text=True, check=False)
                row = {"step": step, "date": day, "returncode": int(result.returncode)}
                executions.append(row)
                if result.returncode:
                    failures.append({**row, "stderr_tail": (result.stderr or "")[-1000:]})

    status = "failed" if failures else "processed" if new_trades else "no_new_closed_trades"
    if not failures and (new_trades or bootstrapped):
        processed.update(_trade_id(trade) for trade in new_trades)
        state = {
            "processed_trade_ids": sorted(processed)[-2000:],
            "last_success_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        _write_json_atomic(state_path, state)

    report = {
        "provider": "post_trade_learning_cycle",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "execution_enabled": False,
        "can_submit_orders": False,
        "automatic_parameter_changes": False,
        "closed_trade_count": len(trades),
        "new_closed_trade_count": len(new_trades),
        "bootstrapped_existing_history": bootstrapped,
        "new_trade_ids": [_trade_id(trade) for trade in new_trades],
        "exit_dates_processed": days,
        "steps": executions,
        "failures": failures,
        "learning_policy": "attribute_then_nominate_shadow_challengers_human_promotion_only",
    }
    _write_json_atomic(report_path, report)
    return report, 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trades-path", type=Path, default=DEFAULT_TRADES_PATH)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args(argv)
    report, returncode = run_cycle(args.trades_path, args.state_path, args.report_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Post-trade learning cycle: {report['status']} new={report['new_closed_trade_count']}")
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
