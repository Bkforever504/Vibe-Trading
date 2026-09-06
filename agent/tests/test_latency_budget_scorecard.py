from scripts.latency_budget_scorecard import build_report, paired_latency_proof


def receipt(**changes):
    return {"event_id": "one", "delivered": True,
            "delivery_timestamp_semantics": "discord_message_timestamp",
            "signal_available_at": "2026-09-04T14:00:00Z",
            "decision_at": "2026-09-04T14:01:20Z",
            "attempted_at": "2026-09-04T14:01:30Z",
            "delivered_at": "2026-09-04T14:01:32Z", **changes}


def test_latency_budget_detects_stage_breach_without_blame_guessing():
    report = build_report({"governed_shadow": [receipt()]})
    stages = report["by_source"]["governed_shadow"]
    assert stages["signal_bar_to_decision"]["p90"] == 80
    assert stages["total_signal_to_delivered"]["p90"] == 92
    assert stages["alert_to_discord_delivered"]["status"] == "within_budget"
    assert len(report["breach_summary"]) == 3


def test_latency_budget_never_substitutes_attempt_for_delivery():
    report = build_report({"governed_shadow": [receipt(delivered_at=None)]})
    assert report["status"] == "insufficient_evidence"
    assert report["by_source"]["governed_shadow"]["total_signal_to_delivered"]["p90"] is None


def test_latency_budget_deduplicates_and_excludes_clock_errors():
    report = build_report({"governed_shadow": [receipt(), receipt(), receipt(event_id="bad", decision_at="2026-09-04T13:59:00Z")]})
    assert report["by_source"]["governed_shadow"]["signal_bar_to_decision"]["count"] == 1
    assert report["excluded_counts"]["duplicate"] == 1
    assert report["excluded_counts"]["non_monotonic_clock"] == 1


def test_latency_budget_partial_receipt_does_not_claim_complete_pipeline():
    report = build_report({"governed_shadow": [receipt(decision_at=None)]})
    assert report["by_source"]["governed_shadow"]["signal_bar_to_decision"]["status"] == "missing"
    assert report["by_source"]["governed_shadow"]["total_signal_to_delivered"]["count"] == 1
    assert report["execution_enabled"] is False


def test_old_http_ack_semantics_are_preinstrumentation_not_exact():
    report = build_report({"governed_shadow": [receipt(delivery_timestamp_semantics="transport_acknowledged")]})
    assert report["status"] == "insufficient_evidence"
    assert report["historical_gap"]["pre_instrumentation_rows"] == 1
    assert report["historical_gap"]["timestamps_synthesized"] == 0


def test_paired_latency_proof_requires_30_and_ci_excluding_zero():
    short = [receipt(event_id=str(i), pair_id=str(i), pipeline_variant="baseline") for i in range(29)]
    short += [receipt(event_id=f"c{i}", pair_id=str(i), pipeline_variant="challenger") for i in range(29)]
    assert paired_latency_proof({"x": short})["status"] == "insufficient_evidence"
    rows = []
    for i in range(30):
        rows += [receipt(event_id=f"b{i}", pair_id=str(i), pipeline_variant="baseline"),
                 receipt(event_id=f"c{i}", pair_id=str(i), pipeline_variant="challenger",
                         delivered_at="2026-09-04T14:01:22Z")]
    proof = paired_latency_proof({"x": rows}, samples=200)
    assert proof["paired_samples"] == 30
    assert proof["status"] == "improvement_supported"
    assert proof["ci95_seconds"][1] < 0
