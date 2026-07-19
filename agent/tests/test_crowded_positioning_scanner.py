from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import crowded_positioning_scanner as scanner


def test_crowded_positioning_scanner_flags_crowded_longs_as_call_caution(tmp_path: Path) -> None:
    moondev = tmp_path / "moondev-liquidation-context.json"
    prediction = tmp_path / "prediction-market-microstructure.json"
    weekly = tmp_path / "weekly-hot-instruments.json"

    moondev.write_text(
        json.dumps(
            {
                "date": "2026-07-06",
                "status": "ok",
                "liquidation_pressure": "long_squeeze_pressure",
                "liquidations": {
                    "count": 120,
                    "total_volume_usd": 180_000_000,
                    "long_volume_usd": 150_000_000,
                    "short_volume_usd": 30_000_000,
                },
                "hlp_sentiment": {
                    "status": "ok",
                    "bias": "retail_long_squeeze_risk",
                    "z_score": -2.6,
                },
                "position_snapshots": {
                    "status": "ok",
                    "total_snapshots": 250,
                    "unique_users": 80,
                    "avg_distance_pct": 3.1,
                },
            }
        ),
        encoding="utf-8",
    )
    prediction.write_text(
        json.dumps(
            {
                "date": "2026-07-06",
                "top_candidates": [
                    {"title": "BTC Up or Down", "directional_hint": "no_flow", "microstructure_score": 7}
                ],
            }
        ),
        encoding="utf-8",
    )
    weekly.write_text(
        json.dumps(
            {
                "date": "2026-07-06",
                "hot_instruments": [
                    {"symbol": "COIN", "bucket": "crypto_equity_proxy", "hot_score": 8.9},
                    {"symbol": "MSTR", "bucket": "crypto_equity_proxy", "hot_score": 6.2},
                ],
            }
        ),
        encoding="utf-8",
    )

    report = scanner.build_report(
        day="2026-07-06",
        moondev_path=moondev,
        prediction_path=prediction,
        weekly_hot_path=weekly,
    )

    assert report["execution_enabled"] is False
    assert report["mode"] == "read_only"
    assert report["summary"]["crowded_side"] == "long"
    assert report["summary"]["crowding_score"] >= 7
    assert report["flip_bot_context"]["posture"] == "cautious"
    assert report["flip_bot_context"]["call_bias"] == "avoid_chasing_calls"
    assert report["crypto_proxy_watchlist"] == ["COIN", "MSTR"]
    assert report["warnings"][0].startswith("Read-only")


def test_crowded_positioning_scanner_flags_crowded_shorts_as_squeeze_watch(tmp_path: Path) -> None:
    moondev = tmp_path / "moondev-liquidation-context.json"
    moondev.write_text(
        json.dumps(
            {
                "date": "2026-07-06",
                "status": "ok",
                "liquidation_pressure": "short_squeeze_pressure",
                "liquidations": {
                    "count": 90,
                    "total_volume_usd": 140_000_000,
                    "long_volume_usd": 20_000_000,
                    "short_volume_usd": 120_000_000,
                },
                "hlp_sentiment": {
                    "status": "ok",
                    "bias": "retail_short_squeeze_risk",
                    "z_score": 2.2,
                },
            }
        ),
        encoding="utf-8",
    )

    report = scanner.build_report(day="2026-07-06", moondev_path=moondev)

    assert report["summary"]["crowded_side"] == "short"
    assert report["flip_bot_context"]["call_bias"] == "watch_for_squeeze_but_require_confirmation"
    assert report["promotion_ready"] is False
