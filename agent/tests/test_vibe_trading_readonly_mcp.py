from __future__ import annotations

import inspect
import json

from vibe_trading_readonly_mcp import (
    get_daily_briefing,
    get_trading_opportunities,
    readonly_tool_names,
)


def test_readonly_mcp_catalog_has_no_mutation_or_order_tools() -> None:
    names = readonly_tool_names()
    forbidden = ("order", "submit", "trade", "write", "update", "delete", "execute", "place")

    assert names
    assert all(not any(token in name.lower() for token in forbidden) for name in names)


def test_readonly_mcp_opportunity_projection_never_grants_authority(monkeypatch, tmp_path) -> None:
    path = tmp_path / "live-opportunity-engine.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": "2026-08-21T14:10:00Z",
                "decision_state": "READY_TO_REVIEW",
                "candidates": [{"symbol": "NVDA", "decision_score": 91}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBE_TRADING_OPPORTUNITY_REPORT", str(path))

    payload = json.loads(inspect.unwrap(get_trading_opportunities)(limit=3))
    briefing = json.loads(inspect.unwrap(get_daily_briefing)())

    assert payload["execution_enabled"] is False
    assert payload["can_submit_orders"] is False
    assert payload["candidates"][0]["symbol"] == "NVDA"
    assert briefing["execution_enabled"] is False
    assert briefing["can_submit_orders"] is False

