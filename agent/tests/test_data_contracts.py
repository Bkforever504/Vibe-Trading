from __future__ import annotations

import pytest

from contracts.schemas import ContractError, validate_ohlcv, validate_scanner_output


def test_ohlcv_contract_accepts_valid_and_rejects_impossible_range():
    row = {"ticker": "SPY", "timestamp": "2026-01-02T14:30:00Z", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 10}
    assert len(validate_ohlcv([row])) == 1
    with pytest.raises(ContractError, match="impossible_range"):
        validate_ohlcv([{**row, "high": 98}])


def test_scanner_contract_fails_loud_on_bad_score_and_side():
    row = {"ticker": "SPY", "ts": "2026-01-02T14:30:00Z", "scanner_id": "a", "score": .7, "side": "LONG", "features_json": "{}"}
    assert len(validate_scanner_output([row])) == 1
    with pytest.raises(ContractError):
        validate_scanner_output([{**row, "score": 1.2}])
    with pytest.raises(ContractError):
        validate_scanner_output([{**row, "side": "BUY"}])
