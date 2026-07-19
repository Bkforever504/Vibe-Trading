#!/usr/bin/env python3
"""Paper trader for Kalshi daily-high weather markets.

Uses public Kalshi fixed-point market data and three Open-Meteo ensemble
families. It has no authenticated client and cannot submit orders.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from strategies.polymarket_weather_bot import PublicClient as ForecastClient
from strategies.polymarket_weather_bot import Station, bucket_probability, TemperatureBucket

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
RUNTIME = Path.home() / ".vibe-trading"
STATE_PATH = RUNTIME / "kalshi-weather-paper-state.json"
REPORT_PATH = RUNTIME / "reports" / "kalshi-weather-bot.json"
LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "kalshi_weather_log.jsonl"

MIN_EDGE = 0.10
MAX_SPREAD = 0.10
MIN_ENSEMBLE_MEMBERS = 20
MAX_MODEL_PROBABILITY_DISAGREEMENT = 0.20
MIN_HOURS_TO_CLOSE = 2.0
MAX_CONTRACTS_PER_POSITION = 1
MAX_DAILY_NEW_RISK = 15.0
MAX_OPEN_POSITIONS = 20
FORECAST_CACHE_HOURS = 6.0
REQUIRED_MODEL_FAMILIES = ("gfs_gefs", "ecmwf_ifs", "icon_eu")


@dataclass(frozen=True)
class WeatherSeries:
    ticker: str
    city: str
    station_code: str
    latitude: float
    longitude: float
    timezone: str
    nws_issued_by: str

    @property
    def station(self) -> Station:
        return Station(self.station_code, self.latitude, self.longitude, self.timezone)


WEATHER_SERIES = {
    row.ticker: row for row in (
        WeatherSeries("KXHIGHNY", "New York", "KNYC", 40.7789, -73.9692, "America/New_York", "NYC"),
        WeatherSeries("KXHIGHCHI", "Chicago", "KMDW", 41.7868, -87.7522, "America/Chicago", "MDW"),
        WeatherSeries("KXHIGHMIA", "Miami", "KMIA", 25.7959, -80.2870, "America/New_York", "MIA"),
        WeatherSeries("KXHIGHAUS", "Austin", "KAUS", 30.1975, -97.6664, "America/Chicago", "AUS"),
        WeatherSeries("KXHIGHTBOS", "Boston", "KBOS", 42.3656, -71.0096, "America/New_York", "BOS"),
        WeatherSeries("KXHIGHDEN", "Denver", "KDEN", 39.8561, -104.6737, "America/Denver", "DEN"),
        WeatherSeries("KXHIGHTATL", "Atlanta", "KATL", 33.6407, -84.4277, "America/New_York", "ATL"),
        WeatherSeries("KXHIGHTMIN", "Minneapolis", "KMSP", 44.8848, -93.2223, "America/Chicago", "MSP"),
        WeatherSeries("KXHIGHTPHX", "Phoenix", "KPHX", 33.4342, -112.0116, "America/Phoenix", "PHX"),
        WeatherSeries("KXHIGHTDAL", "Dallas", "KDFW", 32.8998, -97.0403, "America/Chicago", "DFW"),
        WeatherSeries("KXHIGHTHOU", "Houston", "KHOU", 29.6454, -95.2789, "America/Chicago", "HOU"),
        WeatherSeries("KXHIGHTSEA", "Seattle", "KSEA", 47.4502, -122.3088, "America/Los_Angeles", "SEA"),
        WeatherSeries("KXHIGHTOKC", "Oklahoma City", "KOKC", 35.3931, -97.6007, "America/Chicago", "OKC"),
    )
}


@dataclass(frozen=True)
class KalshiBucket:
    label: str
    lower: int | None
    upper: int | None

    def contains(self, observed: int) -> bool:
        return (self.lower is None or observed >= self.lower) and (self.upper is None or observed <= self.upper)


class KalshiWeatherClient:
    def __init__(self, session: Any | None = None) -> None:
        if session is None:
            import requests
            session = requests.Session()
        self.session = session
        self.forecasts = ForecastClient(session=session)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        for attempt in range(5):
            response = self.session.get(f"{BASE_URL}{path}", params=params or {}, timeout=20)
            status = int(getattr(response, "status_code", 200) or 200)
            if status != 429 and status < 500:
                response.raise_for_status()
                data = response.json()
                return data if isinstance(data, dict) else {}
            if attempt == 4:
                response.raise_for_status()
            time.sleep(0.5 * (2 ** attempt))
        return {}

    def markets(self, series_ticker: str) -> list[dict[str, Any]]:
        data = self._get("/markets", {"series_ticker": series_ticker, "status": "open", "limit": 100})
        return [row for row in data.get("markets", []) if isinstance(row, dict)]

    def market(self, ticker: str) -> dict[str, Any]:
        data = self._get(f"/markets/{ticker}")
        market = data.get("market")
        return market if isinstance(market, dict) else {}

    def orderbook(self, ticker: str) -> dict[str, Any]:
        return self._get(f"/markets/{ticker}/orderbook")

    def orderbooks(self, tickers: list[str]) -> dict[str, dict[str, Any]]:
        books: dict[str, dict[str, Any]] = {}
        for start in range(0, len(tickers), 100):
            data = self._get("/markets/orderbooks", {"tickers": tickers[start : start + 100]})
            for row in data.get("orderbooks", []):
                if isinstance(row, dict) and row.get("ticker"):
                    books[str(row["ticker"])] = row
        return books

    def ensembles(self, station: Station, target_date: str, unit: str) -> dict[str, list[float]]:
        return self.forecasts.ensembles(station, target_date, unit)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _levels(raw: Any) -> list[tuple[float, float]]:
    rows: list[tuple[float, float]] = []
    for level in raw if isinstance(raw, list) else []:
        if isinstance(level, list) and len(level) >= 2:
            try:
                rows.append((float(level[0]), float(level[1])))
            except (TypeError, ValueError):
                continue
    return rows


def parse_orderbook(payload: dict[str, Any]) -> dict[str, float | None]:
    book = payload.get("orderbook_fp") if isinstance(payload.get("orderbook_fp"), dict) else {}
    yes_levels = _levels(book.get("yes_dollars"))
    no_levels = _levels(book.get("no_dollars"))
    best_yes = max(yes_levels, default=(0.0, 0.0), key=lambda row: row[0])
    best_no = max(no_levels, default=(0.0, 0.0), key=lambda row: row[0])
    yes_bid = best_yes[0] or None
    no_bid = best_no[0] or None
    yes_ask = round(1.0 - best_no[0], 4) if no_bid is not None else None
    no_ask = round(1.0 - best_yes[0], 4) if yes_bid is not None else None
    return {
        "yes_bid": yes_bid,
        "yes_bid_size": best_yes[1] if yes_bid is not None else None,
        "yes_ask": yes_ask,
        "yes_ask_size": best_no[1] if yes_ask is not None else None,
        "no_bid": no_bid,
        "no_bid_size": best_no[1] if no_bid is not None else None,
        "no_ask": no_ask,
        "no_ask_size": best_yes[1] if no_ask is not None else None,
    }


def market_bucket(market: dict[str, Any]) -> KalshiBucket:
    strike_type = str(market.get("strike_type") or "").lower()
    floor = market.get("floor_strike")
    cap = market.get("cap_strike")
    if strike_type == "less":
        threshold = int(_float(cap if cap is not None else floor))
        return KalshiBucket(str(market.get("yes_sub_title") or "below"), None, threshold - 1)
    if strike_type == "greater":
        threshold = int(_float(floor if floor is not None else cap))
        return KalshiBucket(str(market.get("yes_sub_title") or "above"), threshold + 1, None)
    return KalshiBucket(str(market.get("yes_sub_title") or "between"), int(_float(floor)), int(_float(cap)))


def _bucket_probability(bucket: KalshiBucket, values: list[float]) -> float | None:
    if not values:
        return None
    hits = sum(bucket.contains(math.floor(float(value) + 0.5)) for value in values)
    return hits / len(values)


def kalshi_taker_fee(price: float, contracts: float, fee_multiplier: float = 1.0) -> float:
    raw = 0.07 * fee_multiplier * max(0.0, contracts) * price * (1.0 - price)
    return math.ceil(raw * 100.0 - 1e-12) / 100.0


def _hours_until(value: Any, now: datetime) -> float | None:
    try:
        target = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (target - now).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return None


def _load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _target_date(market: dict[str, Any]) -> str:
    return str(market.get("occurrence_datetime") or market.get("close_time") or "")[:10]


def build_report(client: KalshiWeatherClient | Any, *, state_path: Path = STATE_PATH, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    state = _load(state_path)
    open_positions = list(state.get("positions") or [])
    closed_positions = list(state.get("closed_positions") or [])
    forecast_cache = dict(state.get("forecast_cache") or {})
    errors: list[str] = []
    still_open: list[dict[str, Any]] = []
    newly_closed: list[dict[str, Any]] = []

    for position in open_positions:
        try:
            market = client.market(str(position.get("ticker") or ""))
        except Exception as exc:
            errors.append(f"{position.get('ticker')}: settlement refresh failed: {exc}")
            still_open.append(position)
            continue
        status = str(market.get("status") or "").lower()
        result = str(market.get("result") or "").lower()
        if status not in {"finalized", "settled"} or result not in {"yes", "no"}:
            still_open.append(position)
            continue
        won = str(position.get("side") or "").lower() == result
        payout = float(position.get("contracts") or 0.0) if won else 0.0
        closed = {
            **position,
            "exit_at": current.isoformat(),
            "exit_reason": f"kalshi_finalized_{result}",
            "settlement_result": result,
            "won": won,
            "pnl_dollars": round(payout - float(position.get("risk_dollars") or 0.0), 2),
        }
        closed_positions.append(closed)
        newly_closed.append(closed)

    raw_markets: list[tuple[WeatherSeries, dict[str, Any]]] = []
    for series in WEATHER_SERIES.values():
        try:
            raw_markets.extend((series, market) for market in client.markets(series.ticker))
        except Exception as exc:
            errors.append(f"{series.ticker}: market discovery failed: {exc}")

    events = {str(market.get("event_ticker") or "") for _, market in raw_markets if market.get("event_ticker")}
    book_cache: dict[str, dict[str, Any]] = {}
    bulk_orderbooks = getattr(client, "orderbooks", None)
    if callable(bulk_orderbooks):
        tickers = [str(market.get("ticker")) for _, market in raw_markets if market.get("ticker")]
        try:
            book_cache = bulk_orderbooks(tickers)
        except Exception as exc:
            errors.append(f"bulk orderbooks failed: {exc}")
    contexts: list[dict[str, Any]] = []
    by_event: dict[str, list[dict[str, Any]]] = {}
    for series, market in raw_markets:
        event_ticker = str(market.get("event_ticker") or "")
        target_date = _target_date(market)
        cache_key = f"{series.ticker}:{target_date}"
        cached = forecast_cache.get(cache_key) if isinstance(forecast_cache.get(cache_key), dict) else {}
        fetched_at = cached.get("fetched_at")
        age_hours = None
        if fetched_at:
            try:
                age_hours = (current - datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))).total_seconds() / 3600.0
            except ValueError:
                age_hours = None
        if age_hours is None or age_hours >= FORECAST_CACHE_HOURS:
            try:
                models = client.ensembles(series.station, target_date, "F")
                forecast_cache[cache_key] = {"fetched_at": current.isoformat(), "models": models}
            except Exception as exc:
                errors.append(f"{cache_key}: forecast failed: {exc}")
                models = {}
        else:
            models = cached.get("models") if isinstance(cached.get("models"), dict) else {}
        valid_models = {
            name: list(models.get(name) or [])
            for name in REQUIRED_MODEL_FAMILIES
            if len(models.get(name) or []) >= MIN_ENSEMBLE_MEMBERS
        }
        if len(valid_models) != len(REQUIRED_MODEL_FAMILIES):
            continue
        try:
            ticker = str(market.get("ticker") or "")
            book_payload = book_cache.get(ticker) if ticker in book_cache else client.orderbook(ticker)
            quote = parse_orderbook(book_payload)
        except Exception as exc:
            errors.append(f"{market.get('ticker')}: orderbook failed: {exc}")
            continue
        bucket = market_bucket(market)
        probabilities = {name: round(float(_bucket_probability(bucket, values) or 0.0), 4) for name, values in valid_models.items()}
        fair_yes = sum(probabilities.values()) / len(probabilities)
        candidates: list[dict[str, Any]] = []
        for side in ("YES", "NO"):
            ask = quote.get(f"{side.lower()}_ask")
            bid = quote.get(f"{side.lower()}_bid")
            if ask is None or bid is None:
                continue
            fair = fair_yes if side == "YES" else 1.0 - fair_yes
            side_probabilities = probabilities if side == "YES" else {name: 1.0 - value for name, value in probabilities.items()}
            fee = kalshi_taker_fee(float(ask), 1)
            model_edges = {name: round(value - float(ask) - fee, 4) for name, value in side_probabilities.items()}
            spread = float(ask) - float(bid)
            hours = _hours_until(market.get("close_time"), current)
            probability_spread = max(side_probabilities.values()) - min(side_probabilities.values())
            eligible = (
                all(value >= MIN_EDGE for value in model_edges.values())
                and probability_spread <= MAX_MODEL_PROBABILITY_DISAGREEMENT
                and spread <= MAX_SPREAD
                and hours is not None and hours >= MIN_HOURS_TO_CLOSE
            )
            candidates.append({
                "side": side,
                "ask": round(float(ask), 4),
                "bid": round(float(bid), 4),
                "spread": round(spread, 4),
                "fair_probability": round(fair, 4),
                "fee_per_contract": fee,
                "edge": round(fair - float(ask) - fee, 4),
                "model_probabilities": {name: round(value, 4) for name, value in side_probabilities.items()},
                "model_edges": model_edges,
                "model_probability_spread": round(probability_spread, 4),
                "eligible": eligible,
                "hours_to_close": round(hours, 2) if hours is not None else None,
            })
        best = max(candidates, key=lambda row: row["edge"], default=None)
        context = {
            "series_ticker": series.ticker,
            "city": series.city,
            "station_code": series.station_code,
            "nws_issued_by": series.nws_issued_by,
            "ticker": market.get("ticker"),
            "event_ticker": event_ticker,
            "target_date": target_date,
            "bucket": asdict(bucket),
            "status": market.get("status"),
            "rules_primary": market.get("rules_primary"),
            "volume": _float(market.get("volume_fp")),
            "open_interest": _float(market.get("open_interest_fp")),
            "model_member_counts": {name: len(values) for name, values in valid_models.items()},
            "best_opportunity": best,
        }
        contexts.append(context)
        if best and best["eligible"]:
            by_event.setdefault(event_ticker, []).append(context)

    existing_events = {
        str(row.get("event_ticker") or "")
        for row in [*still_open, *closed_positions]
        if row.get("event_ticker")
    }
    todays_risk = sum(
        float(row.get("risk_dollars") or 0.0)
        for row in still_open
        if str(row.get("entry_at") or "")[:10] == current.date().isoformat()
    )
    new_positions: list[dict[str, Any]] = []
    for event_ticker, rows in sorted(by_event.items()):
        if event_ticker in existing_events or len(still_open) >= MAX_OPEN_POSITIONS:
            continue
        best_context = max(rows, key=lambda row: float((row.get("best_opportunity") or {}).get("edge") or 0.0))
        opportunity = best_context["best_opportunity"]
        contracts = MAX_CONTRACTS_PER_POSITION
        risk = round(float(opportunity["ask"]) * contracts + kalshi_taker_fee(float(opportunity["ask"]), contracts), 2)
        if todays_risk + risk > MAX_DAILY_NEW_RISK:
            continue
        position = {
            "paper_position_id": f"{best_context['ticker']}:{current.isoformat()}",
            "ticker": best_context["ticker"],
            "event_ticker": event_ticker,
            "series_ticker": best_context["series_ticker"],
            "city": best_context["city"],
            "station_code": best_context["station_code"],
            "nws_issued_by": best_context["nws_issued_by"],
            "target_date": best_context["target_date"],
            "bucket": best_context["bucket"],
            "side": opportunity["side"],
            "entry_at": current.isoformat(),
            "entry_price": opportunity["ask"],
            "entry_fee_dollars": kalshi_taker_fee(float(opportunity["ask"]), contracts),
            "entry_fair_probability": opportunity["fair_probability"],
            "entry_edge": opportunity["edge"],
            "model_probabilities": opportunity["model_probabilities"],
            "model_edges": opportunity["model_edges"],
            "contracts": contracts,
            "risk_dollars": risk,
            "promotion_grade": True,
            "execution_mode": "paper_only",
            "selection_rule": "best_fee_adjusted_edge_per_city_day",
        }
        still_open.append(position)
        new_positions.append(position)
        existing_events.add(event_ticker)
        todays_risk += risk

    new_state = {
        "schema_version": 1,
        "updated_at": current.isoformat(),
        "forecast_cache": forecast_cache,
        "positions": still_open,
        "closed_positions": closed_positions[-5000:],
    }
    _write(state_path, new_state)
    return {
        "provider": "kalshi_weather_bot",
        "timestamp": current.isoformat(),
        "mode": "paper_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "authenticated_client_present": False,
        "series_monitored": len(WEATHER_SERIES),
        "events_discovered": len(events),
        "markets_modeled": len(contexts),
        "opportunity_count": sum(len(rows) for rows in by_event.values()),
        "independent_event_opportunity_count": len(by_event),
        "new_paper_positions": new_positions,
        "open_paper_positions_count": len(still_open),
        "closed_paper_positions_count": len(closed_positions),
        "newly_closed_positions": newly_closed,
        "modeled_markets": contexts,
        "errors": errors[:100],
        "risk_limits": {
            "min_fee_adjusted_edge_per_model": MIN_EDGE,
            "max_spread": MAX_SPREAD,
            "max_model_probability_disagreement": MAX_MODEL_PROBABILITY_DISAGREEMENT,
            "models_required": list(REQUIRED_MODEL_FAMILIES),
            "max_contracts_per_position": MAX_CONTRACTS_PER_POSITION,
            "max_daily_new_risk": MAX_DAILY_NEW_RISK,
            "max_open_positions": MAX_OPEN_POSITIONS,
        },
        "warnings": [
            "Paper only; no authenticated Kalshi order methods exist in this module.",
            "Only one position per city-day is counted as independent promotion evidence.",
            "Paper entry uses the executable reciprocal ask and includes a conservatively rounded taker fee.",
            "Settlement is accepted only from Kalshi finalized market results tied to the NWS daily climate report.",
        ],
    }


def write_outputs(report: dict[str, Any], report_path: Path = REPORT_PATH, log_path: Path = LOG_PATH) -> None:
    _write(report_path, report)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    report = build_report(KalshiWeatherClient(), state_path=args.state_path)
    write_outputs(report, args.report_path, args.log_path)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Kalshi weather paper report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
