import json
from datetime import datetime, timezone

from scripts import governed_shadow_decision as gate


def _candidate(**overrides):
    candidate = {
        "symbol": "SPY",
        "direction": "LONG",
        "setup": "completed_bar_breakout",
        "state": "CONFIRMED",
        "trigger": 600.0,
        "stop": 599.0,
        "target": 602.0,
        "bar_completed_at": "2026-09-02T14:35:00Z",
    }
    candidate.update(overrides)
    return candidate


def test_policy_rejects_stand_aside_without_hiding_candidate():
    candidate = _candidate()
    decision, blockers = gate.policy_gate(
        candidate,
        {"recommendation": "stand_aside", "portfolio_kill_switch": {"active": False}},
        {"recent_regime": {"new_shadow_entries_allowed": True}},
        set(),
    )
    assert decision == "shadow_rejected"
    assert "consensus_not_explicitly_approved:stand_aside" in blockers
    assert gate._candidate_key(candidate)


def test_policy_accepts_valid_completed_bar_with_positive_recent_evidence():
    decision, blockers = gate.policy_gate(
        _candidate(),
        {"recommendation": "approve", "portfolio_kill_switch": {"active": False}},
        {"recent_regime": {"new_shadow_entries_allowed": True}},
        set(),
    )
    assert decision == "shadow_accepted"
    assert blockers == []


def test_ollama_critic_can_only_add_a_shadow_veto():
    base = dict(
        candidate=_candidate(),
        consensus={"recommendation": "approve", "portfolio_kill_switch": {"active": False}},
        learning={"recent_regime": {"new_shadow_entries_allowed": True}},
        prior_keys=set(),
    )
    support, support_blockers = gate.policy_gate(**base, ollama_critic={
        "status": "ok", "authority": "shadow_veto_only", "execution_enabled": False,
        "can_submit_orders": False, "stance": "support", "veto_reasons": [],
    })
    veto_card = {
        "status": "ok", "authority": "shadow_veto_only", "execution_enabled": False,
        "can_submit_orders": False, "stance": "veto", "veto_reasons": ["market_regime_conflict"],
        "evidence_refs": ["e1"], "summary": "Regime conflict.", "model_digest": "sha256:model",
    }
    veto_card["response_hash"] = gate._canonical_hash({key: veto_card.get(key) for key in ("stance", "veto_reasons", "evidence_refs", "summary")})
    veto, veto_blockers = gate.policy_gate(**base, ollama_critic=veto_card)
    assert support == "shadow_accepted" and support_blockers == []
    assert veto == "shadow_rejected" and veto_blockers == ["ollama_local_critic_veto"]


def test_policy_fails_closed_when_learning_report_is_missing():
    decision, blockers = gate.policy_gate(
        _candidate(),
        {"recommendation": "approve", "portfolio_kill_switch": {"active": False}},
        {},
        set(),
    )
    assert decision == "shadow_rejected"
    assert "recent_evidence_missing_or_not_positive" in blockers


def test_policy_whitelists_consensus_instead_of_accepting_unknown_values():
    decision, blockers = gate.policy_gate(
        _candidate(),
        {"recommendation": "yellow", "portfolio_kill_switch": {"active": False}},
        {"recent_regime": {"new_shadow_entries_allowed": True}},
        set(),
    )
    assert decision == "shadow_rejected"
    assert "consensus_not_explicitly_approved:yellow" in blockers


def test_policy_fails_closed_when_kill_switch_state_is_missing():
    decision, blockers = gate.policy_gate(
        _candidate(),
        {"recommendation": "approve"},
        {"recent_regime": {"new_shadow_entries_allowed": True}},
        set(),
    )
    assert decision == "shadow_rejected"
    assert "portfolio_kill_switch_state_missing_or_invalid" in blockers


def test_consensus_lookup_propagates_global_kill_switch():
    result = gate._consensus_for("SPY", {
        "generated_at": "2026-09-03T13:00:00Z",
        "portfolio_kill_switch": {"active": False},
        "decisions": [{"symbol": "SPY", "recommendation": "approve"}],
    })
    assert result["portfolio_kill_switch"] == {"active": False}


def test_policy_rejects_stale_candidate_before_simulated_lifecycle() -> None:
    decision, blockers = gate.policy_gate(
        _candidate(),
        {"recommendation": "approve", "portfolio_kill_switch": {"active": False}},
        {"recent_regime": {"new_shadow_entries_allowed": True}},
        set(),
        now=datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc),
    )
    assert decision == "shadow_rejected"
    assert "candidate_stale_or_future_dated" in blockers


def test_latest_candidates_preserve_independent_3m_and_5m_lanes() -> None:
    five = _candidate(lane="CORE_INDEX_SHADOW", setup="completed_5m_breakout")
    three = _candidate(lane="DAILY_MAP_3M_SHADOW", setup="daily_map_3m_level_reaction")
    rows = gate._latest_confirmed_candidates([five, three], historical=False)
    assert len(rows) == 2
    assert {row["lane"] for row in rows} == {"CORE_INDEX_SHADOW", "DAILY_MAP_3M_SHADOW"}


def test_append_is_idempotent_and_never_enables_execution(tmp_path):
    candidate = _candidate()
    record = {
        "event_id": "event-1",
        "candidate_key": gate._candidate_key(candidate),
        "candidate": candidate,
        "decision": "shadow_accepted",
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    report = {"decisions": [record]}
    ledger = tmp_path / "ledger.jsonl"
    assert gate.append_new(report, ledger) == 1
    assert gate.append_new(report, ledger) == 0
    stored = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert stored["execution_enabled"] is False
    assert stored["can_submit_orders"] is False
