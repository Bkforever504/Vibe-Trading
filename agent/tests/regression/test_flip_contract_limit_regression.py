from strategies import flip_bot


def test_flip_aggregate_limit_allows_exact_configured_capacity(monkeypatch):
    monkeypatch.setattr(flip_bot, "MAX_TOTAL_OPEN_CONTRACTS", 5)
    setup = {"symbol": "SPY", "right": "CALL", "contracts": 5}
    assert flip_bot._aggregate_exposure_blocker(setup, []) is None
