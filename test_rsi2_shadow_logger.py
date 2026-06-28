from pathlib import Path

import pandas as pd

from scripts.rsi2_shadow_logger import compute_signal_from_ohlcv, log_entry


def _sample_ohlcv() -> pd.DataFrame:
    closes = [100.0] * 210 + [130.0, 126.0, 122.0, 121.0, 124.0, 127.0]
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [price + 1 for price in closes],
            "low": [price - 1 for price in closes],
            "close": closes,
            "volume": [1_000_000] * len(closes),
        },
        index=idx,
    )


def test_compute_signal_from_ohlcv_logs_primary_and_comparison_setups():
    entry = compute_signal_from_ohlcv(_sample_ohlcv(), symbol="QQQ", as_of="2024-11-01")

    assert entry["date"] == "2024-11-01"
    assert entry["symbol"] == "QQQ"
    assert entry["execution_mode"] == "shadow_only"
    assert entry["primary_setup"]["name"] == "rsi2_prior_high_source"
    assert entry["comparison_setup"]["name"] == "rsi2_sma_exit_derived"
    assert entry["primary_setup"]["action"] in {"enter_long", "hold_long", "flat"}
    assert entry["comparison_setup"]["action"] in {"enter_long", "hold_long", "flat"}
    assert "rsi2" in entry["features"]
    assert "close" in entry["features"]


def test_log_entry_replaces_same_day_signal(tmp_path: Path):
    log_path = tmp_path / "rsi2_shadow_log.jsonl"
    first = {"date": "2024-01-02", "symbol": "QQQ", "primary_setup": {"action": "flat"}}
    second = {"date": "2024-01-02", "symbol": "QQQ", "primary_setup": {"action": "enter_long"}}

    log_entry(first, log_path)
    log_entry(second, log_path)

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert "enter_long" in lines[0]
