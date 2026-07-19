from __future__ import annotations

import json
from pathlib import Path

from strategies import shadow_consensus


def _write_report(path: Path, decisions: list[dict], *, killed: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "provider": "shadow_consensus_gate",
                "execution_enabled": False,
                "can_submit_orders": False,
                "portfolio_kill_switch": {"active": killed},
                "decisions": decisions,
            }
        ),
        encoding="utf-8",
    )


def test_entry_advice_treats_alpha_stand_aside_as_size_down_advice(tmp_path: Path) -> None:
    report_path = tmp_path / "shadow-consensus-gate.json"
    _write_report(
        report_path,
        [
            {
                "symbol": "SPY",
                "recommendation": "stand_aside",
                "options_playbook": "none",
                "blockers": ["market_force_unclear"],
                "reasons": ["No clean directional edge"],
            }
        ],
    )

    advice = shadow_consensus.entry_advice("SPY", 5, report_path=report_path, enabled=True)

    assert advice["enabled"] is True
    assert advice["allowed"] is True
    assert advice["adjusted_contracts"] == 2
    assert advice["recommendation"] == "stand_aside"
    assert "market_force_unclear" in advice["blockers"]
    assert advice["hard_blockers"] == []
    assert advice["alpha_advisory_only"] is True


def test_entry_advice_still_blocks_execution_safety_failure(tmp_path: Path) -> None:
    report_path = tmp_path / "shadow-consensus-gate.json"
    _write_report(
        report_path,
        [
            {
                "symbol": "SPY",
                "recommendation": "stand_aside",
                "options_playbook": "none",
                "blockers": ["market_force_unclear", "options_liquidity_blocked"],
                "reasons": ["Option market is not executable"],
            }
        ],
    )

    advice = shadow_consensus.entry_advice("SPY", 5, report_path=report_path, enabled=True)

    assert advice["allowed"] is False
    assert advice["adjusted_contracts"] == 0
    assert advice["hard_blockers"] == ["options_liquidity_blocked"]
    assert advice["alpha_advisory_only"] is False


def test_entry_advice_sizes_down_but_never_up(tmp_path: Path) -> None:
    report_path = tmp_path / "shadow-consensus-gate.json"
    _write_report(
        report_path,
        [
            {
                "symbol": "SPY",
                "recommendation": "size_down",
                "options_playbook": "long_put",
                "blockers": ["shadow_not_promotion_ready"],
                "reasons": ["Positive shadow edge but not enough samples"],
            }
        ],
    )

    advice = shadow_consensus.entry_advice("SPY", 5, report_path=report_path, enabled=True)

    assert advice["allowed"] is True
    assert advice["adjusted_contracts"] == 2
    assert advice["options_playbook"] == "long_put"


def test_entry_advice_fails_open_when_report_missing(tmp_path: Path) -> None:
    advice = shadow_consensus.entry_advice("QQQ", 3, report_path=tmp_path / "missing.json", enabled=True)

    assert advice["allowed"] is True
    assert advice["adjusted_contracts"] == 3
    assert advice["recommendation"] == "needs_review"
    assert "shadow_consensus_unavailable" in advice["blockers"]


def test_exit_advice_flags_review_when_kill_switch_or_stand_aside(tmp_path: Path) -> None:
    report_path = tmp_path / "shadow-consensus-gate.json"
    _write_report(
        report_path,
        [{"symbol": "TSLA", "recommendation": "stand_aside", "blockers": ["portfolio_kill_switch_active"], "shadow_exit_control_eligible": True}],
        killed=True,
    )

    advice = shadow_consensus.exit_advice("TSLA", "PUT", report_path=report_path, enabled=True)

    assert advice["action"] == "review_exit"
    assert advice["can_submit_orders"] is False
    assert "portfolio_kill_switch_active" in advice["blockers"]
