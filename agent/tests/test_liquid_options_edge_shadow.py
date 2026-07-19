from __future__ import annotations

from datetime import date
from pathlib import Path

from scripts.liquid_options_edge_shadow import build_report, select_contract


def _candidate(symbol: str, right: str, delta: float, spread: float) -> dict:
    return {
        "option_symbol": symbol,
        "strike": 500.0,
        "right": right,
        "delta": delta,
        "spread_pct": spread,
        "quote_age_seconds": 2.0,
        "expected_move_room": 1.0,
        "premium_expansion_pct": 10.0,
    }


def test_select_contract_uses_direction_and_rejects_bad_spread() -> None:
    rows = [
        _candidate("QQQ260731C00500000", "CALL", 0.50, 25.0),
        _candidate("QQQ260731C00501000", "CALL", 0.52, 3.0),
        _candidate("QQQ260731P00500000", "PUT", -0.50, 2.0),
    ]
    assert select_contract(rows, "long")["option_symbol"].endswith("C00501000")
    assert select_contract(rows, "short")["option_symbol"].endswith("P00500000")


def test_report_is_shadow_only_and_deduplicates(tmp_path: Path) -> None:
    log_path = tmp_path / "signals.jsonl"

    def signal_fetcher(candidate, trading_day):
        return {
            "symbol": candidate["symbol"],
            "strategy": candidate["strategy"],
            "direction": "long",
            "signal_time": f"{trading_day.isoformat()}T10:00:00-04:00",
            "evidence_status": candidate["evidence_status"],
        }

    def contract_fetcher(symbol, direction):
        return [_candidate(f"{symbol}260731C00500000", "CALL", 0.50, 2.0)]

    first = build_report(
        date(2026, 7, 20),
        signal_fetcher=signal_fetcher,
        contract_fetcher=contract_fetcher,
        capture_quotes=False,
        log_path=log_path,
    )
    second = build_report(
        date(2026, 7, 20),
        signal_fetcher=signal_fetcher,
        contract_fetcher=contract_fetcher,
        capture_quotes=False,
        log_path=log_path,
    )
    assert len(first["signals"]) == 2
    assert second["signals"] == []
    assert first["execution_enabled"] is False
    assert first["can_submit_orders"] is False
