from agent.observability.trace_context import current_trace_id, new_trace_id, trace_fields, trace_scope


def test_trace_scope_propagates_and_restores_context():
    assert current_trace_id() is None
    with trace_scope(seed="event-1") as trace_id:
        assert current_trace_id() == trace_id
        assert new_trace_id("event-1") == trace_id
    assert current_trace_id() is None


def test_trace_fields_never_synthesize_missing_clocks_or_authority():
    trace_id = new_trace_id("event-2")
    fields = trace_fields(trace_id=trace_id, bar_close_ts="2026-09-04T15:00:00Z")
    assert fields["scanner_emit_ts"] is None
    assert fields["execution_enabled"] is False
    assert fields["can_submit_orders"] is False

