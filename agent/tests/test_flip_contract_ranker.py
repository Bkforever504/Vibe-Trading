from strategies.flip_contract_ranker import rank_contracts


def test_liquid_atm_contract_ranks_ahead_of_stale_wide_otm() -> None:
    ranked = rank_contracts([
        {
            "option_symbol": "SPYATM", "strike": 750, "right": "CALL", "delta": 0.51,
            "spread_pct": 2.0, "quote_age_seconds": 1.0, "expected_move_room": 1.0,
            "premium_expansion_pct": 20.0,
        },
        {
            "option_symbol": "SPYOTM", "strike": 755, "right": "CALL", "delta": 0.08,
            "spread_pct": 25.0, "quote_age_seconds": 70.0, "expected_move_room": 2.2,
            "premium_expansion_pct": 180.0,
        },
    ])

    assert ranked[0]["option_symbol"] == "SPYATM"
    assert ranked[0]["contract_rank"]["rank"] == 1
    assert ranked[0]["contract_rank"]["disqualified"] is False
    assert ranked[1]["contract_rank"]["disqualified"] is True
    assert "delta_under_0.10" in ranked[1]["contract_rank"]["disqualify_reason"]


def test_missing_optional_telemetry_is_neutral_not_disqualifying() -> None:
    row = rank_contracts([{
        "option_symbol": "SPYATM", "strike": 750, "right": "PUT",
        "delta": None, "spread_pct": 4.0, "quote_age_seconds": None,
        "expected_move_room": None, "premium_expansion_pct": None,
    }])[0]

    assert row["contract_rank"]["disqualified"] is False
    assert row["contract_rank"]["composite_score"] > 0

