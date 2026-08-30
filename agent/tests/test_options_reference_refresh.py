from __future__ import annotations

from datetime import date

from scripts.options_reference_refresh import refresh_references, select_reference_contracts


def test_select_reference_contracts_uses_current_nearest_expiry_and_atm_strike() -> None:
    surface = {"results": [{
        "symbol": "SPY",
        "expiries": [
            {"expiry": "2026-08-25", "atm_strike": 764},
            {"expiry": "2026-08-26", "atm_strike": 766},
            {"expiry": "2026-08-28", "atm_strike": 767},
        ],
    }]}

    rows = select_reference_contracts(surface, today=date(2026, 8, 26))

    assert rows == [
        {"symbol": "SPY", "contract": "SPY260826C00766000", "expiry": "2026-08-26", "right": "C", "strike": 766.0},
        {"symbol": "SPY", "contract": "SPY260826P00766000", "expiry": "2026-08-26", "right": "P", "strike": 766.0},
    ]


def test_refresh_references_is_read_only_and_records_capture_status(monkeypatch) -> None:
    monkeypatch.setattr("scripts.options_reference_refresh.configured_quote_provider", lambda: "tradier")
    calls = []

    def capture(event, contract, **kwargs):
        calls.append((event, contract, kwargs))
        return {"provenance": {"status": "ok"}}

    report = refresh_references(
        [{"symbol": "TSLA", "contract": "TSLA260828C00350000", "expiry": "2026-08-28", "right": "C", "strike": 350.0}],
        capture_fn=capture,
        max_workers=1,
    )

    assert report["captured_count"] == 1
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert calls[0][0:2] == ("monitor", "TSLA260828C00350000")
    assert calls[0][2]["context"]["can_submit_orders"] is False
