import json

from scripts.statistical_governance_report import build_report, latency_proof


def test_latency_proof_reports_no_baseline_honestly(tmp_path):
    path = tmp_path / "pairs.jsonl"
    path.write_text(json.dumps({"trace_id": "t1", "baseline_latency_ms": None,
                                "new_latency_ms": 1200}) + "\n", encoding="utf-8")
    result = latency_proof(path)
    assert result["status"] == "no_baseline"
    assert result["result"] is None


def test_latency_proof_requires_thirty_pairs(tmp_path):
    path = tmp_path / "pairs.jsonl"
    path.write_text(json.dumps({"baseline_latency_ms": 2000, "new_latency_ms": 1000}) + "\n",
                    encoding="utf-8")
    assert latency_proof(path)["status"] == "insufficient_data"


def test_report_reads_latest_gate_only(tmp_path):
    history = tmp_path / "history"
    history.mkdir()
    (history / "a.jsonl").write_text(
        json.dumps({"signal_id": "a", "status": "not_ready"}) + "\n" +
        json.dumps({"signal_id": "a", "status": "needs_review"}) + "\n", encoding="utf-8")
    report = build_report(history, tmp_path / "missing.jsonl")
    assert report["signals"] == [{"signal_id": "a", "status": "needs_review"}]
    assert report["execution_enabled"] is False
