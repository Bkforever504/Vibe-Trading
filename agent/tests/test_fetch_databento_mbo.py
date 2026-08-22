from __future__ import annotations

import pytest

from scripts.fetch_databento_mbo import cache_path, credit_guard, request_kwargs


def test_mbo_request_uses_one_complete_utc_session() -> None:
    assert request_kwargs("2026-07-15") == {
        "dataset": "GLBX.MDP3",
        "schema": "mbo",
        "symbols": "MES.v.0",
        "stype_in": "continuous",
        "start": "2026-07-15T00:00:00Z",
        "end": "2026-07-16T00:00:00Z",
    }


def test_mbo_request_rejects_weekend() -> None:
    with pytest.raises(ValueError, match="weekday"):
        request_kwargs("2026-07-18")


def test_mbo_cache_name_is_session_specific() -> None:
    assert cache_path("2026-07-15").name == "mes_v0_mbo_2026-07-15.dbn.zst"


def test_mbo_credit_guard_preserves_large_reserve() -> None:
    result = credit_guard(2.25, 23.45)
    assert result["estimated_remaining_credits_usd"] == 21.2
    assert result["minimum_credit_buffer_usd"] == 15.0


def test_mbo_credit_guard_rejects_cap_or_reserve_breach() -> None:
    with pytest.raises(RuntimeError, match="hard cap"):
        credit_guard(5.01, 23.45)
    with pytest.raises(RuntimeError, match="safety buffer"):
        credit_guard(4.0, 18.5)
