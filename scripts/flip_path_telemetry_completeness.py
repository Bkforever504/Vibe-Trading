#!/usr/bin/env python3
"""Forward-only Flip path telemetry completeness report.

Counts only observed entry/exit/path telemetry. Legacy reconstructed fields are
kept visible as synthetic rows and never count toward complete evidence.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VIBE_HOME = Path.home() / ".vibe-trading"
TRADES_PATH = VIBE_HOME / "flip-trades.json"
SAMPLES_PATH = VIBE_HOME / "logs" / "option-quote-samples.jsonl"
REPORT_PATH = VIBE_HOME / "reports" / "flip-path-telemetry-completeness.json"
ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "flip_path_telemetry_completeness_log.jsonl"
PATH_FIELDS = ("entry_at", "exit_at", "best_pnl_pct", "worst_pnl_pct")
REQUIRED_EVENTS = ("fill", "monitor", "exit")


def _read_trades(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _read_samples(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return rows
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _synthetic_path_fields(trade: dict[str, Any]) -> list[str]:
    backfilled = set(trade.get("_backfilled_fields") or [])
    provenance = trade.get("telemetry_provenance") or {}
    synthetic = set(field for field in PATH_FIELDS if field in backfilled)
    synthetic.update(
        field
        for field in PATH_FIELDS
        if isinstance(provenance.get(field), str) and "not_observed" in provenance[field]
    )
    if trade.get("path_telemetry_observed") is False or trade.get("telemetry_quality") == "synthetic_legacy_backfill":
        synthetic.update(field for field in PATH_FIELDS if trade.get(field) is not None)
    return sorted(synthetic)


def _sample_key(sample: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    return (
        str(sample.get("trade_id")) if sample.get("trade_id") else None,
        str(sample.get("order_id")) if sample.get("order_id") else None,
        str(sample.get("contract")) if sample.get("contract") else None,
    )


def _quote_observed(sample: dict[str, Any]) -> bool:
    provenance = sample.get("provenance") if isinstance(sample.get("provenance"), dict) else {}
    quote = sample.get("quote") if isinstance(sample.get("quote"), dict) else {}
    status = str(provenance.get("status") or "")
    return status in {"ok", "partial"} and quote.get("bid") is not None and quote.get("ask") is not None


def _samples_for_trade(trade: dict[str, Any], samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = {
        "trade_id": str(trade.get("id")) if trade.get("id") else None,
        "order_id": str(trade.get("alpaca_order_id")) if trade.get("alpaca_order_id") else None,
        "contract": str(trade.get("option_symbol")) if trade.get("option_symbol") else None,
    }
    matches = []
    for sample in samples:
        trade_id, order_id, contract = _sample_key(sample)
        if ids["trade_id"] and trade_id == ids["trade_id"]:
            matches.append(sample)
        elif ids["order_id"] and order_id == ids["order_id"]:
            matches.append(sample)
        elif ids["contract"] and contract == ids["contract"]:
            matches.append(sample)
    return matches


def evaluate_trade(trade: dict[str, Any], samples: list[dict[str, Any]]) -> dict[str, Any]:
    missing_fields = [field for field in PATH_FIELDS if trade.get(field) is None]
    synthetic_fields = _synthetic_path_fields(trade)
    trade_samples = _samples_for_trade(trade, samples)
    events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for sample in trade_samples:
        event = str(sample.get("event") or "")
        if event:
            events[event].append(sample)
    observed_events = sorted(event for event, rows in events.items() if any(_quote_observed(row) for row in rows))
    missing_events = [event for event in REQUIRED_EVENTS if event not in observed_events]
    complete = not missing_fields and not synthetic_fields and not missing_events
    return {
        "trade_id": trade.get("id"),
        "order_id": trade.get("alpaca_order_id"),
        "symbol": trade.get("symbol"),
        "option_symbol": trade.get("option_symbol"),
        "strategy": trade.get("strategy"),
        "status": "complete" if complete else "incomplete",
        "missing_fields": missing_fields,
        "synthetic_fields": synthetic_fields,
        "observed_quote_events": observed_events,
        "missing_quote_events": missing_events,
        "quote_sample_count": len(trade_samples),
    }


def build_report(trades_path: Path = TRADES_PATH, samples_path: Path = SAMPLES_PATH) -> dict[str, Any]:
    closed = [trade for trade in _read_trades(trades_path) if trade.get("status") == "closed"]
    samples = _read_samples(samples_path)
    rows = [evaluate_trade(trade, samples) for trade in closed]
    complete = [row for row in rows if row["status"] == "complete"]
    synthetic = [row for row in rows if row["synthetic_fields"]]
    return {
        "provider": "flip_path_telemetry_completeness",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "trades_path": str(trades_path),
        "samples_path": str(samples_path),
        "closed_trade_count": len(closed),
        "observed_complete_count": len(complete),
        "synthetic_legacy_count": len(synthetic),
        "incomplete_count": len(rows) - len(complete),
        "required_quote_events": list(REQUIRED_EVENTS),
        "trades": rows,
        "warnings": [
            "Read-only analytics. This report cannot submit orders or change thresholds.",
            "Legacy reconstructed fields are never counted as observed path telemetry.",
            "Complete requires observed fill, monitor, and exit quote samples with bid/ask provenance.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trades-path", type=Path, default=TRADES_PATH)
    parser.add_argument("--samples-path", type=Path, default=SAMPLES_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(args.trades_path, args.samples_path)
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Flip path telemetry completeness report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
