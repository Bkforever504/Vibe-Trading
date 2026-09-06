#!/usr/bin/env python3
"""Run the CISD retest detector against explicit completed-bar JSONL input."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.analytics.cisd_shadow import detect_cisd_lifecycle  # noqa: E402


VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_REPORT = VIBE_HOME / "reports" / "cisd-retest-shadow.json"
DEFAULT_LEDGER = VIBE_HOME / "data" / "cisd_retest_shadow.jsonl"
DEFAULT_CONFIG = ROOT / "config" / "cisd_shadow.json"
MARKET_TZ = ZoneInfo("America/New_York")
NYSE_HOLIDAYS_2026 = frozenset({
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
})


def _configuration(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("cisd_shadow_configuration_unavailable") from exc
    if not isinstance(value, dict):
        raise RuntimeError("cisd_shadow_configuration_invalid")
    if value.get("shadow_only") is not True or value.get("execution_enabled") is not False:
        raise RuntimeError("cisd_shadow_authority_configuration_invalid")
    if value.get("can_submit_orders") is not False or value.get("discord_delivery_enabled") is not False:
        raise RuntimeError("cisd_shadow_authority_configuration_invalid")
    return value


def _credentials() -> dict[str, str]:
    values = {
        "ALPACA_API_KEY": os.getenv("ALPACA_API_KEY", ""),
        "ALPACA_SECRET_KEY": os.getenv("ALPACA_SECRET_KEY", ""),
    }
    env_path = ROOT / "agent" / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            if raw.lstrip().startswith("#") or "=" not in raw:
                continue
            key, _, value = raw.partition("=")
            if key.strip() in values and not values[key.strip()]:
                values[key.strip()] = value.strip()
    if not all(values.values()):
        raise RuntimeError("alpaca_market_data_credentials_missing")
    return {
        "APCA-API-KEY-ID": values["ALPACA_API_KEY"],
        "APCA-API-SECRET-KEY": values["ALPACA_SECRET_KEY"],
    }


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fetch_completed_1m(
    symbols: Iterable[str], *, now_et: datetime, feed: str = "iex"
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Fetch read-only market data and reject malformed or incomplete bars."""
    requested = list(dict.fromkeys(str(value).upper() for value in symbols if str(value).strip()))
    start = datetime.combine(now_et.astimezone(MARKET_TZ).date(), wall_time(9, 30), MARKET_TZ)
    params = {
        "symbols": ",".join(requested), "timeframe": "1Min",
        "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "end": now_et.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "adjustment": "raw", "feed": feed, "limit": 10000, "sort": "asc",
    }
    last_error = "unknown"
    for attempt in range(1, 4):
        try:
            response = requests.get(
                "https://data.alpaca.markets/v2/stocks/bars",
                headers=_credentials(), params=params, timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            now_utc = now_et.astimezone(timezone.utc)
            output: dict[str, list[dict[str, Any]]] = {}
            for symbol, rows in (payload.get("bars") or {}).items():
                key = str(symbol).upper()
                if key not in requested:
                    continue
                clean = []
                for source in rows or []:
                    try:
                        started = datetime.fromisoformat(str(source.get("t") or "").replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    values = {field: _finite(source.get(field)) for field in ("o", "h", "l", "c", "v")}
                    if (
                        started.tzinfo is None or any(value is None for value in values.values())
                        or started.second or started.microsecond or values["v"] < 0
                        or min(values[field] for field in ("o", "h", "l", "c")) <= 0
                        or values["h"] < max(values["o"], values["c"])
                        or values["l"] > min(values["o"], values["c"])
                        or started.astimezone(MARKET_TZ).date() != now_et.astimezone(MARKET_TZ).date()
                        or not wall_time(9, 30) <= started.astimezone(MARKET_TZ).time() < wall_time(16)
                        or started.astimezone(timezone.utc) + timedelta(minutes=1) > now_utc
                    ):
                        continue
                    clean.append({"t": started.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), **values})
                unique = {str(row["t"]): row for row in clean}
                output[key] = [unique[value] for value in sorted(unique)]
            return output, []
        except Exception as exc:
            last_error = type(exc).__name__
            if attempt < 3:
                time.sleep(0.2 * attempt)
    return {}, [f"alpaca_completed_1m:{last_error}"]


def completed_input_bars(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        started = datetime.fromisoformat(str(row["t"]).replace("Z", "+00:00"))
        output.append({
            "timestamp": (started + timedelta(minutes=1)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "open": row["o"], "high": row["h"], "low": row["l"], "close": row["c"],
        })
    return output


def aggregate_completed_5m(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    source = list(rows)
    grouped: dict[datetime, list[Mapping[str, Any]]] = {}
    for row in source:
        completed = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
        started = completed - timedelta(minutes=1)
        bucket = started.replace(minute=(started.minute // 5) * 5, second=0, microsecond=0)
        grouped.setdefault(bucket, []).append(row)
    output = []
    for bucket, group in sorted(grouped.items()):
        ordered = sorted(group, key=lambda row: str(row["timestamp"]))
        expected = [bucket + timedelta(minutes=value + 1) for value in range(5)]
        actual = [datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00")) for row in ordered]
        if actual != expected:
            continue
        output.append({
            "timestamp": (bucket + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "open": ordered[0]["open"], "high": max(float(row["high"]) for row in ordered),
            "low": min(float(row["low"]) for row in ordered), "close": ordered[-1]["close"],
        })
    return output


def _event_id(row: Mapping[str, Any]) -> str:
    fields = ("signal_id", "symbol", "timeframe", "state", "reason", "direction", "bar_completed_at", "cisd_level")
    return hashlib.sha256("|".join(str(row.get(key) or "") for key in fields).encode()).hexdigest()


def append_unique(path: Path, events: Iterable[Mapping[str, Any]]) -> int:
    seen: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(str(json.loads(line).get("event_id") or ""))
            except json.JSONDecodeError:
                continue
    fresh = []
    for source in events:
        row = dict(source)
        row["event_id"] = _event_id(row)
        if row["event_id"] not in seen:
            fresh.append(row)
            seen.add(row["event_id"])
    if fresh:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in fresh:
                handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return len(fresh)


def run_live_shadow(*, now_et: datetime | None = None, config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    clock = (now_et or datetime.now(timezone.utc).astimezone(MARKET_TZ)).astimezone(MARKET_TZ)
    config = _configuration(config_path)
    symbols = tuple(str(value).upper() for value in config.get("symbols") or ())
    timeframes = tuple(str(value) for value in config.get("timeframes") or ())
    if not config.get("enabled", False):
        return {
            "schema_version": 1, "status": "disabled", "generated_at": clock.isoformat(),
            "provider": "none", "events": [], "errors": [], "execution_enabled": False,
            "can_submit_orders": False, "shadow_only": True,
        }
    if not symbols or not timeframes or not set(timeframes).issubset({"1m", "5m"}):
        raise RuntimeError("cisd_shadow_configuration_invalid")
    market_open = (
        clock.weekday() < 5 and clock.date().isoformat() not in NYSE_HOLIDAYS_2026
        and wall_time(9, 30) <= clock.time().replace(tzinfo=None) <= wall_time(16, 5)
    )
    if not market_open:
        return {
            "schema_version": 1, "status": "market_closed", "generated_at": clock.isoformat(),
            "provider": "none", "events": [], "errors": [], "execution_enabled": False,
            "can_submit_orders": False, "shadow_only": True,
        }
    feed = str(os.getenv("VIBE_TRADING_STOCK_FEED") or "iex").lower()
    feed = feed if feed in {"iex", "sip"} else "iex"
    raw, errors = fetch_completed_1m(symbols, now_et=clock, feed=feed)
    events: list[dict[str, Any]] = []
    coverage = {}
    for symbol in symbols:
        one_minute = completed_input_bars(raw.get(symbol, []))
        five_minute = aggregate_completed_5m(one_minute)
        coverage[symbol] = {"completed_1m": len(one_minute), "completed_5m": len(five_minute)}
        parameters = {
            "atr_period": int(config["atr_period"]),
            "atr_multiplier": float(config["atr_multiplier"]),
            "pending_timeout_bars": int(config["pending_timeout_bars"]),
            "retest_tolerance_atr": float(config["retest_tolerance_atr"]),
        }
        if "1m" in timeframes and one_minute:
            events.extend(detect_cisd_lifecycle(one_minute, symbol=symbol, timeframe="1m", **parameters))
        if "5m" in timeframes and five_minute:
            events.extend(detect_cisd_lifecycle(five_minute, symbol=symbol, timeframe="5m", **parameters))
    return {
        "schema_version": 1,
        "status": "ok" if not errors and all(value["completed_1m"] for value in coverage.values()) else "missing",
        "generated_at": clock.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": f"alpaca_{feed}_completed_bars",
        "coverage": coverage,
        "events": events,
        "errors": errors,
        "execution_enabled": False,
        "can_submit_orders": False,
        "shadow_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bars", type=Path, help="Completed OHLC bars as JSONL")
    parser.add_argument("--symbol")
    parser.add_argument("--timeframe", choices=("1m", "3m", "5m"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--live-shadow", action="store_true")
    args = parser.parse_args()
    if args.live_shadow:
        report = run_live_shadow()
        written = append_unique(DEFAULT_LEDGER, report["events"])
        report["new_events_written"] = written
        report["events"] = report["events"][-20:]
        DEFAULT_REPORT.parent.mkdir(parents=True, exist_ok=True)
        DEFAULT_REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "events"}))
        return 0 if report["status"] in {"ok", "market_closed"} else 2
    if not args.bars or not args.symbol or not args.timeframe or not args.output:
        parser.error("manual mode requires --bars, --symbol, --timeframe, and --output")
    rows = [json.loads(line) for line in args.bars.read_text(encoding="utf-8").splitlines() if line.strip()]
    events = detect_cisd_lifecycle(rows, symbol=args.symbol, timeframe=args.timeframe)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in events), encoding="utf-8")
    print(json.dumps({
        "status": "ok", "symbol": args.symbol.upper(), "timeframe": args.timeframe,
        "events": len(events), "retest_ready": sum(bool(row["retest_ready"]) for row in events),
        "execution_enabled": False, "can_submit_orders": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
