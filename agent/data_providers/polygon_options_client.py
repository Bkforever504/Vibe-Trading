"""Cost-guarded, read-only Polygon options-chain adapter.

The adapter intentionally returns status-bearing dictionaries instead of raising
for provider availability failures.  Consumers can therefore fail over without
mistaking missing market data for an empty options chain.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


DEFAULT_BUDGET_CONFIG = Path("config/paid_api_budget.json")
DEFAULT_LEDGER = Path.home() / ".vibe-trading" / "data" / "polygon_options_call_ledger.jsonl"
DEFAULT_COST_DIR = Path.home() / ".vibe-trading" / "data" / "paid_api_costs"
FAIL_STATUSES = {"not_configured", "budget_exceeded", "timeout", "missing"}


class PolygonBudgetExceededError(RuntimeError):
    """Raised by the strict budget guard before any provider call."""


@dataclass(frozen=True)
class _CacheEntry:
    inserted_at: float
    value: dict[str, Any]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "__dict__"):
        return vars(value)
    return {}


def _field(value: Any, name: str, default: Any = None) -> Any:
    mapping = _as_mapping(value)
    return mapping.get(name, getattr(value, name, default))


def _compact_contract(raw: Any) -> dict[str, Any]:
    """Keep only decision-useful fields; never persist a raw provider payload."""
    details = _field(raw, "details", {})
    greeks = _field(raw, "greeks", {})
    quote = _field(raw, "last_quote", {})
    day = _field(raw, "day", {})
    return {
        "ticker": _field(details, "ticker", _field(raw, "ticker")),
        "contract_type": _field(details, "contract_type"),
        "expiration_date": _field(details, "expiration_date"),
        "strike_price": _field(details, "strike_price"),
        "bid": _field(quote, "bid", _field(quote, "bid_price")),
        "ask": _field(quote, "ask", _field(quote, "ask_price")),
        "quote_timestamp": _field(quote, "last_updated"),
        "delta": _field(greeks, "delta"),
        "gamma": _field(greeks, "gamma"),
        "theta": _field(greeks, "theta"),
        "vega": _field(greeks, "vega"),
        "implied_volatility": _field(raw, "implied_volatility"),
        "open_interest": _field(raw, "open_interest"),
        "volume": _field(day, "volume"),
        "underlying_price": _field(_field(raw, "underlying_asset", {}), "price"),
    }


class PolygonOptionsClient:
    """Fetch normalized option-chain snapshots with cache, retry, and budget guards."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        budget_path: Path = DEFAULT_BUDGET_CONFIG,
        ledger_path: Path = DEFAULT_LEDGER,
        cost_dir: Path = DEFAULT_COST_DIR,
        cache_ttl_seconds: float = 60.0,
        requests_per_minute: int = 20,
        max_attempts: int = 3,
        client_factory: Callable[[str], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.getenv("POLYGON_API_KEY", "")).strip()
        self.budget_path = Path(budget_path)
        self.ledger_path = Path(ledger_path)
        self.cost_dir = Path(cost_dir)
        self.cache_ttl_seconds = cache_ttl_seconds
        self.min_request_interval_seconds = 60.0 / max(1, requests_per_minute)
        self.max_attempts = max(1, max_attempts)
        self.client_factory = client_factory or self._default_client_factory
        self.clock = clock
        self.sleeper = sleeper
        self.now = now
        self._client: Any | None = None
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()
        self._last_request_at: float | None = None

    @staticmethod
    def _default_client_factory(api_key: str) -> Any:
        # Polygon.io rebranded to Massive; this is the maintained official SDK.
        from massive import RESTClient

        return RESTClient(api_key=api_key)

    def _budget(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.budget_path.read_text(encoding="utf-8"))
            return dict(payload.get("providers", {}).get("polygon_options", {}))
        except (OSError, ValueError, TypeError):
            return {}

    def _month_ledger_cost(self, month: str) -> float:
        if not self.ledger_path.exists():
            return 0.0
        total = 0.0
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if str(row.get("timestamp", "")).startswith(month):
                    total += float(row.get("estimated_cost_usd") or 0.0)
            except (ValueError, TypeError):
                continue
        return total

    def _budget_state(self) -> tuple[bool, float, float]:
        config = self._budget()
        cap = float(config.get("monthly_budget_usd", 0.0) or 0.0)
        cutoff = float(config.get("hard_cutoff_multiplier", 1.05) or 1.05)
        configured_cost = float(config.get("current_month_cost_usd", 0.0) or 0.0)
        ledger_cost = self._month_ledger_cost(self.now().strftime("%Y-%m"))
        used = max(configured_cost, ledger_cost)
        enabled = bool(config.get("enabled", False))
        # Treat the configured boundary as closed; tolerate binary-float noise at 105%.
        return enabled and cap > 0 and used + 1e-9 < cap * cutoff, used, cap

    def assert_budget_available(self) -> tuple[float, float]:
        allowed, used, cap = self._budget_state()
        if not allowed:
            raise PolygonBudgetExceededError("Polygon options monthly budget cutoff reached")
        return used, cap

    def _append_ledger(self, row: Mapping[str, Any]) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(dict(row), sort_keys=True, separators=(",", ":")) + "\n")

    def _rate_limit(self) -> None:
        with self._lock:
            current = self.clock()
            if self._last_request_at is not None:
                remaining = self.min_request_interval_seconds - (current - self._last_request_at)
                if remaining > 0:
                    self.sleeper(remaining)
                    current = self.clock()
            self._last_request_at = current

    def _result(
        self,
        *,
        symbol: str,
        status: str,
        contracts: list[dict[str, Any]] | None = None,
        latency_ms: float = 0.0,
        response_hash: str | None = None,
        cached: bool = False,
        error: str | None = None,
        used: float = 0.0,
        cap: float = 0.0,
    ) -> dict[str, Any]:
        return {
            "provider": "polygon",
            "status": status,
            "symbol": symbol,
            "contracts": contracts or [],
            "contract_count": len(contracts or []),
            "fetched_at": self.now().isoformat(),
            "latency_ms": round(latency_ms, 3),
            "response_hash": response_hash,
            "cached": cached,
            "error": error,
            "monthly_cost_usd": round(used, 6),
            "monthly_budget_usd": round(cap, 6),
            "execution_enabled": False,
            "execution_eligible": False,
            "usage_scope": "shadow_research_and_eod_chain",
        }

    @staticmethod
    def _status_for_exception(exc: Exception) -> str:
        if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
            return "timeout"
        status_code = getattr(exc, "status", getattr(exc, "status_code", None))
        if status_code is not None:
            return f"http_{status_code}"
        return "missing"

    def fetch_chain(self, symbol: str, **params: Any) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        cache_key = json.dumps([symbol, params], sort_keys=True, default=str)
        now_tick = self.clock()
        with self._lock:
            hit = self._cache.get(cache_key)
            if hit and now_tick - hit.inserted_at <= self.cache_ttl_seconds:
                cached = dict(hit.value)
                cached["cached"] = True
                return cached

        if not self.api_key:
            result = self._result(symbol=symbol, status="not_configured")
            self._append_ledger({
                "timestamp": result["fetched_at"], "provider": "polygon", "operation": "options_chain",
                "symbols": [symbol], "status": result["status"], "estimated_cost_usd": 0.0,
                "latency_ms": 0.0, "response_hash": None,
            })
            return result

        try:
            used, cap = self.assert_budget_available()
        except PolygonBudgetExceededError:
            _, used, cap = self._budget_state()
            result = self._result(symbol=symbol, status="budget_exceeded", used=used, cap=cap)
            self._append_ledger({
                "timestamp": result["fetched_at"], "provider": "polygon", "operation": "options_chain",
                "symbols": [symbol], "status": result["status"], "estimated_cost_usd": 0.0,
                "latency_ms": 0.0, "response_hash": None,
            })
            return result

        started = self.clock()
        final_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                if self._client is None:
                    self._client = self.client_factory(self.api_key)
                self._rate_limit()
                raw_items: Iterable[Any] = self._client.list_snapshot_options_chain(symbol, params=params)
                contracts = [_compact_contract(item) for item in raw_items]
                if not contracts:
                    raise RuntimeError("provider returned no option contracts")
                encoded = json.dumps(contracts, sort_keys=True, default=str, separators=(",", ":")).encode()
                response_hash = hashlib.sha256(encoded).hexdigest()
                latency = (self.clock() - started) * 1000.0
                result = self._result(
                    symbol=symbol, status="ok", contracts=contracts, latency_ms=latency,
                    response_hash=response_hash, used=used, cap=cap,
                )
                with self._lock:
                    self._cache[cache_key] = _CacheEntry(self.clock(), result)
                self._append_ledger({
                    "timestamp": result["fetched_at"], "provider": "polygon", "operation": "options_chain",
                    "symbols": [symbol], "status": "ok", "estimated_cost_usd": 0.0,
                    "latency_ms": result["latency_ms"], "response_hash": response_hash,
                })
                return result
            except Exception as exc:  # provider SDK uses several HTTP exception classes
                final_error = exc
                status = self._status_for_exception(exc)
                retryable = status in {"timeout", "http_429", "http_500", "http_502", "http_503", "http_504"}
                if not retryable or attempt == self.max_attempts:
                    break
                self.sleeper(min(2 ** (attempt - 1), 4))

        latency = (self.clock() - started) * 1000.0
        status = self._status_for_exception(final_error or RuntimeError("missing"))
        result = self._result(
            symbol=symbol, status=status, latency_ms=latency,
            error=type(final_error).__name__ if final_error else "missing", used=used, cap=cap,
        )
        self._append_ledger({
            "timestamp": result["fetched_at"], "provider": "polygon", "operation": "options_chain",
            "symbols": [symbol], "status": status, "estimated_cost_usd": 0.0,
            "latency_ms": result["latency_ms"], "response_hash": None,
        })
        return result

    def write_weekly_cost_report(self) -> Path:
        now = self.now()
        week = f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"
        rows: list[dict[str, Any]] = []
        if self.ledger_path.exists():
            for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    timestamp = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
                    iso = timestamp.isocalendar()
                    if iso.year == now.isocalendar().year and iso.week == now.isocalendar().week:
                        rows.append(row)
                except ValueError:
                    continue
        report = {
            "schema_version": 1,
            "week": week,
            "provider": "polygon",
            "calls": len(rows),
            "estimated_variable_cost_usd": round(sum(float(r.get("estimated_cost_usd") or 0) for r in rows), 6),
            "configured_monthly_plan_usd": float(self._budget().get("estimated_monthly_cost_usd", 0.0) or 0.0),
            "generated_at": now.isoformat(),
        }
        self.cost_dir.mkdir(parents=True, exist_ok=True)
        target = self.cost_dir / f"{week}.json"
        target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return target
