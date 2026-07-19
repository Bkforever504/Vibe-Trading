#!/usr/bin/env python3
"""Build read-only Flip exit-quality analytics from durable trade telemetry."""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from flip_exit_taxonomy import classify_exit_quality
except ModuleNotFoundError:
    from scripts.flip_exit_taxonomy import classify_exit_quality


VIBE_HOME = Path.home() / ".vibe-trading"
TRADES_PATH = VIBE_HOME / "flip-trades.json"
REPORT_PATH = VIBE_HOME / "reports" / "flip-exit-quality.json"
ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "flip_exit_quality_log.jsonl"
OBSERVED_PATH_FIELDS = {"entry_at", "exit_at", "best_pnl_pct", "worst_pnl_pct"}


def _read_trades(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    return [row for row in payload if isinstance(row, dict)] if isinstance(payload, list) else []


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value: Any) -> datetime | None:
    try:
        if not value:
            return None
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _synthetic_path_fields(trade: dict[str, Any]) -> list[str]:
    backfilled = set(trade.get("_backfilled_fields") or [])
    provenance = trade.get("telemetry_provenance") or {}
    synthetic = set()
    synthetic.update(field for field in OBSERVED_PATH_FIELDS if field in backfilled)
    synthetic.update(
        field
        for field in OBSERVED_PATH_FIELDS
        if isinstance(provenance.get(field), str) and "not_observed" in provenance[field]
    )
    if trade.get("path_telemetry_observed") is False:
        synthetic.update(field for field in OBSERVED_PATH_FIELDS if trade.get(field) is not None)
    if trade.get("telemetry_quality") == "synthetic_legacy_backfill":
        synthetic.update(field for field in OBSERVED_PATH_FIELDS if trade.get(field) is not None)
    return sorted(synthetic)


def evaluate_trade(trade: dict[str, Any]) -> dict[str, Any]:
    required = {
        "entry_at": _timestamp(trade.get("entry_at")),
        "exit_at": _timestamp(trade.get("exit_at")),
        "entry_price": _number(trade.get("entry_price")),
        "exit_price": _number(trade.get("exit_price")),
        "best_pnl_pct": _number(trade.get("best_pnl_pct")),
        "worst_pnl_pct": _number(trade.get("worst_pnl_pct")),
        "stop_price": _number(trade.get("stop_price")),
    }
    missing = [key for key, value in required.items() if value is None]
    base = {
        "trade_id": trade.get("id"),
        "order_id": trade.get("alpaca_order_id"),
        "symbol": trade.get("symbol"),
        "strategy": trade.get("strategy"),
        "right": trade.get("right"),
        "exit_reason": trade.get("exit_reason"),
    }
    if missing:
        return {**base, "status": "insufficient_data", "missing_fields": missing}

    synthetic = _synthetic_path_fields(trade)
    if synthetic:
        return {
            **base,
            "status": "insufficient_data",
            "missing_fields": [],
            "synthetic_fields": synthetic,
            "reason": "path telemetry was reconstructed from legacy fields, not observed",
        }

    entry_at = required["entry_at"]
    exit_at = required["exit_at"]
    entry = float(required["entry_price"])
    exit_price = float(required["exit_price"])
    mfe = float(required["best_pnl_pct"])
    mae = float(required["worst_pnl_pct"])
    stop_price = float(required["stop_price"])
    if entry <= 0 or exit_at < entry_at:
        invalid = ["entry_price"] if entry <= 0 else ["timestamp_order"]
        return {**base, "status": "insufficient_data", "missing_fields": invalid}

    realized = (exit_price - entry) / entry * 100
    stop_return = (stop_price - entry) / entry * 100
    quality = classify_exit_quality(mfe, realized, trade.get("exit_reason"))
    return {
        **base,
        "status": "complete",
        "hold_minutes": round((exit_at - entry_at).total_seconds() / 60, 2),
        "realized_return_pct": round(realized, 2),
        "mfe_pct": round(mfe, 2),
        "mae_pct": round(mae, 2),
        "exit_quality_classification": quality["exit_quality_classification"],
        "winner_capture_eligible": quality["winner_capture_eligible"],
        "capture_efficiency": quality["capture_efficiency"],
        "giveback_pct": quality["giveback_pct"],
        "favorable_excursion_surrendered_pct": quality["favorable_excursion_surrendered_pct"],
        "stop_return_pct": round(stop_return, 2),
        "mae_vs_stop_distance_pct": round(mae - stop_return, 2),
    }


def build_report(trades_path: Path = TRADES_PATH) -> dict[str, Any]:
    closed = [trade for trade in _read_trades(trades_path) if trade.get("status") == "closed"]
    rows = [evaluate_trade(trade) for trade in closed]
    complete = [row for row in rows if row["status"] == "complete"]
    insufficient = [row for row in rows if row["status"] == "insufficient_data"]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in complete:
        grouped[str(row.get("strategy") or "unknown")].append(row)

    by_strategy = {}
    for strategy, items in sorted(grouped.items()):
        by_strategy[strategy] = {
            "completed_count": len(items),
            "avg_hold_minutes": round(sum(row["hold_minutes"] for row in items) / len(items), 2),
            "avg_capture_efficiency": round(
                sum(row["capture_efficiency"] for row in items if row["capture_efficiency"] is not None)
                / len([row for row in items if row["capture_efficiency"] is not None]),
                3,
            ) if any(row["capture_efficiency"] is not None for row in items) else None,
            "avg_giveback_pct": round(
                sum(row["giveback_pct"] for row in items if row["giveback_pct"] is not None)
                / len([row for row in items if row["giveback_pct"] is not None]),
                2,
            ) if any(row["giveback_pct"] is not None for row in items) else None,
            "loss_after_favorable_excursion_count": sum(
                1 for row in items if row["favorable_excursion_surrendered_pct"] is not None
            ),
            "avg_mae_vs_stop_distance_pct": round(sum(row["mae_vs_stop_distance_pct"] for row in items) / len(items), 2),
        }

    return {
        "provider": "flip_exit_quality_report",
        "mode": "read_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_path": str(trades_path),
        "closed_trade_count": len(closed),
        "complete_count": len(complete),
        "insufficient_data_count": len(insufficient),
        "by_strategy": by_strategy,
        "trades": complete,
        "insufficient_data": insufficient,
        "warnings": [
            "Read-only analytics. This report cannot submit orders or change thresholds.",
            "Missing legacy telemetry is reported as insufficient_data and is never estimated.",
            "Synthetic legacy backfill fields are excluded from complete_count.",
            "Capture efficiency and giveback are defined only for exits above zero; losses use a separate favorable-excursion taxonomy.",
            "Use forward evidence and promotion review before changing exit behavior.",
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
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    report = build_report(args.trades_path)
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Flip exit-quality report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
