#!/usr/bin/env python3
"""Autonomous paper trader for Polymarket daily-high temperature markets.

Public market, order-book, and forecast endpoints only. This module has no
wallet, signing, allowance, deposit, or order-submission capability.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

GAMMA_URL = "https://gamma-api.polymarket.com"
CLOB_URL = "https://clob.polymarket.com"
GEOBLOCK_URL = "https://polymarket.com/api/geoblock"
ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
ROOT = Path(__file__).resolve().parent.parent
RUNTIME = Path.home() / ".vibe-trading"
REPORT_PATH = RUNTIME / "reports" / "polymarket-weather-bot.json"
STATE_PATH = RUNTIME / "polymarket-weather-paper-state.json"
LOG_PATH = ROOT / "data" / "polymarket_weather_log.jsonl"
NEAR_MISS_LOG_PATH = ROOT / "data" / "polymarket_weather_near_miss_log.jsonl"
LOCK_PATH = RUNTIME / "locks" / "polymarket-weather-bot.lock"

MIN_EDGE = 0.10
NEAR_MISS_MIN_EDGE = 0.05
MAX_SPREAD = 0.10
MIN_ENSEMBLE_MEMBERS = 20
MAX_MODEL_PROBABILITY_DISAGREEMENT = 0.20
MIN_HOURS_TO_END = 2.0
MAX_RISK_PER_POSITION = 5.0
MAX_DAILY_NEW_RISK = 25.0
MAX_OPEN_POSITIONS = 5
FORECAST_CACHE_HOURS = 6.0
TAKE_PROFIT_POINTS = 0.15
STOP_LOSS_POINTS = 0.10
WEATHER_FEE_BUFFER = 0.02
KELLY_FRACTION_CAP = 0.25
LADDER_MAX_LEGS = 3
LADDER_PER_LEG_FRACTION = 0.5
ASYMMETRIC_MIN_MODEL_PROB = 0.15
ASYMMETRIC_MAX_ASK = 0.08
ASYMMETRIC_MIN_EDGE = 0.07
REQUIRED_MODEL_FAMILIES = ("gfs_gefs", "ecmwf_ifs", "icon_eu")


@dataclass(frozen=True)
class Station:
    code: str
    latitude: float
    longitude: float
    timezone: str


STATIONS: dict[str, Station] = {
    row.code: row for row in (
        # North America
        Station("KJFK", 40.6413, -73.7781, "America/New_York"),
        Station("KLGA", 40.7769, -73.8740, "America/New_York"),
        Station("KMIA", 25.7959, -80.2870, "America/New_York"),
        Station("KATL", 33.6407, -84.4277, "America/New_York"),
        Station("KORD", 41.9742, -87.9073, "America/Chicago"),
        Station("KDFW", 32.8998, -97.0403, "America/Chicago"),
        Station("KDAL", 32.8473, -96.8515, "America/Chicago"),
        Station("KHOU", 29.6454, -95.2789, "America/Chicago"),
        Station("KAUS", 30.1975, -97.6664, "America/Chicago"),
        Station("KSEA", 47.4502, -122.3088, "America/Los_Angeles"),
        Station("KLAX", 33.9425, -118.4081, "America/Los_Angeles"),
        Station("KSFO", 37.6213, -122.3790, "America/Los_Angeles"),
        Station("KBKF", 39.7015, -104.7504, "America/Denver"),
        Station("CYYZ", 43.6777, -79.6248, "America/Toronto"),
        Station("MMMX", 19.4363, -99.0721, "America/Mexico_City"),
        Station("MPMG",  8.9934, -79.5568, "America/Panama"),
        # South America
        Station("SAEZ", -34.8222, -58.5358, "America/Argentina/Buenos_Aires"),
        Station("SBGR", -23.4356, -46.4731, "America/Sao_Paulo"),
        # Europe
        Station("EGLL", 51.4700,  -0.4543, "Europe/London"),
        Station("EGLC", 51.5048,   0.0495, "Europe/London"),
        Station("EHAM", 52.3105,   4.7683, "Europe/Amsterdam"),
        Station("EFHK", 60.3172,  24.9633, "Europe/Helsinki"),
        Station("LFPB", 48.9694,   2.4414, "Europe/Paris"),
        Station("LEMD", 40.4983,  -3.5676, "Europe/Madrid"),
        Station("LIMC", 45.6306,   8.7281, "Europe/Rome"),
        Station("EDDM", 48.3538,  11.7861, "Europe/Berlin"),
        Station("EPWA", 52.1657,  20.9671, "Europe/Warsaw"),
        Station("LTFM", 41.2753,  28.7519, "Europe/Istanbul"),
        Station("LTAC", 40.1281,  32.9951, "Europe/Istanbul"),
        Station("UUEE", 55.9726,  37.4146, "Europe/Moscow"),
        # Middle East / Africa
        Station("LLBG", 31.9933,  34.8867, "Asia/Jerusalem"),
        Station("OEJN", 21.6796,  39.1565, "Asia/Riyadh"),
        Station("FACT", -33.9715, 18.6021, "Africa/Johannesburg"),
        # South / Southeast Asia
        Station("OPKC", 24.9065,  67.1609, "Asia/Karachi"),
        Station("VILK", 26.7606,  80.8893, "Asia/Kolkata"),
        Station("WMKK",  2.7456, 101.7101, "Asia/Kuala_Lumpur"),
        Station("RPLL", 14.5086, 121.0196, "Asia/Manila"),
        Station("WSSS",  1.3502, 103.9940, "Asia/Singapore"),
        # East Asia
        Station("ZBAA", 40.0799, 116.5844, "Asia/Shanghai"),
        Station("ZUUU", 30.5784, 103.9479, "Asia/Shanghai"),
        Station("ZUCK", 29.7192, 106.6419, "Asia/Shanghai"),
        Station("ZGGG", 23.3924, 113.2990, "Asia/Shanghai"),
        Station("VHHH", 22.3080, 113.9185, "Asia/Hong_Kong"),
        Station("ZSPD", 31.1443, 121.8083, "Asia/Shanghai"),
        Station("ZGSZ", 22.6395, 113.8107, "Asia/Shanghai"),
        Station("ZSJN", 36.8572, 117.0158, "Asia/Shanghai"),
        Station("ZSQD", 36.2661, 120.3744, "Asia/Shanghai"),
        Station("ZHHH", 30.7838, 114.2081, "Asia/Shanghai"),
        Station("ZHCC", 34.5197, 113.8407, "Asia/Shanghai"),
        Station("RJTT", 35.5533, 139.7811, "Asia/Tokyo"),
        Station("RKSI", 37.4602, 126.4407, "Asia/Seoul"),
        Station("RKPK", 35.1795, 128.9382, "Asia/Seoul"),
        Station("RCSS", 25.0694, 121.5522, "Asia/Taipei"),
        # Pacific
        Station("NZWN", -41.3272, 174.8053, "Pacific/Auckland"),
    )
}

# Fallback for cities where Polymarket description omits the Wunderground ICAO code.
_CITY_NAME_STATION: dict[str, str] = {
    "hong kong": "VHHH",
    "istanbul": "LTFM",
    "moscow": "UUEE",
    "tel aviv": "LLBG",
}


@dataclass(frozen=True)
class TemperatureBucket:
    label: str
    value: int
    kind: str
    unit: str

    def contains(self, observed: int) -> bool:
        if self.kind == "at_or_below":
            return observed <= self.value
        if self.kind == "at_or_above":
            return observed >= self.value
        return observed == self.value


def _json_value(value: Any, default: Any) -> Any:
    if isinstance(value, type(default)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, type(default)) else default
        except json.JSONDecodeError:
            return default
    return default


def parse_bucket(label: str, default_unit: str) -> TemperatureBucket | None:
    text = str(label or "").replace("Â", "")
    match = re.search(r"(-?\d+)\s*°?\s*([CF])?", text, re.IGNORECASE)
    if not match:
        return None
    unit = (match.group(2) or default_unit).upper()
    lower = text.lower()
    kind = "at_or_below" if "below" in lower or "lower" in lower else "at_or_above" if "higher" in lower or "above" in lower else "exact"
    return TemperatureBucket(text, int(match.group(1)), kind, unit)


def parse_event(
    event: dict[str, Any],
    *,
    today: date | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    title = str(event.get("title") or "")
    if not title.lower().startswith("highest temperature in "):
        return None
    slug = str(event.get("slug") or "")
    date_match = re.search(r"-on-([a-z]+)-(\d{1,2})-(\d{4})$", slug)
    if not date_match:
        return None
    try:
        target_date = datetime.strptime("-".join(date_match.groups()), "%B-%d-%Y").date()
    except ValueError:
        return None
    description = str(event.get("description") or "")
    station_matches = re.findall(r"wunderground\.com/history/daily/[^\s)]+/([A-Z0-9]{4})(?:[\s).]|$)", description, re.IGNORECASE)
    station_code = station_matches[-1].upper() if station_matches else ""
    station = STATIONS.get(station_code)
    if station is None:
        city_match = re.match(r"highest temperature in (.+?) on", title, re.IGNORECASE)
        if city_match:
            fallback_code = _CITY_NAME_STATION.get(city_match.group(1).strip().lower())
            if fallback_code:
                station = STATIONS.get(fallback_code)
    unit_match = re.search(r"degrees\s+(Celsius|Fahrenheit)", description, re.IGNORECASE)
    unit = "C" if unit_match and unit_match.group(1).lower().startswith("c") else "F" if unit_match else ""
    if not station or not unit:
        return None
    if today is not None:
        station_today = today
    else:
        current = now or datetime.now(timezone.utc)
        station_today = current.astimezone(ZoneInfo(station.timezone)).date()
    if target_date < station_today:
        return None
    markets: list[dict[str, Any]] = []
    for raw in event.get("markets") or []:
        if not isinstance(raw, dict) or not raw.get("acceptingOrders"):
            continue
        bucket = parse_bucket(str(raw.get("groupItemTitle") or raw.get("question") or ""), unit)
        outcomes = _json_value(raw.get("outcomes"), [])
        tokens = _json_value(raw.get("clobTokenIds"), [])
        if bucket is None or bucket.unit != unit or len(outcomes) != 2 or len(tokens) != 2 or "Yes" not in outcomes:
            continue
        yes_index = outcomes.index("Yes")
        markets.append({
            "market_id": str(raw.get("id") or ""),
            "question": raw.get("question"),
            "bucket": asdict(bucket),
            "yes_token_id": str(tokens[yes_index]),
            "fee_type": raw.get("feeType"),
        })
    if not markets:
        return None
    return {
        "event_id": str(event.get("id") or ""),
        "slug": slug,
        "title": title,
        "target_date": target_date.isoformat(),
        "end_date": event.get("endDate"),
        "station": asdict(station),
        "unit": unit,
        "resolution_description": description,
        "markets": markets,
    }


class PublicClient:
    def __init__(self, session: Any | None = None) -> None:
        if session is None:
            import requests
            session = requests.Session()
        self.session = session

    def _get(self, url: str, params: dict[str, Any]) -> Any:
        response = self.session.get(url, params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def events(self, limit: int = 500) -> list[dict[str, Any]]:
        data = self._get(f"{GAMMA_URL}/events", {"active": "true", "closed": "false", "limit": limit, "tag_slug": "weather"})
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    def geoblock(self) -> dict[str, Any]:
        data = self._get(GEOBLOCK_URL, {})
        return data if isinstance(data, dict) else {}

    def event(self, event_id: str) -> dict[str, Any]:
        data = self._get(f"{GAMMA_URL}/events/{event_id}", {})
        return data if isinstance(data, dict) else {}

    def book(self, token_id: str) -> dict[str, Any]:
        data = self._get(f"{CLOB_URL}/book", {"token_id": token_id})
        return data if isinstance(data, dict) else {}

    def ensembles(self, station: Station, target_date: str, unit: str) -> dict[str, list[float]]:
        data = self._get(ENSEMBLE_URL, {
            "latitude": station.latitude,
            "longitude": station.longitude,
            "hourly": "temperature_2m",
            "models": "gfs_seamless,ecmwf_ifs025,icon_seamless",
            "temperature_unit": "fahrenheit" if unit == "F" else "celsius",
            "timezone": station.timezone,
            "forecast_days": 7,
        })
        hourly = data.get("hourly") if isinstance(data, dict) else None
        if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
            return {}
        indexes = [i for i, stamp in enumerate(hourly["time"]) if str(stamp)[:10] == target_date]
        highs: dict[str, list[float]] = {"gfs_gefs": [], "ecmwf_ifs": [], "icon_eu": []}
        for key, values in hourly.items():
            if not key.startswith("temperature_2m") or not isinstance(values, list):
                continue
            samples = [float(values[i]) for i in indexes if i < len(values) and values[i] is not None]
            if samples:
                if "ncep_gefs" in key:
                    family = "gfs_gefs"
                elif "ecmwf_ifs" in key:
                    family = "ecmwf_ifs"
                elif "icon" in key:
                    family = "icon_eu"
                else:
                    family = ""
                if family:
                    highs[family].append(max(samples))
        return highs

    def ensemble(self, station: Station, target_date: str, unit: str) -> list[float]:
        """Compatibility helper returning the combined two-model distribution."""
        families = self.ensembles(station, target_date, unit)
        return [value for values in families.values() for value in values]


def executable_quote(book: dict[str, Any]) -> dict[str, float | None]:
    def levels(name: str) -> list[tuple[float, float]]:
        out = []
        for row in book.get(name) or []:
            if not isinstance(row, dict):
                continue
            try:
                out.append((float(row["price"]), float(row.get("size") or 0.0)))
            except (KeyError, TypeError, ValueError):
                continue
        return out
    bids, asks = levels("bids"), levels("asks")
    bid = max((price for price, _ in bids), default=None)
    ask = min((price for price, _ in asks), default=None)
    return {"bid": bid, "ask": ask, "spread": (ask - bid) if bid is not None and ask is not None else None}


def _round_resolution(value: float) -> int:
    return math.floor(value + 0.5)


def bucket_probability(bucket: TemperatureBucket, ensemble_highs: list[float]) -> float | None:
    if not ensemble_highs:
        return None
    hits = sum(1 for value in ensemble_highs if bucket.contains(_round_resolution(value)))
    return hits / len(ensemble_highs)


def resolved_yes_price(event: dict[str, Any], market_id: str) -> float | None:
    for market in event.get("markets") or []:
        if not isinstance(market, dict) or str(market.get("id") or "") != str(market_id):
            continue
        outcomes = _json_value(market.get("outcomes"), [])
        prices = _json_value(market.get("outcomePrices"), [])
        if not market.get("closed") or "Yes" not in outcomes or len(prices) != len(outcomes):
            return None
        try:
            price = float(prices[outcomes.index("Yes")])
        except (TypeError, ValueError):
            return None
        return 1.0 if price >= 0.99 else 0.0 if price <= 0.01 else None
    return None


def hours_to_end(end_date: Any, now: datetime | None = None) -> float | None:
    try:
        end = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
        current = now or datetime.now(timezone.utc)
        return (end - current).total_seconds() / 3600.0
    except (TypeError, ValueError):
        return None


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "positions": [], "closed_positions": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"schema_version": 1, "positions": [], "closed_positions": []}
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "positions": [], "closed_positions": []}


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
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


def kelly_fraction(edge: float, ask: float) -> float:
    """Return capped binary Kelly telemetry; this does not control sizing."""
    denominator = 1.0 - ask
    if denominator <= 0:
        return 0.0
    return min(max(edge / denominator, 0.0), KELLY_FRACTION_CAP)


def _ladder_opportunities(
    opportunities: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Select the strongest contiguous 2-3 bucket window per event."""
    by_event: dict[str, list[dict[str, Any]]] = {}
    for row in opportunities:
        by_event.setdefault(row["event_id"], []).append(row)
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    for event_id, rows in by_event.items():
        ordered = sorted(rows, key=lambda row: int(row["bucket"]["value"]))
        runs: list[list[dict[str, Any]]] = []
        for row in ordered:
            if not runs or int(row["bucket"]["value"]) != int(runs[-1][-1]["bucket"]["value"]) + 1:
                runs.append([row])
            else:
                runs[-1].append(row)
        windows = [
            run[start : start + size]
            for run in runs
            for size in range(2, min(LADDER_MAX_LEGS, len(run)) + 1)
            for start in range(0, len(run) - size + 1)
        ]
        if windows:
            best = max(windows, key=lambda legs: sum(float(row.get("edge") or 0.0) for row in legs))
            groups.append((event_id, best))
    return groups


def build_report(client: PublicClient | Any, *, state_path: Path = STATE_PATH, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    state = _load_state(state_path)
    positions = list(state.get("positions") or [])
    closed = list(state.get("closed_positions") or [])
    near_miss_observations = list(state.get("near_miss_observations") or [])
    closed_near_miss_observations = list(state.get("closed_near_miss_observations") or [])
    forecast_cache = dict(state.get("forecast_cache") or {})
    errors: list[str] = []
    venue_eligibility = {
        "source": GEOBLOCK_URL,
        "checked": False,
        "blocked": None,
        "country": None,
        "region": None,
        "status": "unverified",
        "eligible_for_order_submission": False,
    }
    geoblock = getattr(client, "geoblock", None)
    if callable(geoblock):
        try:
            result = geoblock()
            if isinstance(result, dict) and isinstance(result.get("blocked"), bool):
                blocked = bool(result["blocked"])
                venue_eligibility.update({
                    "checked": True,
                    "blocked": blocked,
                    "country": result.get("country"),
                    "region": result.get("region"),
                    "status": "blocked" if blocked else "available",
                    "eligible_for_order_submission": not blocked,
                })
        except Exception as exc:
            errors.append(f"geoblock check unavailable: {exc}")
    parsed_events = [parsed for raw in client.events() if (parsed := parse_event(raw, now=current))]
    opportunities: list[dict[str, Any]] = []
    market_context: dict[str, dict[str, Any]] = {}
    for event in parsed_events:
        station = Station(**event["station"])
        cache_key = f"{station.code}|{event['target_date']}|{event['unit']}"
        cached = forecast_cache.get(cache_key) if isinstance(forecast_cache.get(cache_key), dict) else {}
        cached_at = None
        try:
            cached_at = datetime.fromisoformat(str(cached.get("fetched_at") or "").replace("Z", "+00:00"))
        except ValueError:
            cached_at = None
        try:
            cached_models = cached.get("model_highs") if isinstance(cached.get("model_highs"), dict) else {}
            cache_has_required_models = all(
                len(cached_models.get(name) or []) >= MIN_ENSEMBLE_MEMBERS
                for name in REQUIRED_MODEL_FAMILIES
            )
            if cached_at is not None and cache_has_required_models and (current - cached_at).total_seconds() < FORECAST_CACHE_HOURS * 3600:
                model_highs = cached.get("model_highs") or {}
                forecast_status = "cached_under_6h"
            else:
                if hasattr(client, "ensembles"):
                    model_highs = client.ensembles(station, event["target_date"], event["unit"])
                else:
                    model_highs = {"legacy_single_model": client.ensemble(station, event["target_date"], event["unit"])}
                forecast_cache[cache_key] = {"fetched_at": current.isoformat(), "model_highs": model_highs}
                forecast_status = "fresh_model_cycle"
        except Exception as exc:
            errors.append(f"{event['slug']}: forecast unavailable: {exc}")
            continue
        valid_models = {
            name: model_highs.get(name) or []
            for name in REQUIRED_MODEL_FAMILIES
            if len(model_highs.get(name) or []) >= MIN_ENSEMBLE_MEMBERS
        }
        if len(valid_models) != len(REQUIRED_MODEL_FAMILIES):
            missing = sorted(set(REQUIRED_MODEL_FAMILIES) - set(valid_models))
            errors.append(f"{event['slug']}: required model families unavailable: {','.join(missing)}")
            continue
        highs = [value for values in valid_models.values() for value in values]
        remaining = hours_to_end(event.get("end_date"), current)
        for market in event["markets"]:
            try:
                quote = executable_quote(client.book(market["yes_token_id"]))
            except Exception as exc:
                errors.append(f"{market['market_id']}: book unavailable: {exc}")
                continue
            bucket = TemperatureBucket(**market["bucket"])
            model_probabilities = {name: round(float(bucket_probability(bucket, values) or 0.0), 4) for name, values in valid_models.items()}
            fair = sum(model_probabilities.values()) / len(model_probabilities)
            context = {**market, "event_id": event["event_id"], "slug": event["slug"], "title": event["title"], "target_date": event["target_date"], "station": event["station"], "unit": event["unit"], "forecast_status": forecast_status, "forecast_fetched_at": forecast_cache.get(cache_key, {}).get("fetched_at"), "ensemble_members": len(highs), "model_member_counts": {name: len(values) for name, values in valid_models.items()}, "model_probabilities": model_probabilities, "ensemble_high_min": round(min(highs), 2), "ensemble_high_max": round(max(highs), 2), "fair_yes": round(float(fair or 0.0), 4), **quote, "hours_to_end": round(remaining, 2) if remaining is not None else None}
            market_context[market["market_id"]] = context
            ask, spread = quote["ask"], quote["spread"]
            fee_buffer = WEATHER_FEE_BUFFER if market.get("fee_type") == "weather_fees" else 0.0
            edge = (fair - ask - fee_buffer) if fair is not None and ask is not None else None
            context["fee_buffer"] = fee_buffer
            context["edge"] = round(edge, 4) if edge is not None else None
            model_edges = {name: round(probability - float(ask or 0.0) - fee_buffer, 4) for name, probability in model_probabilities.items()}
            context["model_edges"] = model_edges
            probability_spread = max(model_probabilities.values()) - min(model_probabilities.values())
            context["model_probability_spread"] = round(probability_spread, 4)
            context["model_agreement"] = len(model_edges) == len(REQUIRED_MODEL_FAMILIES) and probability_spread <= MAX_MODEL_PROBABILITY_DISAGREEMENT and all(value >= MIN_EDGE for value in model_edges.values())
            context["eligible"] = bool(edge is not None and edge >= MIN_EDGE and context["model_agreement"] and spread is not None and spread <= MAX_SPREAD and remaining is not None and remaining >= MIN_HOURS_TO_END and 0.02 <= ask <= 0.95)
            context["near_miss_candidate"] = bool(
                edge is not None
                and NEAR_MISS_MIN_EDGE <= edge < MIN_EDGE
                and len(model_edges) == len(REQUIRED_MODEL_FAMILIES)
                and probability_spread <= MAX_MODEL_PROBABILITY_DISAGREEMENT
                and all(value >= NEAR_MISS_MIN_EDGE for value in model_edges.values())
                and spread is not None and spread <= MAX_SPREAD
                and remaining is not None and remaining >= MIN_HOURS_TO_END
                and 0.02 <= ask <= 0.95
            )
            fair_yes_val = float(fair or 0.0)
            context["asymmetric_candidate"] = bool(
                ask is not None
                and ASYMMETRIC_MIN_MODEL_PROB <= fair_yes_val
                and 0.02 <= ask <= ASYMMETRIC_MAX_ASK
                and edge is not None and edge >= ASYMMETRIC_MIN_EDGE
                and remaining is not None and remaining >= MIN_HOURS_TO_END
            )
            if context["eligible"]:
                opportunities.append(context)

    near_miss_candidates = [ctx for ctx in market_context.values() if ctx.get("near_miss_candidate")]
    active_near_misses: list[dict[str, Any]] = []
    newly_observed_near_misses: list[dict[str, Any]] = []
    newly_resolved_near_misses: list[dict[str, Any]] = []
    for observation in near_miss_observations:
        context = market_context.get(str(observation.get("market_id") or ""))
        settlement = None
        if context is None:
            try:
                if hasattr(client, "event"):
                    settlement = resolved_yes_price(
                        client.event(str(observation.get("event_id") or "")),
                        str(observation.get("market_id") or ""),
                    )
            except Exception as exc:
                errors.append(f"{observation.get('market_id')}: near-miss settlement unavailable: {exc}")
        if settlement is not None:
            entry_ask = float(observation.get("entry_ask") or 0.0)
            shares = math.floor(1.0 / entry_ask) if entry_ask > 0 else 0
            resolved = {
                **observation,
                "resolved_at": current.isoformat(),
                "resolved_yes": settlement,
                "would_win": settlement == 1.0,
                "hypothetical_risk_dollars": round(shares * entry_ask, 2),
                "hypothetical_pnl_dollars": round((settlement - entry_ask) * shares, 2),
            }
            closed_near_miss_observations.append(resolved)
            newly_resolved_near_misses.append(resolved)
        else:
            active_near_misses.append({
                **observation,
                "mark_bid": context.get("bid") if context else None,
                "mark_status": "observed" if context and context.get("bid") is not None else "unavailable",
            })
    observed_near_miss_ids = {
        str(row.get("market_id") or "")
        for row in [*active_near_misses, *closed_near_miss_observations]
    }
    for candidate in near_miss_candidates:
        if str(candidate["market_id"]) in observed_near_miss_ids:
            continue
        observation = {
            "near_miss_id": f"{candidate['market_id']}:{current.isoformat()}",
            "event_id": candidate["event_id"],
            "market_id": candidate["market_id"],
            "slug": candidate["slug"],
            "target_date": candidate["target_date"],
            "station": candidate["station"],
            "bucket": candidate["bucket"],
            "observed_at": current.isoformat(),
            "entry_ask": candidate["ask"],
            "entry_bid": candidate["bid"],
            "entry_edge": candidate["edge"],
            "entry_fair_yes": candidate["fair_yes"],
            "entry_fee_buffer": candidate["fee_buffer"],
            "entry_lead_hours": candidate["hours_to_end"],
            "model_probabilities": candidate["model_probabilities"],
            "model_edges": candidate["model_edges"],
            "model_probability_spread": candidate["model_probability_spread"],
            "execution_mode": "research_only",
            "promotion_grade": False,
        }
        active_near_misses.append(observation)
        newly_observed_near_misses.append(observation)
        observed_near_miss_ids.add(str(candidate["market_id"]))

    still_open: list[dict[str, Any]] = []
    for position in positions:
        if "entry_fee_buffer" not in position:
            gross_edge = float(position.get("entry_edge") or 0.0)
            position["entry_edge_gross"] = gross_edge
            position["entry_fee_buffer"] = WEATHER_FEE_BUFFER
            position["entry_edge"] = round(gross_edge - WEATHER_FEE_BUFFER, 4)
        if "entry_model_agreement" not in position:
            position["entry_model_agreement"] = False
            position["promotion_grade"] = False
        probabilities = position.get("model_probabilities") if isinstance(position.get("model_probabilities"), dict) else {}
        if len(probabilities) >= 2 and max(float(value) for value in probabilities.values()) - min(float(value) for value in probabilities.values()) > MAX_MODEL_PROBABILITY_DISAGREEMENT:
            position["entry_model_agreement"] = False
            position["promotion_grade"] = False
            position["evidence_invalidation_reason"] = "model_probability_disagreement_over_20_points"
        context = market_context.get(str(position.get("market_id")))
        if not context:
            settlement = None
            try:
                if hasattr(client, "event"):
                    settlement = resolved_yes_price(client.event(str(position.get("event_id") or "")), str(position.get("market_id") or ""))
            except Exception as exc:
                errors.append(f"{position.get('market_id')}: settlement lookup unavailable: {exc}")
            if settlement is not None:
                entry = float(position["entry_price"])
                closed.append({**position, "exit_at": current.isoformat(), "exit_bid": settlement, "exit_reason": "resolved_settlement", "pnl_dollars": round((settlement - entry) * float(position["shares"]), 2)})
                continue
            position["mark_status"] = "unavailable"
            still_open.append(position)
            continue
        if context.get("bid") is None:
            position["mark_status"] = "unavailable"
            still_open.append(position)
            continue
        bid = float(context["bid"])
        entry = float(position["entry_price"])
        reason = None
        if bid >= entry + TAKE_PROFIT_POINTS:
            reason = "take_profit"
        elif bid <= max(0.0, entry - STOP_LOSS_POINTS):
            reason = "stop_loss"
        elif context.get("hours_to_end") is not None and float(context["hours_to_end"]) < MIN_HOURS_TO_END:
            reason = "resolution_window"
        elif float(context.get("fair_yes") or 0.0) <= bid:
            reason = "edge_closed"
        if reason:
            closed.append({**position, "exit_at": current.isoformat(), "exit_bid": bid, "exit_reason": reason, "pnl_dollars": round((bid - entry) * float(position["shares"]), 2)})
        else:
            still_open.append({**position, "mark_status": "observed", "mark_bid": bid, "unrealized_pnl_dollars": round((bid - entry) * float(position["shares"]), 2)})

    opened_ids = {str(position.get("market_id")) for position in still_open}
    closed_ids = {str(position.get("market_id")) for position in closed}
    todays_risk = sum(
        float(position.get("risk_dollars") or 0.0)
        for position in [*still_open, *closed]
        if str(position.get("entry_at") or "")[:10] == current.date().isoformat()
    )
    new_positions = []
    ladder_groups = _ladder_opportunities(opportunities)
    opened_ladder_event_ids: set[str] = set()
    for event_id, legs in ladder_groups:
        if len(still_open) + len(legs) > MAX_OPEN_POSITIONS or todays_risk >= MAX_DAILY_NEW_RISK:
            continue
        if any(leg["market_id"] in opened_ids or leg["market_id"] in closed_ids for leg in legs):
            continue
        event_risk = min(MAX_RISK_PER_POSITION, MAX_DAILY_NEW_RISK - todays_risk)
        per_leg_risk = event_risk / len(legs)
        staged: list[tuple[dict[str, Any], int, float]] = []
        for leg in legs:
            risk = min(per_leg_risk, MAX_RISK_PER_POSITION * LADDER_PER_LEG_FRACTION)
            shares = math.floor(risk / float(leg["ask"]))
            if shares < 3:
                staged = []
                break
            cost = round(shares * float(leg["ask"]), 2)
            staged.append((leg, shares, cost))
        if len(staged) != len(legs):
            continue
        for leg, shares, cost in staged:
            raw_kelly = float(leg["edge"]) / max(1.0 - float(leg["ask"]), 0.01)
            position = {"paper_position_id": f"{leg['market_id']}:{current.isoformat()}", "event_id": leg["event_id"], "market_id": leg["market_id"], "slug": leg["slug"], "target_date": leg["target_date"], "station": leg["station"], "bucket": leg["bucket"], "yes_token_id": leg["yes_token_id"], "entry_at": current.isoformat(), "entry_price": leg["ask"], "entry_fair_yes": leg["fair_yes"], "entry_edge": leg["edge"], "entry_fee_buffer": leg["fee_buffer"], "entry_lead_hours": leg["hours_to_end"], "entry_model_agreement": True, "promotion_grade": True, "model_probabilities": leg["model_probabilities"], "model_edges": leg["model_edges"], "ensemble_members": leg["ensemble_members"], "shares": shares, "risk_dollars": cost, "kelly_fraction_raw": round(raw_kelly, 4), "kelly_fraction": round(kelly_fraction(float(leg["edge"]), float(leg["ask"])), 4), "sizing_method": "fixed_event_cap_ladder_kelly_telemetry", "ladder_event_id": event_id, "ladder_leg_count": len(legs), "execution_mode": "paper_only"}
            still_open.append(position)
            new_positions.append(position)
            opened_ids.add(leg["market_id"])
            todays_risk += cost
        opened_ladder_event_ids.add(event_id)

    for row in sorted(opportunities, key=lambda item: float(item.get("edge") or 0.0), reverse=True):
        if len(still_open) >= MAX_OPEN_POSITIONS or todays_risk >= MAX_DAILY_NEW_RISK:
            break
        if row["market_id"] in opened_ids or row["market_id"] in closed_ids or row["event_id"] in opened_ladder_event_ids:
            continue
        risk = min(MAX_RISK_PER_POSITION, MAX_DAILY_NEW_RISK - todays_risk)
        shares = math.floor(risk / float(row["ask"]))
        if shares < 5:
            continue
        cost = round(shares * float(row["ask"]), 2)
        raw_kelly = float(row["edge"]) / max(1.0 - float(row["ask"]), 0.01)
        position = {"paper_position_id": f"{row['market_id']}:{current.isoformat()}", "event_id": row["event_id"], "market_id": row["market_id"], "slug": row["slug"], "target_date": row["target_date"], "station": row["station"], "bucket": row["bucket"], "yes_token_id": row["yes_token_id"], "entry_at": current.isoformat(), "entry_price": row["ask"], "entry_fair_yes": row["fair_yes"], "entry_edge": row["edge"], "entry_fee_buffer": row["fee_buffer"], "entry_lead_hours": row["hours_to_end"], "entry_model_agreement": True, "promotion_grade": True, "model_probabilities": row["model_probabilities"], "model_edges": row["model_edges"], "ensemble_members": row["ensemble_members"], "shares": shares, "risk_dollars": cost, "kelly_fraction_raw": round(raw_kelly, 4), "kelly_fraction": round(kelly_fraction(float(row["edge"]), float(row["ask"])), 4), "sizing_method": "fixed_position_cap_kelly_telemetry", "execution_mode": "paper_only"}
        still_open.append(position)
        new_positions.append(position)
        opened_ids.add(row["market_id"])
        todays_risk += cost

    asymmetric_candidates = [ctx for ctx in market_context.values() if ctx.get("asymmetric_candidate")]

    state = {"schema_version": 1, "updated_at": current.isoformat(), "forecast_cache": forecast_cache, "positions": still_open, "closed_positions": closed[-1000:], "near_miss_observations": active_near_misses, "closed_near_miss_observations": closed_near_miss_observations[-5000:]}
    _atomic_write(state_path, state)
    return {"provider": "polymarket_weather_bot", "date": current.date().isoformat(), "timestamp": current.isoformat(), "mode": "paper_only", "execution_enabled": False, "can_submit_orders": False, "wallet_connected": False, "venue_eligibility": venue_eligibility, "events_discovered": len(parsed_events), "markets_modeled": len(market_context), "opportunity_count": len(opportunities), "new_paper_positions": new_positions, "open_paper_positions": still_open, "closed_paper_positions_count": len(closed), "modeled_markets": list(market_context.values()), "top_opportunities": sorted(opportunities, key=lambda item: float(item.get("edge") or 0.0), reverse=True)[:20], "near_miss_candidates": sorted(near_miss_candidates, key=lambda item: float(item.get("edge") or 0.0), reverse=True)[:50], "new_near_miss_observations": newly_observed_near_misses, "open_near_miss_observations_count": len(active_near_misses), "closed_near_miss_observations_count": len(closed_near_miss_observations), "newly_resolved_near_misses": newly_resolved_near_misses, "asymmetric_candidates": sorted(asymmetric_candidates, key=lambda item: float(item.get("fair_yes") or 0.0), reverse=True)[:10], "ladder_groups_found": len(ladder_groups), "errors": errors[:50], "risk_limits": {"min_fee_adjusted_edge": MIN_EDGE, "near_miss_min_fee_adjusted_edge": NEAR_MISS_MIN_EDGE, "independent_models_required": len(REQUIRED_MODEL_FAMILIES), "max_model_probability_disagreement": MAX_MODEL_PROBABILITY_DISAGREEMENT, "max_risk_per_position": MAX_RISK_PER_POSITION, "max_daily_new_risk": MAX_DAILY_NEW_RISK, "max_open_positions": MAX_OPEN_POSITIONS, "kelly_fraction_cap": KELLY_FRACTION_CAP, "ladder_max_legs": LADDER_MAX_LEGS, "asymmetric_min_model_prob": ASYMMETRIC_MIN_MODEL_PROB, "asymmetric_max_ask": ASYMMETRIC_MAX_ASK}, "warnings": ["Paper simulation only; no Polymarket credentials or order methods exist.", "Jurisdiction eligibility is checked against Polymarket's official geoblock endpoint and fails closed when blocked or unavailable.", "Forecast probabilities are model estimates, not guarantees.", "Eligibility requires fresh GFS, ECMWF, and ICON families, fee-adjusted edge above 10% in each, and no more than 20 points of probability disagreement.", "Near misses are a separate 5%-to-under-10% research cohort and can never create paper positions.", "Kelly values are telemetry only; paper sizing remains bounded by fixed position and event caps.", "Ladder positions are all-or-none adjacent-bucket baskets capped at $5 total risk per event.", "Asymmetric candidates are research-only; no paper positions are opened for them.", "Unknown stations, units, stale dates, thin forecasts, wide spreads, and near-resolution events fail closed.", "Paper fills use displayed asks and exits use displayed bids; queue position and market impact remain unmodeled."]}


def write_outputs(
    report: dict[str, Any],
    report_path: Path = REPORT_PATH,
    log_path: Path = LOG_PATH,
    near_miss_log_path: Path = NEAR_MISS_LOG_PATH,
) -> None:
    _atomic_write(report_path, report)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")
    near_miss_log_path.parent.mkdir(parents=True, exist_ok=True)
    near_miss_snapshot = {
        "provider": "polymarket_weather_near_miss_cohort",
        "timestamp": report.get("timestamp"),
        "mode": "research_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "edge_band": {"minimum_inclusive": NEAR_MISS_MIN_EDGE, "maximum_exclusive": MIN_EDGE},
        "candidates": report.get("near_miss_candidates") or [],
        "new_observations": report.get("new_near_miss_observations") or [],
        "newly_resolved": report.get("newly_resolved_near_misses") or [],
        "open_count": report.get("open_near_miss_observations_count", 0),
        "closed_count": report.get("closed_near_miss_observations_count", 0),
    }
    with near_miss_log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(near_miss_snapshot, separators=(",", ":"), sort_keys=True) + "\n")


@contextmanager
def single_instance(path: Path = LOCK_PATH):
    """Fail closed when another scheduled scan owns the Windows file lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        import msvcrt
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("polymarket weather scan already running") from exc
        yield
    finally:
        try:
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        handle.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--state-path", type=Path, default=STATE_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--near-miss-log-path", type=Path, default=NEAR_MISS_LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    with single_instance():
        report = build_report(PublicClient(), state_path=args.state_path)
        write_outputs(report, args.report_path, args.log_path, args.near_miss_log_path)
    if args.do_print:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Polymarket weather paper report written to {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
