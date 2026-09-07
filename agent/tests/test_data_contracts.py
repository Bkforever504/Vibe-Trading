from __future__ import annotations

import pytest

from contracts.schemas import ContractError, validate_breadth, validate_hmm, validate_ivr, validate_ohlcv, validate_scanner_output, validate_vwap


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


def test_shared_context_contracts_reject_bad_probabilities_and_bands():
    stamp = "2026-01-02T14:30:00Z"
    assert len(validate_ivr([{"ticker": "SPY", "timestamp": stamp, "ivr": 20, "iv": .2, "rv": .15, "rv_iv_spread": .05}])) == 1
    assert len(validate_breadth([{"ts": stamp, "adv": 3, "dec": 2, "new_highs": 1, "new_lows": 0, "mcclellan": 5}])) == 1
    with pytest.raises(ContractError, match="sum_to_one"):
        validate_hmm([{"ticker": "SPY", "timestamp": stamp, "state": "trend_up", "prob_trend_up": .8, "prob_chop": .5, "prob_trend_down": .1}])
    with pytest.raises(ContractError, match="band_order"):
        validate_vwap([{"ticker": "SPY", "ts": stamp, "vwap": 100, "upper_band": 99, "lower_band": 98, "deviation_z": 1}])
