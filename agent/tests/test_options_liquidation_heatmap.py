from __future__ import annotations

from datetime import date

from scripts import options_liquidation_heatmap as heatmap


def _contract(
    strike: float,
    *,
    bid: float = 1.0,
    ask: float = 1.1,
    volume: int = 100,
    oi: int = 500,
    symbol: str = "OPT",
) -> dict:
    return {
        "contractSymbol": symbol,
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "lastPrice": (bid + ask) / 2,
        "volume": volume,
        "openInterest": oi,
    }


def test_heatmap_builds_pin_and_pressure_zones_without_execution() -> None:
    snapshot = {
        "symbol": "SPY",
        "spot": 100.0,
        "snapshot_at": "2026-07-28T14:30:00Z",
        "chains": [{
            "expiry": "2026-07-28",
            "calls": [_contract(100, oi=900), _contract(105, oi=1800, volume=600)],
            "puts": [_contract(95, oi=1600, volume=500), _contract(100, oi=880)],
        }],
    }

    result = heatmap.analyze_snapshot(
        snapshot,
        today=date(2026, 7, 28),
        gex={"gex_wall": {"strike": 100, "gex": 1200, "bias": "support"}},
    )

    assert result["status"] == "ok"
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False
    assert result["front_heat_state"] == "near_major_heat_zone"
    assert "spot_inside_heat_band" in result["condition_labels"]
    assert result["gex_wall"]["strike"] == 100
    assert result["top_heat_zones"][0]["bias"] in {
        "pin_magnet",
        "call_wall_resistance_proxy",
        "put_wall_support_proxy",
        "call_activity_heat",
        "put_activity_heat",
        "two_sided_heat",
    }


def test_heatmap_report_preserves_fetch_failures_and_proxy_warning() -> None:
    def fetcher(symbol: str, today: date | None) -> dict:
        if symbol == "BAD":
            raise RuntimeError("chain unavailable")
        return {
            "symbol": symbol,
            "spot": 50,
            "chains": [{
                "expiry": "2026-07-31",
                "calls": [_contract(50)],
                "puts": [_contract(50)],
            }],
        }

    report = heatmap.build_report(["SPY", "BAD"], fetcher=fetcher, today=date(2026, 7, 28), gex_by_symbol={})

    assert report["provider"] == "options_liquidation_heatmap"
    assert report["institutional_liquidation_book_available"] is False
    assert report["ok_count"] == 1
    assert report["results"][1]["status"] == "unavailable"
    assert any("proxy" in warning for warning in report["warnings"])
