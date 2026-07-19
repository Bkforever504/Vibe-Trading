"""Read-only social trending-symbol scanner.

Pulls StockTwits public trending symbols as a daily social breadth layer. This
does not replace X/Threads/Instagram/TikTok research; it gives us a stable,
credential-free baseline of which tradable symbols retail traders are talking
about today.

No broker orders. No strategy gates. Research context only.
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "social_trending_symbols_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "social-trending-symbols.json"

STOCKTWITS_TRENDING_URL = "https://api.stocktwits.com/api/2/trending/symbols.json"
USER_AGENT = "VibeTradingSocialTrendScanner/1.0"

CORE_WATCHLIST = {
    "SPY", "QQQ", "IWM", "DIA", "SMH", "XLK", "XLF", "XLE", "XLV", "XLY",
    "AAPL", "MSFT", "NVDA", "AMD", "AVGO", "TSLA", "META", "AMZN", "GOOGL",
    "NFLX", "PLTR", "COIN", "MSTR", "HOOD", "RIVN", "NKE", "LLY", "NVO",
    "JPM", "BAC", "UNH", "CRWD", "SNOW", "SHOP", "SOFI", "GME", "AMC",
}

HIGH_NOISE_CLASSES = {"CRYPTO"}
MEME_HIGH_NOISE_SYMBOLS = {"GME", "AMC"}
SOCIAL_SQUEEZE_WATCH_SYMBOLS = {"FRMM"}
SCAN_START_HOUR_CT = 8
SCAN_START_MINUTE_CT = 20
SCAN_INTERVAL_MINUTES = 120


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return default


def fetch_stocktwits_trending(timeout: int = 20) -> list[dict[str, Any]]:
    req = urllib.request.Request(STOCKTWITS_TRENDING_URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    rows = payload.get("symbols") if isinstance(payload, dict) else []
    return [row for row in rows or [] if isinstance(row, dict)]


def _instrument_bucket(symbol: str, row: dict[str, Any]) -> str:
    instrument_class = str(row.get("instrument_class") or row.get("InstrumentClass") or "").lower()
    if symbol in {"SPY", "QQQ", "IWM", "DIA", "SMH", "XLK", "XLF", "XLE", "XLV", "XLY"}:
        return "etf"
    if instrument_class == "crypto":
        return "crypto"
    sector = str(row.get("sector") or "")
    if "Health" in sector:
        return "biotech_healthcare"
    if symbol in {"NVDA", "AMD", "AVGO", "SMH", "PLTR", "CRWD", "SNOW"}:
        return "ai_semis_software"
    if symbol in {"TSLA", "RIVN", "QS"}:
        return "ev_batteries"
    if symbol in {"COIN", "MSTR", "HOOD"}:
        return "crypto_equity_proxy"
    if symbol in {"GME", "AMC"}:
        return "meme_high_noise"
    if symbol in SOCIAL_SQUEEZE_WATCH_SYMBOLS:
        return "social_squeeze_watch"
    return "single_stock"


def normalize_symbol(row: dict[str, Any]) -> dict[str, Any]:
    symbol = str(row.get("symbol") or row.get("symbol_display") or "").upper()
    trends = row.get("trends") if isinstance(row.get("trends"), dict) else {}
    fundamentals = row.get("fundamentals") if isinstance(row.get("fundamentals"), dict) else {}
    instrument_class = str(row.get("instrument_class") or fundamentals.get("InstrumentClass") or "")
    trending_score = _safe_float(row.get("trending_score"))
    rank = _safe_int(row.get("rank"))
    market_cap = _safe_float(fundamentals.get("MarketCap") or fundamentals.get("MarketCapitalization"))
    avg_volume = _safe_float(fundamentals.get("AverageDailyVolumeLastMonth") or fundamentals.get("AverageDailyVolumeLast3Months"))
    summary = str(trends.get("summary") or "")

    noise_flags: list[str] = []
    if instrument_class.upper() in HIGH_NOISE_CLASSES:
        noise_flags.append("crypto symbol; do not route into equity/options bots")
    if symbol in MEME_HIGH_NOISE_SYMBOLS:
        noise_flags.append("meme-stock baseline trend; require independent catalyst before scoring")
    if symbol in SOCIAL_SQUEEZE_WATCH_SYMBOLS:
        noise_flags.append("social squeeze watch; context only until options/liquidity/outcome validate")
    if market_cap and market_cap < 1000:
        noise_flags.append("small-cap trend; high pump/fade risk")
    if avg_volume and avg_volume < 1_000_000:
        noise_flags.append("thin average volume; liquidity risk")

    action = "context_only"
    if symbol in CORE_WATCHLIST and not noise_flags:
        action = "watch_context"
    elif (
        not noise_flags
        and market_cap >= 10_000
        and avg_volume >= 1_000_000
        and instrument_class.lower() in {"stock", "exchange traded fund"}
    ):
        action = "watch_context"

    return {
        "rank": rank,
        "symbol": symbol,
        "title": row.get("title"),
        "exchange": row.get("exchange"),
        "instrument_class": instrument_class,
        "bucket": _instrument_bucket(symbol, row),
        "sector": row.get("sector"),
        "industry": row.get("industry"),
        "trending_score": round(trending_score, 4),
        "watchlist_count": _safe_int(row.get("watchlist_count")),
        "market_cap_millions": round(market_cap, 2) if market_cap else None,
        "avg_daily_volume": round(avg_volume, 0) if avg_volume else None,
        "summary": summary[:500],
        "summary_at": trends.get("summary_at"),
        "action": action,
        "noise_flags": noise_flags,
        "url": f"https://stocktwits.com/symbol/{symbol}" if symbol else None,
    }


def intraday_scan_index(now: datetime | None = None) -> int:
    """Approximate scheduled scan slot: 0 for 08:20 CT, then every 2 hours."""
    now = now or datetime.now().astimezone()
    minutes = now.hour * 60 + now.minute
    start = SCAN_START_HOUR_CT * 60 + SCAN_START_MINUTE_CT
    if minutes <= start:
        return 0
    return max(0, (minutes - start) // SCAN_INTERVAL_MINUTES)


def build_report(limit: int = 30, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    rows = [normalize_symbol(row) for row in fetch_stocktwits_trending()]
    rows = [row for row in rows if row.get("symbol")]
    rows.sort(key=lambda row: row.get("rank") or 999)
    selected = rows[:limit]
    buckets: dict[str, int] = {}
    for row in selected:
        bucket = str(row.get("bucket") or "unknown")
        buckets[bucket] = buckets.get(bucket, 0) + 1

    return {
        "date": now.date().isoformat(),
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "intraday_scan_index": intraday_scan_index(now.astimezone()),
        "intraday_slot_label": f"slot_{intraday_scan_index(now.astimezone())}",
        "scheduled_start_ct": "08:20",
        "scheduled_interval_minutes": SCAN_INTERVAL_MINUTES,
        "provider": "social_trending_symbols_scanner",
        "source": "stocktwits_public_trending_symbols",
        "mode": "context_only",
        "execution_enabled": False,
        "symbol_count": len(selected),
        "bucket_counts": buckets,
        "symbols": selected,
        "warnings": [
            "Context only. No broker orders are wired.",
            "StockTwits is one social source, not the whole internet.",
            "X/Threads/Instagram/TikTok should feed the separate social-arbitrage observation file when available.",
        ],
    }


def append_log(report: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":")) + "\n")


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report_path


def print_report(report: dict[str, Any]) -> None:
    print("\nSocial Trending Symbols | context only")
    print("=" * 64)
    print(
        f"Source={report['source']} slot={report['intraday_slot_label']} "
        f"symbols={report['symbol_count']} buckets={report['bucket_counts']}"
    )
    for row in report["symbols"][:15]:
        flags = f" flags={'; '.join(row['noise_flags'])}" if row.get("noise_flags") else ""
        print(
            f"{row['rank']:>2}. {row['symbol']:<6} {row['bucket']:<22} "
            f"score={row['trending_score']:<8} action={row['action']}{flags}"
        )
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan public StockTwits trending symbols.")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()

    report = build_report(limit=args.limit)
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Social trending symbols logged to {args.log_path}")
        print(f"Social trending symbols report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
