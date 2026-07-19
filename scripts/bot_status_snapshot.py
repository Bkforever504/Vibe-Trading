#!/usr/bin/env python3
"""Compact read-only status snapshot across the bot stack.

This is the useful part of the go-trader style dashboard pattern: one small
daily row that says whether the stack is healthy, what posture it is in, and
where risk is concentrated. It reads local reports only and never submits orders.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_DIR = VIBE_HOME / "reports"
REPORT_PATH = REPORT_DIR / "bot-status-snapshot.json"
LOG_PATH = ROOT / "data" / "bot_status_snapshot_log.jsonl"
OCC_SYMBOL_RE = re.compile(r"^[A-Z]+\d{6}[CP]\d{8}$")


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _latest_jsonl(path: Path) -> dict[str, Any] | None:
    rows = _read_jsonl(path)
    return rows[-1] if rows else None


def _trade_counts() -> dict[str, Any]:
    flip_rows = _read_json(VIBE_HOME / "flip-trades.json")
    if not isinstance(flip_rows, list):
        flip_rows = []
    iwm_payload = _read_json(VIBE_HOME / "options-trades.json")
    iwm_rows = iwm_payload.get("trades") if isinstance(iwm_payload, dict) else []
    if not isinstance(iwm_rows, list):
        iwm_rows = []
    return {
        "flip": {
            "total": len(flip_rows),
            "open": sum(1 for row in flip_rows if isinstance(row, dict) and row.get("status") == "open"),
            "closed": sum(1 for row in flip_rows if isinstance(row, dict) and row.get("status") == "closed"),
        },
        "iwm_options": {
            "total": len(iwm_rows),
            "open": sum(1 for row in iwm_rows if isinstance(row, dict) and row.get("status") == "open"),
            "closed": sum(1 for row in iwm_rows if isinstance(row, dict) and row.get("status") == "closed"),
        },
    }


def _guard_block_counts() -> dict[str, int]:
    counts = {"alpaca": 0, "kalshi": 0}
    counts["alpaca"] = len(_read_jsonl(VIBE_HOME / "guard-blocks.jsonl"))
    counts["kalshi"] = len(_read_jsonl(VIBE_HOME / "kalshi-guard-blocks.jsonl"))
    return counts


def _health_summary(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {"status": "missing", "ok": 0, "stale": 0, "missing": 0, "error": 0}
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    error_count = int(summary.get("error") or 0)
    missing_count = int(summary.get("missing") or 0)
    stale_count = int(summary.get("stale") or 0)
    status = "ok"
    if error_count:
        status = "error"
    elif missing_count:
        status = "missing"
    elif stale_count:
        status = "stale"
    return {
        "status": status,
        "ok": int(summary.get("ok") or 0),
        "stale": stale_count,
        "missing": missing_count,
        "error": error_count,
    }


def _warning_rollup(*reports: dict[str, Any] | None) -> list[str]:
    warnings: list[str] = []
    for report in reports:
        if not isinstance(report, dict):
            continue
        for key in ("warnings", "notes"):
            values = report.get(key)
            if isinstance(values, list):
                warnings.extend(str(value) for value in values[:5])
    return warnings[:12]


def _option_position_integrity(
    concentration: dict[str, Any] | None,
    trade_state: dict[str, Any] | None,
) -> dict[str, Any]:
    conc = concentration.get("concentration") if isinstance(concentration, dict) else {}
    positions = conc.get("positions") if isinstance(conc, dict) else None
    trades = trade_state.get("trades") if isinstance(trade_state, dict) else []
    if not isinstance(trades, list):
        trades = []

    active = [
        trade for trade in trades
        if isinstance(trade, dict) and trade.get("status") in {"open", "closing"}
    ]
    expected_owners: dict[str, list[str]] = {}
    for trade in active:
        owner = str(trade.get("id") or trade.get("label") or "unknown")
        for symbol in trade.get("legs") or []:
            expected_owners.setdefault(str(symbol), []).append(owner)
    expected = set(expected_owners)

    if not isinstance(positions, list):
        return {
            "status": "unknown" if expected else "ok",
            "broker_option_positions": None,
            "active_groups": len(active),
            "expected_active_legs": len(expected),
            "missing_active_legs": [],
            "untracked_broker_legs": [],
            "closed_trade_legs_still_open": [],
            "duplicate_active_legs": [],
            "issues": ["broker_position_snapshot_unavailable"] if expected else [],
        }

    broker_symbols = {
        str(position.get("symbol"))
        for position in positions
        if isinstance(position, dict) and OCC_SYMBOL_RE.match(str(position.get("symbol") or ""))
    }
    missing = sorted(expected - broker_symbols)
    untracked = sorted(broker_symbols - expected)
    closed_leg_symbols = {
        str(symbol)
        for trade in trades
        if isinstance(trade, dict) and trade.get("status") == "closed"
        for symbol in trade.get("legs") or []
    }
    closed_still_open = sorted(set(untracked) & closed_leg_symbols)
    duplicate_active = sorted(
        symbol for symbol, owners in expected_owners.items() if len(owners) > 1
    )
    issues = []
    if missing:
        issues.append("missing_active_legs")
    if untracked:
        issues.append("untracked_broker_legs")
    if closed_still_open:
        issues.append("closed_trade_legs_still_open")
    if duplicate_active:
        issues.append("duplicate_active_leg_ownership")
    return {
        "status": "review_required" if issues else "ok",
        "broker_option_positions": len(broker_symbols),
        "active_groups": len(active),
        "expected_active_legs": len(expected),
        "missing_active_legs": missing,
        "untracked_broker_legs": untracked,
        "closed_trade_legs_still_open": closed_still_open,
        "duplicate_active_legs": duplicate_active,
        "issues": issues,
    }


def build_snapshot(
    *,
    health_report: dict[str, Any] | None = None,
    market_force: dict[str, Any] | None = None,
    exposure: dict[str, Any] | None = None,
    concentration: dict[str, Any] | None = None,
    outcome: dict[str, Any] | None = None,
    options_state: dict[str, Any] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or datetime.now(timezone.utc)
    health_report = health_report if health_report is not None else _read_json(REPORT_DIR / "signal-stack-health.json")
    market_force = market_force if market_force is not None else _latest_jsonl(ROOT / "data" / "market_force_score_log.jsonl")
    exposure = exposure if exposure is not None else _latest_jsonl(ROOT / "data" / "exposure_coach_log.jsonl")
    concentration = concentration if concentration is not None else _read_json(REPORT_DIR / "portfolio-concentration.json")
    outcome = outcome if outcome is not None else _latest_jsonl(ROOT / "data" / "daily_outcome_review_log.jsonl")
    options_state = options_state if options_state is not None else _read_json(VIBE_HOME / "options-trades.json")

    conc = concentration.get("concentration") if isinstance(concentration, dict) else {}
    account = concentration.get("account") if isinstance(concentration, dict) else {}
    event_summary = outcome.get("event_summary") if isinstance(outcome, dict) else {}
    snapshot = {
        "date": generated_at.date().isoformat(),
        "timestamp": generated_at.isoformat().replace("+00:00", "Z"),
        "provider": "bot_status_snapshot",
        "mode": "read_only",
        "execution_enabled": False,
        "health": _health_summary(health_report),
        "market_force": {
            "classification": (market_force or {}).get("classification"),
            "score": (market_force or {}).get("total_score"),
            "confidence": (market_force or {}).get("confidence"),
        },
        "exposure": {
            "posture": (exposure or {}).get("posture"),
            "score": (exposure or {}).get("score"),
            "max_new_trades": ((exposure or {}).get("advisory_settings") or {}).get("max_new_trades"),
        },
        "portfolio_concentration": {
            "risk_level": conc.get("risk_level"),
            "position_count": conc.get("position_count"),
            "gross_pct_equity": conc.get("gross_pct_equity"),
            "net_directional_beta_pct_equity": conc.get("net_directional_beta_pct_equity"),
            "warnings": conc.get("warnings") or [],
        },
        "option_position_integrity": _option_position_integrity(concentration, options_state),
        "account": {
            "equity": account.get("equity"),
            "day_change": account.get("day_change"),
            "buying_power": account.get("buying_power"),
        },
        "open_trades": _trade_counts(),
        "guard_blocks": _guard_block_counts(),
        "outcome": {
            "verdict": (outcome or {}).get("verdict"),
            "review_score": (outcome or {}).get("review_score"),
            "realized_pnl": (event_summary or {}).get("realized_pnl"),
            "guard_block_count": (event_summary or {}).get("guard_block_count"),
        },
        "warnings": _warning_rollup(market_force, exposure, concentration, outcome),
    }
    status_flags = []
    if snapshot["health"]["status"] not in {"ok", "stale"}:
        status_flags.append(f"health_{snapshot['health']['status']}")
    if snapshot["portfolio_concentration"]["risk_level"] in {"elevated", "high"}:
        status_flags.append(f"concentration_{snapshot['portfolio_concentration']['risk_level']}")
    if snapshot["exposure"]["posture"] in {"blocked", "risk_off"}:
        status_flags.append(f"exposure_{snapshot['exposure']['posture']}")
    integrity_status = snapshot["option_position_integrity"]["status"]
    if integrity_status != "ok":
        status_flags.append(f"option_position_integrity_{integrity_status}")
    snapshot["status"] = "review_required" if integrity_status == "review_required" else ("watch" if status_flags else "normal")
    snapshot["status_flags"] = status_flags
    return snapshot


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), default=str) + "\n")


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report_path


def print_snapshot(report: dict[str, Any]) -> None:
    conc = report["portfolio_concentration"]
    print("\nBot Status Snapshot | read-only")
    print("=" * 72)
    print(
        f"status={report['status']} health={report['health']['status']} "
        f"market={report['market_force']['classification']} exposure={report['exposure']['posture']}"
    )
    print(
        f"account_day_change={report['account']['day_change']} "
        f"concentration={conc['risk_level']} gross={conc['gross_pct_equity']}% "
        f"beta={conc['net_directional_beta_pct_equity']}%"
    )
    print(
        f"open flip={report['open_trades']['flip']['open']} "
        f"iwm={report['open_trades']['iwm_options']['open']} "
        f"guard_blocks={report['guard_blocks']}"
    )
    integrity = report["option_position_integrity"]
    print(
        f"option_integrity={integrity['status']} broker_legs={integrity['broker_option_positions']} "
        f"expected_legs={integrity['expected_active_legs']}"
    )
    if report["status_flags"]:
        print("flags: " + ", ".join(report["status_flags"]))
    print(f"JSON: {REPORT_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    report = build_snapshot()
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_snapshot(report)
    else:
        print(f"Bot status snapshot logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
