"""Vendor-neutral options contract scoring for research and telemetry."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ContractRank:
    option_symbol: str
    strike: float
    right: str
    delta: float | None
    spread_pct: float | None
    quote_age_seconds: float | None
    expected_move_room: float | None
    premium_expansion_pct: float | None
    composite_score: float
    rank: int
    disqualified: bool
    disqualify_reason: str
    component_scores: dict[str, float]
    authority: str = "research_rank_only"

    def to_dict(self) -> dict:
        return asdict(self)


def _linear(value: float, best: float, worst: float, weight: float, *, lower_is_better: bool = True) -> float:
    if lower_is_better:
        if value <= best:
            return weight
        if value >= worst:
            return 0.0
        return weight * (worst - value) / (worst - best)
    if value >= best:
        return weight
    if value <= worst:
        return 0.0
    return weight * (value - worst) / (best - worst)


def _score(candidate: dict[str, Any]) -> tuple[float, dict[str, float], list[str]]:
    delta = abs(float(candidate["delta"])) if candidate.get("delta") is not None else None
    spread = float(candidate["spread_pct"]) if candidate.get("spread_pct") is not None else None
    age = float(candidate["quote_age_seconds"]) if candidate.get("quote_age_seconds") is not None else None
    room = float(candidate["expected_move_room"]) if candidate.get("expected_move_room") is not None else None
    expansion = float(candidate["premium_expansion_pct"]) if candidate.get("premium_expansion_pct") is not None else None
    reasons: list[str] = []
    if spread is not None and spread > 20.0:
        reasons.append("spread_over_20pct")
    if age is not None and age > 60.0:
        reasons.append("quote_older_than_60s")
    if delta is not None and delta < 0.10:
        reasons.append("delta_under_0.10")
    if expansion is not None and expansion > 150.0:
        reasons.append("premium_expansion_over_150pct")

    if delta is None:
        delta_score = 12.5
    elif 0.45 <= delta <= 0.55:
        delta_score = 25.0
    elif delta < 0.45:
        delta_score = _linear(delta, 0.45, 0.10, 25.0, lower_is_better=False)
    else:
        delta_score = _linear(delta, 0.55, 0.85, 25.0)
    spread_score = 12.5 if spread is None else _linear(spread, 3.0, 15.0, 25.0)
    age_score = 10.0 if age is None else _linear(age, 5.0, 30.0, 20.0)
    if room is None:
        room_score = 7.5
    elif 0.5 <= room <= 1.5:
        room_score = 15.0
    elif room < 0.5:
        room_score = _linear(room, 0.5, 0.0, 15.0, lower_is_better=False)
    else:
        room_score = _linear(room, 1.5, 2.0, 15.0)
    expansion_score = 7.5 if expansion is None else _linear(expansion, 30.0, 100.0, 15.0)
    components = {
        "delta": round(delta_score, 2),
        "spread": round(spread_score, 2),
        "quote_age": round(age_score, 2),
        "expected_move_room": round(room_score, 2),
        "premium_expansion": round(expansion_score, 2),
    }
    return round(sum(components.values()), 2), components, reasons


def rank_contracts(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = []
    for candidate in candidates:
        score, components, reasons = _score(candidate)
        scored.append((candidate, score, components, reasons))
    scored.sort(key=lambda item: (bool(item[3]), -item[1]))
    results: list[dict[str, Any]] = []
    for rank, (candidate, score, components, reasons) in enumerate(scored, start=1):
        row = ContractRank(
            option_symbol=str(candidate.get("option_symbol") or ""),
            strike=float(candidate.get("strike") or 0.0),
            right=str(candidate.get("right") or "").upper(),
            delta=float(candidate["delta"]) if candidate.get("delta") is not None else None,
            spread_pct=float(candidate["spread_pct"]) if candidate.get("spread_pct") is not None else None,
            quote_age_seconds=float(candidate["quote_age_seconds"]) if candidate.get("quote_age_seconds") is not None else None,
            expected_move_room=float(candidate["expected_move_room"]) if candidate.get("expected_move_room") is not None else None,
            premium_expansion_pct=float(candidate["premium_expansion_pct"]) if candidate.get("premium_expansion_pct") is not None else None,
            composite_score=score,
            rank=rank,
            disqualified=bool(reasons),
            disqualify_reason=",".join(reasons),
            component_scores=components,
        ).to_dict()
        results.append({**candidate, "contract_rank": row})
    return results
