#!/usr/bin/env python3
"""Refresh current core-leader option quote telemetry before qualification.

The producer selects near-ATM call/put contracts from the latest local option
surface and captures point-in-time quotes through the existing read-only
adapter.  It never submits orders and never upgrades indicative data to OPRA.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_SURFACE = VIBE_HOME / "reports" / "options-surface-intelligence.json"
DEFAULT_OUTPUT = VIBE_HOME / "reports" / "options-reference-refresh.json"
CORE_ORDER = ("SPY", "QQQ", "TSLA", "IWM", "NVDA")

load_dotenv(ROOT / "agent" / ".env")

from scripts.point_in_time_quotes import capture_lifecycle_sample
from scripts.tradier_options_data import configured_quote_provider


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _occ_symbol(symbol: str, expiry: str, right: str, strike: Any) -> str | None:
    symbol = str(symbol or "").strip().upper()
    right = str(right or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{1,6}", symbol) or right not in {"C", "P"}:
        return None
    try:
        expiry_date = date.fromisoformat(str(expiry))
        strike_code = int(round(float(strike) * 1000))
    except (TypeError, ValueError):
        return None
    if strike_code <= 0:
        return None
    return f"{symbol}{expiry_date:%y%m%d}{right}{strike_code:08d}"


def select_reference_contracts(
    surface: Mapping[str, Any],
    *,
    today: date | None = None,
    max_underlyings: int = 5,
) -> list[dict[str, Any]]:
    """Select one near-ATM call and put for each prioritized current expiry."""
    session_date = today or datetime.now(timezone.utc).date()
    rows = surface.get("results") if isinstance(surface.get("results"), list) else []
    by_symbol = {
        str(row.get("symbol") or "").upper(): row
        for row in rows
        if isinstance(row, Mapping) and row.get("symbol")
    }
    selected: list[dict[str, Any]] = []
    for symbol in CORE_ORDER[: max(0, max_underlyings)]:
        row = by_symbol.get(symbol)
        if not isinstance(row, Mapping):
            continue
        expiries = row.get("expiries") if isinstance(row.get("expiries"), list) else []
        current = []
        for raw in expiries:
            if not isinstance(raw, Mapping):
                continue
            try:
                expiry_date = date.fromisoformat(str(raw.get("expiry")))
            except ValueError:
                continue
            if expiry_date >= session_date and raw.get("atm_strike") is not None:
                current.append((expiry_date, raw))
        if not current:
            continue
        expiry_date, expiry_row = min(current, key=lambda item: item[0])
        for right in ("C", "P"):
            contract = _occ_symbol(symbol, expiry_date.isoformat(), right, expiry_row.get("atm_strike"))
            if contract:
                selected.append({
                    "symbol": symbol,
                    "contract": contract,
                    "expiry": expiry_date.isoformat(),
                    "right": right,
                    "strike": float(expiry_row["atm_strike"]),
                })
    return selected


def _alpaca_headers() -> dict[str, str]:
    key = (os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID") or "").strip()
    secret = (
        os.getenv("ALPACA_SECRET_KEY")
        or os.getenv("ALPACA_API_SECRET")
        or os.getenv("APCA_API_SECRET_KEY")
        or ""
    ).strip()
    if not key or not secret:
        return {}
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def refresh_references(
    selections: Sequence[Mapping[str, Any]],
    *,
    capture_fn: Callable[..., dict[str, Any] | None] = capture_lifecycle_sample,
    max_workers: int = 5,
) -> dict[str, Any]:
    provider = configured_quote_provider()
    headers = _alpaca_headers() if provider != "tradier" else {}
    credential_ready = provider == "tradier" or bool(headers)

    def capture(row: Mapping[str, Any]) -> tuple[str, dict[str, Any] | None]:
        contract = str(row.get("contract") or "")
        record = capture_fn(
            "monitor",
            contract,
            bot="dashboard_options_reference_refresh",
            headers=headers or None,
            underlying_symbol=str(row.get("symbol") or ""),
            context={
                "purpose": "current_manual_reference_qualification",
                "selection": dict(row),
                "execution_enabled": False,
                "can_submit_orders": False,
            },
        )
        return contract, record

    captured: list[dict[str, Any]] = []
    if credential_ready and selections:
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(selections)))) as pool:
            futures = [pool.submit(capture, row) for row in selections]
            for future in as_completed(futures):
                contract, record = future.result()
                captured.append({
                    "contract": contract,
                    "captured": bool(record),
                    "quote_status": ((record or {}).get("provenance") or {}).get("status"),
                })
    return {
        "provider": "options_reference_refresh",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "read_only_quote_telemetry",
        "quote_provider": provider,
        "credential_ready": credential_ready,
        "selected_count": len(selections),
        "captured_count": sum(bool(row["captured"]) for row in captured),
        "selections": [dict(row) for row in selections],
        "captures": sorted(captured, key=lambda row: row["contract"]),
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _write_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", type=Path, default=DEFAULT_SURFACE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-underlyings", type=int, default=5)
    args = parser.parse_args()
    surface = _read(args.surface)
    selected = select_reference_contracts(surface, max_underlyings=args.max_underlyings)
    report = refresh_references(selected)
    _write_atomic(args.output, report)
    print(
        "options_reference_refresh "
        f"selected={report['selected_count']} captured={report['captured_count']} "
        f"provider={report['quote_provider']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
