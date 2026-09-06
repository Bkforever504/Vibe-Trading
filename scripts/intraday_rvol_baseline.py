#!/usr/bin/env python3
"""Build read-only same-clock-time cumulative-volume baselines from Alpaca IEX bars.

The resulting profile is an IEX-relative-volume diagnostic, not consolidated
market volume and not an entry/ordering gate.  It exists so the intraday radar
can stop presenting a session-progress estimate as time-matched RVOL.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.premarket_opportunity_radar import _credentials, _finite

VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "intraday-rvol-baseline.json"
ET = ZoneInfo("America/New_York")
MAX_SYMBOLS_PER_REQUEST = 25


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def build_profiles(rows_by_symbol: dict[str, list[dict[str, Any]]], now_et: datetime, *, lookback_sessions: int = 20) -> dict[str, dict[str, Any]]:
    """Return cumulative-volume means at each 5-minute clock time from prior RTH sessions."""
    profiles: dict[str, dict[str, Any]] = {}
    for symbol, rows in rows_by_symbol.items():
        sessions: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
        for row in rows:
            timestamp = str(row.get("t") or "")
            try:
                stamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(ET)
            except ValueError:
                continue
            volume = _finite(row.get("v"))
            if stamp.date() >= now_et.date() or volume is None or not (time(9, 30) <= stamp.time() < time(16, 0)):
                continue
            sessions[stamp.date().isoformat()].append((stamp, volume))
        chosen = sorted(sessions)[-lookback_sessions:]
        by_time: dict[str, list[float]] = defaultdict(list)
        valid_sessions = 0
        for day in chosen:
            ordered = sorted(sessions[day])
            if len(ordered) < 50:  # reject partial sessions from a baseline
                continue
            valid_sessions += 1
            cumulative = 0.0
            for stamp, volume in ordered:
                cumulative += volume
                by_time[stamp.strftime("%H:%M")].append(cumulative)
        profiles[symbol.upper()] = {
            "status": "ok" if valid_sessions >= 10 else "insufficient_prior_sessions",
            "sessions_used": valid_sessions,
            "cumulative_volume_baseline_by_clock_et": {
                clock: round(sum(values) / len(values), 2) for clock, values in sorted(by_time.items())
            },
        }
    return profiles


def fetch_history(symbols: list[str], now_et: datetime) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    errors: list[str] = []
    start = (now_et - timedelta(days=40)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    end = datetime.combine(now_et.date(), time(9, 30), ET).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    for offset in range(0, len(symbols), MAX_SYMBOLS_PER_REQUEST):
        chunk = symbols[offset: offset + MAX_SYMBOLS_PER_REQUEST]
        params: dict[str, Any] = {"symbols": ",".join(chunk), "timeframe": "5Min", "start": start, "end": end, "adjustment": "raw", "feed": "iex", "limit": 10000, "sort": "asc"}
        token = None
        for _ in range(12):
            if token:
                params["page_token"] = token
            else:
                params.pop("page_token", None)
            try:
                response = requests.get("https://data.alpaca.markets/v2/stocks/bars", headers=_credentials(), params=params, timeout=30)
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                errors.append(f"alpaca_rvol_history:{type(exc).__name__}:{','.join(chunk[:3])}")
                break
            for symbol, values in (payload.get("bars") or {}).items():
                rows[str(symbol).upper()].extend(value for value in values or [] if isinstance(value, dict))
            token = payload.get("next_page_token")
            if not token:
                break
    return dict(rows), errors


def build_report(symbols: list[str], now_et: datetime | None = None) -> dict[str, Any]:
    now_et = (now_et or datetime.now(timezone.utc).astimezone(ET)).astimezone(ET)
    clean = sorted({symbol.strip().upper() for symbol in symbols if symbol.strip()})
    rows, errors = fetch_history(clean, now_et)
    profiles = build_profiles(rows, now_et)
    return {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "as_of_et": now_et.isoformat(), "provider": "alpaca_iex_5m", "mode": "read_only_context_only",
        "lookback_sessions": 20, "symbols_requested": clean, "profiles": profiles, "errors": errors,
        "execution_enabled": False, "can_submit_orders": False,
        "warnings": ["IEX-only time-matched cumulative volume; not consolidated RVOL and never an execution gate."],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="", help="Comma-separated equity symbols")
    parser.add_argument("--from-radar", type=Path, help="Use ranked symbols from an intraday radar report")
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    symbols = [value for value in args.symbols.split(",") if value.strip()]
    if args.from_radar:
        radar = _read_json(args.from_radar)
        symbols.extend(str(row.get("symbol") or "") for row in radar.get("ranked_candidates") or [] if isinstance(row, dict))
    if not symbols:
        parser.error("provide --symbols or --from-radar")
    requested = {value.strip().upper() for value in symbols if value.strip()}
    cached = _read_json(args.out)
    cached_symbols = {str(value).upper() for value in cached.get("symbols_requested") or []}
    cached_date = str(cached.get("as_of_et") or "")[:10]
    today_et = datetime.now(timezone.utc).astimezone(ET).date().isoformat()
    if cached_date == today_et and requested.issubset(cached_symbols):
        print(f"Intraday RVOL profiles: current-day cache reused symbols={len(cached_symbols)}")
        return 0
    report = build_report(symbols)
    _atomic_json(args.out, report)
    print(f"Intraday RVOL profiles: symbols={len(report['profiles'])} errors={len(report['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
