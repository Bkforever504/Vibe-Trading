#!/usr/bin/env python3
"""Paper-only Alpaca option/order stream supervisor for Flip protection.

OPRA quote events trigger an immediate serialized monitor pass. Indicative
quotes may be recorded for diagnostics but never receive execution authority.
Broker trade updates always trigger reconciliation. Polling tasks remain the
fallback if either websocket is unavailable.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / "agent" / ".env")

from strategies import flip_bot


STATE_PATH = Path.home() / ".vibe-trading" / "flip-trades.json"
CACHE_PATH = Path.home() / ".vibe-trading" / "state" / "flip-option-stream-quotes.json"
HEALTH_PATH = Path.home() / ".vibe-trading" / "reports" / "flip-event-monitor-health.json"
EVENT_LOG_PATH = Path.home() / ".vibe-trading" / "logs" / "flip-event-monitor.jsonl"
FEED_NAME = os.getenv("FLIP_OPTION_STREAM_FEED", "opra").strip().lower()
ALLOW_INDICATIVE_TELEMETRY = os.getenv("FLIP_ALLOW_INDICATIVE_STREAM_TELEMETRY", "true").lower() == "true"
DEBOUNCE_SECONDS = max(0.25, float(os.getenv("FLIP_EVENT_MONITOR_DEBOUNCE_SECONDS", "0.75")))
_quotes: dict[str, dict[str, Any]] = {}
_quote_lock = threading.Lock()
_trigger_lock = threading.Lock()
_last_trigger = 0.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _event(kind: str, **details: Any) -> None:
    EVENT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": _utc_now(), "kind": kind, **details}
    with EVENT_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _health(status: str, **details: Any) -> None:
    _atomic_json(
        HEALTH_PATH,
        {
            "provider": "flip_event_monitor",
            "generated_at": _utc_now(),
            "status": status,
            "paper": flip_bot.PAPER,
            "live_execution_enabled": flip_bot.LIVE_EXECUTION_ENABLED,
            "requested_feed": FEED_NAME,
            "quote_execution_authority": FEED_NAME == "opra",
            "polling_fallback_retained": True,
            **details,
        },
    )


def _open_option_symbols() -> set[str]:
    if not STATE_PATH.exists():
        return set()
    try:
        rows = json.loads(STATE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        _event("state_read_failed", error=str(exc))
        return set()
    result = set()
    for row in rows if isinstance(rows, list) else []:
        if row.get("status") != "open":
            continue
        for key in ("option_symbol", "short_option_symbol"):
            if row.get(key):
                result.add(str(row[key]))
    return result


def _quote_field(value: Any, *names: str) -> Any:
    if isinstance(value, dict):
        for name in names:
            if name in value:
                return value[name]
        return None
    for name in names:
        if hasattr(value, name):
            return getattr(value, name)
    return None


def _write_quote_cache() -> None:
    with _quote_lock:
        payload = {
            "provider": "alpaca_option_stream",
            "generated_at": _utc_now(),
            "feed": FEED_NAME,
            "quote_authority": "opra" if FEED_NAME == "opra" else "indicative_telemetry_only",
            "quotes": dict(_quotes),
        }
    _atomic_json(CACHE_PATH, payload)


def _trigger_monitor(source: str) -> None:
    global _last_trigger
    with _trigger_lock:
        now = time.monotonic()
        if now - _last_trigger < DEBOUNCE_SECONDS:
            return
        _last_trigger = now
    try:
        flip_bot.run_event_monitor_pass(source=source)
    except Exception as exc:
        _event("monitor_pass_failed", source=source, error=str(exc))


async def _on_quote(quote: Any) -> None:
    symbol = str(_quote_field(quote, "symbol", "S") or "")
    bid = _quote_field(quote, "bid_price", "bp")
    ask = _quote_field(quote, "ask_price", "ap")
    timestamp = _quote_field(quote, "timestamp", "t") or _utc_now()
    if not symbol:
        return
    try:
        bid_value = float(bid or 0.0)
        ask_value = float(ask or 0.0)
    except (TypeError, ValueError):
        return
    with _quote_lock:
        _quotes[symbol] = {
            "bid": bid_value or None,
            "ask": ask_value or None,
            "timestamp": str(timestamp),
            "received_at": _utc_now(),
            "feed": FEED_NAME,
            "quote_authority": "opra" if FEED_NAME == "opra" else "indicative_telemetry_only",
        }
    await asyncio.to_thread(_write_quote_cache)
    if FEED_NAME == "opra":
        await asyncio.to_thread(_trigger_monitor, "opra_option_quote")


async def _on_trade_update(update: Any) -> None:
    event_name = str(_quote_field(update, "event") or "trade_update")
    order = _quote_field(update, "order")
    order_id = _quote_field(order, "id") if order is not None else None
    symbol = _quote_field(order, "symbol") if order is not None else None
    _event("broker_trade_update", event=event_name, order_id=order_id, symbol=symbol)
    await asyncio.to_thread(_trigger_monitor, "broker_trade_update")


def _run_trade_stream(stop_event: threading.Event) -> None:
    try:
        from alpaca.trading.stream import TradingStream

        stream = TradingStream(flip_bot.KEY, flip_bot.SECRET, paper=True)
        stream.subscribe_trade_updates(_on_trade_update)
        _event("trade_stream_started")
        stream.run()
    except Exception as exc:
        _event("trade_stream_failed", error=str(exc))


def _run_option_stream(symbols: set[str]) -> None:
    try:
        from alpaca.data.enums import OptionsFeed
        from alpaca.data.live.option import OptionDataStream

        feed = OptionsFeed.OPRA if FEED_NAME == "opra" else OptionsFeed.INDICATIVE
        stream = OptionDataStream(flip_bot.KEY, flip_bot.SECRET, feed=feed)
        stream.subscribe_quotes(_on_quote, *sorted(symbols))
        _event("option_stream_started", symbols=sorted(symbols), feed=FEED_NAME)
        stream.run()
    except Exception as exc:
        _event("option_stream_failed", symbols=sorted(symbols), feed=FEED_NAME, error=str(exc))


def _within_session() -> bool:
    now_et = flip_bot._now_et()
    return dtime(8, 20) <= now_et.time() <= dtime(16, 10)


def main() -> int:
    if not flip_bot.PAPER or flip_bot.LIVE_EXECUTION_ENABLED:
        _health("blocked", reason="paper_only_supervisor")
        print("Flip event monitor blocked: ALPACA_PAPER=true and live execution disabled are required")
        return 2
    if not flip_bot.KEY or not flip_bot.SECRET:
        _health("blocked", reason="alpaca_credentials_missing")
        print("Flip event monitor blocked: Alpaca credentials missing")
        return 2
    if FEED_NAME not in {"opra", "indicative"}:
        _health("blocked", reason="invalid_feed")
        return 2
    if FEED_NAME == "indicative" and not ALLOW_INDICATIVE_TELEMETRY:
        _health("blocked", reason="indicative_feed_not_authorized")
        return 2

    stop_event = threading.Event()
    trading_thread = threading.Thread(target=_run_trade_stream, args=(stop_event,), daemon=True, name="flip-order-stream")
    trading_thread.start()
    active_symbols: set[str] = set()
    option_thread: threading.Thread | None = None
    _health("running", active_symbols=[])

    while _within_session() and not stop_event.is_set():
        symbols = _open_option_symbols()
        if symbols and (option_thread is None or not option_thread.is_alive() or symbols != active_symbols):
            # A symbol change starts a fresh subscription. Old daemon threads are
            # harmless because closed symbols cannot pass the durable state gate.
            active_symbols = symbols
            option_thread = threading.Thread(target=_run_option_stream, args=(symbols,), daemon=True, name="flip-option-stream")
            option_thread.start()
            _health("running", active_symbols=sorted(active_symbols))
        time.sleep(2)

    _health("stopped", active_symbols=sorted(active_symbols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
