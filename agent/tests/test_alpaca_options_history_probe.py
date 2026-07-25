from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import alpaca_options_history_probe as probe


def test_build_occ_symbol_matches_occ_format() -> None:
    assert probe.build_occ_symbol("SPY", "2024-12-20", "C", 590) == "SPY241220C00590000"
    assert probe.build_occ_symbol("SPY", "2026-03-20", "P", 732.5) == "SPY260320P00732500"


def _probe_row(expiry: str, **endpoint_rows):
    endpoints = {
        kind: {"http_status": 404, "row_count": 0}
        for kind in ("quotes_default", "quotes_feed_indicative", "quotes_feed_opra", "trades", "bars_1min")
    }
    for kind, row_count in endpoint_rows.items():
        endpoints[kind] = {"http_status": 200, "row_count": row_count}
    return {"expiry": expiry, "endpoints": endpoints}


def test_summarize_flags_trades_only_history_as_replay_blocked() -> None:
    summary = probe.summarize([
        _probe_row("2024-03-15", trades=10, bars_1min=10),
        _probe_row("2025-06-20", trades=10, bars_1min=10),
    ])

    assert summary["trades"]["earliest"] == "2024-03-15"
    assert summary["quotes_default"]["dates_with_data"] == []
    assert summary["verdict"] == (
        "trades_or_bars_only_no_historical_quote_endpoint_hybrid_replay_required"
    )


def test_summarize_prefers_quote_availability_verdict() -> None:
    summary = probe.summarize([_probe_row("2025-06-20", quotes_default=10, trades=10)])

    assert summary["verdict"] == "historical_option_quotes_available_review_nbbo_semantics_and_depth"


def test_summarize_reports_total_absence() -> None:
    summary = probe.summarize([_probe_row("2025-06-20")])

    assert summary["verdict"] == (
        "no_historical_option_quotes_endpoint_replay_requires_other_provider_or_forward_capture"
    )
