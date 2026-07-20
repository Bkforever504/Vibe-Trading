#!/usr/bin/env python3
"""Read-only deep liquid universe scanner.

Ranks liquid option-friendly stocks/ETFs for shadow review using price action,
relative volume, dollar volume, and social persistence. This does not submit
orders and does not promote symbols to execution.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_data import data_source, fetch_ohlcv

LOG_PATH = ROOT / "data" / "deep_liquid_universe_scan_log.jsonl"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "deep-liquid-universe-scan.json"
SOCIAL_LOG_PATH = ROOT / "data" / "social_trending_symbols_log.jsonl"

MIN_PRICE = 15.0
MAX_PRICE = 1_200.0
MIN_AVG_DOLLAR_VOLUME = 75_000_000

DEFAULT_UNIVERSE = [
    # Index / sector ETFs
    "SPY", "QQQ", "IWM", "DIA", "SMH", "SOXL", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP",
    "TLT", "GLD", "SLV", "USO", "KRE",
    # Mega-cap / liquid tech
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "AMD", "AVGO",
    "NFLX", "ADBE", "CRM", "ORCL", "INTC", "MU", "QCOM", "TXN", "AMAT", "LRCX",
    "NOW", "SNOW", "PLTR", "CRWD", "PANW", "DDOG", "NET", "MDB",
    # High-beta / retail active
    "COIN", "MSTR", "HOOD", "RBLX", "SHOP", "SQ", "PYPL", "SOFI", "UBER", "ABNB",
    "RDDT", "LYFT",
    "RIVN", "LCID", "NIO", "XPEV", "LI", "GME", "AMC", "BABA", "PDD", "JD",
    # Financials / cyclicals / industrials
    "JPM", "BAC", "GS", "MS", "WFC", "C", "AXP", "V", "MA", "CAT", "DE", "BA", "GE",
    "F", "GM", "NKE", "LULU", "COST", "WMT", "TGT", "HD", "LOW", "MCD", "LTH",
    # Healthcare / GLP-1 / biotech liquid
    "LLY", "NVO", "UNH", "JNJ", "MRK", "PFE", "ABBV", "AMGN", "GILD", "MRNA",
    "BMY", "KVUE", "TDOC", "REGN",
    # Energy / commodities
    "XOM", "CVX", "OXY", "SLB", "FCX", "NEM",
    # AI infra / recent social names with liquidity filter
    "IREN", "CRWV", "NBIS", "APLD", "WULF", "AAOI", "SNDK", "WDC", "GLW", "ORCL",
    "IBM", "PATH", "AUR", "L",
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")


def _cutoff(days: int, today: str | None = None) -> str:
    anchor = date.fromisoformat(today) if today else datetime.now(timezone.utc).date()
    return (anchor - timedelta(days=max(days - 1, 0))).isoformat()


def load_social_context(path: Path = SOCIAL_LOG_PATH, days: int = 7, today: str | None = None) -> dict[str, dict[str, Any]]:
    cutoff = _cutoff(days, today)
    today = today or datetime.now(timezone.utc).date().isoformat()
    context: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(path):
        row_date = str(row.get("date") or "")[:10]
        if not row_date or row_date < cutoff or row_date > today:
            continue
        slot = row.get("intraday_scan_index", 0)
        for item in row.get("symbols") or []:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol") or "").upper()
            if not symbol:
                continue
            ctx = context.setdefault(
                symbol,
                {
                    "social_day_set": set(),
                    "social_slot_set": set(),
                    "best_social_rank": None,
                    "max_social_score": 0.0,
                },
            )
            ctx["social_day_set"].add(row_date)
            ctx["social_slot_set"].add(f"{row_date}:{slot}")
            rank = int(_safe_float(item.get("rank"), 999))
            ctx["best_social_rank"] = rank if ctx["best_social_rank"] is None else min(ctx["best_social_rank"], rank)
            ctx["max_social_score"] = max(_safe_float(ctx["max_social_score"]), _safe_float(item.get("trending_score")))

    normalized: dict[str, dict[str, Any]] = {}
    for symbol, ctx in context.items():
        normalized[symbol] = {
            "social_day_count": len(ctx["social_day_set"]),
            "social_slot_count": len(ctx["social_slot_set"]),
            "best_social_rank": ctx["best_social_rank"],
            "max_social_score": round(_safe_float(ctx["max_social_score"]), 4),
        }
    return normalized


def _pct(current: float, prior: float) -> float:
    return ((current / prior) - 1.0) * 100 if prior else 0.0


def higher_timeframe_volume_features(df: Any) -> dict[str, Any]:
    """Completed weekly/monthly volume context; never uses a partial HTF bar."""
    frame = df.copy()
    frame.index = pd.to_datetime(frame.index).tz_localize(None)
    latest_date = frame.index[-1].normalize()

    def aggregate(rule: str, average_window: int, trend_window: int) -> dict[str, Any]:
        grouped = frame.resample(rule).agg({"close": "last", "volume": "sum"}).dropna()
        grouped = grouped[grouped.index.normalize() <= latest_date]
        if len(grouped) < max(average_window + 1, trend_window):
            return {"relative_volume": None, "trend": "unknown", "periods": len(grouped)}
        latest = grouped.iloc[-1]
        prior_avg = float(grouped["volume"].iloc[-average_window - 1:-1].mean())
        relative = float(latest["volume"]) / prior_avg if prior_avg > 0 else 0.0
        trend_average = float(grouped["close"].tail(trend_window).mean())
        close = float(latest["close"])
        trend = "bullish" if close > trend_average else "bearish" if close < trend_average else "mixed"
        return {
            "relative_volume": round(relative, 3),
            "trend": trend,
            "close": round(close, 4),
            "trend_average": round(trend_average, 4),
            "period_end": str(grouped.index[-1].date()),
            "periods": len(grouped),
        }

    weekly = aggregate("W-FRI", 20, 20)
    monthly = aggregate("ME", 12, 10)
    if weekly["relative_volume"] is None or monthly["relative_volume"] is None:
        state = "insufficient_data"
    elif weekly["relative_volume"] >= 1.25 and monthly["relative_volume"] >= 1.10:
        state = "broad_volume_expansion"
    elif weekly["relative_volume"] >= 1.25:
        state = "weekly_volume_expansion"
    elif monthly["relative_volume"] >= 1.10:
        state = "monthly_volume_expansion"
    else:
        state = "normal"
    return {"weekly": weekly, "monthly": monthly, "state": state}


def score_symbol(symbol: str, df: Any, social_context: dict[str, Any] | None = None) -> dict[str, Any]:
    social_context = social_context or {}
    symbol = symbol.upper()
    if len(df) < 61:
        return {"symbol": symbol, "status": "insufficient_data", "rows": len(df)}

    latest = df.iloc[-1]
    close = float(latest["close"])
    volume = float(latest["volume"])
    prior20 = df.iloc[-21:-1]
    avg_volume_20d = float(prior20["volume"].mean())
    avg_dollar_volume = float((prior20["close"] * prior20["volume"]).mean())
    relative_volume = volume / avg_volume_20d if avg_volume_20d else 0.0
    one_day_pct = _pct(close, float(df.iloc[-2]["close"]))
    five_day_pct = _pct(close, float(df.iloc[-6]["close"]))
    twenty_day_pct = _pct(close, float(df.iloc[-21]["close"]))
    sixty_day_pct = _pct(close, float(df.iloc[-61]["close"]))
    range_pct = ((float(latest["high"]) - float(latest["low"])) / close) * 100 if close else 0.0
    htf_volume = higher_timeframe_volume_features(df)

    risk_flags: list[str] = []
    if close < MIN_PRICE:
        risk_flags.append("price_below_minimum")
    if close > MAX_PRICE:
        risk_flags.append("price_above_maximum")
    if avg_dollar_volume < MIN_AVG_DOLLAR_VOLUME:
        risk_flags.append("thin_dollar_volume")

    score = 0.0
    reasons: list[str] = []
    if avg_dollar_volume >= 500_000_000:
        score += 2.0
        reasons.append("very liquid dollar volume")
    elif avg_dollar_volume >= MIN_AVG_DOLLAR_VOLUME:
        score += 1.0
        reasons.append("passes dollar-volume filter")
    if relative_volume >= 3:
        score += 2.5
        reasons.append("extreme relative volume")
    elif relative_volume >= 2:
        score += 1.75
        reasons.append("high relative volume")
    elif relative_volume >= 1.3:
        score += 0.75
        reasons.append("elevated relative volume")
    if abs(one_day_pct) >= 2:
        score += 1.25
        reasons.append("large one-day move")
    if abs(five_day_pct) >= 4:
        score += 1.0
        reasons.append("strong five-day move")
    if abs(twenty_day_pct) >= 7:
        score += 1.0
        reasons.append("strong twenty-day trend")
    if abs(sixty_day_pct) >= 12:
        score += 0.75
        reasons.append("strong sixty-day trend")
    social_slots = int(_safe_float(social_context.get("social_slot_count")))
    best_rank = social_context.get("best_social_rank")
    if social_slots >= 2:
        score += 1.5
        reasons.append("persistent social attention")
    elif social_slots == 1:
        score += 0.5
        reasons.append("single social trend appearance")
    if best_rank is not None and int(best_rank) <= 10:
        score += 0.75
        reasons.append("top-10 social rank")

    if risk_flags:
        score -= 2.5
    if score >= 6.0 and not risk_flags:
        recommendation = "shadow_review_candidate"
    elif risk_flags:
        recommendation = "reject_for_flip_bot"
    else:
        recommendation = "watch_context"

    return {
        "symbol": symbol,
        "status": "ok",
        "close": round(close, 4),
        "one_day_pct": round(one_day_pct, 3),
        "five_day_pct": round(five_day_pct, 3),
        "twenty_day_pct": round(twenty_day_pct, 3),
        "sixty_day_pct": round(sixty_day_pct, 3),
        "range_pct": round(range_pct, 3),
        "relative_volume": round(relative_volume, 3),
        "higher_timeframe_volume": htf_volume,
        "avg_volume_20d": round(avg_volume_20d, 0),
        "avg_dollar_volume_20d": round(avg_dollar_volume, 0),
        "social_day_count": int(_safe_float(social_context.get("social_day_count"))),
        "social_slot_count": social_slots,
        "best_social_rank": best_rank,
        "max_social_score": round(_safe_float(social_context.get("max_social_score")), 4),
        "deep_score": round(max(score, 0.0), 2),
        "recommendation": recommendation,
        "risk_flags": risk_flags,
        "reasons": reasons,
    }


def scan_symbol(symbol: str, social_context: dict[str, Any] | None = None, lookback_days: int = 800) -> dict[str, Any]:
    try:
        df = fetch_ohlcv(symbol.upper(), lookback_days=lookback_days)
        return score_symbol(symbol, df, social_context=social_context)
    except Exception as exc:
        return {"symbol": symbol.upper(), "status": "unavailable", "warning": str(exc)[:200]}


def build_report(
    *,
    symbols: list[str] | None = None,
    social_context: dict[str, dict[str, Any]] | None = None,
    log_path: Path = LOG_PATH,
    report_path: Path = REPORT_PATH,
) -> dict[str, Any]:
    raw_symbols = symbols or DEFAULT_UNIVERSE
    symbols = list(dict.fromkeys(symbol.upper() for symbol in raw_symbols))
    social_context = social_context if social_context is not None else load_social_context()
    scans = [scan_symbol(symbol, social_context=social_context.get(symbol.upper(), {})) for symbol in symbols]
    ok = [row for row in scans if row.get("status") == "ok"]
    candidates = [row for row in ok if row.get("recommendation") == "shadow_review_candidate"]
    candidates.sort(key=lambda row: float(row.get("deep_score") or 0), reverse=True)
    watch = [row for row in ok if row.get("recommendation") == "watch_context"]
    watch.sort(key=lambda row: float(row.get("deep_score") or 0), reverse=True)
    htf_volume_candidates = [
        row for row in ok
        if row.get("higher_timeframe_volume", {}).get("state") not in {"normal", "insufficient_data", None}
    ]
    htf_volume_candidates.sort(
        key=lambda row: max(
            _safe_float(row.get("higher_timeframe_volume", {}).get("weekly", {}).get("relative_volume")),
            _safe_float(row.get("higher_timeframe_volume", {}).get("monthly", {}).get("relative_volume")),
        ),
        reverse=True,
    )
    htf_state_counts: dict[str, int] = {}
    for row in ok:
        state = str(row.get("higher_timeframe_volume", {}).get("state") or "unknown")
        htf_state_counts[state] = htf_state_counts.get(state, 0) + 1

    report = {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "deep_liquid_universe_scanner",
        "source": data_source(),
        "mode": "context_only",
        "execution_enabled": False,
        "symbol_count": len(symbols),
        "ok_count": len(ok),
        "candidate_count": len(candidates),
        "top_candidates": candidates[:25],
        "watch_context": watch[:25],
        "higher_timeframe_volume_summary": htf_state_counts,
        "higher_timeframe_volume_candidates": htf_volume_candidates[:25],
        "scans": scans,
        "warnings": [
            "Read-only deep scanner. No broker orders are wired.",
            "A symbol must pass 30 trading days and 10 completed shadow samples before any promotion.",
            "Low-priced or thin-dollar-volume names are rejected for Flip Bot even when social attention is high.",
            "Higher-timeframe volume is context-only because its preregistered historical variants did not pass every robustness gate.",
        ] + [
            f"{row.get('symbol')}: {row.get('warning')}"
            for row in scans
            if row.get("status") == "unavailable" and row.get("warning")
        ][:10],
    }
    _append_jsonl(log_path, report)
    _write_report(report_path, report)
    return report


def print_report(report: dict[str, Any]) -> None:
    print("\nDeep Liquid Universe Scanner | context only")
    print("=" * 78)
    print(
        f"source={report['source']} symbols={report['symbol_count']} "
        f"ok={report['ok_count']} candidates={report['candidate_count']}"
    )
    for row in report["top_candidates"][:15]:
        print(
            f"{row['symbol']:<6} score={row['deep_score']:<4} "
            f"rv={row['relative_volume']:<5} 1d={row['one_day_pct']:+.2f}% "
            f"20d={row['twenty_day_pct']:+.2f}% social_slots={row['social_slot_count']} "
            f"reasons={'; '.join(row['reasons'][:3])}"
        )
    if report["higher_timeframe_volume_candidates"]:
        print("\nCompleted weekly/monthly volume expansion (context only)")
        for row in report["higher_timeframe_volume_candidates"][:10]:
            htf = row["higher_timeframe_volume"]
            print(
                f"{row['symbol']:<6} state={htf['state']:<26} "
                f"weekly_rvol={htf['weekly']['relative_volume']} monthly_rvol={htf['monthly']['relative_volume']}"
            )
    print("No orders placed.\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan liquid stocks/ETFs for shadow-review candidates.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_UNIVERSE))
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    args = parser.parse_args()
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    report = build_report(symbols=symbols, log_path=args.log_path, report_path=args.report_path)
    if args.print_output:
        print_report(report)
    else:
        print(f"Deep liquid universe scan logged to {args.log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
