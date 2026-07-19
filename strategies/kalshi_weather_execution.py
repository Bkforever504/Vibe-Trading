#!/usr/bin/env python3
"""Dormant authenticated adapter for future Kalshi weather execution.

Nothing imports or schedules this adapter for order submission. Every call must
pass the evidence report, explicit environment enablement, approval phrase,
credentials, and manual-reset checks before an authenticated POST is possible.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from strategies.kalshi_history_fetcher import make_headers

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
READINESS_PATH = Path.home() / ".vibe-trading" / "reports" / "kalshi-weather-readiness.json"
MANUAL_BLOCK_PATH = Path.home() / ".vibe-trading" / "KALSHI_WEATHER_MANUAL_RESET_REQUIRED.json"
LIVE_APPROVAL_PHRASE = "I_ACKNOWLEDGE_KALSHI_WEATHER_LIVE_RISK"
MAX_CONTRACTS = 1
MAX_ORDER_RISK_DOLLARS = 5.0


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def build_order_payload(
    *,
    ticker: str,
    outcome_side: str,
    contracts: int,
    outcome_price: float,
    client_order_id: str,
) -> dict[str, Any]:
    if int(contracts) != MAX_CONTRACTS:
        raise ValueError("Kalshi weather pilot is capped at one contract")
    price = float(outcome_price)
    if not 0.0 < price < 1.0:
        raise ValueError("outcome price must be between zero and one")
    if price * contracts > MAX_ORDER_RISK_DOLLARS:
        raise ValueError("order exceeds five dollar risk cap")
    normalized = str(outcome_side).upper()
    if normalized not in {"YES", "NO"}:
        raise ValueError("outcome side must be YES or NO")
    # V2 is a single YES book. Buying NO at p is asking YES at 1-p.
    book_side = "bid" if normalized == "YES" else "ask"
    book_price = price if normalized == "YES" else 1.0 - price
    return {
        "ticker": str(ticker),
        "client_order_id": str(client_order_id),
        "side": book_side,
        "count": f"{float(contracts):.2f}",
        "price": f"{book_price:.4f}",
        "time_in_force": "fill_or_kill",
        "self_trade_prevention_type": "taker_at_cross",
        "post_only": False,
        "cancel_order_on_pause": True,
        "reduce_only": False,
        "subaccount": 0,
    }


def execution_preflight(
    *,
    readiness_path: Path = READINESS_PATH,
    live_enabled: bool | None = None,
    approval_ack: str | None = None,
    key_id: str | None = None,
    private_key_path: Path | None = None,
    manual_block_path: Path = MANUAL_BLOCK_PATH,
) -> dict[str, Any]:
    enabled = live_enabled if live_enabled is not None else os.getenv("KALSHI_ENABLE_LIVE_TRADING", "false").lower() == "true"
    ack = approval_ack if approval_ack is not None else os.getenv("KALSHI_LIVE_APPROVAL_ACK", "")
    api_key = key_id if key_id is not None else os.getenv("KALSHI_API_KEY_ID", "").strip()
    key_path = private_key_path if private_key_path is not None else Path(os.getenv("KALSHI_PRIVATE_KEY_PATH", ""))
    readiness = _read(readiness_path)
    blockers: list[str] = []
    if not enabled:
        blockers.append("live_execution_disabled")
    if ack != LIVE_APPROVAL_PHRASE:
        blockers.append("approval_ack_missing")
    if readiness.get("go_live_eligible") is not True:
        blockers.append("readiness_not_passed")
    if not api_key or not str(key_path) or not key_path.is_file():
        blockers.append("credentials_missing")
    if manual_block_path.exists():
        blockers.append("manual_reset_required")
    return {
        "allowed": not blockers,
        "blockers": blockers,
        "readiness_blockers": readiness.get("blockers") or [],
        "max_contracts": MAX_CONTRACTS,
        "max_order_risk_dollars": MAX_ORDER_RISK_DOLLARS,
    }


class KalshiWeatherOrderClient:
    def __init__(self, *, key_id: str, private_key_path: Path, session: Any | None = None) -> None:
        import requests
        self.key_id = key_id
        self.private_key_path = private_key_path
        self.private_key_pem = private_key_path.read_text(encoding="utf-8")
        self.session = session or requests.Session()

    def submit(self, payload: dict[str, Any], *, preflight: dict[str, Any]) -> dict[str, Any]:
        if preflight.get("allowed") is not True:
            raise RuntimeError(f"Kalshi weather order blocked: {preflight.get('blockers')}")
        path = "/portfolio/events/orders"
        sign_path = urlparse(BASE_URL + path).path
        headers = make_headers(self.key_id, self.private_key_pem, "POST", sign_path)
        response = self.session.post(f"{BASE_URL}{path}", json=payload, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}
