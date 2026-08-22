#!/usr/bin/env python3
"""Minimal read-only MCP surface for the Vibe-Trading decision dashboard.

This server intentionally does not import the connector registry.  Its tool
catalog is a closed allowlist of local report readers and cannot submit orders,
change preferences, start jobs, or mutate journals.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from fastmcp import FastMCP


AGENT_DIR = Path(__file__).resolve().parent
ROOT = AGENT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_REPORT = Path.home() / ".vibe-trading" / "reports" / "live-opportunity-engine.json"
DEFAULT_INTRADAY = Path.home() / ".vibe-trading" / "reports" / "intraday-opportunity-radar.json"
DEFAULT_SEC = Path.home() / ".vibe-trading" / "reports" / "sec-catalyst-feed.json"
DEFAULT_INTELLIGENCE = ROOT / "data" / "opportunity_intelligence_report.json"

mcp = FastMCP(
    "Vibe-Trading Read Only",
    instructions=(
        "Use these tools only to inspect research candidates and evidence. "
        "A candidate is not a recommendation. Never imply order authority or "
        "invent missing prices, catalysts, probabilities, or execution state."
    ),
)


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _report_path() -> Path:
    return Path(os.getenv("VIBE_TRADING_OPPORTUNITY_REPORT") or DEFAULT_REPORT)


def _safe(payload: dict[str, Any]) -> str:
    payload = dict(payload)
    payload["execution_enabled"] = False
    payload["can_submit_orders"] = False
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool
def get_trading_opportunities(limit: int = 5, minimum_grade: str = "") -> str:
    """Read the current ranked opportunity queue, capped to 20 candidates."""
    report = _read(_report_path())
    rows = [row for row in report.get("candidates") or [] if isinstance(row, dict)]
    if minimum_grade:
        rows = [row for row in rows if str(row.get("grade") or "").upper() == minimum_grade.upper()]
    return _safe({
        "generated_at": report.get("generated_at"),
        "decision_state": report.get("decision_state", "STAND_ASIDE"),
        "feed": report.get("feed"),
        "candidates": rows[: max(1, min(int(limit), 20))],
        "warning": "Research-priority candidates only; revalidate every field before manual action.",
    })


@mcp.tool
def get_dashboard_snapshot() -> str:
    """Read the normalized dashboard headline, command card, and source health."""
    try:
        from scripts.live_trading_cockpit import build_cockpit

        report = build_cockpit()
    except Exception as exc:
        return _safe({"status": "unavailable", "error": type(exc).__name__})
    return _safe({
        "schema_version": report.get("schema_version"),
        "generated_at": report.get("generated_at"),
        "headline": report.get("headline"),
        "command_card": report.get("command_card"),
        "market": report.get("market"),
        "discovery": report.get("discovery"),
        "sources": report.get("sources"),
        "warnings": report.get("warnings"),
    })


@mcp.tool
def explain_candidate(symbol: str, setup_family: str = "") -> str:
    """Return the source-backed evidence, blockers, and levels for one symbol."""
    clean_symbol = symbol.strip().upper()
    report = _read(_report_path())
    rows = [
        row for row in report.get("candidates") or []
        if isinstance(row, dict)
        and str(row.get("symbol") or "").upper() == clean_symbol
        and (not setup_family or str(row.get("setup_family") or "") == setup_family)
    ]
    return _safe({
        "symbol": clean_symbol,
        "generated_at": report.get("generated_at"),
        "candidates": rows,
        "status": "found" if rows else "not_found",
        "warning": "Missing evidence must remain missing; do not infer a trade plan.",
    })


@mcp.tool
def get_source_health() -> str:
    """Inspect feed, SEC catalyst, radar, and validation-source freshness."""
    opportunity = _read(_report_path())
    radar = _read(DEFAULT_INTRADAY)
    sec = _read(DEFAULT_SEC)
    intelligence = _read(DEFAULT_INTELLIGENCE)
    return _safe({
        "opportunity_feed": opportunity.get("feed"),
        "opportunity_generated_at": opportunity.get("generated_at"),
        "radar_generated_at": radar.get("generated_at"),
        "radar_health": radar.get("operational_health", "missing"),
        "sec_generated_at": sec.get("generated_at"),
        "sec_status": sec.get("status", "missing"),
        "validation_generated_at": intelligence.get("generated_at"),
        "promotion_authority": intelligence.get("promotion_authority", "blocked"),
    })


@mcp.tool
def get_daily_briefing() -> str:
    """Return a compact premarket/intraday briefing from current local evidence."""
    opportunity = _read(_report_path())
    sec = _read(DEFAULT_SEC)
    top = [row for row in opportunity.get("candidates") or [] if isinstance(row, dict)][:3]
    return _safe({
        "generated_at": opportunity.get("generated_at"),
        "decision_state": opportunity.get("decision_state", "STAND_ASIDE"),
        "top_research_priorities": top,
        "fresh_sec_catalysts": [row for row in sec.get("catalysts") or [] if isinstance(row, dict)][:10],
        "stand_aside": not any(row.get("state") == "READY_TO_REVIEW" for row in top),
        "required_manual_checks": [
            "Confirm feed and quote freshness",
            "Confirm completed-bar trigger",
            "Confirm spread and post-friction reward/risk",
            "Confirm catalyst and market/sector alignment",
        ],
    })


def readonly_tool_names() -> tuple[str, ...]:
    return (
        "get_trading_opportunities",
        "get_dashboard_snapshot",
        "explain_candidate",
        "get_source_health",
        "get_daily_briefing",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=("stdio", "sse"), default="stdio")
    parser.add_argument("--port", type=int, default=8902)
    args = parser.parse_args()
    if args.transport == "sse":
        mcp.run(transport="sse", port=args.port)
    else:
        mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
