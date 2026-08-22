#!/usr/bin/env python3
"""Cross-sector premarket opportunity radar (read-only, no order authority)."""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "premarket-opportunity-radar.json"
LOG_PATH = ROOT / "data" / "premarket_opportunity_radar_log.jsonl"
STATE_PATH = VIBE_HOME / "state" / "premarket-opportunity-radar-alerts.json"
DEEP_REPORT_PATH = VIBE_HOME / "reports" / "deep-liquid-universe-scan.json"
SOCIAL_LOG_PATH = ROOT / "data" / "social_trending_symbols_log.jsonl"
MIN_AVG_DOLLAR_VOLUME = 75_000_000
MIN_PRICE = 5.0
MAX_BAR_CANDIDATES = 24
MAX_SPREAD = {"event_gap": 0.008, "momentum_gap": 0.005, "tactical_gap": 0.004}
MIN_RVOL = {"event_gap": 2.0, "momentum_gap": 1.5, "tactical_gap": 1.25}
EXCEPTIONAL_EVENT_GAP_PCT = 0.25
EXCEPTIONAL_EVENT_MAX_SPREAD = 0.03
PRIORITY = {"observe": 0, "medium": 1, "high": 2}

BASE_UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA", "SMH", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP",
    "XLC", "XLU", "XLI", "XLB", "XLRE", "XBI", "IBB", "TLT", "GLD", "SLV", "USO",
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "AMD", "AVGO", "NFLX",
    "ADBE", "CRM", "ORCL", "INTC", "MU", "QCOM", "AMAT", "LRCX", "PLTR", "CRWD",
    "PANW", "SNOW", "COIN", "MSTR", "HOOD", "SHOP", "SQ", "PYPL", "SOFI", "UBER",
    "RDDT", "RIVN", "GME", "AMC", "BABA", "PDD", "JPM", "BAC", "GS", "WFC", "AXP",
    "CAT", "DE", "BA", "GE", "F", "GM", "NKE", "COST", "WMT", "TGT", "HD", "LOW",
    "LLY", "NVO", "UNH", "JNJ", "MRK", "PFE", "ABBV", "AMGN", "GILD", "MRNA", "BMY",
    "REGN", "XOM", "CVX", "OXY", "SLB", "FCX", "NEM", "IREN", "APLD", "WULF", "SNDK",
]

SECTOR_ETF = {
    "AAPL": "XLK", "MSFT": "XLK", "NVDA": "SMH", "AMD": "SMH", "AVGO": "SMH",
    "INTC": "SMH", "MU": "SMH", "QCOM": "SMH", "AMAT": "SMH", "LRCX": "SMH",
    "META": "XLC", "GOOGL": "XLC", "NFLX": "XLC", "AMZN": "XLY", "TSLA": "XLY",
    "JPM": "XLF", "BAC": "XLF", "GS": "XLF", "WFC": "XLF", "LLY": "XLV",
    "NVO": "XLV", "UNH": "XLV", "JNJ": "XLV", "MRK": "XLV", "PFE": "XLV",
    "ABBV": "XLV", "AMGN": "XLV", "GILD": "XLV", "MRNA": "XBI", "REGN": "XBI",
    "XOM": "XLE", "CVX": "XLE", "OXY": "XLE", "SLB": "XLE", "CAT": "XLI",
    "DE": "XLI", "BA": "XLI", "GE": "XLI", "WMT": "XLP", "COST": "XLP",
}


def _credentials() -> dict[str, str]:
    values = {"ALPACA_API_KEY": os.getenv("ALPACA_API_KEY", ""), "ALPACA_SECRET_KEY": os.getenv("ALPACA_SECRET_KEY", "")}
    env_path = ROOT / "agent" / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            if raw.lstrip().startswith("#") or "=" not in raw:
                continue
            key, _, value = raw.partition("=")
            if key.strip() in values and not values[key.strip()]:
                values[key.strip()] = value.strip()
    if not all(values.values()):
        raise RuntimeError("alpaca_market_data_credentials_missing")
    return {"APCA-API-KEY-ID": values["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": values["ALPACA_SECRET_KEY"]}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return []
    result = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            result.append(row)
    return result


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index:index + size] for index in range(0, len(values), size)]


def load_deep_context(path: Path = DEEP_REPORT_PATH) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("symbol") or "").upper(): row
        for row in _read_json(path).get("scans") or []
        if isinstance(row, dict) and row.get("symbol")
    }


def load_social_symbols(as_of: date, path: Path = SOCIAL_LOG_PATH) -> list[str]:
    for row in reversed(_read_jsonl(path)):
        if str(row.get("date") or row.get("timestamp") or "")[:10] == as_of.isoformat():
            return [str(item.get("symbol") or "").upper() for item in row.get("symbols") or [] if isinstance(item, dict)]
    return []


def fetch_news(
    now_et: datetime,
    pages: int = 1,
    symbols: list[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    rows, errors, token = [], [], None
    for _ in range(pages):
        params: dict[str, Any] = {
            "start": (now_et.astimezone(timezone.utc) - timedelta(hours=18)).isoformat().replace("+00:00", "Z"),
            "end": now_et.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "sort": "desc", "limit": 50, "include_content": "false",
        }
        if symbols:
            params["symbols"] = ",".join(symbols)
        if token:
            params["page_token"] = token
        try:
            response = requests.get("https://data.alpaca.markets/v1beta1/news", headers=_credentials(), params=params, timeout=15)
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            errors.append(f"alpaca_news:{type(exc).__name__}")
            break
        rows.extend(row for row in payload.get("news") or [] if isinstance(row, dict))
        token = payload.get("next_page_token")
        if not token:
            break
    return rows, errors


def news_by_symbol(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        for raw_symbol in row.get("symbols") or []:
            symbol = str(raw_symbol).upper().strip()
            if symbol.isalnum() and len(symbol) <= 6:
                output.setdefault(symbol, []).append({
                    "headline": str(row.get("headline") or "")[:240], "created_at": row.get("created_at"),
                    "source": row.get("source"), "url": row.get("url"),
                })
    return output


def fetch_snapshots(symbols: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    output, errors = {}, []
    for chunk in _chunks(symbols, 60):
        try:
            response = requests.get(
                "https://data.alpaca.markets/v2/stocks/snapshots", headers=_credentials(),
                params={"symbols": ",".join(chunk), "feed": "iex"}, timeout=18,
            )
            response.raise_for_status()
            output.update({str(key).upper(): value for key, value in response.json().items() if isinstance(value, dict)})
        except Exception as exc:
            errors.append(f"alpaca_snapshots:{type(exc).__name__}:{','.join(chunk[:3])}")
    return output, errors


def snapshot_metrics(snapshot: dict[str, Any]) -> dict[str, Any]:
    previous, daily = snapshot.get("prevDailyBar") or {}, snapshot.get("dailyBar") or {}
    minute, trade, quote = snapshot.get("minuteBar") or {}, snapshot.get("latestTrade") or {}, snapshot.get("latestQuote") or {}
    previous_close = _finite(previous.get("c"))
    price = _finite(trade.get("p")) or _finite(minute.get("c")) or _finite(daily.get("c"))
    bid, ask = _finite(quote.get("bp")), _finite(quote.get("ap"))
    return {
        "price": price, "previous_close": previous_close,
        "gap_return": price / previous_close - 1 if price and previous_close else None,
        "spread_pct": (ask - bid) / ((ask + bid) / 2) if bid and ask and ask >= bid else None,
        "snapshot_volume": _finite(daily.get("v")), "latest_trade_at": trade.get("t"),
        "latest_quote_at": quote.get("t"),
    }


def fetch_extended_bars(symbols: list[str], now_et: datetime) -> tuple[dict[str, pd.DataFrame], list[str]]:
    raw: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
    errors = []
    start = (now_et - timedelta(days=6)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    end = now_et.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    for chunk in _chunks(symbols, 6):
        token = None
        for _ in range(4):
            params: dict[str, Any] = {"symbols": ",".join(chunk), "timeframe": "5Min", "start": start, "end": end, "adjustment": "raw", "feed": "iex", "limit": 10000, "sort": "asc"}
            if token:
                params["page_token"] = token
            try:
                response = requests.get("https://data.alpaca.markets/v2/stocks/bars", headers=_credentials(), params=params, timeout=22)
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                errors.append(f"alpaca_bars:{type(exc).__name__}:{','.join(chunk[:3])}")
                break
            for symbol, bars in (payload.get("bars") or {}).items():
                raw.setdefault(str(symbol).upper(), []).extend(row for row in bars or [] if isinstance(row, dict))
            token = payload.get("next_page_token")
            if not token:
                break
    frames = {}
    for symbol, rows in raw.items():
        if not rows:
            continue
        frame = pd.DataFrame(rows).rename(columns={"t": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        if not {"timestamp", "open", "high", "low", "close", "volume"}.issubset(frame.columns):
            continue
        frame.index = pd.to_datetime(frame.pop("timestamp"), utc=True).dt.tz_convert("America/New_York")
        frames[symbol] = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce").dropna().sort_index()
    return frames, errors


def fetch_daily_liquidity(symbols: list[str], now_et: datetime) -> tuple[dict[str, float], list[str]]:
    """Return trailing completed-session average dollar volume for dynamic symbols."""
    if not symbols:
        return {}, []
    raw: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
    errors: list[str] = []
    start = (now_et - timedelta(days=40)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    end = now_et.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    for chunk in _chunks(symbols, 24):
        params = {
            "symbols": ",".join(chunk), "timeframe": "1Day", "start": start, "end": end,
            "adjustment": "raw", "feed": "iex", "limit": 10000, "sort": "asc",
        }
        try:
            response = requests.get(
                "https://data.alpaca.markets/v2/stocks/bars",
                headers=_credentials(), params=params, timeout=18,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            errors.append(f"alpaca_daily_bars:{type(exc).__name__}:{','.join(chunk[:3])}")
            continue
        for symbol, bars in (payload.get("bars") or {}).items():
            raw.setdefault(str(symbol).upper(), []).extend(row for row in bars or [] if isinstance(row, dict))
    output: dict[str, float] = {}
    for symbol, rows in raw.items():
        completed = []
        for row in rows:
            timestamp = pd.to_datetime(row.get("t"), utc=True, errors="coerce")
            close, volume = _finite(row.get("c")), _finite(row.get("v"))
            if pd.isna(timestamp) or timestamp.date() >= now_et.date() or close is None or volume is None:
                continue
            completed.append(close * volume)
        if completed:
            output[symbol] = sum(completed[-20:]) / len(completed[-20:])
    return output, errors


def premarket_features(frame: pd.DataFrame, now_et: datetime) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {"status": "unavailable", "premarket_rvol": None}
    cutoff = min(now_et.time(), time(9, 29, 59))
    current = frame[(frame.index.date == now_et.date()) & (frame.index.time >= time(4)) & (frame.index.time <= cutoff)]
    if current.empty:
        return {"status": "no_premarket_bars", "premarket_rvol": None}
    totals = []
    for session in sorted(set(frame.index.date)):
        if session >= now_et.date():
            continue
        prior = frame[(frame.index.date == session) & (frame.index.time >= time(4)) & (frame.index.time <= cutoff)]
        if not prior.empty:
            totals.append(float(prior["volume"].sum()))
    volume = float(current["volume"].sum())
    baseline = statistics.median(totals[-5:]) if totals else None
    rvol = volume / baseline if baseline else None
    return {
        "status": "ok", "bars": len(current), "premarket_open": round(float(current.open.iloc[0]), 4),
        "premarket_high": round(float(current.high.max()), 4), "premarket_low": round(float(current.low.min()), 4),
        "premarket_close": round(float(current.close.iloc[-1]), 4), "premarket_volume": round(volume),
        "same_time_baseline_sessions": len(totals[-5:]), "same_time_median_volume": round(baseline) if baseline else None,
        "premarket_rvol": round(rvol, 3) if rvol is not None else None,
    }


def lane_for_gap(gap_return: float | None) -> str | None:
    magnitude = abs(gap_return or 0)
    return "event_gap" if magnitude >= 0.06 else "momentum_gap" if magnitude >= 0.02 else "tactical_gap" if magnitude >= 0.0075 else None


def evaluate_candidate(symbol: str, metrics: dict[str, Any], premarket: dict[str, Any], deep: dict[str, Any], articles: list[dict[str, Any]], sector_gap: float | None) -> dict[str, Any]:
    gap = _finite(metrics.get("gap_return"))
    lane = lane_for_gap(gap)
    base = {"symbol": symbol, "lane": lane, "execution_enabled": False, "can_submit_orders": False, "formula_version": "premarket_gap_rvol_news_sector_liquidity_v1"}
    if lane is None:
        return {**base, "state": "below_tactical_gap", "priority": "observe", "alertable": False}
    price, spread = _finite(metrics.get("price")), _finite(metrics.get("spread_pct"))
    rvol, avg_dollar = _finite(premarket.get("premarket_rvol")), _finite(deep.get("avg_dollar_volume_20d"))
    direction = "bull" if (gap or 0) > 0 else "bear"
    sector_confirmed = bool(sector_gap is not None and abs(sector_gap) >= 0.002 and ((sector_gap > 0) == (direction == "bull")))
    liquidity_ok = bool(avg_dollar is not None and avg_dollar >= MIN_AVG_DOLLAR_VOLUME)
    spread_ok = bool(spread is not None and spread <= MAX_SPREAD[lane])
    rvol_ok = bool(rvol is not None and rvol >= MIN_RVOL[lane])
    catalyst = bool(articles)
    gates = {
        "price": bool(price is not None and price >= MIN_PRICE), "historical_dollar_liquidity": liquidity_ok,
        "executable_underlying_spread": spread_ok, "same_time_premarket_rvol": rvol_ok,
        "catalyst_or_sector_context": lane == "event_gap" or catalyst or sector_confirmed,
    }
    gap_points = 3 if lane == "event_gap" else 2 if lane == "momentum_gap" else 1
    rvol_points = 0 if rvol is None else 3 if rvol >= 4 else 2 if rvol >= 2 else 1 if rvol >= 1.25 else 0
    score = gap_points + rvol_points + 2 * int(catalyst) + int(sector_confirmed) + int(liquidity_ok) + int(spread_ok)
    ready = all(gates.values())
    exceptional_event_watch = bool(
        lane == "event_gap"
        and abs(gap or 0.0) >= EXCEPTIONAL_EVENT_GAP_PCT
        and catalyst
        and gates["price"]
        and liquidity_ok
        and (spread is None or spread <= EXCEPTIONAL_EVENT_MAX_SPREAD)
    )
    priority = (
        "high"
        if (ready and score >= 7 and lane != "tactical_gap") or exceptional_event_watch
        else "medium" if ready and score >= 5 else "observe"
    )
    route = {"event_gap": "event_gap_continuation_shadow", "momentum_gap": "premarket_ema_retest_shadow", "tactical_gap": "trend_participation_shadow"}[lane]
    return {
        **base,
        "state": "watch_ready" if ready else "exceptional_event_watch" if exceptional_event_watch else "context_incomplete",
        "priority": priority,
        "alertable": priority != "observe", "direction": direction, "gap_pct": round((gap or 0) * 100, 3),
        "price": round(price, 4) if price is not None else None,
        "underlying_spread_pct": round(spread * 100, 4) if spread is not None else None,
        "premarket_rvol": rvol, "avg_dollar_volume_20d": round(avg_dollar) if avg_dollar else None,
        "sector_etf": SECTOR_ETF.get(symbol), "sector_gap_pct": round(sector_gap * 100, 3) if sector_gap is not None else None,
        "sector_confirmed": sector_confirmed, "catalyst_available": catalyst, "catalyst_headlines": articles[:3],
        "hard_gates": gates, "score": score, "routed_shadow_playbook": route, "premarket": premarket,
        "exceptional_event_watch": exceptional_event_watch,
        "watch_degradation_reasons": [name for name, passed in gates.items() if not passed],
        "latest_trade_at": metrics.get("latest_trade_at"),
        "latest_quote_at": metrics.get("latest_quote_at"),
        "paper_signal_eligible": False,
        "entry_rule": "watch_only_then_wait_for_completed_price_volume_confirmation", "authority": "discovery_and_alert_only",
    }


def build_report(*, now_et: datetime | None = None, symbols: list[str] | None = None) -> dict[str, Any]:
    if now_et is None:
        from zoneinfo import ZoneInfo
        now_et = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York"))
    if now_et.tzinfo is None:
        raise ValueError("now_et must be timezone-aware")
    in_scan_window = time(4) <= now_et.time() <= time(9, 29, 59)
    if not in_scan_window:
        return {
            "schema_version": 1, "provider": "premarket_opportunity_radar",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "as_of_et": now_et.isoformat(), "date": now_et.date().isoformat(),
            "mode": "read_only_shadow_routing", "session_status": "outside_premarket_scan_window",
            "market_timezone": "America/New_York",
            "execution_enabled": False, "can_submit_orders": False, "universe_count": 0,
            "snapshot_count": 0, "bar_candidate_count": 0, "news_article_count": 0,
            "high_priority": [], "medium_priority": [], "observations": [], "errors": [],
            "operational_health": {"status": "idle", "reason": "outside_premarket_scan_window"},
            "warnings": ["Cannot predict surprise news before publication.", "Watch alerts are not entries.", "Alpaca IEX is a screening feed, not full SIP coverage.", "No broker imports and no order authority."],
        }
    explicit_symbols = [symbol.upper() for symbol in symbols or []]
    news, errors = fetch_news(now_et, symbols=explicit_symbols or None)
    news_map = news_by_symbol(news)
    discovery = [] if explicit_symbols else load_social_symbols(now_et.date()) + list(news_map)[:30]
    universe = list(dict.fromkeys((explicit_symbols or BASE_UNIVERSE) + list(SECTOR_ETF.values()) + discovery))[:140]
    snapshots, more_errors = fetch_snapshots(universe)
    errors.extend(more_errors)
    metrics = {symbol: snapshot_metrics(value) for symbol, value in snapshots.items()}
    selected = sorted(
        (symbol for symbol, row in metrics.items() if abs(float(row.get("gap_return") or 0)) >= 0.0075),
        key=lambda symbol: abs(float(metrics[symbol].get("gap_return") or 0)), reverse=True,
    )[:MAX_BAR_CANDIDATES]
    frames, more_errors = fetch_extended_bars(selected, now_et)
    errors.extend(more_errors)
    daily_liquidity, more_errors = fetch_daily_liquidity(selected, now_et)
    errors.extend(more_errors)
    deep = load_deep_context()
    for symbol, avg_dollar_volume in daily_liquidity.items():
        deep.setdefault(symbol, {})["avg_dollar_volume_20d"] = avg_dollar_volume
    sector_gaps = {symbol: _finite(row.get("gap_return")) for symbol, row in metrics.items() if symbol in set(SECTOR_ETF.values())}
    observations = [
        evaluate_candidate(symbol, metrics[symbol], premarket_features(frames.get(symbol, pd.DataFrame()), now_et), deep.get(symbol, {}), news_map.get(symbol, []), sector_gaps.get(SECTOR_ETF.get(symbol, "")))
        for symbol in selected
    ]
    observations.sort(key=lambda row: (PRIORITY.get(str(row.get("priority")), 0), int(row.get("score") or 0), abs(float(row.get("gap_pct") or 0))), reverse=True)
    return {
        "schema_version": 1, "provider": "premarket_opportunity_radar", "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "as_of_et": now_et.isoformat(), "date": now_et.date().isoformat(), "mode": "read_only_shadow_routing", "session_status": "premarket_scan_window",
        "market_timezone": "America/New_York",
        "execution_enabled": False, "can_submit_orders": False, "universe_count": len(universe), "snapshot_count": len(snapshots),
        "bar_candidate_count": len(selected), "news_article_count": len(news),
        "high_priority": [row for row in observations if row.get("priority") == "high"],
        "medium_priority": [row for row in observations if row.get("priority") == "medium"],
        "observations": observations, "errors": errors,
        "operational_health": {
            "status": "ok" if snapshots and not errors else "degraded",
            "snapshots_available": bool(snapshots),
            "snapshot_coverage_pct": round(len(snapshots) / len(universe) * 100.0, 2) if universe else 0.0,
            "selected_symbols_with_bars": len(frames),
            "errors": len(errors),
        },
        "warnings": ["Cannot predict surprise news before publication.", "Watch alerts are not entries.", "Alpaca IEX is a screening feed, not full SIP coverage.", "No broker imports and no order authority."],
    }


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def write_report(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    _atomic_json(report_path, report)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def _post_discord(message: str) -> bool:
    from scripts.shadow_alerts import webhook_url
    url = webhook_url()
    if not url:
        return False
    request = urllib.request.Request(url, data=json.dumps({"content": message}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10):
            return True
    except Exception:
        return False


def send_watch_alerts(report: dict[str, Any], *, state_path: Path = STATE_PATH, min_priority: str = "high", sender: Callable[[str], bool] = _post_discord) -> int:
    state = _read_json(state_path)
    sent = state.get("sent") if isinstance(state.get("sent"), dict) else {}
    count = 0
    for row in report.get("observations") or []:
        if not row.get("alertable") or PRIORITY.get(str(row.get("priority")), 0) < PRIORITY[min_priority]:
            continue
        key = f"{report.get('date')}:{row.get('symbol')}:{row.get('lane')}:{row.get('priority')}"
        if key in sent:
            continue
        headlines = row.get("catalyst_headlines") or []
        headline = str(headlines[0].get("headline") or "none tagged") if headlines else "none tagged"
        message = (
            f"**Premarket watch: {row.get('symbol')} {row.get('direction')}**\n"
            f"Lane=`{row.get('lane')}` priority=`{row.get('priority')}` score=`{row.get('score')}` gap=`{row.get('gap_pct')}%`\n"
            f"Same-time RVOL=`{row.get('premarket_rvol')}` sector=`{row.get('sector_etf')}` confirmed=`{row.get('sector_confirmed')}`\n"
            f"Route=`{row.get('routed_shadow_playbook')}`\nCatalyst: {headline[:300]}\n"
            f"State=`{row.get('state')}` missing gates=`{','.join(row.get('watch_degradation_reasons') or []) or 'none'}`\n"
            "Watch only. Wait for completed price/volume confirmation. No orders placed."
        )
        if sender(message):
            sent[key], count = report.get("generated_at"), count + 1
    _atomic_json(state_path, {"schema_version": 1, "sent": sent})
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="")
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument("--no-alert", action="store_true")
    parser.add_argument("--alert-min-priority", choices=("medium", "high"), default="high")
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    symbols = [part.strip().upper() for part in args.symbols.split(",") if part.strip()] or None
    report = build_report(symbols=symbols)
    if report.get("session_status") == "outside_premarket_scan_window":
        previous = _read_json(args.report_path)
        if (
            previous.get("date") == report.get("date")
            and previous.get("session_status") == "premarket_scan_window"
        ):
            previous["last_invocation"] = {
                "generated_at": report.get("generated_at"),
                "status": "outside_premarket_scan_window_preserved_prior_scan",
            }
            write_report(previous, args.report_path, args.log_path)
            print("Premarket radar: outside window; preserved today's completed premarket scan")
            return 0
    write_report(report, args.report_path, args.log_path)
    report["alerts_sent"] = 0 if args.no_alert else send_watch_alerts(report, state_path=args.state_path, min_priority=args.alert_min_priority)
    _atomic_json(args.report_path, report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Premarket radar: high={len(report['high_priority'])} medium={len(report['medium_priority'])} alerts={report['alerts_sent']} errors={len(report['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
