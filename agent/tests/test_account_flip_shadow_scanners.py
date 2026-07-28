from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _intraday_fixture(direction: str = "bull") -> pd.DataFrame:
    idx = []
    rows = []
    base = datetime(2026, 7, 1, 4, 0)
    for i in range(330):
        ts = base + timedelta(minutes=i)
        idx.append(pd.Timestamp(ts, tz="America/New_York"))
        price = 100 + (i % 20) * 0.01
        rows.append({"open": price, "high": price + 0.05, "low": price - 0.05, "close": price, "volume": 1000})
    rth_base = datetime(2026, 7, 1, 9, 30)
    for i in range(80):
        ts = rth_base + timedelta(minutes=i)
        idx.append(pd.Timestamp(ts, tz="America/New_York"))
        if direction == "bull":
            price = 100.4 + i * 0.05
            low = price - (0.35 if i == 70 else 0.04)
        else:
            price = 100.0 - i * 0.05
            low = price - 0.04
        rows.append({"open": price, "high": price + 0.05, "low": low, "close": price, "volume": 2000})
    return pd.DataFrame(rows, index=idx)


def test_premarket_ema_retest_detects_bullish_shadow_setup() -> None:
    from scripts.premarket_ema_retest_shadow_logger import compute_premarket_ema_retest

    row = compute_premarket_ema_retest("SPY", _intraday_fixture("bull"))

    assert row["status"] == "ok"
    assert row["execution_enabled"] is False if "execution_enabled" in row else True
    assert row["action"] == "watch_call_retest"
    assert row["features"]["broke_pm_high"] is True
    assert row["features"]["bull_stack_13_48_200"] is True


def test_premarket_ema_retest_tracks_previous_day_levels() -> None:
    from scripts.premarket_ema_retest_shadow_logger import compute_premarket_ema_retest

    current = _intraday_fixture("bull")
    prior_index = pd.date_range(
        "2026-06-30 09:30",
        periods=30,
        freq="1min",
        tz="America/New_York",
    )
    prior = pd.DataFrame(
        {
            "open": [99.0] * 30,
            "high": [100.75] * 30,
            "low": [98.5] * 30,
            "close": [100.0] * 30,
            "volume": [1500] * 30,
        },
        index=prior_index,
    )

    row = compute_premarket_ema_retest("SPY", pd.concat([prior, current]).sort_index())

    assert row["previous_day_date"] == "2026-06-30"
    assert row["previous_day_high"] == 100.75
    assert row["previous_day_low"] == 98.5
    assert row["features"]["broke_previous_day_high"] is True
    assert row["features"]["held_above_previous_day_high"] is True


def test_premarket_ema_retest_requires_aligned_ema_stack() -> None:
    from scripts.premarket_ema_retest_shadow_logger import compute_premarket_ema_retest

    frame = _intraday_fixture("bull")
    rth_mask = frame.index.time >= datetime.strptime("09:30", "%H:%M").time()
    frame.loc[rth_mask, "close"] = 101.05
    frame.loc[rth_mask, "open"] = 101.0
    frame.loc[rth_mask, "high"] = 101.1
    frame.loc[rth_mask, "low"] = 100.9
    prior_index = pd.date_range(
        "2026-06-30 09:30",
        periods=30,
        freq="1min",
        tz="America/New_York",
    )
    prior = pd.DataFrame(
        {
            "open": [100.0] * 30,
            "high": [100.75] * 30,
            "low": [98.5] * 30,
            "close": [100.0] * 30,
            "volume": [1500] * 30,
        },
        index=prior_index,
    )

    row = compute_premarket_ema_retest("SPY", pd.concat([prior, frame]).sort_index())

    assert row["bull_score"] >= 7
    assert row["features"]["bull_stack_13_48_200"] is False
    assert row["features"]["bear_stack_13_48_200"] is False
    assert row["action"] == "stand_aside"


def test_premarket_report_is_shadow_only(monkeypatch, tmp_path) -> None:
    from scripts import premarket_ema_retest_shadow_logger as scanner

    monkeypatch.setattr(scanner, "scan_symbol", lambda symbol, trading_day=None: {"symbol": symbol, "status": "ok", "action": "stand_aside"})
    report = scanner.build_report(["SPY"])
    scanner.append_log(report, tmp_path / "log.jsonl")
    scanner.write_report(report, tmp_path / "report.json")

    assert report["execution_mode"] == "shadow_only"
    assert report["execution_enabled"] is False
    assert json.loads((tmp_path / "log.jsonl").read_text(encoding="utf-8"))["provider"] == "premarket_ema_retest_shadow_logger"


def test_adaptive_options_bearish_playbook_selects_long_put() -> None:
    from scripts.adaptive_options_shadow_playbook import evaluate_symbol_playbook

    row = evaluate_symbol_playbook(
        "SPY",
        {
            "trend": "bearish",
            "below_vwap": True,
            "below_ema50": True,
            "bearish_orb": True,
            "credit_to_risk": 0.16,
            "liquidity_ok": True,
            "flip_recent_direction": "bearish",
            "flip_recent_win_rate": 1.0,
        },
    )

    assert row["execution_enabled"] is False
    assert row["selected_playbook"] == "long_put"
    assert row["action"] == "shadow_watch_bearish_long_put"
    assert "bearish tape favors directional debit exposure" in row["explanation"]["primary_reason"]


def test_adaptive_options_bearish_playbook_stands_aside_when_credit_is_thin() -> None:
    from scripts.adaptive_options_shadow_playbook import evaluate_symbol_playbook

    row = evaluate_symbol_playbook(
        "SPY",
        {
            "trend": "bearish",
            "below_vwap": True,
            "below_ema50": True,
            "bearish_orb": True,
            "credit_to_risk": 0.16,
            "liquidity_ok": True,
            "flip_recent_direction": "bullish",
            "flip_recent_win_rate": 0.4,
        },
    )

    assert row["selected_playbook"] == "none"
    assert row["action"] == "stand_aside"
    assert "Flip evidence does not confirm bearish direction" in row["explanation"]["blockers"]


def test_adaptive_options_builds_context_from_local_logs(tmp_path, monkeypatch) -> None:
    from scripts import adaptive_options_shadow_playbook as playbook

    vibe_home = tmp_path / "home"
    report_dir = vibe_home / "reports"
    report_dir.mkdir(parents=True)
    (vibe_home / "flip-trades.json").write_text(
        json.dumps(
            [
                {"symbol": "SPY", "status": "closed", "strategy": "bear_trend", "pnl": 100},
                {"symbol": "SPY", "status": "closed", "strategy": "bear_trend", "pnl": 200},
            ]
        ),
        encoding="utf-8",
    )
    (report_dir / "options-liquidity-feasibility.json").write_text(
        json.dumps(
            {
                "results": [
                    {"symbol": "SPY", "flip_shadow_eligible": True, "criteria": {"spread_ok": True}, "score": 4}
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "market_force_score_log.jsonl").write_text(
        json.dumps({"date": "2026-07-02", "classification": "bearish_lean"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(playbook, "VIBE_HOME", vibe_home)
    monkeypatch.setattr(playbook, "MARKET_FORCE_LOG", tmp_path / "market_force_score_log.jsonl")

    contexts = playbook.build_contexts(["SPY"])

    assert contexts["SPY"]["trend"] == "bearish"
    assert contexts["SPY"]["liquidity_ok"] is True
    assert contexts["SPY"]["flip_recent_direction"] == "bearish"
    assert contexts["SPY"]["flip_recent_win_rate"] == 1.0


def test_adaptive_options_labels_every_market_condition() -> None:
    from scripts.adaptive_options_shadow_playbook import classify_market_conditions

    conditions = classify_market_conditions(
        {
            "trend": "bearish",
            "opening_range_state": "below_opening_range",
            "volatility_regime": "vol_expansion",
            "liquidity_ok": True,
            "credit_to_risk": 0.16,
            "flip_recent_direction": "bearish",
            "flip_recent_win_rate": 1.0,
        }
    )

    labels = {item["label"] for item in conditions}
    assert labels == {
        "bearish_trend",
        "bearish_opening_range",
        "volatility_expansion",
        "liquid_options",
        "thin_credit",
        "flip_bearish_confirmed",
    }
    assert all(item["evidence"] for item in conditions)


def test_adaptive_options_labels_expected_move_context_without_changing_playbook() -> None:
    from scripts.adaptive_options_shadow_playbook import evaluate_symbol_playbook

    row = evaluate_symbol_playbook(
        "SPY",
        {
            "trend": "mixed",
            "opening_range_state": "inside_opening_range",
            "volatility_regime": "balanced",
            "liquidity_ok": True,
            "opening_range_fraction": 0.18,
            "opening_range_bucket": "compressed_under_20pct",
            "expected_move_consumed_fraction": 0.42,
            "breakout_overshoot_fraction": 0.0,
            "options_heat_state": "near_major_heat_zone",
            "options_heat_labels": ["spot_inside_heat_band", "put_oi_pressure"],
        },
    )

    labels = set(row["condition_summary"]["labels"])
    assert "expected_move_compressed_under_20pct" in labels
    assert "expected_move_under_half_consumed" in labels
    assert "options_heat_near_major_heat_zone" in labels
    assert "spot_inside_options_heat_band" in labels
    assert "put_oi_pressure" in labels
    assert row["selected_playbook"] == "none"
    assert row["action"] == "stand_aside"
    assert row["inputs"]["expected_move_consumed_fraction"] == 0.42
    assert row["inputs"]["options_heat_state"] == "near_major_heat_zone"


def test_adaptive_options_report_contains_condition_summary_and_explained_stand_aside() -> None:
    from scripts.adaptive_options_shadow_playbook import build_report

    report = build_report(
        symbols=["SPY"],
        contexts={
            "SPY": {
                "trend": "mixed",
                "opening_range_state": "inside_opening_range",
                "volatility_regime": "normal",
                "liquidity_ok": True,
                "credit_to_risk": 0.0,
            }
        },
    )

    row = report["rows"][0]
    assert row["selected_playbook"] == "none"
    assert row["action"] == "stand_aside"
    assert row["market_conditions"]
    assert row["condition_summary"]["primary_regime"] == "mixed_chop"
    assert row["explanation"]["blockers"]
    assert "Market regime is unclear or mixed" in row["explanation"]["blockers"]


def test_adaptive_options_market_closed_overrides_playbook_selection() -> None:
    from scripts.adaptive_options_shadow_playbook import evaluate_symbol_playbook

    row = evaluate_symbol_playbook(
        "SPY",
        {
            "trend": "bearish",
            "opening_range_state": "market_closed",
            "liquidity_ok": True,
            "below_vwap": True,
            "below_ema50": True,
            "bearish_orb": True,
            "flip_recent_direction": "bearish",
            "flip_recent_win_rate": 1.0,
        },
    )

    assert row["selected_playbook"] == "none"
    assert row["action"] == "stand_aside"
    assert "Market is closed" in row["explanation"]["blockers"]


def test_prediction_microstructure_scores_short_horizon_flow(monkeypatch) -> None:
    from scripts import prediction_market_microstructure_scanner as scanner

    monkeypatch.setattr(
        scanner,
        "scan_limitless",
        lambda top=10, min_usd=100: {
            "markets_scanned": 1,
            "top_markets": [
                {
                    "slug": "btc-up-or-down-15m",
                    "title": "BTC Up or Down - 15 Min",
                    "volume": 1000,
                    "yes_price": 0.55,
                    "no_price": 0.45,
                    "yes_spread": 0.04,
                    "no_spread": 0.04,
                    "url": "https://limitless.exchange/markets/btc-up-or-down-15m",
                }
            ],
            "whale_events": [
                {"market_slug": "btc-up-or-down-15m", "outcome": "YES", "usd": 600, "wallet": "0x1"},
                {"market_slug": "btc-up-or-down-15m", "outcome": "NO", "usd": 100, "wallet": "0x2"},
            ],
        },
    )

    report = scanner.build_microstructure_report()

    assert report["execution_enabled"] is False
    assert report["candidate_count"] == 1
    assert report["top_candidates"][0]["microstructure_score"] >= 5
    assert report["top_candidates"][0]["directional_hint"] == "yes_flow"
