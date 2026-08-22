from __future__ import annotations

from src.tools.pattern_grade_scorer import score_pattern_grade


def test_rubric_weights_and_a_grade_are_canonical_and_manual_only() -> None:
    result = score_pattern_grade(
        components={
            "base_rate": 80,
            "volume_rvol": 100,
            "mtf_alignment": 100,
            "regime_fit": 100,
            "confluence": 100,
            "reward_risk": 100,
        },
        evidence={"base_rate": "local_forward_validated", "order_flow": "unavailable"},
    )

    assert result["rubric_version"] == "pattern_grade_v1"
    assert result["weights"] == {
        "base_rate": 0.25,
        "volume_rvol": 0.15,
        "mtf_alignment": 0.20,
        "regime_fit": 0.15,
        "confluence": 0.15,
        "reward_risk": 0.10,
    }
    assert result["raw_score"] == 95.0
    assert result["final_score"] == 95.0
    assert result["grade"] == "A"
    assert result["label"] == "ALL_OBSERVED_CONDITIONS_ALIGNED"
    assert result["execution_enabled"] is False
    assert result["can_submit_orders"] is False


def test_all_penalties_are_multiplicative_and_disclosed() -> None:
    result = score_pattern_grade(
        components={name: 100 for name in (
            "base_rate",
            "volume_rvol",
            "mtf_alignment",
            "regime_fit",
            "confluence",
            "reward_risk",
        )},
        penalties={
            "anti_pattern": True,
            "macro_window": True,
            "wide_spread": True,
            "stale_feed": True,
        },
    )

    assert result["penalty_factors"] == {
        "anti_pattern": 0.5,
        "macro_window": 0.6,
        "wide_spread": 0.7,
        "stale_feed": 0.5,
    }
    assert result["final_score"] == 10.5
    assert result["grade"] == "D"
    assert result["label"] == "PASS"


def test_grade_thresholds_are_stable() -> None:
    def grade(score: float) -> str:
        return score_pattern_grade(
            components={name: score for name in (
                "base_rate",
                "volume_rvol",
                "mtf_alignment",
                "regime_fit",
                "confluence",
                "reward_risk",
            )}
        )["grade"]

    assert grade(85) == "A"
    assert grade(84.99) == "B"
    assert grade(70) == "B"
    assert grade(69.99) == "C"
    assert grade(55) == "C"
    assert grade(54.99) == "D"


def test_unknown_base_rate_is_a_labeled_neutral_prior_not_a_fake_probability() -> None:
    result = score_pattern_grade(
        components={
            "volume_rvol": 100,
            "mtf_alignment": 100,
            "regime_fit": 100,
            "confluence": 100,
            "reward_risk": 100,
        }
    )

    assert result["components"]["base_rate"] == 55.0
    assert result["evidence"]["base_rate"] == "unknown_neutral_prior"
    assert result["validation_status"] == "UNCALIBRATED"
    assert result["warnings"]

