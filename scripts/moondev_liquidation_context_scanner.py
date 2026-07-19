#!/usr/bin/env python3
"""Read-only MoonDev liquidation/context scanner.

Extracted from MoonDev's public Hyperliquid data-layer examples, but deliberately
kept as context only. This scanner can help us study whether crypto/perp
liquidation pressure, HLP sentiment, and whale flow correlate with risk-on/risk-off
conditions in our equity/options bots.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG_PATH = ROOT / "data" / "moondev_liquidation_context_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "moondev-liquidation-context.json"
API_BASE = "https://api.moondev.com"
SOURCE_REPO = "moondevonyt/Hyperliquid-Data-Layer-API"
DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "HYPE"]


def _load_env() -> None:
    env_path = ROOT / "agent" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def _get_json(endpoint: str, *, api_key: str | None, params: dict[str, Any] | None = None) -> dict[str, Any] | list[Any]:
    url = f"{API_BASE}{endpoint}"
    if params:
        url = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None})}"
    headers = {"User-Agent": "VibeTrading/1.0 read-only context scanner"}
    if api_key:
        headers["X-API-Key"] = api_key
    request = Request(url, headers=headers)
    with urlopen(request, timeout=20) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _sum_liquidation_values(items: list[Any]) -> tuple[int, float, float, float]:
    count = 0
    total = 0.0
    long_value = 0.0
    short_value = 0.0
    for item in items:
        if not isinstance(item, dict):
            continue
        value = _safe_float(
            item.get("value")
            or item.get("usd_value")
            or item.get("value_usd")
            or item.get("notional")
            or item.get("quantity")
        )
        side = str(item.get("side") or item.get("direction") or "").lower()
        count += 1
        total += value
        if side in {"long", "buy", "b"}:
            long_value += value
        elif side in {"short", "sell", "s"}:
            short_value += value
    return count, total, long_value, short_value


def _liquidation_summary(data: dict[str, Any] | list[Any]) -> dict[str, Any]:
    if isinstance(data, list):
        count, total, long_value, short_value = _sum_liquidation_values(data)
        return {
            "count": count,
            "total_volume_usd": round(total, 2),
            "long_volume_usd": round(long_value, 2),
            "short_volume_usd": round(short_value, 2),
        }
    if not isinstance(data, dict):
        return {"count": 0, "total_volume_usd": 0.0, "long_volume_usd": 0.0, "short_volume_usd": 0.0}
    rows = data.get("liquidations") or data.get("data") or []
    if isinstance(rows, list) and rows:
        summary = _liquidation_summary(rows)
    else:
        summary = {
            "count": int(_safe_float(data.get("total_count") or data.get("count"))),
            "total_volume_usd": round(_safe_float(data.get("total_volume") or data.get("total_value_usd")), 2),
            "long_volume_usd": round(_safe_float(data.get("long_volume")), 2),
            "short_volume_usd": round(_safe_float(data.get("short_volume")), 2),
        }
    by_coin = data.get("by_coin") or data.get("coins") or {}
    if isinstance(by_coin, dict):
        top = []
        for coin, info in by_coin.items():
            if not isinstance(info, dict):
                continue
            top.append({
                "symbol": str(coin).replace("USDT", "").replace("USD", "")[:12],
                "volume_usd": round(_safe_float(info.get("volume") or info.get("total_value")), 2),
                "count": int(_safe_float(info.get("count"))),
            })
        summary["top_symbols"] = sorted(top, key=lambda row: row["volume_usd"], reverse=True)[:8]
    return summary


def _classify_liquidation_pressure(summary: dict[str, Any]) -> str:
    total = _safe_float(summary.get("total_volume_usd"))
    long_value = _safe_float(summary.get("long_volume_usd"))
    short_value = _safe_float(summary.get("short_volume_usd"))
    if total <= 0:
        return "unknown"
    imbalance = (short_value - long_value) / total
    if total >= 100_000_000 and imbalance >= 0.25:
        return "short_squeeze_pressure"
    if total >= 100_000_000 and imbalance <= -0.25:
        return "long_squeeze_pressure"
    if total >= 100_000_000:
        return "high_two_sided_liquidation"
    return "normal"


def _normalize_hlp_sentiment(data: dict[str, Any] | list[Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"status": "unavailable"}
    z_score = _safe_float(data.get("z_score") or data.get("zscore"))
    signal = data.get("signal") or data.get("interpretation") or ""
    if isinstance(signal, dict):
        signal = signal.get("text") or signal.get("message") or signal.get("signal") or str(signal)
    if z_score >= 2.0:
        bias = "retail_short_squeeze_risk"
    elif z_score <= -2.0:
        bias = "retail_long_squeeze_risk"
    else:
        bias = "neutral"
    return {
        "status": "ok",
        "z_score": round(z_score, 3),
        "signal": str(signal),
        "bias": bias,
        "net_delta": data.get("net_delta") or data.get("delta"),
        "percentile": data.get("percentile") or data.get("pct"),
    }


def _normalize_position_stats(data: dict[str, Any] | list[Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"status": "unavailable"}
    overall = data.get("overall") if isinstance(data.get("overall"), dict) else {}
    by_symbol = data.get("by_symbol") if isinstance(data.get("by_symbol"), dict) else {}
    closest = data.get("top_10_closest") if isinstance(data.get("top_10_closest"), list) else []
    return {
        "status": "ok",
        "total_snapshots": int(_safe_float(overall.get("total_snapshots"))),
        "unique_users": int(_safe_float(overall.get("unique_users"))),
        "avg_distance_pct": round(_safe_float(overall.get("avg_distance_pct")), 3),
        "by_symbol": by_symbol,
        "closest": closest[:10],
    }


def _normalize_poly_whales(data: dict[str, Any] | list[Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {"status": "unavailable", "trade_count": 0, "buy_usd": 0.0, "sell_usd": 0.0}
    rows = data.get("trades") or data.get("data") or []
    buy_usd = 0.0
    sell_usd = 0.0
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            usd = _safe_float(row.get("usd_amount") or row.get("notional") or row.get("value_usd"))
            side = str(row.get("side") or "").upper()
            if side == "BUY":
                buy_usd += usd
            elif side == "SELL":
                sell_usd += usd
    return {
        "status": "ok",
        "trade_count": len(rows) if isinstance(rows, list) else 0,
        "buy_usd": round(buy_usd, 2),
        "sell_usd": round(sell_usd, 2),
        "net_buy_usd": round(buy_usd - sell_usd, 2),
        "top_trades": rows[:8] if isinstance(rows, list) else [],
    }


def scan_moondev_context(
    *,
    api_key: str | None = None,
    timeframe: str = "1h",
    hours: int = 24,
    min_poly_usd: float = 5_000,
) -> dict[str, Any]:
    api_key = api_key or os.getenv("MOONDEV_API_KEY")
    base = {
        "date": date.today().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "moondev_liquidation_context",
        "source_repo": SOURCE_REPO,
        "source_repo_url": "https://github.com/moondevonyt/Hyperliquid-Data-Layer-API",
        "mode": "read_only",
        "execution_enabled": False,
        "live_trading_allowed": False,
        "timeframe": timeframe,
        "warnings": [
            "Context only. Do not use liquidation data as a direct execution signal.",
            "MoonDev API data requires independent 30-day outcome validation before any gate change.",
        ],
    }
    if not api_key:
        return {
            **base,
            "status": "auth_missing",
            "summary": "Set MOONDEV_API_KEY in agent/.env to enable this read-only context scanner.",
        }

    errors: list[str] = []

    def fetch(label: str, endpoint: str, params: dict[str, Any] | None = None) -> Any:
        try:
            return _get_json(endpoint, api_key=api_key, params=params)
        except HTTPError as exc:
            errors.append(f"{label}: HTTP {exc.code}")
        except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            errors.append(f"{label}: {str(exc)[:120]}")
        return None

    all_liqs = fetch("all_liquidations", f"/api/all_liquidations/{timeframe}.json")
    all_stats = fetch("all_liquidation_stats", "/api/all_liquidations/stats.json")
    hlp = fetch("hlp_sentiment", "/api/hlp/sentiment")
    positions = fetch("position_snapshot_stats", "/api/position_snapshots/stats", {"hours": hours})
    whales = fetch("poly_whales", "/api/poly/whales", {"min_usd": int(min_poly_usd), "days": 1, "limit": 50})

    liquidation = _liquidation_summary(all_liqs if all_liqs is not None else all_stats)
    pressure = _classify_liquidation_pressure(liquidation)
    hlp_sentiment = _normalize_hlp_sentiment(hlp)
    position_stats = _normalize_position_stats(positions)
    poly_whales = _normalize_poly_whales(whales)

    if pressure in {"short_squeeze_pressure", "long_squeeze_pressure"} or hlp_sentiment.get("bias") != "neutral":
        market_bias = "crypto_stress_watch"
    elif poly_whales.get("trade_count", 0) >= 10:
        market_bias = "prediction_whale_activity"
    else:
        market_bias = "normal_context"

    return {
        **base,
        "status": "ok" if not errors else "partial",
        "errors": errors,
        "liquidations": liquidation,
        "liquidation_pressure": pressure,
        "hlp_sentiment": hlp_sentiment,
        "position_snapshots": position_stats,
        "polymarket_whales": poly_whales,
        "market_bias": market_bias,
        "feeds": [
            "market_force_score_context",
            "daily_activity_csv",
            "signal_stack_leaderboard",
        ],
    }


def append_log(row: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")


def write_report(row: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def print_report(row: dict[str, Any]) -> None:
    print("\nMoonDev Liquidation Context | read-only")
    print("=" * 72)
    print(f"status={row.get('status')} bias={row.get('market_bias', '-')}")
    if row.get("status") == "auth_missing":
        print(row.get("summary"))
    else:
        liq = row.get("liquidations", {})
        hlp = row.get("hlp_sentiment", {})
        print(
            f"liqs={liq.get('count', 0)} volume=${liq.get('total_volume_usd', 0):,.0f} "
            f"pressure={row.get('liquidation_pressure')}"
        )
        print(f"hlp_bias={hlp.get('bias')} z={hlp.get('z_score')}")
        if row.get("errors"):
            print("errors=" + "; ".join(row["errors"][:4]))
    print(f"JSON: {REPORT_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--min-poly-usd", type=float, default=5000)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    _load_env()
    row = scan_moondev_context(timeframe=args.timeframe, hours=args.hours, min_poly_usd=args.min_poly_usd)
    append_log(row, args.log_path)
    write_report(row, args.report_path)
    if args.print_output:
        print_report(row)
    else:
        print(f"MoonDev liquidation context logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
