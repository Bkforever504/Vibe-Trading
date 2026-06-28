from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.trading_dashboard import (
    bot_status_context,
    daily_shadow_context,
    daily_shadow_panel,
    momentum_shadow_context,
    momentum_shadow_panel,
    option_group_summaries,
    polymarket_wallet_context,
    polymarket_wallet_panel,
    tradingview_context,
    tradingview_panel,
)


def test_option_group_summary_calculates_risk_distances_and_dte() -> None:
    state = {
        "trades": [
            {
                "label": "IWM put spread",
                "status": "open",
                "strategy": "put_spread",
                "underlying": "IWM",
                "legs": ["IWM260717P00200000", "IWM260717P00197000"],
                "net_credit": 0.54,
                "qty": 1,
                "profit_close_pct": 0.50,
                "stop_loss_pct": -2.0,
                "expiry": "2026-07-17",
            }
        ]
    }
    positions = [
        {"symbol": "IWM260717P00200000", "asset_class": "us_option", "unrealized_pl": "-20.00"},
        {"symbol": "IWM260717P00197000", "asset_class": "us_option", "unrealized_pl": "5.00"},
    ]

    rows = option_group_summaries(state, positions, today=date(2026, 7, 1))

    assert rows == [
        {
            "label": "IWM put spread",
            "strategy": "put_spread",
            "underlying": "IWM",
            "status": "open",
            "exit_status": "open",
            "legs_open": 2,
            "legs_expected": 2,
            "credit_received": 54.0,
            "pnl": -15.0,
            "pnl_pct": -27.77777777777778,
            "profit_target": 27.0,
            "profit_target_distance": 42.0,
            "stop_loss": -108.0,
            "stop_loss_distance": 93.0,
            "days_to_expiry": 16,
        }
    ]


def test_option_group_summary_flags_missing_legs_for_manual_review() -> None:
    state = {
        "trades": [
            {
                "label": "Recovered MLEG [IWM]",
                "status": "open",
                "legs": ["IWM260717P00200000", "IWM260717P00197000"],
                "net_credit": 0.54,
                "qty": 1,
                "expiry": "2026-07-17",
            }
        ]
    }
    positions = [
        {"symbol": "IWM260717P00200000", "asset_class": "us_option", "unrealized_pl": "-20.00"},
    ]

    rows = option_group_summaries(state, positions, today=date(2026, 7, 1))

    assert rows[0]["exit_status"] == "manual review: missing legs"
    assert rows[0]["legs_open"] == 1
    assert rows[0]["legs_expected"] == 2


def test_tradingview_context_summarizes_delayed_bearish_report(tmp_path) -> None:
    report = tmp_path / "tradingview-validation.json"
    report.write_text(
        """
        {
          "connected": true,
          "symbol": "CME_MINI_DL:NQ1!",
          "timeframe": "1",
          "description": "E-mini Nasdaq-100 Futures",
          "is_delayed": true,
          "bias": "bearish",
          "quote": {"last": 29984.75},
          "ohlcv_summary": {"change": -82.75, "change_pct": "-0.28%", "bar_count": 100},
          "warnings": ["TradingView symbol is delayed; use for validation only, not execution"]
        }
        """,
        encoding="utf-8",
    )

    context = tradingview_context(report)

    assert context["available"] is True
    assert context["symbol"] == "CME_MINI_DL:NQ1!"
    assert context["bias"] == "bearish"
    assert context["last"] == 29984.75
    assert context["is_delayed"] is True


def test_tradingview_panel_renders_warning_and_symbol() -> None:
    html = tradingview_panel({
        "available": True,
        "connected": True,
        "symbol": "CME_MINI_DL:NQ1!",
        "timeframe": "1",
        "description": "E-mini Nasdaq-100 Futures",
        "is_delayed": True,
        "bias": "bearish",
        "last": 29984.75,
        "change": -82.75,
        "change_pct": "-0.28%",
        "bar_count": 100,
        "warnings": ["TradingView symbol is delayed; use for validation only, not execution"],
    })

    assert "TradingView Futures Context" in html
    assert "CME_MINI_DL:NQ1!" in html
    assert "bearish" in html
    assert "validation only" in html


def test_polymarket_wallet_panel_renders_read_only_wallet_report(tmp_path) -> None:
    report = tmp_path / "polymarket-wallet-tracker.json"
    report.write_text(
        """
        {
          "mode": "read_only",
          "execution_enabled": false,
          "wallet_count": 1,
          "wallets": [
            {
              "handle": "0xabc",
              "trades": 120,
              "win_rate": 0.62,
              "profit_factor": 1.8,
              "realized_pnl": 2400,
              "green_months": 6,
              "confidence": 9,
              "status": "paper_watch",
              "risk_flags": []
            }
          ],
          "warnings": ["Read-only: public Polymarket endpoints only."]
        }
        """,
        encoding="utf-8",
    )

    context = polymarket_wallet_context(report)
    html = polymarket_wallet_panel(context)

    assert context["wallet_count"] == 1
    assert "Polymarket Wallet Tracker" in html
    assert "0xabc" in html
    assert "execution disabled" in html
    assert "public Polymarket endpoints only" in html


def test_momentum_shadow_context_calculates_forward_return_from_log(tmp_path) -> None:
    log = tmp_path / "momentum_shadow_log.jsonl"
    log.write_text(
        """
{"date":"2026-06-22","holdings":["XLK","IWM"],"weights":{"XLK":0.5,"IWM":0.5},"close_prices":{"XLK":100.0,"IWM":200.0},"in_cash":false,"lookback_months":12,"top_n":2,"universe":["SPY","QQQ","XLK","IWM"]}
{"date":"2026-06-29","holdings":["QQQ","SPY"],"weights":{"QQQ":0.5,"SPY":0.5},"close_prices":{"XLK":110.0,"IWM":190.0,"QQQ":500.0,"SPY":600.0},"in_cash":false,"lookback_months":12,"top_n":2,"universe":["SPY","QQQ","XLK","IWM"],"ranked":[["QQQ",0.25],["SPY",0.2]]}
        """.strip(),
        encoding="utf-8",
    )

    context = momentum_shadow_context(log)

    assert context["available"] is True
    assert context["latest"]["holdings"] == ["QQQ", "SPY"]
    assert context["previous"]["holdings"] == ["XLK", "IWM"]
    assert context["last_period_return_pct"] == 2.5
    assert context["log_count"] == 2
    assert context["execution_enabled"] is False


def test_momentum_shadow_panel_renders_holdings_and_return() -> None:
    html = momentum_shadow_panel({
        "available": True,
        "execution_enabled": False,
        "log_count": 2,
        "latest": {
            "date": "2026-06-29",
            "holdings": ["QQQ", "SPY"],
            "weights": {"QQQ": 0.5, "SPY": 0.5},
            "in_cash": False,
            "lookback_months": 12,
            "top_n": 2,
            "universe": ["SPY", "QQQ", "XLK", "IWM"],
            "ranked": [["QQQ", 0.25], ["SPY", 0.2]],
        },
        "previous": {"date": "2026-06-22", "holdings": ["XLK", "IWM"]},
        "last_period_return_pct": 2.5,
        "warnings": ["Shadow-only. No Alpaca orders are wired."],
    })

    assert "Momentum Rotation Shadow" in html
    assert "QQQ (50%)" in html
    assert "SPY (50%)" in html
    assert "+2.50%" in html
    assert "No Alpaca orders" in html


def test_daily_shadow_context_reads_latest_signal(tmp_path) -> None:
    log = tmp_path / "rsi2_shadow_log.jsonl"
    log.write_text(
        """
{"date":"2026-06-26","symbol":"QQQ","execution_mode":"shadow_only","primary_setup":{"name":"rsi2_prior_high_source","action":"hold_long","confidence":8.7},"comparison_setup":{"name":"rsi2_sma_exit_derived","action":"flat","confidence":9.1},"features":{"close":706.52,"rsi2":36.8759},"paper_rules":{"minimum_forward_days":30,"minimum_signals_before_review":10,"live_execution_allowed":false}}
        """.strip(),
        encoding="utf-8",
    )

    context = daily_shadow_context(log, "RSI-2 QQQ Shadow")

    assert context["available"] is True
    assert context["title"] == "RSI-2 QQQ Shadow"
    assert context["latest"]["symbol"] == "QQQ"
    assert context["log_count"] == 1
    assert context["entry_count"] == 0
    assert context["execution_enabled"] is False


def test_daily_shadow_panel_renders_gate_status() -> None:
    html = daily_shadow_panel({
        "available": True,
        "title": "KAMA QQQ Shadow",
        "latest": {
            "date": "2026-06-26",
            "symbol": "QQQ",
            "primary_setup": {"name": "kama_trend_fast3_slow20_slope3", "action": "flat", "confidence": 8.2},
            "comparison_setup": {"name": "kama_trend_fast2_slow30_slope5", "action": "flat", "confidence": 8.0},
            "features": {"close": 706.52, "kama": 710.1},
        },
        "log_count": 1,
        "entry_count": 0,
        "min_days": 30,
        "min_entries": 10,
        "execution_enabled": False,
        "warnings": ["Shadow-only. No broker orders are wired."],
    })

    assert "KAMA QQQ Shadow" in html
    assert "kama_trend_fast3_slow20_slope3" in html
    assert "NOT READY" in html
    assert "No broker orders" in html


def test_bot_status_includes_momentum_rotation_shadow() -> None:
    context = bot_status_context()

    names = [bot["name"] for bot in context["bots"]]

    assert "Momentum Rotation Shadow" in names
    momentum = next(bot for bot in context["bots"] if bot["name"] == "Momentum Rotation Shadow")
    assert momentum["mode"] == "shadow"
    assert momentum["live_enabled"] is False
    assert momentum["execution"] == "weekly-shadow-only"
