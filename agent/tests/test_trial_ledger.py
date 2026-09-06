import json

from agent.governance.trial_ledger import count_trials, family_for, record_trial


def test_trial_is_append_only_and_idempotent(tmp_path):
    ledger = tmp_path / "trial.jsonl"
    assert record_trial("one", "hash-1", family_key="momentum", path=ledger)
    assert not record_trial("one", "hash-1", family_key="momentum", path=ledger)
    assert count_trials("momentum", path=ledger) == 1
    assert len(ledger.read_text().splitlines()) == 1


def test_family_key_shares_trial_pool(tmp_path):
    ledger = tmp_path / "trial.jsonl"
    record_trial("one", "hash-1", family_key="orderflow", path=ledger)
    record_trial("two", "hash-2", family_key="orderflow", path=ledger)
    assert count_trials("orderflow", path=ledger) == 2


def test_family_assignment_reads_reviewable_config(tmp_path):
    config = tmp_path / "families.json"
    config.write_text(json.dumps({"default_family": "other", "families": {"momentum": ["breakout"]}}))
    assert family_for("opening_breakout", families_path=config) == "momentum"

