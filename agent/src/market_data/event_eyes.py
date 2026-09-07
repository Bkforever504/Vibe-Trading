"""Deterministic event-time market-data intelligence for shadow evaluation.

This module deliberately has no network, broker, order, or notification code.  It
turns already-received market events into auditable observations that a caller can
compare with a slower completed-bar lane.  Missing, stale, corrected, or
out-of-sequence data always abstains instead of being inferred.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Iterable


SHADOW_AUTHORITY = {
    "execution_enabled": False,
    "can_submit_orders": False,
    "authority": "shadow_observation_only",
}


class EventKind(StrEnum):
    TRADE = "trade"
    QUOTE = "quote"
    BAR = "bar"
    UPDATED_BAR = "updated_bar"
    CORRECTION = "correction"
    CANCEL_ERROR = "cancel_error"
    STATUS = "status"
    LULD = "luld"


class LevelDirection(StrEnum):
    LONG = "long"
    SHORT = "short"


class LevelState(StrEnum):
    WATCH = "WATCH"
    PROXIMITY = "PROXIMITY"
    TOUCH = "TOUCH"
    HOLDING = "HOLDING"
    INVALIDATED = "INVALIDATED"
    UNAVAILABLE = "UNAVAILABLE"


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _finite_positive(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value > 0


@dataclass(frozen=True)
class MarketEvent:
    """Normalized event envelope; unused payload fields remain ``None``."""

    symbol: str
    kind: EventKind
    event_ts: datetime
    received_ts: datetime
    sequence: int | None = None
    source: str = "unknown"
    price: float | None = None
    size: float | None = None
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    conditions: tuple[str, ...] = ()
    status_code: str | None = None
    reason_code: str | None = None
    lower_band: float | None = None
    upper_band: float | None = None
    original_sequence: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "event_ts", _utc(self.event_ts))
        object.__setattr__(self, "received_ts", _utc(self.received_ts))
        object.__setattr__(self, "conditions", tuple(str(value).upper() for value in self.conditions))
        object.__setattr__(self, "status_code", self.status_code.strip().upper() if self.status_code else None)
        object.__setattr__(self, "reason_code", self.reason_code.strip().upper() if self.reason_code else None)


@dataclass(frozen=True)
class SaleConditionPolicy:
    """Conservative price-formation policy for trade-driven observations.

    The default exclusions are common CTA/UTP non-regular or non-price-forming
    conditions.  Deployments should version and override this set for their feed;
    unknown conditions fail closed by default.
    """

    excluded: frozenset[str] = frozenset({"B", "C", "G", "H", "I", "M", "N", "P", "Q", "U", "V", "W", "Z", "4"})
    # F/T commonly accompany the regular-sale marker in Alpaca's documented
    # examples. I (odd lot) is recognized above but excluded from the primary
    # price-forming lane; it can be studied separately as BOLO evidence.
    regular: frozenset[str] = frozenset({"@", "F", "T", ""})
    allow_unknown: bool = False

    def evaluate(self, event: MarketEvent) -> dict[str, object]:
        if event.kind != EventKind.TRADE:
            return _result("not_applicable", eligible=False, reason="not_a_trade")
        if not _finite_positive(event.price) or not _finite_positive(event.size):
            return _result("unavailable", eligible=False, reason="missing_or_invalid_trade_fields")
        conditions = set(event.conditions) or {""}
        excluded = sorted(conditions & self.excluded)
        unknown = sorted(conditions - self.excluded - self.regular)
        if excluded:
            return _result("rejected", eligible=False, reason="excluded_sale_condition", conditions=excluded)
        if unknown and not self.allow_unknown:
            return _result("rejected", eligible=False, reason="unknown_sale_condition", conditions=unknown)
        return _result("available", eligible=True, reason=None, conditions=sorted(conditions))


def _result(status: str, **fields: object) -> dict[str, object]:
    return {"status": status, **fields, **SHADOW_AUTHORITY}


class EventTimeGuard:
    """Validate freshness, causality, sequence monotonicity, and event payloads."""

    def __init__(self, *, max_age: timedelta = timedelta(seconds=60), future_tolerance: timedelta = timedelta(seconds=1)):
        if max_age.total_seconds() <= 0 or future_tolerance.total_seconds() < 0:
            raise ValueError("invalid event-time tolerances")
        self.max_age = max_age
        self.future_tolerance = future_tolerance
        self._last_sequence: dict[tuple[str, str, EventKind], int] = {}
        self._last_event_ts: dict[tuple[str, str, EventKind], datetime] = {}

    def evaluate(self, event: MarketEvent, *, now: datetime) -> dict[str, object]:
        now_utc = _utc(now)
        reasons: list[str] = []
        if not event.symbol:
            reasons.append("missing_symbol")
        if event.received_ts + self.future_tolerance < event.event_ts:
            reasons.append("event_after_receive_time")
        if event.event_ts > now_utc + self.future_tolerance:
            reasons.append("future_event")
        if now_utc - event.event_ts > self.max_age:
            reasons.append("stale_event")

        key = (event.source, event.symbol, event.kind)
        last_sequence = self._last_sequence.get(key)
        last_ts = self._last_event_ts.get(key)
        if event.sequence is not None and last_sequence is not None:
            if event.sequence == last_sequence:
                reasons.append("duplicate_sequence")
            elif event.sequence < last_sequence:
                reasons.append("out_of_sequence")
            elif event.sequence > last_sequence + 1:
                reasons.append("sequence_gap")
        if last_ts is not None and event.event_ts < last_ts:
            reasons.append("event_time_regression")

        reasons.extend(self._payload_errors(event))
        accepted = not reasons
        if accepted:
            if event.sequence is not None:
                self._last_sequence[key] = event.sequence
            self._last_event_ts[key] = event.event_ts
        return _result(
            "available" if accepted else "rejected",
            accepted=accepted,
            reasons=reasons,
            event_kind=event.kind.value,
            symbol=event.symbol,
            source=event.source,
            event_ts=event.event_ts.isoformat(),
            received_ts=event.received_ts.isoformat(),
            transport_latency_ms=max(0.0, (event.received_ts - event.event_ts).total_seconds() * 1000),
        )

    @staticmethod
    def _payload_errors(event: MarketEvent) -> list[str]:
        if event.kind == EventKind.TRADE and (not _finite_positive(event.price) or not _finite_positive(event.size)):
            return ["invalid_trade_payload"]
        if event.kind == EventKind.QUOTE:
            if not all(_finite_positive(value) for value in (event.bid, event.ask, event.bid_size, event.ask_size)):
                return ["invalid_quote_payload"]
            if event.bid is not None and event.ask is not None and event.bid > event.ask:
                return ["crossed_quote"]
        if event.kind in {EventKind.CORRECTION, EventKind.CANCEL_ERROR} and event.original_sequence is None:
            return ["missing_original_sequence"]
        if event.kind == EventKind.STATUS and not event.status_code:
            return ["missing_status_code"]
        if event.kind == EventKind.LULD:
            if not _finite_positive(event.lower_band) or not _finite_positive(event.upper_band):
                return ["missing_luld_bands"]
            if event.lower_band is not None and event.upper_band is not None and event.lower_band >= event.upper_band:
                return ["invalid_luld_bands"]
        return []


class TapeTruthBook:
    """Remember tape states that can make an otherwise valid signal unusable.

    Feed-specific status codes are configurable.  Unknown status codes are kept
    visible but cannot silently clear a known halt.  Corrections and cancel/error
    messages revoke their referenced source sequence; they never become prices.
    """

    def __init__(
        self,
        *,
        halt_status_codes: Iterable[str] = ("2", "H", "P", "HALT", "PAUSED"),
        resume_status_codes: Iterable[str] = ("3", "Q", "T", "RESUME", "TRADING"),
        halt_reason_codes: Iterable[str] = (
            "T1", "T2", "T5", "T6", "T8", "T12", "H4", "H9", "H10", "H11",
            "01", "IPO1", "M1", "M2", "LUDP", "LUDS", "MWC1", "MWC2", "MWC3",
            "MWC0", "T3", "T7",
        ),
        resume_reason_codes: Iterable[str] = (
            "R4", "R9", "C3", "C4", "C9", "C11", "R1", "R", "IPOQ", "IPOE", "MWCQ",
        ),
        luld_buffer_bps: float = 5.0,
    ):
        if luld_buffer_bps < 0:
            raise ValueError("luld_buffer_bps cannot be negative")
        self.halt_codes = frozenset(code.upper() for code in halt_status_codes)
        self.resume_codes = frozenset(code.upper() for code in resume_status_codes)
        self.halt_reason_codes = frozenset(code.upper() for code in halt_reason_codes)
        self.resume_reason_codes = frozenset(code.upper() for code in resume_reason_codes)
        self.luld_buffer_bps = luld_buffer_bps
        self._halted: dict[str, bool] = {}
        self._bands: dict[str, tuple[float, float, datetime]] = {}
        self._revoked: dict[tuple[str, str], set[int]] = defaultdict(set)
        self._updated_bar_ts: dict[tuple[str, str], datetime] = {}

    def apply(self, event: MarketEvent, *, integrity_accepted: bool) -> dict[str, object]:
        if not integrity_accepted:
            return self._view(event, status="unavailable", reason="integrity_rejected")

        reason: str | None = None
        if event.kind == EventKind.STATUS:
            assert event.status_code is not None
            code = event.status_code.upper()
            reason_code = event.reason_code or ""
            if code in self.halt_codes or reason_code in self.halt_reason_codes:
                self._halted[event.symbol] = True
                reason = "halt_or_pause"
            elif code in self.resume_codes or reason_code in self.resume_reason_codes:
                self._halted[event.symbol] = False
                reason = "trading_resumed"
            elif code in {"5", "6", "7", "8", "9", "A", "C", "D", "E", "F"}:
                # Recognized informational statuses (indications, imbalances,
                # SSR and LULD). They are observable but do not silently clear
                # an existing halt; the dedicated LULD stream owns band risk.
                reason = "recognized_non_terminal_status"
            else:
                reason = "unknown_status_code"
        elif event.kind == EventKind.LULD:
            assert event.lower_band is not None and event.upper_band is not None
            self._bands[event.symbol] = (event.lower_band, event.upper_band, event.event_ts)
        elif event.kind in {EventKind.CORRECTION, EventKind.CANCEL_ERROR}:
            assert event.original_sequence is not None
            self._revoked[(event.source, event.symbol)].add(event.original_sequence)
            reason = "source_event_revoked"
        elif event.kind == EventKind.UPDATED_BAR:
            self._updated_bar_ts[(event.source, event.symbol)] = event.event_ts
            reason = "bar_revision_observed"

        return self._view(event, status="available", reason=reason)

    def tradability(self, *, symbol: str, price: float | None, as_of: datetime, max_band_age: timedelta = timedelta(seconds=60)) -> dict[str, object]:
        normalized = symbol.strip().upper()
        as_of_utc = _utc(as_of)
        if not _finite_positive(price):
            return _result("unavailable", symbol=normalized, tradable=False, reasons=["missing_price"])
        reasons: list[str] = []
        if self._halted.get(normalized, False):
            reasons.append("halted_or_paused")
        bands = self._bands.get(normalized)
        band_view: dict[str, object] | None = None
        if bands is None:
            reasons.append("luld_unavailable")
        else:
            lower, upper, observed_at = bands
            age = as_of_utc - observed_at
            band_view = {"lower": lower, "upper": upper, "observed_at": observed_at.isoformat()}
            if age > max_band_age or age.total_seconds() < 0:
                reasons.append("luld_stale")
            else:
                lower_buffer = lower * (1 + self.luld_buffer_bps / 10_000)
                upper_buffer = upper * (1 - self.luld_buffer_bps / 10_000)
                if not lower_buffer < float(price) < upper_buffer:
                    reasons.append("at_or_near_luld_band")
        return _result(
            "available" if not reasons else "blocked",
            symbol=normalized,
            price=price,
            tradable=not reasons,
            reasons=reasons,
            luld=band_view,
            halted=self._halted.get(normalized),
        )

    def is_revoked(self, *, source: str, symbol: str, sequence: int) -> bool:
        return sequence in self._revoked[(source, symbol.strip().upper())]

    def _view(self, event: MarketEvent, *, status: str, reason: str | None) -> dict[str, object]:
        return _result(
            status,
            symbol=event.symbol,
            event_kind=event.kind.value,
            reason=reason,
            halted=self._halted.get(event.symbol),
            luld_available=event.symbol in self._bands,
            referenced_sequence=event.original_sequence,
            price_forming=event.kind == EventKind.TRADE,
        )


@dataclass(frozen=True)
class HotCandidate:
    symbol: str
    base_score: float | None
    distance_bps: float | None
    data_status: str = "available"

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", self.symbol.strip().upper())


class HotSetSelector:
    """Reserve must-watch symbols, then fill capacity by deterministic rank."""

    def __init__(self, capacity: int, *, reserved_symbols: Iterable[str] = ()):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.reserved_symbols = tuple(dict.fromkeys(symbol.strip().upper() for symbol in reserved_symbols if symbol.strip()))
        if len(self.reserved_symbols) > capacity:
            raise ValueError("reserved symbols exceed capacity")

    def select(self, candidates: Iterable[HotCandidate]) -> dict[str, object]:
        by_symbol = {candidate.symbol: candidate for candidate in candidates if candidate.symbol}
        rows: list[dict[str, object]] = []
        unavailable: list[dict[str, str]] = []
        for symbol in self.reserved_symbols:
            candidate = by_symbol.pop(symbol, None)
            if candidate is None or candidate.data_status != "available":
                unavailable.append({"symbol": symbol, "reason": "missing" if candidate is None else candidate.data_status})
            rows.append({"symbol": symbol, "reserved": True, "rank_score": None, "data_status": candidate.data_status if candidate else "missing"})

        eligible = [candidate for candidate in by_symbol.values() if self._eligible(candidate)]
        eligible.sort(key=lambda candidate: (-self._score(candidate), candidate.symbol))
        for candidate in eligible[: self.capacity - len(rows)]:
            rows.append({
                "symbol": candidate.symbol,
                "reserved": False,
                "rank_score": round(self._score(candidate), 6),
                "data_status": candidate.data_status,
            })
        return _result(
            "available" if rows else "unavailable",
            symbols=[row["symbol"] for row in rows],
            selections=rows,
            unavailable_reserved=unavailable,
            capacity=self.capacity,
        )

    @staticmethod
    def _eligible(candidate: HotCandidate) -> bool:
        return (
            candidate.data_status == "available"
            and candidate.base_score is not None
            and candidate.distance_bps is not None
            and math.isfinite(candidate.base_score)
            and math.isfinite(candidate.distance_bps)
            and candidate.distance_bps >= 0
        )

    @staticmethod
    def _score(candidate: HotCandidate) -> float:
        assert candidate.base_score is not None and candidate.distance_bps is not None
        return float(candidate.base_score) - min(float(candidate.distance_bps), 10_000.0) / 100.0


class LevelStateMachine:
    """Track event-time approach, touch, and sustained hold around one level."""

    def __init__(
        self,
        *,
        symbol: str,
        level: float,
        direction: LevelDirection,
        proximity_bps: float = 15.0,
        touch_tolerance_bps: float = 1.0,
        hold_seconds: float = 5.0,
        invalidation_bps: float = 20.0,
    ):
        if not _finite_positive(level) or min(proximity_bps, touch_tolerance_bps, hold_seconds, invalidation_bps) < 0:
            raise ValueError("invalid level configuration")
        self.symbol = symbol.strip().upper()
        self.level = float(level)
        self.direction = direction
        self.proximity_bps = proximity_bps
        self.touch_tolerance_bps = touch_tolerance_bps
        self.hold_seconds = hold_seconds
        self.invalidation_bps = invalidation_bps
        self.state = LevelState.WATCH
        self.touched_at: datetime | None = None
        self.last_ts: datetime | None = None

    def observe(self, *, price: float | None, event_ts: datetime | None, data_status: str = "available") -> dict[str, object]:
        prior = self.state
        if data_status != "available" or not _finite_positive(price) or event_ts is None:
            self.state = LevelState.UNAVAILABLE
            return self._observation(prior, reason="market_data_unavailable", event_ts=None, price=price)
        ts = _utc(event_ts)
        if self.state == LevelState.INVALIDATED:
            return self._observation(prior, reason="terminal_invalidation", event_ts=ts, price=price)
        if self.last_ts is not None and ts < self.last_ts:
            self.state = LevelState.UNAVAILABLE
            return self._observation(prior, reason="event_time_regression", event_ts=ts, price=price)
        self.last_ts = ts
        distance_bps = abs(float(price) - self.level) / self.level * 10_000
        favorable = float(price) >= self.level if self.direction == LevelDirection.LONG else float(price) <= self.level
        invalid = (
            float(price) < self.level * (1 - self.invalidation_bps / 10_000)
            if self.direction == LevelDirection.LONG
            else float(price) > self.level * (1 + self.invalidation_bps / 10_000)
        )

        reason: str | None = None
        if self.touched_at is not None and invalid:
            self.state = LevelState.INVALIDATED
            reason = "post_touch_invalidation"
        elif favorable or distance_bps <= self.touch_tolerance_bps:
            if self.touched_at is None:
                self.touched_at = ts
            held_for = (ts - self.touched_at).total_seconds()
            self.state = LevelState.HOLDING if favorable and held_for >= self.hold_seconds else LevelState.TOUCH
        elif distance_bps <= self.proximity_bps:
            # A hold is continuous by definition. Losing the favorable side of
            # the level restarts the clock even if price remains nearby.
            self.touched_at = None
            self.state = LevelState.PROXIMITY
        else:
            self.touched_at = None
            self.state = LevelState.WATCH
        return self._observation(prior, reason=reason, event_ts=ts, price=price)

    def _observation(self, prior: LevelState, *, reason: str | None, event_ts: datetime | None, price: float | None) -> dict[str, object]:
        return _result(
            "unavailable" if self.state == LevelState.UNAVAILABLE else "available",
            symbol=self.symbol,
            direction=self.direction.value,
            level=self.level,
            price=price,
            prior_state=prior.value,
            state=self.state.value,
            transition=f"{prior.value}->{self.state.value}" if prior != self.state else None,
            event_ts=event_ts.isoformat() if event_ts else None,
            touched_at=self.touched_at.isoformat() if self.touched_at else None,
            reason=reason,
        )


class QuotePersistence:
    """Evaluate executable-looking quote persistence and liquidity withdrawal."""

    def __init__(
        self,
        *,
        window_seconds: float = 5.0,
        minimum_samples: int = 3,
        max_spread_bps: float = 12.0,
        minimum_total_size: float = 2.0,
        vacuum_size_ratio: float = 0.35,
        vacuum_spread_ratio: float = 1.5,
    ):
        if window_seconds <= 0 or minimum_samples < 2 or min(max_spread_bps, minimum_total_size) <= 0:
            raise ValueError("invalid quote-persistence configuration")
        self.window = timedelta(seconds=window_seconds)
        self.minimum_samples = minimum_samples
        self.max_spread_bps = max_spread_bps
        self.minimum_total_size = minimum_total_size
        self.vacuum_size_ratio = vacuum_size_ratio
        self.vacuum_spread_ratio = vacuum_spread_ratio
        self._quotes: dict[str, deque[MarketEvent]] = defaultdict(deque)

    def observe(self, event: MarketEvent, *, integrity_accepted: bool) -> dict[str, object]:
        if event.kind != EventKind.QUOTE:
            return _result("unavailable", state="UNAVAILABLE", reason="not_a_quote", symbol=event.symbol)
        if not integrity_accepted:
            return _result("unavailable", state="UNAVAILABLE", reason="integrity_rejected", symbol=event.symbol)
        quotes = self._quotes[event.symbol]
        quotes.append(event)
        cutoff = event.event_ts - self.window
        # Retain the last observation immediately before the window so
        # irregularly-timed streams can still prove full-duration persistence.
        while len(quotes) > 1 and quotes[1].event_ts <= cutoff:
            quotes.popleft()

        metrics = [self._metrics(quote) for quote in quotes]
        if any(metric is None for metric in metrics):
            return _result("unavailable", state="UNAVAILABLE", reason="invalid_quote", symbol=event.symbol)
        valid_metrics = [metric for metric in metrics if metric is not None]
        current_spread, current_size = valid_metrics[-1]
        peak_size = max(size for _, size in valid_metrics)
        baseline_spread = min(spread for spread, _ in valid_metrics)
        size_ratio = current_size / peak_size if peak_size else 0.0
        spread_ratio = current_spread / baseline_spread if baseline_spread else 1.0

        vacuum = (
            len(valid_metrics) >= 2
            and size_ratio <= self.vacuum_size_ratio
            and spread_ratio >= self.vacuum_spread_ratio
        )
        coverage = (quotes[-1].event_ts - quotes[0].event_ts).total_seconds()
        persistent = (
            len(valid_metrics) >= self.minimum_samples
            and coverage >= self.window.total_seconds()
            and all(spread <= self.max_spread_bps and size >= self.minimum_total_size for spread, size in valid_metrics)
        )
        state = "LIQUIDITY_VACUUM" if vacuum else "PERSISTENT" if persistent else "OBSERVING"
        return _result(
            "available",
            state=state,
            reason=None,
            symbol=event.symbol,
            samples=len(valid_metrics),
            coverage_seconds=coverage,
            spread_bps=round(current_spread, 6),
            total_size=current_size,
            size_ratio=round(size_ratio, 6),
            spread_ratio=round(spread_ratio, 6),
            quote_persistent=persistent,
            liquidity_vacuum=vacuum,
        )

    @staticmethod
    def _metrics(event: MarketEvent) -> tuple[float, float] | None:
        if not all(_finite_positive(value) for value in (event.bid, event.ask, event.bid_size, event.ask_size)):
            return None
        assert event.bid is not None and event.ask is not None
        assert event.bid_size is not None and event.ask_size is not None
        midpoint = (event.bid + event.ask) / 2
        if event.bid > event.ask or midpoint <= 0:
            return None
        return ((event.ask - event.bid) / midpoint * 10_000, event.bid_size + event.ask_size)
