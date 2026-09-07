#!/usr/bin/env python3
"""Chart-align scanner alerts and nominate leakage-safe B+ shadow upgrades.

The module consumes timestamped provider OHLCV bars.  It does not scrape or
reconstruct TradingView candles, claim fills, mutate grades, or submit orders.
Missing or sequence-ambiguous evidence is returned as unavailable/not_scored.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

BAR = timedelta(minutes=1)
MIN_SAMPLE = 30
MIN_FORWARD_SAMPLE = 10


def _timestamp(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _first_full_bar_after(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0) + BAR


def _base(signal: Mapping[str, Any], provider: str, status: str, reason: str) -> dict[str, Any]:
    return {
        "schema_version": "chart-aligned-shadow-learning-v1",
        "signal_id": signal.get("signal_id") or signal.get("alert_id"),
        "symbol": str(signal.get("symbol") or "").upper(),
        "setup": signal.get("setup"),
        "family_key": signal.get("family_key") or signal.get("setup"),
        "grade": signal.get("grade"),
        "regime_bucket": dict(signal.get("regime_bucket") or {})
        if isinstance(signal.get("regime_bucket"), Mapping)
        else {},
        "provider": provider or "missing",
        "status": status,
        "reason": reason,
        "scored": False,
        "shadow_only": True,
        "execution_enabled": False,
        "can_submit_orders": False,
        "grade_mutated": False,
        "limitations": "Provider OHLCV path observation; not a TradingView candle, option return, broker fill, or execution claim.",
    }


def _normalize_bars(bars: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    normalized: list[dict[str, Any]] = []
    for raw in bars:
        stamp = _timestamp(raw.get("t") or raw.get("timestamp"))
        values = {key: _number(raw.get(key)) for key in ("o", "h", "l", "c", "v")}
        if stamp is None or any(value is None for value in values.values()):
            return [], "malformed_provider_bar"
        assert all(value is not None for value in values.values())
        if values["v"] < 0 or values["l"] <= 0 or not (
            values["l"] <= min(values["o"], values["c"])
            <= max(values["o"], values["c"]) <= values["h"]
        ):
            return [], "malformed_provider_bar"
        normalized.append({"t": stamp, **values})
    normalized.sort(key=lambda row: row["t"])
    if len({row["t"] for row in normalized}) != len(normalized):
        return [], "duplicate_provider_bar"
    for left, right in zip(normalized, normalized[1:]):
        if right["t"] - left["t"] != BAR:
            return [], "missing_provider_bar"
    return normalized, None


def _pre_signal_features(
    bars: Sequence[Mapping[str, Any]], signal_at: datetime, entry: float,
) -> dict[str, Any]:
    # A bar is eligible only when its close was knowable at signal_at.
    known = [row for row in bars if row["t"] + BAR <= signal_at]
    if not known:
        return {"status": "unavailable", "reason": "no_completed_pre_signal_bars"}
    recent = known[-5:]
    last = recent[-1]
    features: dict[str, Any] = {
        "status": "available",
        "feature_cutoff_at": _iso(last["t"] + BAR),
        "bars_used": len(recent),
        "distance_to_entry_pct": round((last["c"] - entry) / entry * 100.0, 6),
        "range_pct": round((last["h"] - last["l"]) / last["c"] * 100.0, 6),
    }
    if len(recent) >= 2 and recent[-2]["c"]:
        features["return_1bar_pct"] = round((last["c"] / recent[-2]["c"] - 1.0) * 100.0, 6)
    if len(recent) >= 4 and recent[-4]["c"]:
        features["return_3bar_pct"] = round((last["c"] / recent[-4]["c"] - 1.0) * 100.0, 6)
    prior_volumes = [row["v"] for row in recent[:-1] if row["v"] > 0]
    if prior_volumes:
        features["volume_ratio"] = round(last["v"] / statistics.mean(prior_volumes), 6)
    return features


def _path(
    bars: Sequence[Mapping[str, Any]], *, start: datetime, direction: str,
    entry: float, stop: float, target: float,
) -> dict[str, Any]:
    eligible = [row for row in bars if row["t"] >= start]
    if not eligible:
        return {"status": "not_scored", "reason": "no_eligible_provider_bars"}
    risk = entry - stop if direction == "LONG" else stop - entry
    fill_index: int | None = None
    fill: float | None = None
    for index, row in enumerate(eligible):
        if direction == "LONG":
            if row["o"] <= stop:
                return {"status": "observed", "entry_status": "invalidated_before_entry", "terminal_bar_start": _iso(row["t"]), "terminal_at": _iso(row["t"] + BAR)}
            if row["o"] >= target:
                return {"status": "observed", "entry_status": "target_passed_before_entry", "terminal_bar_start": _iso(row["t"]), "terminal_at": _iso(row["t"] + BAR)}
            touched, invalidated = row["h"] >= entry, row["l"] <= stop
            if row["o"] >= entry:
                fill, fill_index = row["o"], index
                break
        else:
            if row["o"] >= stop:
                return {"status": "observed", "entry_status": "invalidated_before_entry", "terminal_bar_start": _iso(row["t"]), "terminal_at": _iso(row["t"] + BAR)}
            if row["o"] <= target:
                return {"status": "observed", "entry_status": "target_passed_before_entry", "terminal_bar_start": _iso(row["t"]), "terminal_at": _iso(row["t"] + BAR)}
            touched, invalidated = row["l"] <= entry, row["h"] >= stop
            if row["o"] <= entry:
                fill, fill_index = row["o"], index
                break
        if touched and invalidated:
            return {"status": "not_scored", "reason": "same_bar_entry_stop_ambiguity"}
        if invalidated:
            return {"status": "observed", "entry_status": "invalidated_before_entry", "terminal_bar_start": _iso(row["t"]), "terminal_at": _iso(row["t"] + BAR)}
        if touched:
            fill, fill_index = entry, index
            break
    if fill is None or fill_index is None:
        return {"status": "observed", "entry_status": "not_triggered"}
    actual_risk = fill - stop if direction == "LONG" else stop - fill
    if actual_risk <= 0:
        return {"status": "observed", "entry_status": "chased_past_invalidation"}
    after = eligible[fill_index:]
    sign = 1.0 if direction == "LONG" else -1.0
    terminal = "neither"
    target_before_stop: bool | None = None
    terminal_at = after[-1]["t"] + BAR
    observed_path: list[Mapping[str, Any]] = []
    for row in after:
        observed_path.append(row)
        target_hit = row["h"] >= target if direction == "LONG" else row["l"] <= target
        stop_hit = row["l"] <= stop if direction == "LONG" else row["h"] >= stop
        if target_hit and stop_hit:
            return {
                "status": "not_scored", "reason": "same_bar_target_stop_ambiguity",
                "entry_status": "triggered", "entry_at": _iso(eligible[fill_index]["t"]),
            }
        if target_hit:
            terminal, target_before_stop = "target", True
            terminal_at = row["t"] + BAR
            break
        if stop_hit:
            terminal, target_before_stop = "stop", False
            terminal_at = row["t"] + BAR
            break
    favorable = [
        sign * (row["h"] - fill) if direction == "LONG" else sign * (row["l"] - fill)
        for row in observed_path
    ]
    adverse = [
        sign * (row["l"] - fill) if direction == "LONG" else sign * (row["h"] - fill)
        for row in observed_path
    ]
    prior_favorable = favorable[:-1] if terminal != "neither" else favorable
    prior_adverse = adverse[:-1] if terminal != "neither" else adverse
    mfe_r: float | None
    mae_r: float | None
    mfe_bounds: list[float] | None = None
    mae_bounds: list[float] | None = None
    if terminal == "stop":
        # The terminal minute cannot reveal whether its favorable extreme came
        # before or after the stop. Preserve a point-identifiable stop MAE and
        # expose an MFE interval instead of pretending the ordering is known.
        mfe_r = None
        mae_r = -1.0
        mfe_bounds = [
            max([0.0, *prior_favorable]) / actual_risk,
            max([0.0, *favorable]) / actual_risk,
        ]
        mae_bounds = [-1.0, -1.0]
    elif terminal == "target":
        mfe_r = ((target - fill) if direction == "LONG" else (fill - target)) / actual_risk
        mae_r = None
        mfe_bounds = [mfe_r, mfe_r]
        mae_bounds = [
            min([0.0, *adverse]) / actual_risk,
            min([0.0, *prior_adverse]) / actual_risk,
        ]
    else:
        mfe_r = max([0.0, *favorable]) / actual_risk
        mae_r = min([0.0, *adverse]) / actual_risk
    return {
        "status": "scored",
        "entry_status": "triggered",
        "entry_at": _iso(eligible[fill_index]["t"]),
        "entry_price": round(fill, 6),
        "planned_risk": round(risk, 6),
        "actual_risk": round(actual_risk, 6),
        "mfe_r": round(mfe_r, 6) if mfe_r is not None else None,
        "mae_r": round(mae_r, 6) if mae_r is not None else None,
        "mfe_r_bounds": [round(value, 6) for value in mfe_bounds] if mfe_bounds else None,
        "mae_r_bounds": [round(value, 6) for value in mae_bounds] if mae_bounds else None,
        "excursion_identification": "terminal_bar_bounded" if terminal != "neither" else "point_observed_over_horizon",
        "terminal_event": terminal,
        "terminal_bar_start": _iso(terminal_at - BAR),
        "terminal_at": _iso(terminal_at),
        "valid_for_seconds": round(max(0.0, (terminal_at - start).total_seconds()), 3),
        "target_before_stop": target_before_stop,
    }


def align_signal_to_chart(
    signal: Mapping[str, Any], bars: Iterable[Mapping[str, Any]], *,
    provider: str, provider_status: str = "available", horizon_bars: int = 30,
) -> dict[str, Any]:
    """Align one signal to completed 1m provider bars without hindsight."""
    if provider_status != "available" or not provider:
        return _base(signal, provider, "unavailable", f"provider_{provider_status or 'missing'}")
    signal_at = _timestamp(signal.get("signal_available_at") or signal.get("signal_at"))
    delivered_at = _timestamp(signal.get("delivered_at") or signal.get("discord_delivered_at"))
    direction = str(signal.get("direction") or "").upper()
    entry, stop, target = (_number(signal.get(key)) for key in ("entry", "stop", "target"))
    base = _base(signal, provider, "not_scored", "invalid_signal_contract")
    if signal_at is None or delivered_at is None or direction not in {"LONG", "SHORT"} or None in {entry, stop, target}:
        return base
    assert entry is not None and stop is not None and target is not None
    if delivered_at < signal_at:
        return {**base, "reason": "delivery_precedes_signal"}
    valid_geometry = (direction == "LONG" and stop < entry < target) or (direction == "SHORT" and target < entry < stop)
    if not valid_geometry or horizon_bars < 1:
        return {**base, "reason": "invalid_plan_geometry"}
    normalized, error = _normalize_bars(bars)
    if error:
        return {**base, "reason": error}
    if not normalized:
        return _base(signal, provider, "unavailable", "missing_provider_bars")
    signal_start, delivery_start = _first_full_bar_after(signal_at), _first_full_bar_after(delivered_at)
    needed_end = max(signal_start, delivery_start) + horizon_bars * BAR
    selected = [row for row in normalized if row["t"] < needed_end]
    first_needed = min(signal_start, delivery_start)
    relevant = [row for row in selected if row["t"] >= first_needed]
    if len([row for row in relevant if signal_start <= row["t"] < signal_start + horizon_bars * BAR]) != horizon_bars:
        return {**base, "reason": "incomplete_signal_horizon"}
    if len([row for row in relevant if delivery_start <= row["t"] < delivery_start + horizon_bars * BAR]) != horizon_bars:
        return {**base, "reason": "incomplete_delivery_horizon"}
    signal_window = [row for row in normalized if signal_start <= row["t"] < signal_start + horizon_bars * BAR]
    delivery_window = [row for row in normalized if delivery_start <= row["t"] < delivery_start + horizon_bars * BAR]
    signal_path = _path(signal_window, start=signal_start, direction=direction, entry=entry, stop=stop, target=target)
    signal_terminal = _timestamp(signal_path.get("terminal_at"))
    terminal_bar_start = _timestamp(signal_path.get("terminal_bar_start"))
    if signal_terminal is not None and signal_terminal <= delivered_at:
        delivery_path = {
            "status": "observed",
            "entry_status": "opportunity_expired_before_delivery",
            "source_terminal_at": _iso(signal_terminal),
        }
    elif signal_terminal is not None and terminal_bar_start is not None and terminal_bar_start < delivered_at < signal_terminal:
        delivery_path = {
            "status": "not_scored",
            "reason": "delivery_terminal_order_ambiguous",
            "source_terminal_bar_start": _iso(terminal_bar_start),
            "source_terminal_at": _iso(signal_terminal),
        }
    else:
        delivery_path = _path(delivery_window, start=delivery_start, direction=direction, entry=entry, stop=stop, target=target)
    if signal_path.get("status") == "not_scored" or delivery_path.get("status") == "not_scored":
        reasons = [path.get("reason") for path in (signal_path, delivery_path) if path.get("status") == "not_scored"]
        return {**base, "reason": reasons[0], "signal_path": signal_path, "delivery_path": delivery_path}
    pre = _pre_signal_features(normalized, signal_at, entry)
    result = {
        **base,
        "status": "scored",
        "reason": None,
        "scored": True,
        "signal_available_at": _iso(signal_at),
        "delivered_at": _iso(delivered_at),
        "signal_entry_boundary": _iso(signal_start),
        "delivery_entry_boundary": _iso(delivery_start),
        "horizon_bars": horizon_bars,
        "horizon_resolved_at": _iso(delivery_start + horizon_bars * BAR),
        "latency_seconds": round((delivered_at - signal_at).total_seconds(), 3),
        "pre_signal_features": pre,
        "signal_path": signal_path,
        "delivery_path": delivery_path,
    }
    signal_mfe, delivery_mfe = _number(signal_path.get("mfe_r")), _number(delivery_path.get("mfe_r"))
    if signal_mfe is not None and delivery_mfe is not None:
        result["latency_edge_decay_r"] = round(signal_mfe - delivery_mfe, 6)
        result["opportunity_capture"] = round(max(0.0, min(1.0, delivery_mfe / signal_mfe)), 6) if signal_mfe > 0 else None
    signal_ref, delivery_ref = signal_window[0]["o"], delivery_window[0]["o"]
    planned_risk = entry - stop if direction == "LONG" else stop - entry
    signed_chase = (delivery_ref - signal_ref) if direction == "LONG" else (signal_ref - delivery_ref)
    result["chase_decay_r"] = round(signed_chase / planned_risk, 6)
    return result


def _regime_key(value: Any) -> str | None:
    if not isinstance(value, Mapping) or not value:
        return None
    if any(str(item).lower() in {"", "missing", "unknown", "unavailable"} for item in value.values()):
        return None
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"))


def _wilson(wins: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 1.0
    p = wins / total
    denominator = 1.0 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def _feature_values(row: Mapping[str, Any]) -> dict[str, float]:
    source = row.get("pre_signal_features")
    if not isinstance(source, Mapping) or source.get("status") != "available":
        return {}
    output = {}
    for key, value in source.items():
        parsed = _number(value)
        if key not in {"bars_used"} and parsed is not None:
            output[key] = parsed
    return output


def _won(row: Mapping[str, Any]) -> bool:
    return row.get("delivery_path", {}).get("target_before_stop") is True


def build_bplus_upgrade_nominations(
    outcomes: Iterable[Mapping[str, Any]], *, as_of: datetime,
    minimum_sample: int = MIN_SAMPLE, minimum_forward_sample: int = MIN_FORWARD_SAMPLE,
    minimum_lift: float = 0.15,
) -> dict[str, Any]:
    """Discover on older outcomes and validate once on later outcomes."""
    minimum_sample = max(MIN_SAMPLE, minimum_sample)
    minimum_forward_sample = max(MIN_FORWARD_SAMPLE, minimum_forward_sample)
    as_of = as_of.astimezone(timezone.utc)
    excluded: Counter[str] = Counter()
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    seen: set[str] = set()
    for raw in outcomes:
        row = dict(raw)
        identity = str(row.get("outcome_id") or row.get("signal_id") or "")
        if not identity or identity in seen:
            excluded["missing_or_duplicate_identity"] += 1
            continue
        resolved = _timestamp(row.get("horizon_resolved_at"))
        signal_at = _timestamp(row.get("signal_available_at"))
        feature_cutoff = _timestamp((row.get("pre_signal_features") or {}).get("feature_cutoff_at"))
        if resolved is None or resolved > as_of:
            excluded["not_resolved_as_of_cutoff"] += 1
            continue
        if signal_at is None or feature_cutoff is None or feature_cutoff > signal_at:
            excluded["feature_leakage_or_missing_cutoff"] += 1
            continue
        if row.get("status") != "scored" or row.get("scored") is not True:
            excluded["not_scored"] += 1
            continue
        if str(row.get("grade") or "").upper() != "B+":
            excluded["not_bplus"] += 1
            continue
        family, regime = str(row.get("family_key") or ""), _regime_key(row.get("regime_bucket"))
        if not family or regime is None:
            excluded["missing_family_or_regime"] += 1
            continue
        if not _feature_values(row):
            excluded["missing_pre_signal_features"] += 1
            continue
        seen.add(identity)
        row["_identity"], row["_resolved"] = identity, resolved
        groups[(family, regime)].append(row)
    nominations: list[dict[str, Any]] = []
    cohort_reports: list[dict[str, Any]] = []
    for (family, regime), rows in sorted(groups.items()):
        rows.sort(key=lambda row: (row["_resolved"], row["_identity"]))
        if len(rows) < minimum_sample:
            cohort_reports.append({"family_key": family, "regime_bucket": json.loads(regime), "sample_size": len(rows), "status": "insufficient_data"})
            continue
        validation_size = max(minimum_forward_sample, math.ceil(len(rows) * 0.3))
        if len(rows) - validation_size < minimum_forward_sample:
            cohort_reports.append({"family_key": family, "regime_bucket": json.loads(regime), "sample_size": len(rows), "status": "insufficient_chronological_split"})
            continue
        train, validation = rows[:-validation_size], rows[-validation_size:]
        feature_names = sorted(set.intersection(*[set(_feature_values(row)) for row in train]))
        candidates: list[tuple[float, str, str, float]] = []
        for feature in feature_names:
            values = sorted(_feature_values(row)[feature] for row in train)
            threshold = statistics.median(values)
            for operator in (">=", "<="):
                selected = [row for row in train if (_feature_values(row)[feature] >= threshold if operator == ">=" else _feature_values(row)[feature] <= threshold)]
                if len(selected) < minimum_forward_sample:
                    continue
                lift = sum(_won(row) for row in selected) / len(selected) - sum(_won(row) for row in train) / len(train)
                candidates.append((lift, feature, operator, threshold))
        cohort = {"family_key": family, "regime_bucket": json.loads(regime), "sample_size": len(rows), "training_size": len(train), "forward_size": len(validation)}
        if not candidates:
            cohort_reports.append({**cohort, "status": "no_candidate"})
            continue
        _, feature, operator, threshold = max(candidates, key=lambda item: (item[0], item[1], item[2]))
        selected = [row for row in validation if feature in _feature_values(row) and (_feature_values(row)[feature] >= threshold if operator == ">=" else _feature_values(row)[feature] <= threshold)]
        if len(selected) < minimum_forward_sample:
            cohort_reports.append({**cohort, "status": "insufficient_forward_candidate_sample", "candidate_feature": feature})
            continue
        base_wins, selected_wins = sum(_won(row) for row in validation), sum(_won(row) for row in selected)
        base_rate, selected_rate = base_wins / len(validation), selected_wins / len(selected)
        lower, upper = _wilson(selected_wins, len(selected))
        base_lower, base_upper = _wilson(base_wins, len(validation))
        lift = selected_rate - base_rate
        confidence_lift = lower - base_rate
        status = (
            "nomination_ready"
            if lift >= minimum_lift and selected_rate > 0.5 and confidence_lift >= minimum_lift
            else "forward_evidence_insufficient"
        )
        cohort_reports.append({
            **cohort, "status": status, "candidate_feature": feature,
            "forward_candidate_size": len(selected), "forward_lift": round(lift, 6),
            "confidence_lower_bound_lift": round(confidence_lift, 6),
        })
        if status != "nomination_ready":
            continue
        evidence = [row["_identity"] for row in selected]
        material = json.dumps([family, regime, feature, operator, threshold, evidence], sort_keys=True)
        nominations.append({
            "nomination_id": hashlib.sha256(material.encode()).hexdigest(),
            "action": "nominate_bplus_to_aplus_shadow_rule_review",
            "family_key": family,
            "regime_bucket": json.loads(regime),
            "current_grade": "B+",
            "proposed_shadow_grade": "A+",
            "proposed_shadow_rule": {"feature": feature, "operator": operator, "threshold": round(threshold, 6)},
            "chronological_evidence": {"training_size": len(train), "forward_size": len(validation), "forward_candidate_size": len(selected), "forward_evidence_ids": evidence},
            "confidence": {"method": "wilson_95", "candidate_hit_rate": round(selected_rate, 6), "candidate_interval": [round(lower, 6), round(upper, 6)], "cohort_hit_rate": round(base_rate, 6), "cohort_interval": [round(base_lower, 6), round(base_upper, 6)], "observed_lift": round(lift, 6), "multiple_testing_note": "candidate selected on training split; evaluated once on chronological forward split"},
            "evidence_class": "exploratory_shadow_hypothesis",
            "confidence_gate": "candidate_wilson_lower_minus_forward_cohort_point_rate_at_least_minimum_lift",
            "forward_window": {
                "first_resolved_at": _iso(validation[0]["_resolved"]),
                "last_resolved_at": _iso(validation[-1]["_resolved"]),
                "reuse_policy": "freeze_by_nomination_id_and_do_not_reuse_as_a_new_independent_test",
            },
            "promotion_status": "human_review_required",
            "automatic_parameter_changes": False,
            "grade_mutated": False,
            "shadow_only": True,
            "execution_enabled": False,
            "can_submit_orders": False,
        })
    return {
        "schema_version": "bplus-chart-upgrade-nominations-v1",
        "generated_at": _iso(datetime.now(timezone.utc)),
        "as_of": _iso(as_of),
        "qualified_outcomes": len(seen),
        "minimum_sample": minimum_sample,
        "minimum_forward_sample": minimum_forward_sample,
        "excluded_counts": dict(sorted(excluded.items())),
        "cohorts": cohort_reports,
        "nominations": nominations,
        "evidence_policy": "provider_bars_only_chronological_train_then_forward_validation",
        "promotion_status": "human_review_required",
        "automatic_parameter_changes": False,
        "shadow_only": True,
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def persist_report(report: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(dict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)
