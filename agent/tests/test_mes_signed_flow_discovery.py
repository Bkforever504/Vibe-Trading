from __future__ import annotations

import json
from pathlib import Path

import pytest

from research import mes_signed_flow_discovery as discovery


def test_quote_test_and_prior_tick_carry() -> None:
    assert discovery.classify_sign(100.25, 100.00, 100.25) == 1
    assert discovery.classify_sign(100.00, 100.00, 100.25) == -1
    assert discovery.classify_sign(100.10, 100.00, 100.25, prior_sign=1) == 1
    assert discovery.classify_sign(100.10, 100.00, 100.25) == 0


def test_quality_gates_require_every_threshold() -> None:
    passing = discovery.quality_gates(
        sessions=40, quote_match_rate=0.95, signed_volume_rate=0.90
    )
    assert passing["all_pass"] is True
    failing = discovery.quality_gates(
        sessions=39, quote_match_rate=0.99, signed_volume_rate=0.99
    )
    assert failing["all_pass"] is False


def test_exclusions_include_roll_and_degraded_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = {
        "results": [{
            "roll_sessions_excluded": ["2025-12-17", "2026-03-18"],
            "dataset_condition_dates_excluded": {"2025-11-28": "degraded"},
        }]
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(discovery, "OHLC_MANIFEST", path)
    assert discovery.excluded_sessions() == {"2025-11-28", "2025-12-17"}


@pytest.mark.parametrize("forbidden", ["pnl", "future_return", "profit_factor", "outcome"])
def test_phase_a_rejects_outcome_fields(forbidden: str) -> None:
    with pytest.raises(ValueError, match="forbidden key"):
        discovery.validate_outcome_blind({"coverage": {}, forbidden: 1})


def test_phase_a_accepts_contemporaneous_features() -> None:
    discovery.validate_outcome_blind(
        {"feature_distributions": {"signed_imbalance": {}, "mid_displacement": {}}}
    )
