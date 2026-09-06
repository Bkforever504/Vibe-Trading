from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.daily_move_coverage_review import build_review
from scripts.intraday_opportunity_radar import select_symbols_for_intraday_bars
from scripts.priority_focus_universe import PRIORITY_FOCUS_UNIVERSE


def test_priority_focus_universe_includes_dell_and_is_shared_by_daily_level_map() -> None:
    from scripts.daily_level_map_shadow import UNIVERSE

    assert PRIORITY_FOCUS_UNIVERSE == (
        "SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "DELL",
    )
    assert UNIVERSE == PRIORITY_FOCUS_UNIVERSE


def test_priority_symbols_are_reserved_ahead_of_top_mover_quota() -> None:
    discovered = {
        f"X{index}": {"symbol": f"X{index}", "sources": ["movers_gainers"], "source_ranks": {"movers_gainers": index + 1}}
        for index in range(40)
    }
    metrics = {symbol: {"gap_return": 0.50, "snapshot_volume": 10_000_000} for symbol in discovered}
    for symbol in PRIORITY_FOCUS_UNIVERSE:
        discovered[symbol] = {"symbol": symbol, "sources": ["priority_focus_universe"], "source_ranks": {}}
        metrics[symbol] = {"gap_return": 0.0, "snapshot_volume": 1.0}

    selected = select_symbols_for_intraday_bars(discovered, metrics, limit=len(PRIORITY_FOCUS_UNIVERSE) + 2)

    assert selected[: len(PRIORITY_FOCUS_UNIVERSE)] == list(PRIORITY_FOCUS_UNIVERSE)
    assert "DELL" in selected


def test_move_review_audits_priority_names_absent_from_provider_mover_denominator() -> None:
    latest = {"date": "2026-09-04", "market_movers": [{"symbol": "SPY", "percent_change": 3.5}]}
    history = [{
        "date": "2026-09-04", "as_of_et": "2026-09-04T10:00:00-04:00",
        "all_discovered_symbols": list(PRIORITY_FOCUS_UNIVERSE),
        "ranked_candidates": [{"symbol": "SPY", "change_pct": 1.0, "state": "precision_watch"}],
        "coverage_trace": [
            {"symbol": symbol, "stop_stage": "evaluated" if symbol in {"SPY", "DELL"} else "not_selected_for_intraday_bars"}
            for symbol in PRIORITY_FOCUS_UNIVERSE
        ],
    }]

    review = build_review(latest, history)
    priority = review["priority_universe_coverage"]
    rows = {row["symbol"]: row for row in priority["symbols"]}

    assert "DELL" in priority["absent_from_provider_mover_denominator"]
    assert rows["DELL"]["evaluated"] is True
    assert rows["DELL"]["outcome_in_provider_denominator"] is False
    assert rows["DELL"]["outcome_status"] == "unknown_not_in_provider_top_movers"
    assert priority["recall_pct"] is None
    assert priority["recall_not_computable_reason"] == "provider_top_movers_do_not_supply_outcomes_for_omitted_priority_symbols"
    assert review["summary"]["stage_denominator"] == "final_covered_source_market_movers"


def test_priority_not_evaluated_is_explicit_coverage_debt() -> None:
    review = build_review(
        {"date": "2026-09-04", "market_movers": []},
        [{"date": "2026-09-04", "as_of_et": "2026-09-04T11:00:00-04:00", "all_discovered_symbols": ["DELL"], "coverage_trace": []}],
    )
    priority = review["priority_universe_coverage"]
    row = next(row for row in priority["symbols"] if row["symbol"] == "DELL")
    assert row["coverage_debt"] == "discovered_not_evaluated"
    assert "DELL" in priority["not_evaluated"]


def test_daily_level_map_intraday_fetch_chunks_priority_universe_so_dell_is_not_truncated(monkeypatch) -> None:
    from scripts import daily_level_map_shadow as level_map

    calls: list[list[str]] = []

    class Response:
        status_code = 200

        def __init__(self, symbols: list[str]) -> None:
            self.symbols = symbols

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"bars": {symbol: [{"t": "2026-09-04T13:30:00Z"}] for symbol in self.symbols}}

    def fake_get(_url: str, **kwargs):
        symbols = str(kwargs["params"]["symbols"]).split(",")
        calls.append(symbols)
        return Response(symbols)

    monkeypatch.setattr(level_map, "_credentials", lambda: {})
    monkeypatch.setattr(level_map.requests, "get", fake_get)
    result = level_map.fetch_intraday_1m(
        PRIORITY_FOCUS_UNIVERSE,
        now_et=datetime(2026, 9, 4, 10, 0, tzinfo=ZoneInfo("America/New_York")),
    )

    assert len(calls) == 3
    assert max(map(len, calls)) == 5
    assert result["DELL"] == [{"t": "2026-09-04T13:30:00Z"}]
