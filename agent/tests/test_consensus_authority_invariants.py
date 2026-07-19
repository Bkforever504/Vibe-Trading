"""Locks the decision-authority boundary between safety facts and alpha advice.

Root cause of the 2026-07-14/15 setup-agnostic gate mismatches: advisory
modules accumulated hard-veto authority inside the consensus gate, letting
bullish-playbook and credit-spread rules kill bearish long-option setups.
These invariants must hold permanently.
"""
from __future__ import annotations

import json
from pathlib import Path

from strategies.flip_bot import PRIMARY_STAND_ASIDE_BLOCKERS
from strategies.shadow_consensus import entry_advice


def _write_report(path: Path, blockers: list[str], recommendation: str = "stand_aside") -> None:
    payload = {
        "portfolio_kill_switch": {"active": False},
        "decisions": [{
            "symbol": "SPY",
            "recommendation": recommendation,
            "options_playbook": "bull_put_spread",
            "blockers": blockers,
            "reasons": ["test"],
        }],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_direction_specific_advisory_blockers_cannot_veto(tmp_path: Path) -> None:
    report = tmp_path / "consensus.json"
    _write_report(report, [
        "adaptive_flip_evidence_does_not_confirm_bullish_direction",
        "adaptive_call_credit_spread_credit/risk_is_below_minimum",
        "htf_bullish_put_spread_blocked_by_htf",
    ])
    advice = entry_advice("SPY", 2, report_path=report, enabled=True)
    assert advice["allowed"] is True
    assert advice["alpha_advisory_only"] is True
    assert advice["hard_blockers"] == []
    assert advice["adjusted_contracts"] == 1  # stand_aside sizes down, never vetoes


def test_only_safety_facts_retain_hard_block_authority(tmp_path: Path) -> None:
    report = tmp_path / "consensus.json"
    _write_report(report, ["options_liquidity_blocked"])
    advice = entry_advice("SPY", 1, report_path=report, enabled=True)
    assert advice["allowed"] is False
    assert advice["adjusted_contracts"] == 0

    _write_report(report, ["portfolio_kill_switch_active"])
    advice = entry_advice("SPY", 1, report_path=report, enabled=True)
    assert advice["allowed"] is False
    assert advice["adjusted_contracts"] == 0


def test_primary_stand_aside_blockers_are_direction_neutral() -> None:
    forbidden = ("bullish", "bearish", "credit_spread", "call", "put")
    for blocker in sorted(PRIMARY_STAND_ASIDE_BLOCKERS):
        assert not any(term in blocker for term in forbidden), (
            f"Direction- or instrument-specific blocker {blocker!r} must not hold "
            "primary stand-aside caution authority over unrelated setup families."
        )
