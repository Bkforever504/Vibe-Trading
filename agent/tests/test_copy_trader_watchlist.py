from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_copy_trader_score_rewards_verified_sample_and_controls_leverage() -> None:
    from strategies.copy_trader_watchlist import TraderProfile, score_trader

    profile = TraderProfile(
        handle="0xsteady",
        platform="polymarket",
        source="public_wallet",
        trades=120,
        win_rate=0.62,
        realized_pnl=8400.0,
        max_drawdown_pct=0.11,
        avg_leverage=1.0,
        profit_factor=1.85,
        verified=True,
    )

    scored = score_trader(profile)

    assert scored.confidence >= 8
    assert scored.status == "paper_watch"
    assert "verified history" in scored.reason
    assert scored.risk_flags == []


def test_copy_trader_score_blocks_high_leverage_and_tiny_sample() -> None:
    from strategies.copy_trader_watchlist import TraderProfile, score_trader

    profile = TraderProfile(
        handle="moonshot",
        platform="invo",
        source="social_screenshot",
        trades=9,
        win_rate=0.92,
        realized_pnl=12000.0,
        max_drawdown_pct=0.48,
        avg_leverage=18.0,
        profit_factor=1.2,
        verified=False,
    )

    scored = score_trader(profile)

    assert scored.confidence < 5
    assert scored.status == "reject"
    assert "sample too small" in scored.risk_flags
    assert "high leverage" in scored.risk_flags
    assert "unverified social data" in scored.risk_flags


def test_copy_watchlist_report_is_paper_only_and_serializable(tmp_path) -> None:
    from strategies.copy_trader_watchlist import TraderProfile, build_report, write_report

    report = build_report(
        [
            TraderProfile(
                handle="0xsteady",
                platform="polymarket",
                source="public_wallet",
                trades=120,
                win_rate=0.62,
                realized_pnl=8400.0,
                max_drawdown_pct=0.11,
                avg_leverage=1.0,
                profit_factor=1.85,
                verified=True,
            )
        ]
    )
    out = tmp_path / "copy-trader-watchlist.json"

    write_report(report, out)
    saved = json.loads(out.read_text(encoding="utf-8"))

    assert saved["mode"] == "paper_only"
    assert saved["execution_enabled"] is False
    assert saved["watched_traders"][0]["handle"] == "0xsteady"
    assert saved["watched_traders"][0]["confidence"] >= 8


def test_copy_watchlist_loads_profiles_from_json(tmp_path) -> None:
    from strategies.copy_trader_watchlist import load_profiles

    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            [
                {
                    "handle": "0xsteady",
                    "platform": "polymarket",
                    "source": "public_wallet",
                    "trades": 120,
                    "win_rate": 0.62,
                    "realized_pnl": 8400,
                    "max_drawdown_pct": 0.11,
                    "avg_leverage": 1,
                    "profit_factor": 1.85,
                    "verified": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    profiles = load_profiles(path)

    assert profiles[0].handle == "0xsteady"
    assert profiles[0].platform == "polymarket"


def test_copy_watchlist_loads_powershell_utf8_bom_json(tmp_path) -> None:
    from strategies.copy_trader_watchlist import load_profiles

    path = tmp_path / "profiles.json"
    path.write_text(
        '\ufeff[{"handle":"0xsteady","platform":"polymarket","source":"public_wallet","trades":120}]',
        encoding="utf-8",
    )

    profiles = load_profiles(path)

    assert profiles[0].handle == "0xsteady"


def test_crypto_wallet_profile_gets_source_and_category_context() -> None:
    from strategies.copy_trader_watchlist import TraderProfile, score_trader

    profile = TraderProfile(
        handle="0xwhale",
        platform="solana",
        source="public_wallet",
        trades=180,
        win_rate=0.58,
        realized_pnl=52_000,
        max_drawdown_pct=0.18,
        avg_leverage=1,
        profit_factor=1.72,
        verified=True,
        category="crypto_wallet",
    )

    scored = score_trader(profile)

    assert scored.status == "paper_watch"
    assert scored.category == "crypto_wallet"
    assert "public wallet history" in scored.reason


def test_kalshi_weather_profile_scores_only_as_paper_watch_when_verified() -> None:
    from strategies.copy_trader_watchlist import TraderProfile, score_trader

    profile = TraderProfile(
        handle="weather_sharp",
        platform="kalshi",
        source="exported_history",
        trades=95,
        win_rate=0.57,
        realized_pnl=1300,
        max_drawdown_pct=0.08,
        avg_leverage=1,
        profit_factor=1.61,
        verified=True,
        category="weather",
    )

    scored = score_trader(profile)

    assert scored.status == "paper_watch"
    assert scored.category == "weather"
    assert scored.confidence >= 8


def test_copy_signal_simulation_caps_size_and_blocks_stale_prices() -> None:
    from strategies.copy_trader_watchlist import CopySignal, TraderProfile, simulate_copy_signal

    profile = TraderProfile(
        handle="0xsteady",
        platform="polymarket",
        source="public_wallet",
        trades=120,
        win_rate=0.62,
        realized_pnl=8400.0,
        max_drawdown_pct=0.11,
        avg_leverage=1.0,
        profit_factor=1.85,
        verified=True,
    )
    signal = CopySignal(
        trader="0xsteady",
        platform="polymarket",
        symbol="KXWEATHER-NYC-RAIN",
        side="YES",
        leader_price=0.42,
        current_price=0.44,
        leader_notional=5000,
        observed_at="2026-06-25T01:00:00Z",
    )

    paper = simulate_copy_signal(signal, profile, account_size=5000)

    assert paper["action"] == "paper_copy"
    assert paper["notional"] == 50.0
    assert paper["risk_pct"] == 0.01
    assert paper["kelly_fraction"] > 0
    assert paper["stale_price"] is False

    stale = simulate_copy_signal(
        CopySignal(
            trader="0xsteady",
            platform="polymarket",
            symbol="KXWEATHER-NYC-RAIN",
            side="YES",
            leader_price=0.42,
            current_price=0.47,
            leader_notional=5000,
            observed_at="2026-06-25T01:00:00Z",
        ),
        profile,
        account_size=5000,
    )

    assert stale["action"] == "skip"
    assert stale["stale_price"] is True
    assert stale["risk_pct"] == 0.0


def test_copy_watchlist_report_includes_paper_signals() -> None:
    from strategies.copy_trader_watchlist import CopySignal, TraderProfile, build_report

    report = build_report(
        [
            TraderProfile(
                handle="0xsteady",
                platform="polymarket",
                source="public_wallet",
                trades=120,
                win_rate=0.62,
                realized_pnl=8400.0,
                max_drawdown_pct=0.11,
                avg_leverage=1.0,
                profit_factor=1.85,
                verified=True,
            )
        ],
        signals=[
            CopySignal(
                trader="0xsteady",
                platform="polymarket",
                symbol="KXWEATHER-NYC-RAIN",
                side="YES",
                leader_price=0.42,
                current_price=0.44,
                leader_notional=5000,
                observed_at="2026-06-25T01:00:00Z",
            )
        ],
    )

    assert report["paper_signals"][0]["action"] == "paper_copy"
    assert report["paper_signal_count"] == 1


def test_copy_watchlist_report_explains_rejected_traders() -> None:
    from strategies.copy_trader_watchlist import TraderProfile, build_report

    report = build_report(
        [
            TraderProfile(
                handle="viral_clip_trader",
                platform="coinpilot",
                source="social_screenshot",
                trades=8,
                win_rate=0.91,
                realized_pnl=10_000,
                max_drawdown_pct=0.45,
                avg_leverage=12,
                profit_factor=1.1,
                verified=False,
            )
        ]
    )

    rejected = report["rejected_traders"]
    assert report["rejected_count"] == 1
    assert rejected[0]["handle"] == "viral_clip_trader"
    assert "sample too small" in rejected[0]["risk_flags"]
    assert "Need: 30+ trades minimum, 100+ preferred" in rejected[0]["what_would_help"]
    assert "Need: exported broker history or verified public wallet" in rejected[0]["what_would_help"]


def test_public_kalshi_leaderboard_without_win_rate_stays_review_only() -> None:
    from strategies.copy_trader_watchlist import TraderProfile, score_trader

    profile = TraderProfile(
        handle="lad.",
        platform="kalshi",
        source="public_leaderboard",
        trades=134_340,
        win_rate=0.0,
        realized_pnl=4_594_531.0,
        max_drawdown_pct=0.0,
        avg_leverage=1.0,
        profit_factor=0.0,
        verified=True,
        category="kalshi_social",
    )

    scored = score_trader(profile)

    assert scored.status == "review"
    assert "public leaderboard lacks win rate" in scored.risk_flags
    assert "missing exported trade history" in scored.risk_flags


def test_public_profile_history_counts_as_public_platform_history() -> None:
    from strategies.copy_trader_watchlist import TraderProfile, score_trader

    profile = TraderProfile(
        handle="weatherman.allday",
        platform="kalshi",
        source="public_profile",
        trades=150,
        win_rate=0.58,
        realized_pnl=2_500.0,
        max_drawdown_pct=0.08,
        avg_leverage=1.0,
        profit_factor=1.8,
        verified=True,
        pnl_smoothness=0.75,
        green_months=6,
        monthly_consistency=0.75,
        worst_month_pct=-0.05,
        avg_edge_per_trade=0.03,
        fee_adjusted_return=0.09,
        trade_frequency="moderate",
    )

    scored = score_trader(profile)

    assert scored.status == "paper_watch"
    assert "public profile history" in scored.reason


def test_public_wallet_with_activity_but_no_measurable_pnl_is_rejected() -> None:
    from strategies.copy_trader_watchlist import TraderProfile, score_trader

    profile = TraderProfile(
        handle="0x204f72f35326db932158cba6adff0b9a1da95e14",
        platform="polymarket",
        source="public_wallet",
        trades=500,
        win_rate=0.0,
        realized_pnl=0.0,
        max_drawdown_pct=0.0,
        avg_leverage=1.0,
        profit_factor=0.0,
        verified=True,
        trade_frequency="hyperactive",
    )

    scored = score_trader(profile)

    assert scored.status == "reject"
    assert "unmeasurable pnl history" in scored.risk_flags


def test_copy_trader_score_rewards_smooth_green_months_and_viable_edge() -> None:
    from strategies.copy_trader_watchlist import TraderProfile, score_trader

    profile = TraderProfile(
        handle="coinpilot_style",
        platform="polymarket",
        source="exported_history",
        trades=160,
        win_rate=0.59,
        realized_pnl=14_000.0,
        max_drawdown_pct=0.08,
        avg_leverage=1.0,
        profit_factor=1.72,
        verified=True,
        pnl_smoothness=0.84,
        green_months=6,
        monthly_consistency=0.78,
        worst_month_pct=-0.04,
        avg_edge_per_trade=0.035,
        fee_adjusted_return=0.18,
        trade_frequency="selective",
    )

    scored = score_trader(profile)

    assert scored.status == "paper_watch"
    assert scored.confidence == 10
    assert scored.conviction_score >= 8
    assert scored.suggested_copy_size == 15.0
    assert "smooth pnl curve" in scored.reason
    assert "all tracked months green" in scored.reason
    assert scored.risk_flags == []


def test_copy_trader_score_flags_choppy_fee_drag_and_overtrading() -> None:
    from strategies.copy_trader_watchlist import TraderProfile, score_trader

    profile = TraderProfile(
        handle="filter_farmed",
        platform="polymarket",
        source="exported_history",
        trades=1200,
        win_rate=0.57,
        realized_pnl=2_000.0,
        max_drawdown_pct=0.14,
        avg_leverage=1.0,
        profit_factor=1.22,
        verified=True,
        pnl_smoothness=0.18,
        green_months=2,
        monthly_consistency=0.22,
        worst_month_pct=-0.24,
        avg_edge_per_trade=0.004,
        fee_adjusted_return=0.015,
        trade_frequency="hyperactive",
    )

    scored = score_trader(profile)

    assert scored.status != "paper_watch"
    assert "choppy pnl curve" in scored.risk_flags
    assert "weak month-to-month consistency" in scored.risk_flags
    assert "edge too small after fees" in scored.risk_flags
    assert "overtrading risk" in scored.risk_flags
    assert scored.suggested_copy_size == 0.0


def test_profile_from_dict_loads_copy_diligence_fields() -> None:
    from strategies.copy_trader_watchlist import profile_from_dict

    profile = profile_from_dict(
        {
            "handle": "0xsteady",
            "platform": "polymarket",
            "source": "public_wallet",
            "trades": 140,
            "pnl_smoothness": "0.82",
            "green_months": "5",
            "monthly_consistency": "0.74",
            "worst_month_pct": "-0.03",
            "avg_edge_per_trade": "0.031",
            "fee_adjusted_return": "0.16",
            "trade_frequency": "selective",
        }
    )

    assert profile.pnl_smoothness == 0.82
    assert profile.green_months == 5
    assert profile.monthly_consistency == 0.74
    assert profile.worst_month_pct == -0.03
    assert profile.avg_edge_per_trade == 0.031
    assert profile.fee_adjusted_return == 0.16
    assert profile.trade_frequency == "selective"


def test_dashboard_renders_copy_watchlist_panel(tmp_path) -> None:
    from strategies.trading_dashboard import copy_watchlist_context, copy_watchlist_panel

    report = tmp_path / "copy-trader-watchlist.json"
    report.write_text(
        json.dumps(
            {
                "provider": "copy_trader_watchlist",
                "mode": "paper_only",
                "execution_enabled": False,
                "watched_traders": [
                    {
                        "handle": "0xsteady",
                        "platform": "polymarket",
                        "confidence": 8,
                        "status": "paper_watch",
                        "realized_pnl": 8400,
                        "win_rate": 0.62,
                        "profit_factor": 1.85,
                        "conviction_score": 9,
                        "suggested_copy_size": 15,
                        "risk_flags": [],
                    }
                ],
                "paper_signal_count": 1,
                "paper_signals": [
                    {
                        "trader": "0xsteady",
                        "platform": "polymarket",
                        "symbol": "KXWEATHER-NYC-RAIN",
                        "side": "YES",
                        "action": "paper_copy",
                        "notional": 50,
                        "price_drift": 0.05,
                    }
                ],
                "warnings": ["Paper-only: no copy-trading execution is implemented."],
            }
        ),
        encoding="utf-8",
    )

    context = copy_watchlist_context(report)
    html = copy_watchlist_panel(context)

    assert context["available"] is True
    assert context["top_traders"][0]["handle"] == "0xsteady"
    assert "Copy Trader Watchlist" in html
    assert "0xsteady" in html
    assert "Conviction" in html
    assert "$15.00" in html
    assert "KXWEATHER-NYC-RAIN" in html
    assert "paper_copy" in html
    assert "Paper-only" in html
