#!/usr/bin/env python3
"""Run a shadow scanner with Discord alerts and fail-closed health state."""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.notifier import redact, send_discord
from scripts.shadow_ops import is_halted, kill_switch_active, record_failure, record_success


SCANNERS = {
    "mes-orb-v2": {
        "module": "scripts.mes_orb_0932_vix_v2_shadow",
        "label": "MES ORB v2",
    },
    "mes-reopen-v2": {
        "module": "scripts.mes_reopen_drift_v2_shadow",
        "label": "MES reopen v2",
    },
    "equity-orb-scout-v1": {
        "module": "scripts.equity_orb_scout_v1_shadow",
        "label": "Equity ORB Scout v1",
    },
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _row_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("event_type") or row.get("type") or ""),
        str(row.get("plan_id") or ""),
        str(row.get("resolved_at") or ""),
        str(row.get("captured_at") or row.get("timestamp") or ""),
    )


def _new_rows(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prior = {_row_key(row) for row in before}
    return [row for row in after if _row_key(row) not in prior]


def _failure_row(rows: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for row in rows:
        event = str(row.get("event_type") or row.get("type") or "").lower()
        reason = str(row.get("reason") or "").lower()
        if event.endswith("_error") or reason == "market_data_incomplete" or reason.startswith("error:"):
            return row
    return None


def _levels(row: Mapping[str, Any]) -> str:
    symbol = str(row.get("symbol") or "MES")
    direction = str(row.get("direction") or "?").upper()
    grade = row.get("grade")
    grade_text = f" grade={float(grade):.3f}" if isinstance(grade, (int, float)) else ""
    return (
        f"{symbol} {direction} entry={row.get('entry_price')} stop={row.get('stop_price')} "
        f"T1={row.get('t1_price')} T2={row.get('t2_price')}{grade_text}"
    )


def format_entry_alert(label: str, rows: list[Mapping[str, Any]]) -> str:
    eligible = [row for row in rows if row.get("event_type") == "entry" and row.get("should_enter") is True]
    eligible.sort(
        key=lambda row: (
            int(row.get("dashboard_rank_in_top_n") or 10_000),
            -float(row.get("grade") or 0.0),
        )
    )
    lines = [f"**{label} entry scan**", f"Qualified setups: {len(eligible)}"]
    for index, row in enumerate(eligible[:20], 1):
        lines.append(f"{index}. {_levels(row)}")
    if not eligible:
        skipped = [row for row in rows if row.get("event_type") in {"entry", "universe_skip"}]
        reasons: dict[str, int] = {}
        for row in skipped:
            reason = str(row.get("reason") or "unknown")
            reasons[reason] = reasons.get(reason, 0) + 1
        if reasons:
            lines.append("Skipped: " + ", ".join(f"{key}={value}" for key, value in sorted(reasons.items())[:8]))
    lines.append("Shadow/manual-review only. No order authority.")
    return "\n".join(lines)


def format_resolve_alert(
    label: str,
    rows: list[Mapping[str, Any]],
    *,
    ledger_rows: list[Mapping[str, Any]] | None = None,
) -> str:
    exits = [row for row in rows if row.get("event_type") == "exit" and row.get("outcome")]
    session_dates = {str(row.get("session_date")) for row in rows if row.get("session_date")}
    entries = [
        row
        for row in (ledger_rows or rows)
        if row.get("event_type") == "entry"
        and (not session_dates or str(row.get("session_date")) in session_dates)
    ]
    wins = sum(row.get("outcome") == "win" for row in exits)
    losses = sum(row.get("outcome") == "loss" for row in exits)
    flats = len(exits) - wins - losses
    ranked = sorted(exits, key=lambda row: abs(float(row.get("net_dollar") or 0.0)), reverse=True)
    lines = [
        f"**{label} EOD resolve**",
        f"Setups scanned={len({str(row.get('plan_id')) for row in entries if row.get('plan_id')})}",
        f"Resolved={len(exits)} W/L/Flat={wins}/{losses}/{flats}",
    ]
    for row in ranked[:10]:
        lines.append(
            f"{row.get('symbol') or 'MES'} {row.get('outcome')} net=${float(row.get('net_dollar') or 0.0):.2f} "
            f"exit={row.get('exit_reason') or row.get('reason')}"
        )
    if not exits:
        lines.append("No terminal setups were available for this run.")
    lines.append("Shadow evidence only. No order authority.")
    return "\n".join(lines)


def run_guarded(
    scanner: str,
    mode: str,
    *,
    notify: Callable[[str], Mapping[str, Any]] = send_discord,
    smoke: bool = False,
) -> dict[str, Any]:
    config = SCANNERS[scanner]
    label = str(config["label"])
    if kill_switch_active():
        notify(f"**KILL SWITCH ACTIVE** — {label} {mode} did not run.")
        return {"status": "killed", "scanner": scanner, "mode": mode, "exit_code": 0}
    if is_halted(scanner):
        return {"status": "auto_halted", "scanner": scanner, "mode": mode, "exit_code": 2}

    module = importlib.import_module(str(config["module"]))
    log_path = Path(module.LOG_PATH)
    if smoke:
        if scanner == "equity-orb-scout-v1":
            module.load_universe()
        return {"status": "smoke_pass", "scanner": scanner, "mode": mode, "exit_code": 0}

    before = _read_jsonl(log_path)
    try:
        result = module.run_entry(log_path=log_path) if mode == "entry" else module.run_resolve(log_path=log_path)
        if result != 0:
            raise RuntimeError(f"scanner_returned_{result}")
        after = _read_jsonl(log_path)
        rows = _new_rows(before, after)
        failure = _failure_row(rows)
        if failure is not None:
            reason = str(failure.get("error") or failure.get("reason") or "scanner_internal_failure")
            state = record_failure(scanner, error_type="scanner_internal_failure", reason=reason)
            notify(
                f"**{label} FAILURE {state['consecutive_failures']}/3**\n"
                f"mode={mode} reason={redact(reason)}\n"
                + ("AUTO-HALTED after three consecutive failures." if state["halted"] else "")
            )
            return {"status": "failed_closed", "scanner": scanner, "mode": mode, "exit_code": 1}

        state = record_success(scanner)
        from scripts.shadow_outcome_resolver import run_once as resolve_all

        resolver = resolve_all()
        message = (
            format_entry_alert(label, rows)
            if mode == "entry"
            else format_resolve_alert(label, rows, ledger_rows=after)
        )
        if scanner == "mes-orb-v2" and mode == "entry":
            hmm_skip = next(
                (row for row in rows if "hmm_state_unavailable" in str(row.get("reason") or "")),
                None,
            )
            if hmm_skip is not None:
                message = "**MES ORB v2 AUTO-HALT FOR STALE/MISSING HMM**\n" + message
        notification = notify(message)
        return {
            "status": "completed",
            "scanner": scanner,
            "mode": mode,
            "new_rows": len(rows),
            "resolver": resolver,
            "health": state,
            "notification": dict(notification),
            "exit_code": 0,
        }
    except Exception as exc:
        stack = redact(traceback.format_exc(limit=12))
        state = record_failure(scanner, error_type=type(exc).__name__, reason=str(exc))
        notify(
            f"**{label} EXCEPTION {state['consecutive_failures']}/3**\n"
            f"mode={mode} error={type(exc).__name__}: {redact(str(exc))}\n```\n{stack[-1400:]}\n```\n"
            + ("AUTO-HALTED after three consecutive failures." if state["halted"] else "")
        )
        return {
            "status": "exception",
            "scanner": scanner,
            "mode": mode,
            "error_type": type(exc).__name__,
            "exit_code": 1,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scanner", choices=tuple(SCANNERS), required=True)
    parser.add_argument("--mode", choices=("entry", "resolve"), required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    report = run_guarded(args.scanner, args.mode, smoke=args.smoke)
    print(json.dumps(report, sort_keys=True))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
