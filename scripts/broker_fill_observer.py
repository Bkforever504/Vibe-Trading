#!/usr/bin/env python3
"""Observe recent Alpaca fills and link them to canonical plans, read-only.

This adapter is deliberately separated from order submission.  It exposes only
two fixed Alpaca Trading API GET routes, writes one redacted snapshot report,
and never persists broker/account/order identifiers or credentials.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import requests


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "broker-fill-observer.json"
PLAN_REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "pattern-grader-grades.json"

ALLOWED_METHOD = "GET"
ALLOWED_ENDPOINTS = frozenset({"/v2/account/activities/FILL", "/v2/orders"})
ALLOWED_BASE_URLS = frozenset(
    {
        "https://api.alpaca.markets",
        "https://paper-api.alpaca.markets",
    }
)
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9./_-]{1,48}$")
Fetcher = Callable[..., Any]


@dataclass(frozen=True)
class ObservationBounds:
    """Hard limits for one broker observation cycle."""

    lookback_days: int = 7
    max_pages: int = 10
    page_size: int = 100
    timeout_seconds: float = 12.0
    linkage_window_minutes: int = 240

    def validate(self) -> "ObservationBounds":
        if not 1 <= int(self.lookback_days) <= 30:
            raise ValueError("lookback_days must be between 1 and 30")
        if not 1 <= int(self.max_pages) <= 10:
            raise ValueError("max_pages must be between 1 and 10")
        if not 1 <= int(self.page_size) <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if not 1.0 <= float(self.timeout_seconds) <= 30.0:
            raise ValueError("timeout_seconds must be between 1 and 30")
        if not 1 <= int(self.linkage_window_minutes) <= 1440:
            raise ValueError("linkage_window_minutes must be between 1 and 1440")
        return self


def validate_request(method: str, endpoint: str) -> None:
    """Fail closed before a caller can reach any write or arbitrary route."""
    if str(method).upper() != ALLOWED_METHOD:
        raise ValueError("Alpaca broker fill observer is GET-only")
    if endpoint not in ALLOWED_ENDPOINTS:
        raise ValueError("Alpaca broker fill observer endpoint is not allowlisted")


def validate_base_url(base_url: str) -> str:
    normalized = str(base_url).strip().rstrip("/")
    if normalized not in ALLOWED_BASE_URLS:
        raise ValueError("Alpaca broker fill observer base URL is not allowlisted")
    return normalized


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_symbol(value: Any) -> str | None:
    symbol = str(value or "").strip().upper()
    return symbol if SYMBOL_PATTERN.fullmatch(symbol) else None


def _payload_list(payload: Any) -> list[Mapping[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("Alpaca read returned an unexpected payload type")
    return [row for row in payload if isinstance(row, Mapping)]


def _fetch(
    fetcher: Fetcher,
    *,
    endpoint: str,
    params: Mapping[str, Any],
    timeout: float,
) -> list[Mapping[str, Any]]:
    validate_request(ALLOWED_METHOD, endpoint)
    payload = fetcher(
        method=ALLOWED_METHOD,
        endpoint=endpoint,
        params=dict(params),
        timeout=float(timeout),
    )
    return _payload_list(payload)


def _default_fetcher() -> Fetcher:
    """Reuse the configured Alpaca broker profile without exposing its values."""
    from strategies import flip_bot

    if not flip_bot.KEY or not flip_bot.SECRET:
        raise RuntimeError("alpaca_auth_unavailable")
    base_url = validate_base_url(flip_bot.BASE)
    headers = {
        "APCA-API-KEY-ID": flip_bot.KEY,
        "APCA-API-SECRET-KEY": flip_bot.SECRET,
    }
    session = requests.Session()

    def fetcher(*, method: str, endpoint: str, params: Mapping[str, Any], timeout: float) -> Any:
        validate_request(method, endpoint)
        response = session.get(
            f"{base_url}{endpoint}",
            headers=headers,
            params=dict(params),
            timeout=timeout,
            allow_redirects=False,
        )
        if 300 <= response.status_code < 400:
            raise RuntimeError("alpaca_redirect_refused")
        response.raise_for_status()
        return response.json()

    return fetcher


def _order_index(orders: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """Keep identifiers only in memory for enrichment; none enter the report."""
    result: dict[str, Mapping[str, Any]] = {}
    for order in orders:
        order_id = order.get("id")
        if order_id is not None:
            result[str(order_id)] = order
    return result


def _fee_total(activity: Mapping[str, Any]) -> tuple[float | None, str]:
    keys = ("fee", "fees", "commission", "regulatory_fee", "transaction_fee")
    present = False
    total = 0.0
    for key in keys:
        if key not in activity or activity.get(key) is None:
            continue
        value = _finite(activity.get(key))
        if value is None:
            continue
        present = True
        total += abs(value)
    return (round(total, 8), "reported") if present else (None, "unavailable")


def _fill_state(activity: Mapping[str, Any], order: Mapping[str, Any]) -> str:
    leaves = _finite(activity.get("leaves_qty"))
    status = str(order.get("status") or activity.get("order_status") or "").lower()
    if (leaves is not None and leaves > 0) or status == "partially_filled":
        return "partial_fill"
    order_qty = _finite_positive(order.get("qty"))
    filled_qty = _finite_positive(order.get("filled_qty"))
    if order_qty is not None and filled_qty is not None and filled_qty < order_qty:
        return "partial_fill"
    return "fill"


def _normalize_activity(
    activity: Mapping[str, Any],
    orders: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, str | None]:
    order = orders.get(str(activity.get("order_id") or ""), {})
    symbol = _safe_symbol(activity.get("symbol") or order.get("symbol"))
    side = str(activity.get("side") or order.get("side") or "").strip().lower()
    quantity = _finite_positive(activity.get("qty") or activity.get("quantity"))
    price = _finite_positive(activity.get("price"))
    filled_at = _parse_time(
        activity.get("transaction_time")
        or activity.get("filled_at")
        or activity.get("timestamp")
    )
    if symbol is None or side not in {"buy", "sell"} or quantity is None or price is None or filled_at is None:
        return None, "malformed_fill"
    fees, fee_status = _fee_total(activity)
    return (
        {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "filled_at": _iso_utc(filled_at),
            "fill_state": _fill_state(activity, order),
            "fees": fees,
            "fee_status": fee_status,
            "_filled_at_dt": filled_at,
        },
        None,
    )


def _nested(mapping: Mapping[str, Any], *path: str) -> Any:
    current: Any = mapping
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _plan_fields(plan: Mapping[str, Any]) -> tuple[str, str, str, datetime] | None:
    detection_id = str(plan.get("detection_id") or plan.get("lifecycle_id") or "").strip()
    symbol = _safe_symbol(plan.get("symbol") or _nested(plan, "immutable_plan", "symbol"))
    direction = str(
        plan.get("direction")
        or _nested(plan, "immutable_plan", "direction")
        or _nested(plan, "best_setup", "direction")
        or ""
    ).lower()
    expected_side = {
        "bullish": "buy",
        "bull": "buy",
        "long": "buy",
        "buy": "buy",
        "bearish": "sell",
        "bear": "sell",
        "short": "sell",
        "sell": "sell",
    }.get(direction)
    triggered_at = _parse_time(
        plan.get("trigger_bar_ts")
        or plan.get("detected_at")
        or plan.get("timestamp")
        or _nested(plan, "immutable_plan", "trigger_bar_ts")
    )
    if not detection_id or symbol is None or expected_side is None or triggered_at is None:
        return None
    return detection_id, symbol, expected_side, triggered_at


def _link_fill(
    fill: Mapping[str, Any],
    plans: Iterable[Mapping[str, Any]],
    *,
    window_minutes: int,
) -> dict[str, Any]:
    fill_time = fill.get("_filled_at_dt")
    candidates: list[tuple[str, float]] = []
    if isinstance(fill_time, datetime):
        for plan in plans:
            fields = _plan_fields(plan)
            if fields is None:
                continue
            detection_id, symbol, expected_side, triggered_at = fields
            lag_seconds = (fill_time - triggered_at).total_seconds()
            if (
                symbol == fill.get("symbol")
                and expected_side == fill.get("side")
                and 0 <= lag_seconds <= window_minutes * 60
            ):
                candidates.append((detection_id, lag_seconds))
    base = {
        "detection_id": None,
        "method": "symbol_direction_causal_time_window_v1",
        "candidate_count": len(candidates),
        "lag_seconds": None,
    }
    if len(candidates) == 1:
        detection_id, lag_seconds = candidates[0]
        return {**base, "status": "matched", "detection_id": detection_id, "lag_seconds": round(lag_seconds, 3)}
    if len(candidates) > 1:
        return {**base, "status": "ambiguous"}
    return {**base, "status": "unmatched"}


def _dedupe_key(activity: Mapping[str, Any]) -> tuple[Any, ...]:
    identifier = activity.get("id")
    if identifier is not None:
        return ("id", str(identifier))
    return (
        "fields",
        activity.get("order_id"),
        activity.get("symbol"),
        activity.get("side"),
        activity.get("qty"),
        activity.get("price"),
        activity.get("transaction_time"),
    )


def observe_fills(
    *,
    fetcher: Fetcher,
    plans: Iterable[Mapping[str, Any]],
    now: datetime | None = None,
    bounds: ObservationBounds | None = None,
) -> dict[str, Any]:
    """Fetch and redact one bounded snapshot using an injected GET transport."""
    limits = (bounds or ObservationBounds()).validate()
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    observed_at = observed_at.astimezone(timezone.utc)
    after = observed_at - timedelta(days=limits.lookback_days)
    common_window = {"after": _iso_utc(after), "until": _iso_utc(observed_at), "direction": "desc"}

    orders = _fetch(
        fetcher,
        endpoint="/v2/orders",
        params={**common_window, "status": "all", "limit": 500, "nested": "false"},
        timeout=limits.timeout_seconds,
    )
    order_index = _order_index(orders)

    raw_fills: list[Mapping[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    page_token: str | None = None
    pages_observed = 0
    for _ in range(limits.max_pages):
        params: dict[str, Any] = {**common_window, "page_size": limits.page_size}
        if page_token:
            params["page_token"] = page_token
        page = _fetch(
            fetcher,
            endpoint="/v2/account/activities/FILL",
            params=params,
            timeout=limits.timeout_seconds,
        )
        pages_observed += 1
        for activity in page:
            key = _dedupe_key(activity)
            if key not in seen:
                seen.add(key)
                raw_fills.append(activity)
        next_token = str(page[-1].get("id") or "") if page else ""
        if len(page) < limits.page_size or not next_token:
            break
        page_token = next_token

    canonical_plans = [plan for plan in plans if isinstance(plan, Mapping)]
    normalized: list[dict[str, Any]] = []
    skipped = 0
    for activity in raw_fills:
        fill, error = _normalize_activity(activity, order_index)
        if fill is None:
            skipped += int(error == "malformed_fill")
            continue
        linkage = _link_fill(fill, canonical_plans, window_minutes=limits.linkage_window_minutes)
        fill.pop("_filled_at_dt", None)
        normalized.append(
            {
                **fill,
                "linkage": linkage,
                "source": {
                    "provider": "alpaca",
                    "label": "alpaca_account_activity_fill",
                    "method": "GET",
                    "endpoint": "/v2/account/activities/FILL",
                },
                "execution_enabled": False,
                "can_submit_orders": False,
            }
        )
    normalized.sort(key=lambda row: str(row.get("filled_at") or ""))
    summary = {
        "fill_count": len(normalized),
        "partial_fill_count": sum(row["fill_state"] == "partial_fill" for row in normalized),
        "matched_count": sum(row["linkage"]["status"] == "matched" for row in normalized),
        "ambiguous_count": sum(row["linkage"]["status"] == "ambiguous" for row in normalized),
        "unmatched_count": sum(row["linkage"]["status"] == "unmatched" for row in normalized),
        "skipped_malformed_count": skipped,
    }
    return {
        "schema_version": 1,
        "provider": "broker_fill_observer",
        "generated_at": _iso_utc(observed_at),
        "status": "ok" if normalized else "no_fills",
        "mode": "read_only_redacted_broker_observation",
        "lookback": {
            "after": _iso_utc(after),
            "until": _iso_utc(observed_at),
            "days": limits.lookback_days,
        },
        "request_policy": {
            "allowed_method": ALLOWED_METHOD,
            "allowed_endpoints": sorted(ALLOWED_ENDPOINTS),
            "max_pages": limits.max_pages,
            "page_size": limits.page_size,
            "timeout_seconds": limits.timeout_seconds,
            "activity_pages_observed": pages_observed,
        },
        "privacy": {
            "raw_payloads_persisted": False,
            "broker_and_account_identifiers_persisted": False,
            "credentials_persisted": False,
        },
        "summary": summary,
        "fills": normalized,
        "errors": [],
        "warnings": [
            "Observed broker fills are evidence, not order authority.",
            "Linkage is withheld when symbol, direction, and causal time do not identify exactly one plan.",
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _empty_failure_report(now: datetime, exc: Exception) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "provider": "broker_fill_observer",
        "generated_at": _iso_utc(now),
        "status": "unavailable",
        "mode": "read_only_redacted_broker_observation",
        "summary": {
            "fill_count": 0,
            "partial_fill_count": 0,
            "matched_count": 0,
            "ambiguous_count": 0,
            "unmatched_count": 0,
            "skipped_malformed_count": 0,
        },
        "fills": [],
        # Exception text is intentionally excluded because HTTP/client errors can
        # echo credentials, account IDs, order IDs, or request details.
        "errors": [{"type": type(exc).__name__, "reason": "broker_read_unavailable"}],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def load_canonical_plans(path: Path = PLAN_REPORT_PATH) -> list[Mapping[str, Any]]:
    """Load only the known local pattern report; malformed data fails to empty."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, Mapping):
        return []
    rows = payload.get("latest_detections") or payload.get("detections") or []
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def run_once(
    *,
    fetcher: Fetcher | None = None,
    plans: Iterable[Mapping[str, Any]] | None = None,
    now: datetime | None = None,
    bounds: ObservationBounds | None = None,
    report_path: Path = REPORT_PATH,
) -> dict[str, Any]:
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    try:
        transport = fetcher or _default_fetcher()
        report = observe_fills(
            fetcher=transport,
            plans=list(plans) if plans is not None else load_canonical_plans(),
            now=observed_at,
            bounds=bounds,
        )
    except Exception as exc:
        report = _empty_failure_report(observed_at.astimezone(timezone.utc), exc)
    _atomic_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=float, default=12.0)
    parser.add_argument("--linkage-window-minutes", type=int, default=240)
    args = parser.parse_args()
    bounds = ObservationBounds(
        lookback_days=args.lookback_days,
        max_pages=args.max_pages,
        page_size=args.page_size,
        timeout_seconds=args.timeout_seconds,
        linkage_window_minutes=args.linkage_window_minutes,
    ).validate()
    result = run_once(bounds=bounds)
    print(
        json.dumps(
            {
                "status": result["status"],
                "fill_count": result["summary"]["fill_count"],
                "matched_count": result["summary"]["matched_count"],
                "execution_enabled": False,
                "can_submit_orders": False,
            },
            sort_keys=True,
        )
    )
    return 0 if result["status"] != "unavailable" else 1


if __name__ == "__main__":
    raise SystemExit(main())
