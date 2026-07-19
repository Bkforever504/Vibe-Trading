#!/usr/bin/env python3
"""Read-only Tradovate market data helpers for MNQ/NQ shadow validation.

This module never submits orders. It only authenticates, resolves a futures
contract, and requests chart bars from Tradovate's market-data WebSocket.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

try:
    from strategies.topstep_prop_bot import Candle
except ModuleNotFoundError:
    from topstep_prop_bot import Candle


@dataclass(frozen=True)
class TradovateEndpoints:
    rest_base: str
    market_data_ws: str


@dataclass(frozen=True)
class TradovateSettings:
    username: str
    password: str
    app_id: str
    app_version: str
    cid: str
    sec: str
    device_id: str = "vibe-trading-local"
    env: str = "demo"

    @classmethod
    def from_env(cls) -> "TradovateSettings":
        return cls(
            username=os.getenv("TRADOVATE_USERNAME", "").strip(),
            password=os.getenv("TRADOVATE_PASSWORD", "").strip(),
            app_id=os.getenv("TRADOVATE_APP_ID", "").strip(),
            app_version=os.getenv("TRADOVATE_APP_VERSION", "1.0").strip() or "1.0",
            cid=os.getenv("TRADOVATE_CID", "").strip(),
            sec=os.getenv("TRADOVATE_SEC", "").strip(),
            device_id=os.getenv("TRADOVATE_DEVICE_ID", "vibe-trading-local").strip() or "vibe-trading-local",
            env=os.getenv("TRADOVATE_ENV", "demo").strip().lower() or "demo",
        )

    def missing_fields(self) -> list[str]:
        fields = [
            ("TRADOVATE_USERNAME", self.username),
            ("TRADOVATE_PASSWORD", self.password),
            ("TRADOVATE_APP_ID", self.app_id),
            ("TRADOVATE_CID", self.cid),
            ("TRADOVATE_SEC", self.sec),
        ]
        return [name for name, value in fields if not value]


@dataclass(frozen=True)
class TradovateToken:
    access_token: str
    market_data_token: str


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def tradovate_endpoints(env: str) -> TradovateEndpoints:
    normalized = (env or "demo").lower()
    if normalized == "live":
        return TradovateEndpoints(
            rest_base="https://live.tradovateapi.com/v1",
            market_data_ws="wss://md.tradovateapi.com/v1/websocket",
        )
    return TradovateEndpoints(
        rest_base="https://demo.tradovateapi.com/v1",
        market_data_ws="wss://md-demo.tradovateapi.com/v1/websocket",
    )


def current_front_month_symbol(root: str, *, today: date | None = None) -> str:
    """Return a Tradovate-style quarterly futures symbol, e.g. MNQU6.

    Conservative simple roll: after the 15th of a quarterly expiry month,
    advance to the next quarterly contract.
    """
    today = today or date.today()
    root = root.upper().lstrip("@")
    if root.endswith("=F"):
        root = root[:-2]

    quarters = [(3, "H"), (6, "M"), (9, "U"), (12, "Z")]
    year = today.year
    month = today.month
    for q_month, code in quarters:
        if month < q_month or (month == q_month and today.day <= 15):
            return f"{root}{code}{str(year)[-1]}"
    return f"{root}H{str(year + 1)[-1]}"


def auth_payload(settings: TradovateSettings) -> dict[str, str]:
    return {
        "name": settings.username,
        "password": settings.password,
        "appId": settings.app_id,
        "appVersion": settings.app_version,
        "cid": settings.cid,
        "sec": settings.sec,
        "deviceId": settings.device_id,
    }


def request_access_token(settings: TradovateSettings) -> TradovateToken:
    import requests

    missing = settings.missing_fields()
    if missing:
        raise RuntimeError(f"Missing Tradovate credentials: {', '.join(missing)}")

    endpoints = tradovate_endpoints(settings.env)
    resp = requests.post(
        f"{endpoints.rest_base}/auth/accessTokenRequest",
        json=auth_payload(settings),
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    access_token = str(data.get("accessToken") or "")
    market_data_token = str(data.get("mdAccessToken") or access_token)
    if not access_token:
        raise RuntimeError(f"Tradovate auth did not return accessToken: {data}")
    return TradovateToken(access_token=access_token, market_data_token=market_data_token)


def resolve_contract(symbol: str, token: TradovateToken, *, env: str = "demo") -> dict[str, Any]:
    import requests

    endpoints = tradovate_endpoints(env)
    resp = requests.get(
        f"{endpoints.rest_base}/contract/find",
        params={"name": symbol},
        headers={"Authorization": f"Bearer {token.access_token}"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or not data.get("name"):
        raise RuntimeError(f"Tradovate contract lookup failed for {symbol}: {data}")
    return data


def build_chart_request(symbol: str, *, bars: int = 120, interval_minutes: int = 1) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "chartDescription": {
            "underlyingType": "MinuteBar",
            "elementSize": interval_minutes,
            "elementSizeUnit": "UnderlyingUnits",
            "withHistogram": True,
        },
        "timeRange": {"asMuchAsElements": bars},
    }


def encode_ws_request(endpoint: str, request_id: int, payload: str | dict[str, Any]) -> str:
    body = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
    return f"{endpoint}\n{request_id}\n\n{body}"


def decode_ws_message(raw: str) -> list[dict[str, Any]]:
    if not raw or raw in {"o", "h"}:
        return []
    if raw.startswith("a"):
        try:
            payload = json.loads(raw[1:])
            return [item for item in payload if isinstance(item, dict)]
        except json.JSONDecodeError:
            return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return [payload] if isinstance(payload, dict) else []


def _find_bar_lists(value: Any) -> list[list[dict[str, Any]]]:
    found: list[list[dict[str, Any]]] = []
    if isinstance(value, dict):
        for key in ("bars", "candles"):
            bars = value.get(key)
            if isinstance(bars, list):
                found.append([item for item in bars if isinstance(item, dict)])
        for child in value.values():
            found.extend(_find_bar_lists(child))
    elif isinstance(value, list):
        for item in value:
            found.extend(_find_bar_lists(item))
    return found


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / (1000 if value > 10_000_000_000 else 1), tz=timezone.utc).replace(tzinfo=None)
    text = str(value or "")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed


def _bar_to_candle(row: dict[str, Any]) -> Candle | None:
    timestamp = _first(row, ("timestamp", "time", "t", "ts"))
    open_ = _first(row, ("openPrice", "open", "o"))
    high = _first(row, ("highPrice", "high", "h"))
    low = _first(row, ("lowPrice", "low", "l"))
    close = _first(row, ("closePrice", "close", "c"))
    if timestamp is None or open_ is None or high is None or low is None or close is None:
        return None
    volume = _first(row, ("volume", "v"))
    if volume is None:
        volume = float(row.get("upVolume") or 0) + float(row.get("downVolume") or 0)
    return Candle(
        timestamp=_parse_timestamp(timestamp),
        open=float(open_),
        high=float(high),
        low=float(low),
        close=float(close),
        volume=int(float(volume or 0)),
    )


def extract_chart_candles(messages: list[dict[str, Any]]) -> list[Candle]:
    candles: list[Candle] = []
    seen: set[datetime] = set()
    for message in messages:
        for bars in _find_bar_lists(message):
            for row in bars:
                candle = _bar_to_candle(row)
                if candle and candle.timestamp not in seen:
                    candles.append(candle)
                    seen.add(candle.timestamp)
    return sorted(candles, key=lambda c: c.timestamp)


def fetch_chart_candles(
    symbol: str,
    *,
    bars: int = 120,
    interval_minutes: int = 1,
    settings: TradovateSettings | None = None,
    timeout_seconds: int = 20,
) -> list[Candle]:
    """Fetch recent chart candles from Tradovate market-data WebSocket."""
    try:
        import websocket  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "websocket-client is required for Tradovate live data. "
            "Run with: uv run --no-project --with websocket-client --with requests ..."
        ) from exc

    settings = settings or TradovateSettings.from_env()
    endpoints = tradovate_endpoints(settings.env)
    token = request_access_token(settings)
    resolve_contract(symbol, token, env=settings.env)

    ws = websocket.create_connection(endpoints.market_data_ws, timeout=timeout_seconds)
    try:
        ws.recv()  # opening frame
        ws.send(encode_ws_request("authorize", 1, token.market_data_token))
        chart_request = build_chart_request(symbol, bars=bars, interval_minutes=interval_minutes)
        ws.send(encode_ws_request("md/getChart", 2, chart_request))

        deadline = time.monotonic() + timeout_seconds
        messages: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            raw = ws.recv()
            decoded = decode_ws_message(raw)
            messages.extend(decoded)
            candles = extract_chart_candles(messages)
            if len(candles) >= min(bars, 2):
                return candles[-bars:]
            if any(isinstance(msg.get("d"), dict) and msg["d"].get("eoh") for msg in decoded):
                break
        return extract_chart_candles(messages)[-bars:]
    finally:
        ws.close()


def write_candles_csv(candles: list[Candle], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["timestamp,open,high,low,close,volume"]
    for candle in candles:
        lines.append(
            f"{candle.timestamp.isoformat()},{candle.open},{candle.high},{candle.low},{candle.close},{candle.volume}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def redacted_settings(settings: TradovateSettings) -> dict[str, str]:
    def mask(value: str) -> str:
        if not value:
            return ""
        return value[:2] + "***" + value[-2:] if len(value) > 4 else "***"

    return {
        "env": settings.env,
        "username": mask(settings.username),
        "app_id": mask(settings.app_id),
        "app_version": settings.app_version,
        "cid": mask(settings.cid),
        "sec": mask(settings.sec),
        "device_id": settings.device_id,
    }


def likely_contract_symbol(root_or_symbol: str) -> str:
    text = root_or_symbol.strip().upper()
    if re.fullmatch(r"[A-Z]{2,5}[FGHJKMNQUVXZ]\d", text):
        return text
    return current_front_month_symbol(text)
