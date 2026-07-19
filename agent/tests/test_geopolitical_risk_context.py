from __future__ import annotations

from scripts import geopolitical_risk_context as risk


def test_explicit_geopolitical_energy_shock_creates_high_veto() -> None:
    articles = [{
        "headline": "US and Iran claim control of Strait of Hormuz after missile attack as Brent oil surges",
        "summary": "Shipping blockade risk is lifting crude prices.",
        "symbols": ["USO"],
        "created_at": "2026-07-13T14:00:00Z",
    }]
    result = risk.classify_risk(articles, None, day="2026-07-13")
    assert result["risk_level"] == "high"
    assert result["recommended_posture"] == "stand_aside"
    assert "dynamic_geopolitical_risk" in result["vetoes"]
    assert "new_short_premium_blocked" in result["vetoes"]


def test_unrelated_company_news_cannot_create_veto() -> None:
    articles = [{
        "headline": "Software company reports quarterly earnings",
        "summary": "Revenue exceeded estimates.",
        "symbols": ["ORCL"],
    }]
    result = risk.classify_risk(articles, None, day="2026-07-13")
    assert result["risk_level"] == "none"
    assert result["vetoes"] == []


def test_social_energy_symbol_requires_geopolitical_text() -> None:
    social = {
        "symbols": [{
            "symbol": "USO",
            "title": "United States Oil Fund",
            "summary": "Routine technical discussion without breaking macro news.",
        }]
    }
    result = risk.classify_risk([], social, day="2026-07-13")
    assert result["risk_level"] == "none"
