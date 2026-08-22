from __future__ import annotations

from datetime import date

import pandas as pd

from scripts import event_gap_continuation_shadow as scanner


def _frame(rows: list[tuple[float, float, float, float, float]], start: str = "2026-08-19 09:30") -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["open", "high", "low", "close", "volume"],
        index=pd.date_range(start, periods=len(rows), freq="5min", tz="America/New_York"),
    )


def test_event_gap_candidate_requires_completed_or_break_volume_and_relative_strength(monkeypatch) -> None:
    monkeypatch.setattr(scanner, "MIN_DIRECTIONAL_RELATIVE_PCT", 0.02)
    bars = _frame(
        [
            (110, 116, 109, 115, 100),
            (115, 119, 113, 118, 110),
            (118, 120, 116, 119, 100),
            (119, 126, 118, 125, 180),
        ]
    )
    benchmark = _frame(
        [(100, 101, 99, 100, 100), (100, 101, 99, 100, 100), (100, 101, 99, 100, 100), (100, 101, 99, 101, 100)]
    )
    result = scanner.evaluate_event_gap(bars, previous_close=100, benchmark_bars=benchmark, symbol="MRNA")
    assert result["eligible"] is True
    assert result["state"] == "shadow_candidate"
    assert result["entry_time"].endswith("09:45:00-04:00")
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False


def test_event_gap_rejects_breakout_without_volume() -> None:
    bars = _frame(
        [(110, 116, 109, 115, 100), (115, 119, 113, 118, 100), (118, 120, 116, 119, 100), (119, 126, 118, 125, 80)]
    )
    benchmark = _frame([(100, 101, 99, 100, 100)] * 4)
    result = scanner.evaluate_event_gap(bars, previous_close=100, benchmark_bars=benchmark, symbol="MRNA")
    assert result["eligible"] is False
    assert result["state"] == "breakout_without_confluence"
    assert result["breakout_observations"][0]["volume_ratio"] == 0.8


def test_event_gap_uses_prior_same_slot_volume_instead_of_event_opening_volume() -> None:
    bars = _frame(
        [(110, 116, 109, 115, 100), (115, 119, 113, 118, 100), (118, 120, 116, 119, 100), (119, 126, 118, 125, 80)]
    )
    bars.attrs["same_slot_volume_baseline"] = {"09:45": 50.0}
    benchmark = _frame([(100, 101, 99, 100, 100)] * 4)
    result = scanner.evaluate_event_gap(bars, previous_close=100, benchmark_bars=benchmark, symbol="MRNA")
    assert result["eligible"] is True
    assert result["volume_ratio"] == 1.6


def test_event_gap_outcome_uses_only_bars_after_entry() -> None:
    bars = _frame(
        [
            (110, 116, 109, 115, 100),
            (115, 119, 113, 118, 100),
            (118, 120, 116, 119, 100),
            (119, 126, 118, 125, 180),
            (125, 142, 124, 140, 160),
        ]
    )
    benchmark = _frame([(100, 101, 99, 100, 100)] * 5)
    result = scanner.evaluate_event_gap(bars, previous_close=100, benchmark_bars=benchmark, symbol="MRNA")
    assert result["entry_time"].endswith("09:45:00-04:00")
    assert result["post_entry_outcome"]["status"] == "target"
    assert result["post_entry_outcome"]["time"].endswith("09:50:00-04:00")


def test_dynamic_symbols_uses_social_for_discovery_not_authority(tmp_path) -> None:
    social = tmp_path / "social.jsonl"
    deep = tmp_path / "deep.jsonl"
    social.write_text(
        '{"date":"2026-08-19","symbols":[{"symbol":"MRNA","rank":2}]}\n', encoding="utf-8"
    )
    deep.write_text(
        '{"date":"2026-08-19","top_candidates":[{"symbol":"NVDA","deep_score":9}]}\n', encoding="utf-8"
    )
    radar = tmp_path / "radar.json"
    assert scanner.dynamic_symbols(as_of=date(2026, 8, 19), social_path=social, deep_path=deep, radar_path=radar) == ["MRNA", "NVDA"]


def test_dynamic_discovery_carries_same_session_provenance(tmp_path) -> None:
    social = tmp_path / "social.jsonl"
    deep = tmp_path / "deep.jsonl"
    social.write_text(
        '{"date":"2026-08-19","symbols":[{"symbol":"MRNA","rank":2}]}\n',
        encoding="utf-8",
    )
    deep.write_text(
        '{"date":"2026-08-19","top_candidates":[{"symbol":"MRNA","deep_score":9}]}\n',
        encoding="utf-8",
    )

    rows = scanner.dynamic_symbol_discovery(
        as_of=date(2026, 8, 19),
        social_path=social,
        deep_path=deep,
        radar_path=tmp_path / "radar.json",
    )

    assert rows == [
        {
            "symbol": "MRNA",
            "score": 98.0,
            "sources": ["deep_liquid_universe", "social_trending"],
            "as_of": "2026-08-19",
            "authority": "discovery_only_no_directional_or_execution_authority",
        }
    ]


def test_dynamic_symbols_rejects_non_equity_social_tickers(tmp_path) -> None:
    social = tmp_path / "social.jsonl"
    social.write_text(
        '{"date":"2026-08-19","symbols":[{"symbol":"BTC.X","rank":1},{"symbol":"MRNA","rank":2}]}\n',
        encoding="utf-8",
    )
    assert scanner.dynamic_symbols(
        as_of=date(2026, 8, 19), social_path=social,
        deep_path=tmp_path / "deep.jsonl", radar_path=tmp_path / "radar.json",
    ) == ["MRNA"]


def test_dynamic_symbols_prioritizes_current_premarket_event_gap(tmp_path) -> None:
    radar = tmp_path / "radar.json"
    radar.write_text(
        '{"date":"2026-08-19","session_status":"premarket_scan_window","observations":['
        '{"symbol":"MRNA","lane":"event_gap","priority":"high","score":10},'
        '{"symbol":"AAPL","lane":"tactical_gap","priority":"high","score":10}]}'
        , encoding="utf-8"
    )
    symbols = scanner.dynamic_symbols(
        as_of=date(2026, 8, 19), social_path=tmp_path / "social.jsonl",
        deep_path=tmp_path / "deep.jsonl", radar_path=radar,
    )
    assert symbols == ["MRNA"]


def test_report_is_shadow_only(monkeypatch) -> None:
    bars = _frame([(100, 101, 99, 100, 100)] * 4)
    monkeypatch.setattr(scanner, "fetch_intraday", lambda _symbol, _now: (bars, 100.0))
    report = scanner.build_report(["MRNA"])
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
    assert report["social_can_create_trade"] is False


def test_report_attaches_discovery_without_granting_authority(monkeypatch) -> None:
    bars = _frame([(100, 101, 99, 100, 100)] * 4)
    monkeypatch.setattr(scanner, "fetch_intraday", lambda _symbol, _now: (bars, 100.0))
    provenance = [{
        "symbol": "MRNA",
        "score": 99.0,
        "sources": ["social_trending"],
        "as_of": "2026-08-19",
        "authority": "discovery_only_no_directional_or_execution_authority",
    }]

    report = scanner.build_report(
        ["MRNA"],
        now_et=pd.Timestamp("2026-08-19 10:00", tz="America/New_York").to_pydatetime(),
        discovery=provenance,
    )

    assert report["observations"][0]["discovery_provenance"] == provenance[0]
    assert report["execution_enabled"] is False
    assert report["can_submit_orders"] is False
