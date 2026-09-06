import json

import numpy as np

from agent.governance.statistical_gate import (StatisticalGate,
                                                append_gate_history, cpcv_audit, default_outcome_loader,
                                                deflated_sharpe_score, pbo_score)
from agent.governance.trial_ledger import record_trial


def _registry(path, *, status="shadow", minimum=30):
    path.write_text(json.dumps({"signals": [{"id": "signal-a", "status": status,
        "family_key": "momentum", "promotion_gate": {"min_outcomes": minimum,
        "min_deflated_sharpe": 0.0, "min_psr": 0.95, "max_pbo": 0.5,
        "requires_human_review": True}}]}), encoding="utf-8")


def test_cpcv_purged_embargo_no_leakage():
    audit = cpcv_audit(40)
    assert audit["folds"] > 1
    assert audit["leakage"] is False
    assert all(not row["overlap"] and not row["embargo_violation"] for row in audit["splits"])


def test_deflated_sharpe_penalizes_trials():
    returns = np.random.default_rng(1).normal(.1, 1, 200)
    one = deflated_sharpe_score(returns, 1, [.1])
    many = deflated_sharpe_score(returns, 100, [value / 10 for value in range(-10, 11)])
    assert one is not None and many is not None
    assert many < one


def test_pbo_flags_overfit():
    matrix = np.random.default_rng(1).normal(size=(4, 64))
    assert pbo_score(matrix) > 0.5


def test_gate_fail_closed_on_missing_outcomes(tmp_path):
    registry, ledger = tmp_path / "registry.json", tmp_path / "trials.jsonl"
    _registry(registry)
    record_trial("signal-a", "h1", family_key="momentum", path=ledger)
    gate = StatisticalGate(registry_path=registry, ledger_path=ledger, outcome_loader=lambda _: [1] * 5)
    result = gate.evaluate("signal-a")
    assert result.status == "not_ready"
    assert result.reason == "insufficient_outcomes:5/30"


def test_gate_fail_closed_on_missing_trial_ledger(tmp_path):
    registry = tmp_path / "registry.json"
    _registry(registry)
    result = StatisticalGate(registry_path=registry, ledger_path=tmp_path / "missing.jsonl",
                             outcome_loader=lambda _: [1] * 40).evaluate("signal-a")
    assert result.status == "error"
    assert result.n_trials is None


def test_no_auto_demotion(tmp_path):
    registry, ledger = tmp_path / "registry.json", tmp_path / "trials.jsonl"
    _registry(registry, status="execution_capable_paper")
    before = registry.read_text()
    record_trial("signal-a", "h1", family_key="momentum", path=ledger)
    result = StatisticalGate(registry_path=registry, ledger_path=ledger,
                             outcome_loader=lambda _: [-1] * 5).evaluate("signal-a")
    assert result.status == "needs_review"
    assert result.registry_promotion_unchanged is True
    assert registry.read_text() == before


def test_model_version_hash_persists(tmp_path):
    registry, ledger = tmp_path / "registry.json", tmp_path / "trials.jsonl"
    _registry(registry)
    record_trial("signal-a", "h1", family_key="momentum", path=ledger)
    result = StatisticalGate(registry_path=registry, ledger_path=ledger,
                             outcome_loader=lambda _: [1] * 5).evaluate("signal-a")
    target = append_gate_history(result, directory=tmp_path / "history")
    row = json.loads(target.read_text())
    assert row["model_version"] == result.model_version
    assert row["n"] == row["n_outcomes"] == 5
    assert row["t"] == row["n_trials"] == 1
    assert row["k"] == row["iterations"]
    assert row["iterations"] >= 1000


def test_outcome_loader_excludes_pre_configuration_rows(tmp_path):
    path = tmp_path / "outcomes.json"
    path.write_text(json.dumps([
        {"status": "closed", "exit_date": "2026-01-01", "pnl": 100},
        {"status": "closed", "exit_date": "2026-02-01", "pnl": 2},
    ]), encoding="utf-8")
    values = default_outcome_loader({"log_path": str(path), "post_config_start_date": "2026-01-15"})
    assert values == [2.0]
