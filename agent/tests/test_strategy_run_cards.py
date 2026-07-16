import json

import pytest

from research.strategy_run_cards import build_run_card, write_run_card
from research.strategy_trial_bridge import ledger_trial_from_run_card


def _packet():
    return {
        "name": "test",
        "thesis": "test edge",
        "research": {
            "dataset_start": "2025-01-01",
            "dataset_end": "2025-12-31",
            "oos_start": "2025-10-01",
            "oos_end": "2025-12-31",
            "cost_model": "half_spread",
        },
        "provenance": {"source": "test"},
    }


def test_run_card_is_research_only_and_reproducible(tmp_path):
    card = build_run_card(
        packet_id="abc123",
        packet=_packet(),
        validation={"valid": True, "errors": []},
        metrics=None,
        code_version="deadbeef",
    )
    assert card["execution_enabled"] is False
    assert card["can_submit_orders"] is False
    assert card["status"] == "validated_not_backtested"
    first = write_run_card(card, tmp_path)
    second = write_run_card(card, tmp_path)
    assert first == second
    assert first.read_bytes() == second.read_bytes()


def test_different_content_cannot_overwrite_same_run_id(tmp_path):
    card = build_run_card("abc", _packet(), {"valid": True}, None, code_version="deadbeef")
    path = write_run_card(card, tmp_path)
    changed = json.loads(path.read_text())
    changed["status"] = "tampered"
    with pytest.raises(FileExistsError):
        write_run_card(changed, tmp_path)


def test_incomplete_metrics_do_not_create_research_complete_card():
    card = build_run_card(
        "abc",
        _packet(),
        {"valid": True},
        {"oos_trade_count": 40},
        code_version="deadbeef",
    )
    assert card["status"] == "incomplete_metrics"


def test_validation_only_card_cannot_enter_trial_ledger():
    with pytest.raises(ValueError, match="completed research metrics required"):
        ledger_trial_from_run_card({"status": "validated_not_backtested", "metrics": None})


def test_completed_card_maps_oos_metrics_without_promotion():
    metrics = {
        "oos_trade_count": 40,
        "oos_expectancy": 0.02,
        "oos_profit_factor": 1.3,
        "oos_max_drawdown": 0.12,
        "oos_p_value": 0.01,
    }
    card = build_run_card(
        "abc",
        _packet(),
        {"valid": True},
        metrics,
        code_version="deadbeef",
    )
    trial = ledger_trial_from_run_card(card)
    assert trial["stage"] == "out_of_sample"
    assert trial["metrics"] == metrics
    assert trial["execution_enabled"] is False
    assert trial["can_submit_orders"] is False


def test_invalid_validation_never_becomes_research_complete():
    metrics = {
        "oos_trade_count": 40,
        "oos_expectancy": 0.02,
        "oos_profit_factor": 1.3,
        "oos_max_drawdown": 0.12,
    }
    card = build_run_card("abc", _packet(), {"valid": False}, metrics, code_version="deadbeef")
    assert card["status"] == "validation_failed"
