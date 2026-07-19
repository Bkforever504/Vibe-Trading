from __future__ import annotations

from datetime import date

from scripts.gex_scanner import compute_gex


DAY = date(2026, 7, 14)


def _contract(
    right: str,
    gamma: float,
    size: int,
    *,
    expiry: str = "2026-07-14",
    source: str = "open_interest",
) -> dict:
    return {
        "expiry": expiry,
        "strike": 750.0,
        "right": right,
        "gamma": gamma,
        "size_used": size,
        "size_source": source,
    }


def test_gex_requires_same_day_expiration() -> None:
    result = compute_gex([_contract("call", 0.1, 100, expiry="2026-07-15")], as_of=DAY)
    assert result["status"] == "unavailable"
    assert result["expiry_filter"] == "0dte_required"


def test_gex_rejects_quote_size_proxy() -> None:
    contracts = [
        _contract("call", 0.1, 100, source="ask_size_proxy"),
        _contract("put", 0.1, 100, source="ask_size_proxy"),
    ]
    result = compute_gex(contracts, as_of=DAY)
    assert result["status"] == "unavailable"
    assert result["open_interest_contract_count"] == 0


def test_gex_rejects_thin_open_interest_coverage() -> None:
    contracts = [_contract("call", 0.1, 100)] + [
        _contract("put", 0.1, 0, source="missing") for _ in range(4)
    ]
    result = compute_gex(contracts, as_of=DAY)
    assert result["status"] == "unavailable"
    assert result["open_interest_coverage"] == 0.2


def test_gex_reports_proxy_provenance_without_claiming_dealer_inventory() -> None:
    result = compute_gex(
        [_contract("call", 0.2, 100), _contract("put", 0.1, 50)],
        as_of=DAY,
    )
    assert result["status"] == "ok"
    assert result["net_gex"] == 1500.0
    assert result["dealer_positioning_observed"] is False
    assert result["sign_assumption"] == "calls_positive_puts_negative"
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False
