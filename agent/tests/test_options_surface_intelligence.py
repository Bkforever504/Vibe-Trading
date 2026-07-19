from __future__ import annotations

from datetime import date

from scripts import options_surface_intelligence as surface


def _contract(
    strike: float,
    *,
    bid: float = 1.0,
    ask: float = 1.1,
    iv: float = 0.40,
    volume: int = 200,
    oi: int = 500,
    symbol: str = "OPT",
) -> dict:
    return {
        "contractSymbol": symbol,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "lastPrice": (bid + ask) / 2,
        "impliedVolatility": iv,
        "volume": volume,
        "openInterest": oi,
    }


def test_surface_computes_skew_term_structure_and_unsigned_flow() -> None:
    snapshot = {
        "symbol": "SPY",
        "spot": 100.0,
        "snapshot_at": "2026-07-13T20:00:00Z",
        "chains": [
            {
                "expiry": "2026-07-20",
                "calls": [_contract(100, iv=0.30), _contract(110, iv=0.36, volume=400, oi=100)],
                "puts": [_contract(90, iv=0.50), _contract(100, iv=0.32)],
            },
            {
                "expiry": "2026-08-10",
                "calls": [_contract(100, iv=0.40), _contract(110, iv=0.42)],
                "puts": [_contract(90, iv=0.48), _contract(100, iv=0.40)],
            },
        ],
    }

    result = surface.analyze_snapshot(snapshot, today=date(2026, 7, 13))

    assert result["status"] == "ok"
    assert result["front_put_skew_vs_atm"] == 0.18
    assert result["front_call_wing_vs_atm"] == 0.06
    assert result["atm_iv_term_slope_per_30d"] > 0
    assert result["term_structure"] == "contango_or_flat"
    assert result["unsigned_unusual_contract_count"] >= 1
    assert result["institutional_flow_available"] is False
    unusual = result["expiries"][0]["unusual_unsigned_contracts"][0]
    assert unusual["trade_direction"] == "unknown_unsigned_snapshot"


def test_surface_flags_cheap_high_iv_wide_spread_lottery_risk() -> None:
    risky = _contract(15, bid=0.05, ask=0.45, iv=1.8, volume=600, oi=100, symbol="RISK")
    snapshot = {
        "symbol": "RIVN",
        "spot": 12.0,
        "chains": [
            {"expiry": "2026-07-20", "calls": [_contract(12), risky], "puts": [_contract(12), _contract(10)]},
            {"expiry": "2026-08-10", "calls": [_contract(12)], "puts": [_contract(12)]},
        ],
    }

    result = surface.analyze_snapshot(snapshot, today=date(2026, 7, 13))

    assert result["retail_lottery_risk"] is True
    assert result["lottery_contract_count"] >= 1
    assert "low_price_underlying" in result["retail_lottery_risk_reasons"]
    assert "cheap_high_iv_wide_spread_wings" in result["retail_lottery_risk_reasons"]


def test_report_is_read_only_and_preserves_fetch_failures() -> None:
    def fetcher(symbol: str, today: date | None) -> dict:
        if symbol == "BAD":
            raise RuntimeError("chain unavailable")
        return {
            "symbol": symbol,
            "spot": 100,
            "chains": [{
                "expiry": "2026-07-20",
                "calls": [_contract(100)],
                "puts": [_contract(100)],
            }],
        }

    result = surface.build_report(["SPY", "BAD"], fetcher=fetcher, today=date(2026, 7, 13))

    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False
    assert result["institutional_flow_available"] is False
    assert result["ok_count"] == 1
    assert next(row for row in result["results"] if row["symbol"] == "BAD")["status"] == "unavailable"
