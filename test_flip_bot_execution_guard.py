from pathlib import Path


def test_run_entry_blocks_low_confidence_before_submit(monkeypatch, tmp_path: Path) -> None:
    from strategies import flip_bot

    monkeypatch.setattr(flip_bot, "DEFAULT_BLOCK_FILE", tmp_path / "manual_reset.json")
    monkeypatch.setattr(flip_bot, "PAPER", True)
    monkeypatch.setattr(flip_bot, "_market_open", lambda: True)
    monkeypatch.setattr(flip_bot, "_load", lambda: [])
    monkeypatch.setattr(flip_bot, "_save", lambda trades: None)
    monkeypatch.setattr(flip_bot, "_alert", lambda message: None)
    monkeypatch.setattr(flip_bot, "find_bear_trend_day", lambda account: {
        "strategy": "bear_trend_day",
        "symbol": "SPY",
        "right": "put",
        "option_symbol": "SPY260626P00500000",
        "strike": 500,
        "expiry": "2026-06-26",
        "contracts": 1,
        "entry_price_est": 1.00,
        "confidence": 8,
    })
    monkeypatch.setattr(flip_bot, "find_bull_trend_day", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_0dte", lambda account: None)
    monkeypatch.setattr(flip_bot, "find_earnings", lambda account: [])
    monkeypatch.setattr(flip_bot, "find_breakouts", lambda account: [])

    submitted = []
    monkeypatch.setattr(flip_bot, "_submit", lambda *args, **kwargs: submitted.append(args) or {"id": "bad"})

    flip_bot.run_entry(10_000)

    assert submitted == []
