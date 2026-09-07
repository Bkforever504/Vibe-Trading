from scripts.options_tape_intelligence_shadow import aggregate_tcbbo_impulse, build_report, classify_tcbbo_trade


def trade(price=1.02, condition="SIMPLE", package_id=None):
    return {
        "symbol": "QQQ  260904P00718000", "price": price, "size": 10,
        "bid_px_00": 1.00, "ask_px_00": 1.02,
        "ts_event": "2026-09-04T13:31:00.100000Z",
        "quote_ts": "2026-09-04T13:31:00Z", "sequence": 7,
        "trade_condition": condition, "package_id": package_id,
    }


def test_simple_tcbbo_trade_is_only_a_location_inference():
    result = classify_tcbbo_trade(trade())
    assert result["status"] == "classified"
    assert result["inferred_trade_location"] == "near_ask"
    assert result["aggressor_side"] == "not_provided_by_opra"
    assert result["opening_closing_intent"] == "unknown"
    assert result["execution_enabled"] is False


def test_complex_and_stale_prints_are_excluded_not_directional():
    complex_print = classify_tcbbo_trade(trade(condition="COMPLEX_SPREAD", package_id="abc"))
    stale = trade()
    stale["quote_ts"] = "2026-09-04T13:30:50Z"
    assert "complex_or_packaged_trade" in complex_print["blockers"]
    assert "pre_trade_quote_stale_or_unordered" in classify_tcbbo_trade(stale)["blockers"]


def test_aggregate_retains_ambiguity_and_requires_multiple_clean_prints():
    result = aggregate_tcbbo_impulse([trade(), trade(1.00), trade(1.01)])
    assert result["status"] == "observed"
    assert result["near_ask_premium_usd"] > 0
    assert result["near_bid_premium_usd"] > 0
    assert result["ambiguous_premium_usd"] > 0
    assert result["can_submit_orders"] is False
    insufficient = aggregate_tcbbo_impulse([trade(condition="AUCTION")])
    assert insufficient["status"] == "insufficient_independent_evidence"
    assert insufficient["signed_premium_imbalance"] is None


def test_native_tcbbo_does_not_treat_capture_time_as_quote_time_or_invent_complex_status():
    row = trade()
    row.pop("quote_ts")
    row.pop("trade_condition")
    row.pop("package_id")
    row.update({"ts_recv": "2026-09-04T13:31:00.101000Z", "side": "N", "flags": 0, "publisher_id": 31})
    result = classify_tcbbo_trade(row)
    assert "pre_trade_quote_stale_or_unordered" not in result["blockers"]
    assert "complex_classification_unavailable" in result["blockers"]
    assert result["quote_provenance"] == "tcbbo_immediately_preceding_cbbo_by_schema"
    assert result["native_side"] == "N"


def test_missing_tcbbo_adapter_input_fails_honestly(tmp_path):
    report = build_report(tmp_path / "missing.jsonl")
    assert report["status"] == "not_configured"
    assert report["reason"] == "timestamped_opra_tcbbo_event_file_missing"
    assert report["execution_enabled"] is False
