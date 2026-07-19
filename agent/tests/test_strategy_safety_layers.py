from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.risk_kill_switch import KillSwitchConfig, evaluate_kill_switch
from strategies.shadow_ai_signals import ShadowSignal, append_shadow_signal
from strategies.prop_rule_gate import AccountState, ProposedTrade, evaluate_prop_trade, load_rule_profile


def test_daily_loss_breach_creates_manual_reset_block_file(tmp_path: Path) -> None:
    block_file = tmp_path / "manual-reset-required.json"
    config = KillSwitchConfig(max_daily_loss_pct=0.02, max_drawdown_pct=0.10)

    decision = evaluate_kill_switch(
        equity=97_500.0,
        start_equity=100_000.0,
        peak_equity=101_000.0,
        block_file=block_file,
        config=config,
        source="test",
    )

    assert decision.allowed is False
    assert decision.reason == "daily_loss_limit"
    payload = json.loads(block_file.read_text(encoding="utf-8"))
    assert payload["status"] == "blocked"
    assert payload["manual_reset_required"] is True
    assert payload["source"] == "test"


def test_existing_manual_reset_block_file_blocks_even_without_new_breach(tmp_path: Path) -> None:
    block_file = tmp_path / "manual-reset-required.json"
    block_file.write_text(
        json.dumps({"status": "blocked", "reason": "prior_drawdown"}),
        encoding="utf-8",
    )

    decision = evaluate_kill_switch(
        equity=100_000.0,
        start_equity=100_000.0,
        peak_equity=100_000.0,
        block_file=block_file,
        config=KillSwitchConfig(),
    )

    assert decision.allowed is False
    assert decision.reason == "manual_reset_required"


def test_shadow_signal_journal_is_shadow_only_jsonl(tmp_path: Path) -> None:
    journal = tmp_path / "shadow-signals.jsonl"
    signal = ShadowSignal(
        symbol="NQ",
        strategy="opening_range_breakout",
        proposed_action="buy",
        confidence=0.64,
        thesis="Trend and volume aligned, but this is shadow mode only.",
        risk_notes=["No order authority", "Needs deterministic gate"],
    )

    written = append_shadow_signal(signal, journal)

    assert written["mode"] == "shadow_only"
    assert written["executable"] is False
    assert written["proposed_action"] == "buy"
    rows = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert rows == [written]


def test_prop_gate_blocks_when_automation_is_prohibited(tmp_path: Path) -> None:
    profile_path = tmp_path / "apex.json"
    profile_path.write_text(
        json.dumps(
            {
                "firm": "Apex Test",
                "account_type": "PA",
                "automation": {"allowed": False, "status": "prohibited"},
                "risk": {"max_daily_loss": 1000, "max_trailing_drawdown": 2500, "max_contracts": 5},
                "consistency": {"enabled": True, "max_best_day_pct": 0.30},
                "unknown_rules_block": True,
            }
        ),
        encoding="utf-8",
    )

    decision = evaluate_prop_trade(
        load_rule_profile(profile_path),
        ProposedTrade(symbol="NQ", side="buy", contracts=1, risk_dollars=100, automated=True),
        AccountState(equity=50_000, start_equity=50_000, day_pnl=0, trailing_drawdown_remaining=2500),
    )

    assert decision.allowed is False
    assert decision.confidence_score >= 90
    assert any("automation" in reason.lower() for reason in decision.reasons)


def test_prop_gate_blocks_trade_that_would_break_daily_loss() -> None:
    profile = {
        "firm": "Topstep Test",
        "account_type": "50K combine",
        "automation": {"allowed": True, "status": "allowed_with_conditions", "requires_local_device": True},
        "risk": {"max_daily_loss": 1000, "max_trailing_drawdown": 2000, "max_contracts": 5},
        "consistency": {"enabled": True, "max_best_day_pct": 0.50},
        "unknown_rules_block": True,
    }

    decision = evaluate_prop_trade(
        profile,
        ProposedTrade(symbol="NQ", side="buy", contracts=1, risk_dollars=250, automated=True, running_on_vps=False),
        AccountState(equity=50_000, start_equity=50_000, day_pnl=-850, trailing_drawdown_remaining=2000),
    )

    assert decision.allowed is False
    assert "daily_loss_limit" in decision.reasons


def test_prop_gate_allows_small_trade_inside_verified_rules() -> None:
    profile = {
        "firm": "Topstep Test",
        "account_type": "50K combine",
        "automation": {"allowed": True, "status": "allowed_with_conditions", "requires_local_device": True},
        "risk": {"max_daily_loss": 1000, "max_trailing_drawdown": 2000, "max_contracts": 5},
        "consistency": {"enabled": True, "max_best_day_pct": 0.50},
        "unknown_rules_block": True,
    }

    decision = evaluate_prop_trade(
        profile,
        ProposedTrade(symbol="MNQ", side="buy", contracts=1, risk_dollars=100, automated=True, running_on_vps=False),
        AccountState(equity=50_000, start_equity=50_000, day_pnl=-100, trailing_drawdown_remaining=1900),
    )

    assert decision.allowed is True
    assert decision.confidence_score >= 90
    assert decision.reasons == ["rules_passed"]


def test_checked_in_conservative_profiles_are_not_accidentally_permissive() -> None:
    profiles_dir = ROOT / "rules" / "prop_firms"
    apex = load_rule_profile(profiles_dir / "apex_conservative.json")
    tradeify = load_rule_profile(profiles_dir / "tradeify_conservative.json")

    for profile in (apex, tradeify):
        decision = evaluate_prop_trade(
            profile,
            ProposedTrade(symbol="NQ", side="buy", contracts=1, risk_dollars=100, automated=True),
            AccountState(equity=50_000, start_equity=50_000, day_pnl=0, trailing_drawdown_remaining=2500),
        )
        assert decision.allowed is False
        assert "automation_prohibited" in decision.reasons
