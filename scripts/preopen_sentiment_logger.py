"""Pre-open SPY/QQQ sentiment context logger.

Read-only. No broker orders. Pulls recent public StockTwits messages for SPY
and QQQ, computes a lightweight bullish/bearish score, and appends one JSONL
row to data/preopen_sentiment_log.jsonl.

This is the conservative version of the "sentiment agent" idea: it records
market narrative context next to GEX/IVR, but it does not change any bot signal.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "data" / "preopen_sentiment_log.jsonl"
SYMBOLS = ["SPY", "QQQ"]
STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
USER_AGENT = "VibeTradingPreopenSentiment/1.0"

BULLISH_WORDS = {
    "all time high",
    "ath",
    "bounce",
    "breakout",
    "bull",
    "bullish",
    "buy",
    "call",
    "calls",
    "green",
    "higher",
    "long",
    "moon",
    "pump",
    "rally",
    "rip",
    "support",
    "uptrend",
}

BEARISH_WORDS = {
    "bear",
    "bearish",
    "breakdown",
    "crash",
    "dump",
    "falling",
    "lower",
    "puts",
    "red",
    "rejection",
    "resistance",
    "rug",
    "sell",
    "short",
    "trap",
    "weak",
}


def fetch_stocktwits_messages(symbol: str, limit: int = 30, timeout: int = 15) -> list[dict[str, Any]]:
    url = STOCKTWITS_URL.format(symbol=symbol.upper())
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    messages = data.get("messages") or []
    return [m for m in messages[:limit] if isinstance(m, dict)]


def _clean_text(text: str) -> str:
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\$[A-Z.]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _lexicon_score(text: str) -> int:
    lowered = text.lower()
    bullish = sum(1 for word in BULLISH_WORDS if word in lowered)
    bearish = sum(1 for word in BEARISH_WORDS if word in lowered)
    if bullish > bearish:
        return 1
    if bearish > bullish:
        return -1
    return 0


def classify_message(message: dict[str, Any]) -> dict[str, Any]:
    body = str(message.get("body") or "")
    sentiment = ((message.get("entities") or {}).get("sentiment") or {}).get("basic")
    label = str(sentiment or "").lower()
    if label == "bullish":
        score = 1
        source = "stocktwits_tag"
    elif label == "bearish":
        score = -1
        source = "stocktwits_tag"
    else:
        score = _lexicon_score(body)
        source = "lexicon" if score else "unclassified"

    user = message.get("user") or {}
    followers = int(user.get("followers") or 0)
    weight = 1.0 + min(math.log10(followers + 1), 4.0) / 4.0

    return {
        "id": message.get("id"),
        "created_at": message.get("created_at"),
        "username": user.get("username"),
        "followers": followers,
        "body": _clean_text(body)[:240],
        "score": score,
        "score_source": source,
        "weight": round(weight, 3),
    }


def summarize_symbol(symbol: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    classified = [classify_message(m) for m in messages]
    scored = [m for m in classified if m["score"] != 0]
    bullish = [m for m in scored if m["score"] > 0]
    bearish = [m for m in scored if m["score"] < 0]
    weighted_sum = sum(m["score"] * m["weight"] for m in scored)
    weight_total = sum(m["weight"] for m in scored)
    sentiment_score = weighted_sum / weight_total if weight_total else 0.0

    if sentiment_score >= 0.25:
        bias = "bullish"
    elif sentiment_score <= -0.25:
        bias = "bearish"
    else:
        bias = "neutral"

    top_messages = sorted(scored, key=lambda m: m["followers"], reverse=True)[:5]
    return {
        "symbol": symbol.upper(),
        "source": "stocktwits_public_stream",
        "message_count": len(classified),
        "classified_count": len(scored),
        "bullish_count": len(bullish),
        "bearish_count": len(bearish),
        "sentiment_score": round(sentiment_score, 3),
        "bias": bias,
        "top_messages": top_messages,
    }


def aggregate_bias(scans: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [s for s in scans if s.get("status") == "ok"]
    if not usable:
        return {"bias": "unavailable", "sentiment_score": 0.0}
    total_messages = sum(int(s.get("classified_count") or 0) for s in usable)
    if total_messages <= 0:
        return {"bias": "neutral", "sentiment_score": 0.0}
    score = sum(float(s.get("sentiment_score") or 0.0) * int(s.get("classified_count") or 0) for s in usable) / total_messages
    if score >= 0.25:
        bias = "bullish"
    elif score <= -0.25:
        bias = "bearish"
    else:
        bias = "neutral"
    return {"bias": bias, "sentiment_score": round(score, 3), "classified_count": total_messages}


def scan_symbol(symbol: str, limit: int = 30) -> dict[str, Any]:
    try:
        messages = fetch_stocktwits_messages(symbol, limit=limit)
        return {"status": "ok", **summarize_symbol(symbol, messages)}
    except Exception as exc:
        return {
            "symbol": symbol.upper(),
            "status": "error",
            "source": "stocktwits_public_stream",
            "error": str(exc)[:200],
        }


def build_entry(symbols: list[str] | None = None, limit: int = 30) -> dict[str, Any]:
    symbols = symbols or SYMBOLS
    scans = [scan_symbol(symbol, limit=limit) for symbol in symbols]
    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "mode": "context_only",
        "execution_enabled": False,
        "provider": "preopen_sentiment_logger",
        "aggregate": aggregate_bias(scans),
        "scans": scans,
        "warnings": [
            "Sentiment is context only. No broker orders are wired.",
            "StockTwits data is noisy and must be reviewed against actual forward bot performance.",
        ],
    }


def append_log(entry: dict[str, Any], log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def print_report(entry: dict[str, Any]) -> None:
    agg = entry.get("aggregate") or {}
    print("\nPre-open Sentiment | context only")
    print("=" * 54)
    print(f"Aggregate: {agg.get('bias')} score={agg.get('sentiment_score')} classified={agg.get('classified_count', 0)}")
    for scan in entry.get("scans", []):
        symbol = scan.get("symbol")
        if scan.get("status") != "ok":
            print(f"{symbol}: ERROR - {scan.get('error')}")
            continue
        print(
            f"{symbol}: {scan.get('bias')} score={scan.get('sentiment_score')} "
            f"bull={scan.get('bullish_count')} bear={scan.get('bearish_count')} "
            f"classified={scan.get('classified_count')}/{scan.get('message_count')}"
        )
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Log pre-open SPY/QQQ public sentiment context.")
    parser.add_argument("--symbols", default=",".join(SYMBOLS), help="Comma-separated symbols, default SPY,QQQ")
    parser.add_argument("--limit", type=int, default=30, help="Messages per symbol")
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    entry = build_entry(symbols=symbols, limit=args.limit)
    append_log(entry, args.log_path)
    if args.print_output:
        print_report(entry)
    else:
        print(f"Pre-open sentiment logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
