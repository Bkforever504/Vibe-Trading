from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd


def _load_logger_module():
    path = Path("scripts/momentum_shadow_logger.py")
    spec = importlib.util.spec_from_file_location("momentum_shadow_logger", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compute_current_signal_records_close_prices(monkeypatch) -> None:
    module = _load_logger_module()
    idx = pd.date_range("2025-01-01", periods=260, freq="B")
    closes = pd.DataFrame(
        {
            "AAA": [100 + i for i in range(260)],
            "BBB": [100 + i * 0.8 for i in range(260)],
            "CCC": [200 - i * 0.1 for i in range(260)],
        },
        index=idx,
    )
    monkeypatch.setattr(module, "_fetch_close", lambda symbols, start, end: closes[symbols])

    entry = module.compute_current_signal(symbols=["AAA", "BBB", "CCC"], lookback_days=252, top_n=2)

    assert entry["holdings"] == ["AAA", "BBB"]
    assert entry["weights"] == {"AAA": 0.5, "BBB": 0.5}
    assert entry["close_prices"] == {"AAA": 359.0, "BBB": 307.2, "CCC": 174.1}
    assert entry["execution_mode"] == "shadow_only"


def test_compute_current_signal_sets_cash_when_all_assets_negative(monkeypatch) -> None:
    module = _load_logger_module()
    idx = pd.date_range("2025-01-01", periods=260, freq="B")
    closes = pd.DataFrame(
        {
            "AAA": [200 - i for i in range(260)],
            "BBB": [100 - i * 0.2 for i in range(260)],
        },
        index=idx,
    )
    monkeypatch.setattr(module, "_fetch_close", lambda symbols, start, end: closes[symbols])

    entry = module.compute_current_signal(symbols=["AAA", "BBB"], lookback_days=252, top_n=2)

    assert entry["holdings"] == []
    assert entry["weights"] == {}
    assert entry["in_cash"] is True


def test_log_entry_replaces_existing_entry_for_same_date(tmp_path) -> None:
    module = _load_logger_module()
    log_path = tmp_path / "momentum_shadow_log.jsonl"
    module.log_entry({"date": "2026-06-28", "holdings": ["XLK"]}, log_path)
    module.log_entry({"date": "2026-06-28", "holdings": ["IWM"]}, log_path)

    rows = log_path.read_text(encoding="utf-8").splitlines()

    assert len(rows) == 1
    assert '"holdings": ["IWM"]' in rows[0]


def test_log_entry_collapses_preexisting_duplicate_dates(tmp_path) -> None:
    module = _load_logger_module()
    log_path = tmp_path / "momentum_shadow_log.jsonl"
    log_path.write_text(
        '{"date": "2026-06-28", "holdings": ["OLD"]}\n'
        '{"date": "2026-06-28", "holdings": ["DUP"]}\n',
        encoding="utf-8",
    )

    module.log_entry({"date": "2026-06-28", "holdings": ["NEW"]}, log_path)

    rows = log_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 1
    assert '"holdings": ["NEW"]' in rows[0]
