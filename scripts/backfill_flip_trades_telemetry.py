#!/usr/bin/env python3
"""One-time legacy annotation for Flip trades.

This script may reconstruct useful context for old trades, but reconstructed
fields are not observed path telemetry and must not be counted as complete
entry/exit evidence by downstream reports.

- entry_at: inferred from entry_date at market open; exact time was not recorded
- exit_at: inferred from exit_date and configured close time; exact time was not recorded
- best_pnl_pct: parsed from exit_reason when explicitly present, otherwise reconstructed
- configured_stop_return_pct: derived from stop_price; not observed worst excursion
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo


TRADES_PATH = Path.home() / ".vibe-trading" / "flip-trades.json"
DRY_RUN = True  # set False only for a deliberate one-time migration


def _parse_best_pnl_from_reason(exit_reason: str | None, exit_return_pct: float | None) -> float | None:
    if not exit_reason:
        return exit_return_pct
    match = re.search(r"best \+?([-\d.]+)%", exit_reason, re.IGNORECASE)
    if match:
        return float(match.group(1))
    match = re.search(r"(PROFIT TARGET|STOP LOSS)\s+([+-]?[\d.]+)%", exit_reason, re.IGNORECASE)
    if match:
        return float(match.group(2))
    return exit_return_pct


def _ny_timestamp(date_value: str, hhmm: str) -> str:
    hour, minute = map(int, hhmm.split(":"))
    local = datetime.combine(
        datetime.fromisoformat(date_value).date(),
        time(hour, minute),
        tzinfo=ZoneInfo("America/New_York"),
    )
    return local.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z")


def _backfill_trade(trade: dict) -> tuple[dict, list[str]]:
    filled: list[str] = []
    provenance = dict(trade.get("telemetry_provenance") or {})
    entry_price = float(trade.get("entry_price") or 0.0)
    exit_price = float(trade.get("exit_price") or 0.0)
    stop_price = float(trade.get("stop_price") or 0.0)

    if not trade.get("entry_at") and trade.get("entry_date"):
        trade["entry_at"] = _ny_timestamp(str(trade["entry_date"]), "09:30")
        provenance["entry_at"] = "inferred_market_open_from_entry_date_not_observed"
        filled.append("entry_at")

    if not trade.get("exit_at") and trade.get("exit_date"):
        hard_close_time = str(trade.get("hard_close_time") or "13:45")
        trade["exit_at"] = _ny_timestamp(str(trade["exit_date"]), hard_close_time)
        provenance["exit_at"] = "inferred_configured_close_from_exit_date_not_observed"
        filled.append("exit_at")

    if trade.get("best_pnl_pct") is None and entry_price > 0 and exit_price > 0:
        exit_return_pct = (exit_price - entry_price) / entry_price * 100
        best = _parse_best_pnl_from_reason(trade.get("exit_reason"), exit_return_pct)
        if best is not None:
            trade["best_pnl_pct"] = round(best, 2)
            provenance["best_pnl_pct"] = "legacy_reconstructed_from_exit_reason_or_exit_price_not_path_observed"
            filled.append("best_pnl_pct")

    if trade.get("configured_stop_return_pct") is None and entry_price > 0 and stop_price > 0:
        stop_return = (stop_price - entry_price) / entry_price * 100
        trade["configured_stop_return_pct"] = round(stop_return, 2)
        provenance["configured_stop_return_pct"] = "derived_from_configured_stop_price_not_path_observed"
        filled.append("configured_stop_return_pct")

    if filled:
        trade["_backfilled_fields"] = filled
        trade["_backfill_source"] = "backfill_flip_trades_telemetry.py"
        trade["path_telemetry_observed"] = False
        trade["telemetry_quality"] = "synthetic_legacy_backfill"
        trade["telemetry_provenance"] = provenance

    return trade, filled


def main() -> int:
    try:
        raw = json.loads(TRADES_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR reading {TRADES_PATH}: {exc}")
        return 1

    if not isinstance(raw, list):
        print("ERROR: flip-trades.json is not a list")
        return 1

    total_filled = 0
    for trade in raw:
        if not isinstance(trade, dict) or trade.get("status") != "closed":
            continue
        _, filled = _backfill_trade(trade)
        if filled:
            total_filled += 1
            print(
                f"  {str(trade.get('id', '?'))[:8]}  {trade.get('exit_date')}  "
                f"{str(trade.get('exit_reason', ''))[:40]}  => filled: {filled}"
            )

    print(f"\n{total_filled} trade(s) annotated.")

    if DRY_RUN:
        print("DRY RUN - no file written.")
        return 0

    backup = TRADES_PATH.with_suffix(".json.bak")
    backup.write_text(json.dumps(json.loads(TRADES_PATH.read_text(encoding="utf-8-sig")), indent=2) + "\n", encoding="utf-8")
    print(f"Backup -> {backup}")

    out = json.dumps(raw, indent=2) + "\n"
    tmp = TRADES_PATH.with_suffix(".json.tmp")
    tmp.write_text(out, encoding="utf-8")
    os.replace(tmp, TRADES_PATH)
    print(f"Written -> {TRADES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
