from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_tradingview_report_classifies_delayed_futures_context() -> None:
    from scripts.tradingview_validation_report import build_report

    report = build_report(
        status={
            "success": True,
            "cdp_connected": True,
            "chart_symbol": "CME_MINI_DL:NQ1!",
            "chart_resolution": "1",
        },
        quote={
            "success": True,
            "symbol": "CME_MINI_DL:NQ1!",
            "close": 29944.0,
            "description": "E-mini Nasdaq-100 Futures",
            "type": "futures",
        },
        ohlcv={
            "success": True,
            "bar_count": 100,
            "open": 30020.0,
            "close": 29944.0,
            "high": 30040.0,
            "low": 29920.0,
            "change": -76.0,
            "change_pct": "-0.25%",
        },
    )

    assert report["connected"] is True
    assert report["symbol"] == "CME_MINI_DL:NQ1!"
    assert report["timeframe"] == "1"
    assert report["is_delayed"] is True
    assert report["bias"] == "bearish"
    assert "delayed" in report["warnings"][0].lower()


def test_tradingview_report_flags_unusable_bridge() -> None:
    from scripts.tradingview_validation_report import build_report

    report = build_report(
        status={"success": False, "error": "CDP connection failed"},
        quote={"success": False},
        ohlcv={"success": False},
    )

    assert report["connected"] is False
    assert report["bias"] == "unknown"
    assert "TradingView bridge is not connected" in report["warnings"]


def test_tv_command_falls_back_to_appdata(monkeypatch, tmp_path) -> None:
    from scripts import tradingview_validation_report as report

    npm_dir = tmp_path / "npm"
    npm_dir.mkdir()
    tv_cmd = npm_dir / "tv.cmd"
    tv_cmd.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(report.shutil, "which", lambda name: None)

    assert report._tv_command() == str(tv_cmd)
