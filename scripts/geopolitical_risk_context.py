#!/usr/bin/env python3
"""Intraday geopolitical and energy-shock risk context.

Uses Alpaca's authenticated news feed plus the existing StockTwits context.
The output is a veto-only report: it can recommend standing aside but can
never create a trade, choose direction, or submit an order.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
VIBE_HOME = Path.home() / ".vibe-trading"
REPORT_PATH = VIBE_HOME / "reports" / "geopolitical-risk-context.json"
LOG_PATH = ROOT / "data" / "geopolitical_risk_context_log.jsonl"
SOCIAL_LOG_PATH = ROOT / "data" / "social_trending_symbols_log.jsonl"

CRITICAL_PHRASES = {
    "strait of hormuz",
    "military strike",
    "missile attack",
    "air strike",
    "airstrike",
    "naval blockade",
    "declaration of war",
    "ceasefire collapse",
}
GEOPOLITICAL_TERMS = {
    "iran", "israel", "middle east", "war", "conflict", "sanction",
    "attack", "missile", "blockade", "tanker", "geopolitical", "military",
}
ENERGY_TERMS = {"oil", "crude", "brent", "wti", "energy", "natural gas", "shipping"}
ENERGY_SYMBOLS = {"USO", "XLE", "XOM", "CVX", "OXY", "COP", "BNO"}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _latest_social(day: str, path: Path = SOCIAL_LOG_PATH) -> dict[str, Any] | None:
    rows = [row for row in _read_jsonl(path) if str(row.get("date")) == day]
    return rows[-1] if rows else None


def fetch_alpaca_news(now: datetime | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    now = now or datetime.now(timezone.utc)
    key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    if not key or not secret:
        return [], ["alpaca_news_credentials_missing"]
    try:
        response = requests.get(
            "https://data.alpaca.markets/v1beta1/news",
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            params={
                "start": (now - timedelta(hours=4)).isoformat().replace("+00:00", "Z"),
                "sort": "desc",
                "limit": 50,
                "include_content": "false",
            },
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return [], [f"alpaca_news_error:{type(exc).__name__}"]
    articles = payload.get("news") if isinstance(payload, dict) else []
    return ([item for item in articles or [] if isinstance(item, dict)], [])


def _evidence_score(text: str, symbols: list[str] | None = None) -> tuple[int, list[str]]:
    lowered = text.lower()
    critical = sorted(phrase for phrase in CRITICAL_PHRASES if phrase in lowered)
    geo = sorted(term for term in GEOPOLITICAL_TERMS if term in lowered)
    energy = sorted(term for term in ENERGY_TERMS if term in lowered)
    tagged_energy = sorted(set(symbols or []).intersection(ENERGY_SYMBOLS))
    score = 0
    if critical:
        score += 3
    score += min(3, len(geo))
    if energy and (critical or geo):
        score += 1
    if tagged_energy and (critical or geo):
        score += 1
    matches = critical + geo + energy + tagged_energy
    return score, sorted(set(matches))


def classify_risk(
    articles: list[dict[str, Any]],
    social: dict[str, Any] | None,
    *,
    day: str,
) -> dict[str, Any]:
    evidence = []
    for article in articles:
        text = " ".join(str(article.get(key) or "") for key in ("headline", "summary"))
        symbols = [str(item).upper() for item in article.get("symbols") or []]
        score, matches = _evidence_score(text, symbols)
        if score >= 2:
            evidence.append({
                "source": "alpaca_news",
                "score": score,
                "headline": str(article.get("headline") or "")[:240],
                "created_at": article.get("created_at"),
                "symbols": symbols[:12],
                "matches": matches,
                "url": article.get("url"),
            })

    for row in (social or {}).get("symbols", []):
        if not isinstance(row, dict):
            continue
        text = " ".join(str(row.get(key) or "") for key in ("title", "summary"))
        symbol = str(row.get("symbol") or "").upper()
        score, matches = _evidence_score(text, [symbol])
        if score >= 2:
            evidence.append({
                "source": "stocktwits_context",
                "score": score,
                "headline": str(row.get("summary") or row.get("title") or "")[:240],
                "created_at": row.get("summary_at"),
                "symbols": [symbol] if symbol else [],
                "matches": matches,
                "url": row.get("url"),
            })

    evidence.sort(key=lambda row: (int(row["score"]), str(row.get("created_at") or "")), reverse=True)
    strong_count = sum(1 for row in evidence if int(row["score"]) >= 3)
    max_score = max((int(row["score"]) for row in evidence), default=0)
    if max_score >= 5 or strong_count >= 2:
        level = "high"
    elif max_score >= 3:
        level = "medium"
    else:
        level = "none"
    vetoes = []
    if level == "high":
        vetoes = ["dynamic_geopolitical_risk", "new_short_premium_blocked", "size_down_required"]
    elif level == "medium":
        vetoes = ["dynamic_geopolitical_caution", "size_down_required"]
    return {
        "date": day,
        "risk_level": level,
        "max_evidence_score": max_score,
        "strong_evidence_count": strong_count,
        "vetoes": vetoes,
        "recommended_posture": "stand_aside" if level == "high" else "size_down" if level == "medium" else "normal_rules",
        "evidence": evidence[:12],
    }


def build_report(
    *,
    day: str | None = None,
    now: datetime | None = None,
    articles: list[dict[str, Any]] | None = None,
    social: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    day = day or now.date().isoformat()
    errors: list[str] = []
    if articles is None:
        articles, errors = fetch_alpaca_news(now)
    if social is None:
        social = _latest_social(day)
    risk = classify_risk(articles, social, day=day)
    return {
        "provider": "geopolitical_risk_context",
        "mode": "veto_only",
        "execution_enabled": False,
        "can_submit_orders": False,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        **risk,
        "sources": {
            "alpaca_news_article_count": len(articles),
            "stocktwits_context_available": social is not None,
        },
        "errors": errors,
        "warnings": [
            "Breaking-news classification is a protective veto, never a directional trade signal.",
            "A missing source cannot create an approval or loosen another gate.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build veto-only geopolitical risk context.")
    parser.add_argument("--date")
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--print", action="store_true", dest="do_print")
    args = parser.parse_args()
    load_dotenv(ROOT / "agent" / ".env")
    report = build_report(day=args.date)
    write_report(report, args.report_path)
    append_log(report, args.log_path)
    if args.do_print:
        print(json.dumps(report, indent=2))
    else:
        print(f"Geopolitical risk: {report['risk_level']} evidence={len(report['evidence'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
