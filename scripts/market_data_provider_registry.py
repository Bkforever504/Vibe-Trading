#!/usr/bin/env python3
"""Read-only provider readiness inventory for opportunity discovery."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]


def _present(env: Mapping[str, str], *names: str) -> bool:
    return any(bool(str(env.get(name) or "").strip()) for name in names)


def _configured_values(root: Path) -> dict[str, str]:
    values = dict(os.environ)
    env_path = root / "agent" / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        if raw.lstrip().startswith("#") or "=" not in raw:
            continue
        key, _, value = raw.partition("=")
        key = key.strip()
        if key and not values.get(key):
            values[key] = value.strip()
    return values


def build_provider_registry(env: Mapping[str, str] | None = None, *, root: Path = ROOT) -> dict[str, Any]:
    # Read only presence from the same local environment source used by the
    # dashboard. Credential values are never included in the returned report.
    values = env if env is not None else _configured_values(root)
    feed = str(values.get("VIBE_TRADING_STOCK_FEED") or "iex").lower()
    if feed not in {"iex", "sip"}:
        feed = "iex"
    rows = [
        {
            "name": "alpaca",
            "status": "configured" if _present(values, "APCA_API_KEY_ID", "ALPACA_API_KEY") and _present(values, "APCA_API_SECRET_KEY", "ALPACA_SECRET_KEY") else "missing_credentials",
            "capabilities": ["stock_stream", "quotes", "bars", "screeners", "options_chain"],
            "provenance": f"alpaca_{feed}",
            "required_environment": ["existing Alpaca market-data credentials"],
        },
        {
            "name": "sec_edgar",
            "status": "configured" if "@" in str(values.get("SEC_USER_AGENT") or "") else "disabled_identity_required",
            "capabilities": ["company_filings", "material_8k", "periodic_reports"],
            "provenance": "sec_submissions_api",
            "required_environment": ["SEC_USER_AGENT with contact email"],
        },
        {
            "name": "benzinga",
            "status": "configured" if _present(values, "BENZINGA_API_KEY", "BENZINGA_TOKEN") else "optional_not_configured",
            "capabilities": ["earnings_calendar", "news", "movers", "wiim"],
            "provenance": "benzinga_api",
            "required_environment": ["BENZINGA_API_KEY"],
        },
        {
            "name": "massive",
            "status": "configured" if _present(values, "MASSIVE_API_KEY", "POLYGON_API_KEY") else "optional_not_configured",
            "capabilities": ["full_market_snapshot", "broad_universe_scan"],
            "provenance": "massive_snapshot_api",
            "required_environment": ["MASSIVE_API_KEY"],
        },
        {
            "name": "quartr",
            "status": "configured" if _present(values, "QUARTR_API_KEY") else "optional_plugin_or_export_required",
            "capabilities": ["earnings_events", "transcripts", "presentations"],
            "provenance": "quartr",
            "required_environment": ["Quartr plugin, API access, or exported source packet"],
        },
        {
            "name": "opra",
            "status": "local_evidence_available" if any((root / "data" / "databento").glob("opra_*")) else "optional_not_configured",
            "capabilities": ["options_nbbo", "implied_volatility", "greeks", "open_interest"],
            "provenance": "opra_nbbo_no_aggressor_side",
            "required_environment": ["licensed OPRA source such as Databento or Cboe"],
        },
    ]
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "providers": rows,
        "configured_count": sum(row["status"] in {"configured", "local_evidence_available"} for row in rows),
        "warning": "Provider readiness is configuration evidence, not proof of current entitlement or freshness.",
        "execution_enabled": False,
        "can_submit_orders": False,
    }


if __name__ == "__main__":
    print(json.dumps(build_provider_registry(), indent=2, sort_keys=True))
