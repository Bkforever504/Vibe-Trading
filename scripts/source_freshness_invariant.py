#!/usr/bin/env python3
"""Identify report sources that must be quarantined after 24 hours."""
from __future__ import annotations

import json
from typing import Any, Iterable

try:
    from scripts.live_trading_cockpit import build_cockpit
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from live_trading_cockpit import build_cockpit


def evaluate_sources(sources: Iterable[dict[str, Any]]) -> dict[str, Any]:
    quarantined = []
    for source in sources:
        age = source.get("age_seconds")
        if not source.get("available") or not isinstance(age, (int, float)) or age > 24 * 60 * 60:
            quarantined.append({"name": source.get("name"), "reason": "missing" if not source.get("available") else "older_than_24h", "execution_enabled": False, "can_submit_orders": False})
    return {"status": "degraded" if quarantined else "healthy", "quarantined": quarantined, "execution_enabled": False, "can_submit_orders": False}


def main() -> int:
    report = evaluate_sources(build_cockpit().get("sources", []))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
