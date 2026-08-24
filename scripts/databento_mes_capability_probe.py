#!/usr/bin/env python3
"""Probe Databento MES capabilities without printing credentials or market data."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.databento_mes_evidence import DATASET, load_api_key, mes_front_contract


DEFAULT_OUTPUT = ROOT / "data" / "databento_mes_capability.json"


def probe_live(
    *,
    now: datetime | None = None,
    client_factory: Callable[..., Any] | None = None,
    key: str | None = None,
    timeout_seconds: float = 2.0,
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if client_factory is None:
        import databento as db

        client_factory = db.Live
    client = None
    try:
        client = client_factory(key=key or load_api_key())
        contract = mes_front_contract(now)
        client.subscribe(
            dataset=DATASET,
            schema="mbo",
            symbols=contract.raw_symbol,
            stype_in="raw_symbol",
            snapshot=True,
        )
        # subscribe() only queues a request. Starting the session and waiting
        # for the gateway is what surfaces entitlement/acknowledgment errors.
        client.start()
        client.block_for_close(timeout=timeout_seconds)
        status = "available"
        reason = "mbo_session_validated"
    except Exception as exc:
        message = str(exc).lower()
        status = "unavailable"
        reason = (
            "live_data_license_required"
            if "live data license" in message or "license is required" in message
            else f"live_probe_failed:{type(exc).__name__}"
        )
    finally:
        if client is not None:
            try:
                client.terminate()
            except Exception:
                pass
    return {
        "schema_version": 1,
        "provider": "databento",
        "dataset": DATASET,
        "probed_at": now.isoformat().replace("+00:00", "Z"),
        "live_status": status,
        "live_reason": reason,
        "historical_regrade_supported": True,
        "credentials_logged": False,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = probe_live()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".partial")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
