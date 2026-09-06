from scripts.intraday_sector_posture import build_posture


def test_narrow_sector_posture_is_descriptive_and_non_executable() -> None:
    snapshot = {
        "spy_session_return_pct": -0.2,
        "qqq_spy_regime": "balanced",
        "sector_leaders": [{"etf": "XLE", "session_return_pct": 1.5}],
        "sector_laggards": [
            {"etf": "XLK", "session_return_pct": -1.0},
            {"etf": "XLI", "session_return_pct": -0.8},
            {"etf": "XLU", "session_return_pct": -0.6},
        ],
    }
    result = build_posture(snapshot)
    assert result["state"] == "narrow_or_concentrated_participation"
    assert result["positive_count"] == 1
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False
