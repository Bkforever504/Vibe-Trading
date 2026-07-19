#!/usr/bin/env python3
"""Read-only Ironbeam futures market-data setup helpers.

Ironbeam API access currently requires a funded live account before API
credentials are issued. This module keeps that requirement explicit so the
MNQ bot cannot silently switch to an unavailable or paid feed.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IronbeamSettings:
    username: str
    password: str
    api_key: str
    base_url: str = "https://api.ironbeam.com"
    env: str = "sim"
    funded_account_confirmed: bool = False

    @classmethod
    def from_env(cls) -> "IronbeamSettings":
        return cls(
            username=os.getenv("IRONBEAM_USERNAME", "").strip(),
            password=os.getenv("IRONBEAM_PASSWORD", "").strip(),
            api_key=os.getenv("IRONBEAM_API_KEY", "").strip(),
            base_url=os.getenv("IRONBEAM_BASE_URL", "https://api.ironbeam.com").strip().rstrip("/"),
            env=os.getenv("IRONBEAM_ENV", "sim").strip().lower() or "sim",
            funded_account_confirmed=os.getenv("IRONBEAM_FUNDED_ACCOUNT_CONFIRMED", "false").strip().lower() == "true",
        )

    def missing_fields(self) -> list[str]:
        fields = [
            ("IRONBEAM_USERNAME", self.username),
            ("IRONBEAM_PASSWORD", self.password),
            ("IRONBEAM_API_KEY", self.api_key),
        ]
        return [name for name, value in fields if not value]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def current_front_month_symbol(root: str, *, today: date | None = None) -> str:
    today = today or date.today()
    root = root.upper().strip().lstrip("@")
    if root.endswith("=F"):
        root = root[:-2]

    quarters = [(3, "H"), (6, "M"), (9, "U"), (12, "Z")]
    year = today.year
    for q_month, code in quarters:
        if today.month < q_month or (today.month == q_month and today.day <= 15):
            return f"{root}{code}{str(year)[-1]}"
    return f"{root}H{str(year + 1)[-1]}"


def likely_contract_symbol(root_or_symbol: str) -> str:
    text = root_or_symbol.strip().upper().lstrip("@")
    if re.fullmatch(r"[A-Z]{2,5}[FGHJKMNQUVXZ]\d", text):
        return text
    return current_front_month_symbol(text)


def readiness_report(settings: IronbeamSettings | None = None) -> dict[str, Any]:
    settings = settings or IronbeamSettings.from_env()
    blockers = settings.missing_fields()
    if not settings.funded_account_confirmed:
        blockers.append("funded account not confirmed")
    return {
        "provider": "ironbeam",
        "ready": not blockers,
        "env": settings.env,
        "base_url": settings.base_url,
        "blockers": blockers,
        "note": (
            "Ironbeam API credentials require funded-account API access. "
            "Keep MNQ_DATA_SOURCE=yfinance until this report is ready."
        ),
    }


def request_access_token(settings: IronbeamSettings | None = None) -> str:
    """Request an Ironbeam bearer token.

    This is intentionally small and only used by the connection check once
    credentials exist. Endpoint details can be adjusted after Ironbeam issues
    account-specific API documentation.
    """
    import requests

    settings = settings or IronbeamSettings.from_env()
    report = readiness_report(settings)
    if not report["ready"]:
        raise RuntimeError(f"Ironbeam not ready: {', '.join(report['blockers'])}")

    resp = requests.post(
        f"{settings.base_url}/auth",
        json={
            "username": settings.username,
            "password": settings.password,
            "apiKey": settings.api_key,
            "environment": settings.env,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    token = str(data.get("access_token") or data.get("accessToken") or data.get("token") or "")
    if not token:
        raise RuntimeError(f"Ironbeam auth did not return a bearer token: {data}")
    return token


def redacted_settings(settings: IronbeamSettings | None = None) -> dict[str, str]:
    settings = settings or IronbeamSettings.from_env()

    def mask(value: str) -> str:
        if not value:
            return ""
        return value[:2] + "***" + value[-2:] if len(value) > 4 else "***"

    return {
        "env": settings.env,
        "base_url": settings.base_url,
        "username": mask(settings.username),
        "api_key": mask(settings.api_key),
        "funded_account_confirmed": str(settings.funded_account_confirmed).lower(),
    }
