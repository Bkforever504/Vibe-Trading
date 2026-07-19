from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import opening_range_breadth_scanner as orb
from scripts import relative_volume_scanner as rv
from scripts import sec_insider_buying_scanner as sec


def test_relative_volume_flags_unusual_volume() -> None:
    idx = pd.date_range("2026-05-01", periods=22, freq="B")
    df = pd.DataFrame(
        {
            "open": [100.0] * 22,
            "high": [101.0] * 22,
            "low": [99.0] * 22,
            "close": [100.0] * 21 + [103.0],
            "volume": [1_000_000] * 21 + [3_500_000],
        },
        index=idx,
    )

    result = rv.compute_relative_volume("QQQ", df)

    assert result["status"] == "ok"
    assert result["context_signal"] is True
    assert result["relative_volume"] == 3.5
    assert result["intensity"] == "extreme"


def test_relative_volume_build_report_is_context_only(monkeypatch) -> None:
    df = pd.DataFrame(
        {
            "open": [100.0] * 22,
            "high": [101.0] * 22,
            "low": [99.0] * 22,
            "close": [100.0] * 22,
            "volume": [1_000_000] * 22,
        },
        index=pd.date_range("2026-05-01", periods=22, freq="B"),
    )
    monkeypatch.setattr(rv, "fetch_ohlcv", lambda symbol, lookback_days=90: df)
    monkeypatch.setattr(rv, "data_source", lambda: "mock")

    report = rv.build_report(symbols=["SPY"])

    assert report["mode"] == "context_only"
    assert report["execution_enabled"] is False
    assert report["source"] == "mock"


def test_sec_parse_form4_acquisitions() -> None:
    xml = """
    <ownershipDocument xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
      <issuer><issuerTradingSymbol>ABC</issuerTradingSymbol></issuer>
      <reportingOwner><reportingOwnerId><rptOwnerName>Jane Insider</rptOwnerName></reportingOwnerId></reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <securityTitle><value>Common Stock</value></securityTitle>
          <transactionDate><value>2026-06-29</value></transactionDate>
          <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
          <transactionAmounts>
            <transactionShares><value>1000</value></transactionShares>
            <transactionPricePerShare><value>12.5</value></transactionPricePerShare>
            <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
          </transactionAmounts>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>
    """

    result = sec.parse_form4_acquisitions(xml)

    assert result["issuer_symbol"] == "ABC"
    assert result["owner_name"] == "Jane Insider"
    assert result["acquisition_count"] == 1
    assert result["total_estimated_value"] == 12_500


def test_sec_build_report_uses_cik_map_and_stays_context_only(monkeypatch) -> None:
    monkeypatch.setattr(sec, "fetch_ticker_cik_map", lambda: {"ABC": "0000001234"})
    monkeypatch.setattr(
        sec,
        "scan_symbol",
        lambda symbol, cik, lookback_days=14: {
            "symbol": symbol,
            "status": "ok",
            "cik": cik,
            "buy_event_count": 1,
            "total_estimated_value": 1000,
            "context_signal": True,
            "events": [],
        },
    )

    report = sec.build_report(symbols=["ABC"], lookback_days=7)

    assert report["provider"] == "sec_insider_buying_scanner"
    assert report["execution_enabled"] is False
    assert report["signal_count"] == 1


def test_opening_range_detects_bearish_breakdown() -> None:
    idx = pd.to_datetime(
        [
            "2026-06-30 09:30",
            "2026-06-30 09:31",
            "2026-06-30 09:32",
            "2026-06-30 09:33",
            "2026-06-30 09:34",
            "2026-06-30 09:35",
            "2026-06-30 09:40",
        ]
    ).tz_localize("America/New_York")
    df = pd.DataFrame(
        {
            "open": [100, 100.5, 100.2, 100.1, 99.9, 99.8, 98.5],
            "high": [101, 100.8, 100.7, 100.4, 100.2, 100.0, 98.8],
            "low": [99.5, 99.7, 99.8, 99.6, 99.4, 99.0, 98.0],
            "close": [100.2, 100.1, 100.0, 99.8, 99.7, 99.2, 98.2],
            "volume": [1000] * 7,
        },
        index=idx,
    )

    result = orb.compute_opening_range_signal("SPY", df)

    assert result["status"] == "ok"
    assert result["broke_down"] is True
    assert result["state"] == "below_opening_range"


def test_opening_range_aggregate_breadth() -> None:
    agg = orb.aggregate_breadth(
        [
            {"status": "ok", "state": "above_opening_range"},
            {"status": "ok", "state": "above_opening_range"},
            {"status": "ok", "state": "inside_opening_range"},
            {"status": "ok", "state": "below_opening_range"},
        ]
    )

    assert agg["ok_count"] == 4
    assert agg["breadth_score"] == 0.25
    assert agg["bias"] == "mixed"


def test_opening_range_prints_market_closed_without_aggregate(capsys) -> None:
    report = orb.build_report(symbols=["SPY"], trading_day=date(2026, 7, 5))

    orb.print_report(report)

    output = capsys.readouterr().out
    assert report["status"] == "market_closed"
    assert "status=market_closed" in output
    assert "No orders placed." in output


def test_append_log_writes_jsonl(tmp_path) -> None:
    path = tmp_path / "scanner.jsonl"
    entry = {"date": "2026-06-30", "provider": "relative_volume_scanner"}

    rv.append_log(entry, path)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows == [entry]
