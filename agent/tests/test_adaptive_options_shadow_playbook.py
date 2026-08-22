from __future__ import annotations

from scripts import adaptive_options_shadow_playbook as playbook


def test_default_universe_covers_consensus_options_symbols() -> None:
    expected = {"SPY", "QQQ", "IWM", "NVDA", "TSLA", "AAPL", "PLTR", "RIVN", "HOOD", "COIN", "NFLX"}
    assert expected.issubset(set(playbook.DEFAULT_SYMBOLS))


def test_report_exposes_complete_symbol_coverage() -> None:
    contexts = {symbol: {} for symbol in ("SPY", "QQQ")}
    report = playbook.build_report(["spy", "SPY", "qqq"], contexts)
    assert report["coverage"] == {
        "requested_symbols": ["SPY", "QQQ"],
        "row_count": 2,
        "missing_symbols": [],
    }
