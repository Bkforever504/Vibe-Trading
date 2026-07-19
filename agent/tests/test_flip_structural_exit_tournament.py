from strategies.flip_shadow_setup_challengers import simulate_structural_exit_tournament


def test_structural_paths_use_forward_marks_and_do_not_submit_orders() -> None:
    observations = [
        {"scanned_at": "2026-07-17T14:00:00Z", "right": "CALL", "return_pct_at_mark": 0,
         "underlying_close": 100, "underlying_vwap": 99.5, "underlying_prior_5m_close": 99.8,
         "underlying_mark_status": "observed_forward"},
        {"scanned_at": "2026-07-17T14:05:00Z", "right": "CALL", "return_pct_at_mark": 25,
         "underlying_close": 101, "underlying_vwap": 100, "underlying_prior_5m_close": 100.5,
         "underlying_mark_status": "observed_forward"},
        {"scanned_at": "2026-07-17T14:10:00Z", "right": "CALL", "return_pct_at_mark": 18,
         "underlying_close": 99.8, "underlying_vwap": 100, "underlying_prior_5m_close": 100.7,
         "underlying_mark_status": "observed_forward"},
    ]

    result = simulate_structural_exit_tournament(observations)

    assert result["structural_vwap_trail"]["exit_trigger"] == "vwap_cross"
    assert result["structural_5m_close_trail"]["hypothetical_exit_pct"] == 18
    assert result["current_ratchet"]["exit_trigger"] == "observed_path_end"


def test_structural_paths_reject_mixed_provenance() -> None:
    observations = [
        {"scanned_at": "2026-07-17T14:00:00Z", "right": "CALL", "return_pct_at_mark": 0,
         "underlying_close": 100, "underlying_vwap": 99.5, "underlying_prior_5m_close": 99.8,
         "underlying_mark_status": "observed_forward"},
        {"scanned_at": "2026-07-17T14:05:00Z", "right": "CALL", "return_pct_at_mark": 25,
         "underlying_close": 101, "underlying_vwap": 100, "underlying_prior_5m_close": 100.5,
         "underlying_mark_status": "unavailable"},
    ]

    assert simulate_structural_exit_tournament(observations) == {}
