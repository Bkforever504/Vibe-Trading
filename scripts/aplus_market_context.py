#!/usr/bin/env python3
"""Fail-closed shadow market-context challengers for A+ candidates.

This module intentionally does not generate trades, alter scanner ranks, or
contact a market-data provider.  It consumes timestamped, normalized rows and
emits three independent context-only challengers:

1. a causal ES/NQ impulse plus *breadth acceleration* state;
2. a small Bayesian online change-point detector used only to abstain/widen
   uncertainty while a regime is changing; and
3. opening-only auction/overnight context from normalized NOII/imbalance rows.

The constants below are the preregistration.  They are deliberately few and
are not selected by a parameter search.  A future experiment must change the
schema version and document any threshold changes before opening outcomes.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo


SCHEMA_VERSION = 1
ET = ZoneInfo("America/New_York")
DEFAULT_REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "aplus-market-context.json"

# Frozen breadth/futures thresholds.  Returns are basis points; participation
# acceleration is percentage points; dollar-balance velocity is a unit ratio.
FUTURES_IMPULSE_THRESHOLD_BPS = 3.0
BREADTH_ACCELERATION_THRESHOLD_PP = 1.0
DOLLAR_BALANCE_VELOCITY_THRESHOLD = 0.03
HIGH_LOW_VELOCITY_THRESHOLD = 1.0
MAX_CONTEXT_GAP_SECONDS = 10 * 60

# Frozen BOCPD specification.  One expected change per RTH session is a weak,
# transparent prior, not a fitted value.  Inputs use fixed research units.
BOCPD_HAZARD = 1.0 / 78.0
BOCPD_CHANGE_THRESHOLD = 0.35
BOCPD_MIN_OBSERVATIONS = 5
BOCPD_MAX_RUN_LENGTH = 156
BOCPD_RETURN_SCALE_BPS = 10.0
BOCPD_BREADTH_VELOCITY_SCALE_PP = 5.0
BOCPD_UNCERTAINTY_MULTIPLIER = 2.0

# NOII is observed before the opening cross; the challenger is applicable only
# around the open and never leaks a later imbalance into an earlier row.
AUCTION_START_ET = time(9, 25)
AUCTION_OBSERVATION_END_ET = time(9, 30)
OPENING_CONTEXT_END_ET = time(9, 35)
AUCTION_IMBALANCE_RATIO_THRESHOLD = 0.05
OVERNIGHT_IMPULSE_THRESHOLD_BPS = 10.0

BREADTH_REQUIRED_FIELDS = (
    "es_return_1m_bps",
    "nq_return_1m_bps",
    "breadth_above_vwap_pct",
    "advancing_dollar_volume",
    "declining_dollar_volume",
    "new_intraday_highs",
    "new_intraday_lows",
)
CHANGE_REQUIRED_FIELDS = ("index_return_1m_bps", "realized_vol_z")
OVERNIGHT_REQUIRED_FIELDS = (
    "overnight_es_return_bps",
    "overnight_nq_return_bps",
    "spy_premarket_gap_bps",
    "qqq_premarket_gap_bps",
)
AUCTION_REQUIRED_FIELDS = ("paired_shares", "imbalance_shares", "imbalance_direction")


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sign(value: float, threshold: float) -> int:
    if value >= threshold:
        return 1
    if value <= -threshold:
        return -1
    return 0


def _missing_numeric(row: Mapping[str, Any], fields: Sequence[str]) -> list[str]:
    return [field for field in fields if _finite(row.get(field)) is None]


def _normalize_market_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    valid: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[datetime] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            errors.append(f"market_row_{index}:not_an_object")
            continue
        timestamp = _parse_timestamp(raw.get("timestamp") or raw.get("known_at") or raw.get("as_of"))
        if timestamp is None:
            errors.append(f"market_row_{index}:missing_or_naive_timestamp")
            continue
        if timestamp in seen:
            errors.append(f"market_row_{index}:duplicate_timestamp:{_iso_utc(timestamp)}")
            continue
        seen.add(timestamp)
        row = dict(raw)
        row["_timestamp"] = timestamp
        valid.append(row)
    valid.sort(key=lambda item: item["_timestamp"])
    return valid, errors


def _direction(value: Any) -> int | None:
    text = str(value or "").strip().lower()
    if text in {"b", "buy", "buy_imbalance", "bid", "+", "1", "positive"}:
        return 1
    if text in {"s", "sell", "sell_imbalance", "ask", "-", "-1", "negative"}:
        return -1
    if text in {"n", "none", "neutral", "0", "no_imbalance"}:
        return 0
    return None


def _normalize_auction_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    valid: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            errors.append(f"auction_row_{index}:not_an_object")
            continue
        timestamp = _parse_timestamp(raw.get("timestamp") or raw.get("known_at") or raw.get("as_of"))
        if timestamp is None:
            errors.append(f"auction_row_{index}:missing_or_naive_timestamp")
            continue
        local_time = timestamp.astimezone(ET).time().replace(tzinfo=None)
        if not (AUCTION_START_ET <= local_time <= AUCTION_OBSERVATION_END_ET):
            errors.append(f"auction_row_{index}:outside_frozen_observation_window")
            continue
        missing = _missing_numeric(raw, ("paired_shares", "imbalance_shares"))
        direction = _direction(raw.get("imbalance_direction"))
        if missing or direction is None:
            detail = ",".join(missing + (["imbalance_direction"] if direction is None else []))
            errors.append(f"auction_row_{index}:invalid_normalized_fields:{detail}")
            continue
        row = dict(raw)
        row["_timestamp"] = timestamp
        row["_direction"] = direction
        row["symbol"] = str(raw.get("symbol") or "MARKET").upper()
        valid.append(row)
    valid.sort(key=lambda item: item["_timestamp"])
    return valid, errors


def _dollar_balance(row: Mapping[str, Any]) -> float | None:
    advancing = _finite(row.get("advancing_dollar_volume"))
    declining = _finite(row.get("declining_dollar_volume"))
    if advancing is None or declining is None or advancing < 0 or declining < 0:
        return None
    total = advancing + declining
    return (advancing - declining) / total if total > 0 else None


def breadth_futures_context(rows: Sequence[Mapping[str, Any]], index: int) -> dict[str, Any]:
    """Return a causal multivariate participation state for ``rows[index]``.

    Only the current and two earlier timestamped rows are used.  This is not a
    fixed leader-return -> lagging-instrument trade rule: futures impulse must
    agree with acceleration in multiple independent participation measures,
    and the result is context-only.
    """
    current = rows[index]
    missing = _missing_numeric(current, BREADTH_REQUIRED_FIELDS)
    if missing:
        return _unavailable("missing_fields", missing)
    if index < 2:
        return _unavailable("insufficient_causal_history", [])
    previous, prior = rows[index - 1], rows[index - 2]
    history_missing = sorted(set(
        _missing_numeric(previous, BREADTH_REQUIRED_FIELDS)
        + _missing_numeric(prior, ("breadth_above_vwap_pct",))
    ))
    if history_missing:
        return _unavailable("missing_history_fields", history_missing)
    current_ts = current["_timestamp"]
    previous_ts = previous["_timestamp"]
    prior_ts = prior["_timestamp"]
    gaps = [(current_ts - previous_ts).total_seconds(), (previous_ts - prior_ts).total_seconds()]
    if any(gap <= 0 or gap > MAX_CONTEXT_GAP_SECONDS for gap in gaps):
        return _unavailable("stale_or_noncausal_history", [])

    futures_impulse = (
        float(current["es_return_1m_bps"]) + float(current["nq_return_1m_bps"])
    ) / 2.0
    breadth_now = float(current["breadth_above_vwap_pct"])
    breadth_previous = float(previous["breadth_above_vwap_pct"])
    breadth_prior = float(prior["breadth_above_vwap_pct"])
    breadth_velocity = breadth_now - breadth_previous
    prior_velocity = breadth_previous - breadth_prior
    breadth_acceleration = breadth_velocity - prior_velocity
    current_balance = _dollar_balance(current)
    previous_balance = _dollar_balance(previous)
    if current_balance is None or previous_balance is None:
        return _unavailable("invalid_dollar_volume", [])
    balance_velocity = current_balance - previous_balance
    high_low_now = float(current["new_intraday_highs"]) - float(current["new_intraday_lows"])
    high_low_previous = float(previous["new_intraday_highs"]) - float(previous["new_intraday_lows"])
    high_low_velocity = high_low_now - high_low_previous

    futures_direction = _sign(futures_impulse, FUTURES_IMPULSE_THRESHOLD_BPS)
    participation_votes = [
        _sign(breadth_acceleration, BREADTH_ACCELERATION_THRESHOLD_PP),
        _sign(balance_velocity, DOLLAR_BALANCE_VELOCITY_THRESHOLD),
        _sign(high_low_velocity, HIGH_LOW_VELOCITY_THRESHOLD),
    ]
    aligned_votes = sum(vote == futures_direction for vote in participation_votes if futures_direction)
    opposed_votes = sum(vote == -futures_direction for vote in participation_votes if futures_direction)
    if futures_direction == 1 and aligned_votes >= 2:
        state = "risk_on_participation_accelerating"
    elif futures_direction == -1 and aligned_votes >= 2:
        state = "risk_off_participation_accelerating"
    elif futures_direction and opposed_votes >= 2:
        state = "futures_breadth_divergence"
    else:
        state = "mixed_or_below_threshold"
    return {
        "status": "available",
        "state": state,
        "futures_impulse_bps": round(futures_impulse, 4),
        "breadth_velocity_pp": round(breadth_velocity, 4),
        "breadth_acceleration_pp": round(breadth_acceleration, 4),
        "advancing_dollar_balance": round(current_balance, 6),
        "advancing_dollar_balance_velocity": round(balance_velocity, 6),
        "new_highs_minus_lows_velocity": round(high_low_velocity, 4),
        "participation_votes": participation_votes,
        "agreement_count": aligned_votes,
        "legacy_pairwise_rule_reactivated": False,
        "distinction_from_rejected_pairwise": (
            "multivariate_state_requires_timestamped_futures_and_breadth_acceleration;"
            "no_leader_to_lagged_instrument_trade_rule"
        ),
        "authority": "shadow_context_only_no_rank_gate_or_sizing_effect",
    }


def _unavailable(reason: str, missing_fields: Sequence[str]) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "missing_fields": list(missing_fields),
        "authority": "shadow_context_only_no_rank_gate_or_sizing_effect",
    }


def _logsumexp(values: Sequence[float]) -> float:
    maximum = max(values)
    return maximum + math.log(sum(math.exp(value - maximum) for value in values))


def _predictive_log_likelihood(features: Sequence[float], count: int, sums: Sequence[float]) -> float:
    # Independent standardized Gaussian dimensions with a N(0, 1) prior on
    # each unknown mean and known unit observation variance.
    precision = 1.0 + count
    predictive_variance = 1.0 + 1.0 / precision
    total = 0.0
    for value, total_sum in zip(features, sums):
        mean = total_sum / precision
        total += -0.5 * (
            math.log(2.0 * math.pi * predictive_variance)
            + ((value - mean) ** 2) / predictive_variance
        )
    return total


def _update_stats(count: int, sums: Sequence[float], features: Sequence[float]) -> tuple[int, tuple[float, ...]]:
    return count + 1, tuple(old + new for old, new in zip(sums, features))


class OnlineChangePoint:
    """Small exact run-length posterior under the frozen Gaussian model."""

    def __init__(self, dimensions: int = 3) -> None:
        self._probabilities = [1.0]
        self._stats: list[tuple[int, tuple[float, ...]]] = [(0, tuple(0.0 for _ in range(dimensions)))]
        self.observations = 0

    def observe(self, features: Sequence[float]) -> dict[str, Any]:
        if len(features) != len(self._stats[0][1]) or any(not math.isfinite(value) for value in features):
            raise ValueError("change-point features must be finite and match the frozen dimensions")
        prior_stats = (0, tuple(0.0 for _ in features))
        prior_log_likelihood = _predictive_log_likelihood(features, *prior_stats)
        change_log_joint = math.log(BOCPD_HAZARD) + prior_log_likelihood
        growth_logs = [
            math.log(probability) + math.log1p(-BOCPD_HAZARD)
            + _predictive_log_likelihood(features, count, sums)
            for probability, (count, sums) in zip(self._probabilities, self._stats)
            if probability > 0
        ]
        log_joints = [change_log_joint, *growth_logs]
        normalizer = _logsumexp(log_joints)
        probabilities = [math.exp(value - normalizer) for value in log_joints]
        stats = [
            _update_stats(*prior_stats, features),
            *[_update_stats(count, sums, features) for count, sums in self._stats],
        ]
        if len(probabilities) > BOCPD_MAX_RUN_LENGTH + 1:
            probabilities = probabilities[: BOCPD_MAX_RUN_LENGTH + 1]
            stats = stats[: BOCPD_MAX_RUN_LENGTH + 1]
            retained = sum(probabilities)
            probabilities = [value / retained for value in probabilities]
        self._probabilities = probabilities
        self._stats = stats
        self.observations += 1

        change_probability = probabilities[0]
        most_likely_run_length = max(range(len(probabilities)), key=probabilities.__getitem__)
        expected_run_length = sum(index * probability for index, probability in enumerate(probabilities))
        insufficient = self.observations < BOCPD_MIN_OBSERVATIONS
        high_change = change_probability >= BOCPD_CHANGE_THRESHOLD
        abstain = insufficient or high_change
        reason = "insufficient_history" if insufficient else "change_probability_high" if high_change else None
        widening = 1.0 + BOCPD_UNCERTAINTY_MULTIPLIER * change_probability + (0.5 if insufficient else 0.0)
        return {
            "status": "available",
            "posterior_change_probability": round(change_probability, 6),
            "most_likely_run_length": most_likely_run_length,
            "expected_run_length": round(expected_run_length, 4),
            "observations": self.observations,
            "abstain_from_aplus": abstain,
            "abstention_reason": reason,
            "uncertainty_widening_factor": round(min(widening, 3.0), 6),
            "calibration_locally_applicable": not abstain,
            "authority": "shadow_abstention_challenger_no_trade_generation",
        }


def change_point_features(current: Mapping[str, Any], previous: Mapping[str, Any] | None) -> tuple[float, ...] | None:
    if _missing_numeric(current, CHANGE_REQUIRED_FIELDS + ("breadth_above_vwap_pct",)):
        return None
    if previous is None or _finite(previous.get("breadth_above_vwap_pct")) is None:
        return None
    breadth_velocity = float(current["breadth_above_vwap_pct"]) - float(previous["breadth_above_vwap_pct"])
    return (
        float(current["index_return_1m_bps"]) / BOCPD_RETURN_SCALE_BPS,
        float(current["realized_vol_z"]),
        breadth_velocity / BOCPD_BREADTH_VELOCITY_SCALE_PP,
    )


def opening_auction_context(
    market_row: Mapping[str, Any], auction_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    decision_timestamp = market_row["_timestamp"]
    local_time = decision_timestamp.astimezone(ET).time().replace(tzinfo=None)
    if local_time < AUCTION_START_ET:
        return {"status": "not_applicable", "reason": "before_opening_window", "authority": "shadow_context_only"}
    if local_time > OPENING_CONTEXT_END_ET:
        return {"status": "not_applicable", "reason": "outside_opening_window", "authority": "shadow_context_only"}
    missing_overnight = _missing_numeric(market_row, OVERNIGHT_REQUIRED_FIELDS)
    if missing_overnight:
        return _unavailable("missing_overnight_fields", missing_overnight)

    latest_by_symbol: dict[str, Mapping[str, Any]] = {}
    for row in auction_rows:
        timestamp = row["_timestamp"]
        if timestamp > decision_timestamp:
            break
        latest_by_symbol[str(row["symbol"])] = row
    if not latest_by_symbol:
        return _unavailable("no_normalized_auction_rows_known_at_decision", [])

    signed_imbalance = 0.0
    total_interest = 0.0
    source_timestamps: list[datetime] = []
    for row in latest_by_symbol.values():
        paired = float(row["paired_shares"])
        imbalance = float(row["imbalance_shares"])
        if paired < 0 or imbalance < 0:
            return _unavailable("negative_auction_size", [])
        signed_imbalance += float(row["_direction"]) * imbalance
        total_interest += paired + imbalance
        source_timestamps.append(row["_timestamp"])
    if total_interest <= 0:
        return _unavailable("zero_auction_interest", [])
    imbalance_ratio = signed_imbalance / total_interest
    overnight_composite = sum(float(market_row[field]) for field in OVERNIGHT_REQUIRED_FIELDS) / len(OVERNIGHT_REQUIRED_FIELDS)
    auction_direction = _sign(imbalance_ratio, AUCTION_IMBALANCE_RATIO_THRESHOLD)
    overnight_direction = _sign(overnight_composite, OVERNIGHT_IMPULSE_THRESHOLD_BPS)
    if auction_direction == overnight_direction == 1:
        state = "aligned_positive_opening_inventory"
    elif auction_direction == overnight_direction == -1:
        state = "aligned_negative_opening_inventory"
    elif auction_direction and overnight_direction and auction_direction != overnight_direction:
        state = "auction_overnight_conflict"
    elif auction_direction:
        state = "auction_imbalance_without_overnight_confirmation"
    elif overnight_direction:
        state = "overnight_impulse_without_auction_confirmation"
    else:
        state = "balanced_opening_context"
    return {
        "status": "available",
        "state": state,
        "signed_auction_imbalance_ratio": round(imbalance_ratio, 6),
        "overnight_composite_bps": round(overnight_composite, 4),
        "auction_symbol_count": len(latest_by_symbol),
        "latest_auction_source_timestamp": _iso_utc(max(source_timestamps)),
        "future_auction_rows_used": False,
        "authority": "shadow_opening_context_only_no_rank_gate_or_sizing_effect",
    }


def build_report(
    market_rows: Iterable[Mapping[str, Any]],
    auction_rows: Iterable[Mapping[str, Any]] | None = None,
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    raw_market = list(market_rows)
    raw_auction = list(auction_rows or [])
    normalized_market, market_errors = _normalize_market_rows(raw_market)
    normalized_auction, auction_errors = _normalize_auction_rows(raw_auction)
    detector = OnlineChangePoint()
    contexts: list[dict[str, Any]] = []
    for index, row in enumerate(normalized_market):
        breadth = breadth_futures_context(normalized_market, index)
        features = change_point_features(row, normalized_market[index - 1] if index else None)
        if features is None:
            change = {
                "status": "unavailable",
                "reason": "missing_features_or_causal_history",
                "abstain_from_aplus": True,
                "abstention_reason": "change_point_unavailable",
                "uncertainty_widening_factor": 2.0,
                "calibration_locally_applicable": False,
                "authority": "shadow_abstention_challenger_no_trade_generation",
            }
        else:
            change = detector.observe(features)
        contexts.append({
            "timestamp": _iso_utc(row["_timestamp"]),
            "causal_input_cutoff": _iso_utc(row["_timestamp"]),
            "inputs_known_at_or_before_timestamp": True,
            "breadth_futures": breadth,
            "change_point": change,
            "opening_auction_overnight": opening_auction_context(row, normalized_auction),
            "execution_enabled": False,
            "can_submit_orders": False,
        })

    breadth_available = sum(row["breadth_futures"].get("status") == "available" for row in contexts)
    change_available = sum(row["change_point"].get("status") == "available" for row in contexts)
    opening_applicable = [
        row for row in contexts if row["opening_auction_overnight"].get("status") != "not_applicable"
    ]
    opening_available = sum(
        row["opening_auction_overnight"].get("status") == "available" for row in opening_applicable
    )
    validation_errors = [*market_errors, *auction_errors]
    if not contexts:
        health = "unavailable"
    elif validation_errors or breadth_available == 0 or change_available == 0 or (opening_applicable and opening_available == 0):
        health = "degraded"
    else:
        health = "ok"
    created = generated_at or datetime.now(timezone.utc)
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "aplus_market_context_shadow",
        "generated_at": _iso_utc(created),
        "as_of": contexts[-1]["timestamp"] if contexts else None,
        "mode": "fail_closed_shadow_context",
        "execution_enabled": False,
        "can_submit_orders": False,
        "preregistration": {
            "parameter_search_performed": False,
            "futures_impulse_threshold_bps": FUTURES_IMPULSE_THRESHOLD_BPS,
            "breadth_acceleration_threshold_pp": BREADTH_ACCELERATION_THRESHOLD_PP,
            "dollar_balance_velocity_threshold": DOLLAR_BALANCE_VELOCITY_THRESHOLD,
            "bocpd_hazard": BOCPD_HAZARD,
            "bocpd_change_threshold": BOCPD_CHANGE_THRESHOLD,
            "bocpd_min_observations": BOCPD_MIN_OBSERVATIONS,
            "auction_window_et": "09:25-09:35",
            "auction_imbalance_ratio_threshold": AUCTION_IMBALANCE_RATIO_THRESHOLD,
            "overnight_impulse_threshold_bps": OVERNIGHT_IMPULSE_THRESHOLD_BPS,
        },
        "coverage": {
            "market_rows_received": len(raw_market),
            "market_rows_valid": len(normalized_market),
            "auction_rows_received": len(raw_auction),
            "auction_rows_valid": len(normalized_auction),
            "context_rows": len(contexts),
            "breadth_futures_available": breadth_available,
            "change_point_available": change_available,
            "opening_applicable_rows": len(opening_applicable),
            "opening_available_rows": opening_available,
        },
        "data_quality": {
            "status": health,
            "causal_sort_applied": True,
            "timezone_aware_timestamps_required": True,
            "future_auction_rows_prohibited": True,
            "validation_errors": validation_errors,
        },
        "contexts": contexts,
        "operational_health": health,
        "warnings": [
            "Shadow context only; this report cannot create, rank, size, or submit a trade.",
            "Missing or stale inputs produce unavailable/abstain, never a favorable imputation.",
            "The breadth challenger is multivariate participation acceleration, not the rejected fixed pairwise lead-lag rule.",
            "Change-point probability is a model diagnostic, not a forecast of direction or profitability.",
            "Auction context is applicable only from 09:25 through 09:35 America/New_York.",
        ],
    }


def _load_rows(path: Path, preferred_key: str) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        rows = payload.get(preferred_key, payload.get("rows"))
        if isinstance(rows, list):
            return rows
    raise ValueError(f"{path} must contain a JSON list, JSONL rows, or a '{preferred_key}' list")


def write_report(report: Mapping[str, Any], path: Path = DEFAULT_REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market-input", type=Path, required=True, help="Timestamped market rows (JSON or JSONL).")
    parser.add_argument("--auction-input", type=Path, help="Optional normalized NOII/imbalance rows (JSON or JSONL).")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args()
    market_rows = _load_rows(args.market_input, "market_rows")
    auction_rows = _load_rows(args.auction_input, "auction_rows") if args.auction_input else []
    report = build_report(market_rows, auction_rows)
    write_report(report, args.output)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"A+ market context: rows={report['coverage']['context_rows']} "
            f"health={report['operational_health']} output={args.output}"
        )
    return 0 if report["operational_health"] != "unavailable" else 2


if __name__ == "__main__":
    raise SystemExit(main())
