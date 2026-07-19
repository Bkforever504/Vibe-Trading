from scripts import research_asset_utilization_audit as audit


def test_cloned_source_alone_is_not_integration(tmp_path) -> None:
    (tmp_path / "source").mkdir()
    asset = {
        "id": "sample",
        "priority": 1,
        "capability": "sample capability",
        "source": ["source"],
        "intake": [],
        "adapter": [],
        "consumer": [],
        "evidence": [],
        "next_action": "build it",
    }

    row = audit.evaluate_asset(asset, tmp_path)

    assert row["stages"]["source"] is True
    assert row["utilization_score"] == 0
    assert row["status"] == "untracked"


def test_full_chain_is_operational_and_measured(tmp_path) -> None:
    for name in ("intake.md", "adapter.py", "consumer.py", "evidence.jsonl"):
        (tmp_path / name).write_text("ok", encoding="utf-8")
    asset = {
        "id": "sample",
        "priority": 1,
        "capability": "sample capability",
        "source": [],
        "intake": ["intake.md"],
        "adapter": ["adapter.py"],
        "consumer": ["consumer.py"],
        "evidence": ["evidence.jsonl"],
        "next_action": "measure lift",
    }

    row = audit.evaluate_asset(asset, tmp_path)

    assert row["status"] == "operational_measured"
    assert row["utilization_score"] == 4


def test_report_creates_concrete_gap_queue(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(audit, "ASSETS", [{
        "id": "gap",
        "priority": 1,
        "capability": "unused idea",
        "source": [],
        "intake": ["intake.md"],
        "adapter": [],
        "consumer": [],
        "evidence": [],
        "next_action": "implement adapter",
    }])
    (tmp_path / "intake.md").write_text("ok", encoding="utf-8")

    report = audit.build_report(tmp_path)

    assert report["gap_count"] == 1
    assert report["implementation_queue"][0]["next_action"] == "implement adapter"
    assert report["policy"]["intake_report_counts_as_integrated"] is False
