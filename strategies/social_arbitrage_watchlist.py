#!/usr/bin/env python3
"""Read-only social arbitrage watchlist.

Turns manually collected social trend observations into scored ticker watch
ideas. This is intentionally not a scraper and not an executor. It exists to
separate "viral product chatter" from investable, measurable public tickers.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUNTIME_DIR = Path(os.path.expanduser(r"~\.vibe-trading"))
REPORT_DIR = RUNTIME_DIR / "reports"
OBSERVATIONS_FILE = RUNTIME_DIR / "social-arb-observations.json"
MAPPING_FILE = RUNTIME_DIR / "social-arb-keyword-map.json"
REPORT_FILE = REPORT_DIR / "social-arbitrage-watchlist.json"
MIN_SOURCE_COUNT = 2
MIN_SCORE_FOR_WATCH = 7.0

DEFAULT_KEYWORD_MAP = {
    "stanley cup": {"ticker": "SWK", "theme": "consumer trend", "notes": "Brand/product trend; verify parent exposure."},
    "prime drink": {"ticker": "CELH", "theme": "beverage momentum", "notes": "Proxy for energy drink shelf demand."},
    "nvidia ai": {"ticker": "NVDA", "theme": "ai demand", "notes": "High crowding risk; require non-price catalyst."},
    "ozempic": {"ticker": "LLY", "theme": "glp-1", "notes": "Also map to NVO manually when relevant."},
    "weight loss drug": {"ticker": "LLY", "theme": "glp-1", "notes": "Needs news cross-check before trading."},
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return default


def _load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback


def load_keyword_map(path: Path = MAPPING_FILE) -> dict[str, dict[str, Any]]:
    data = _load_json(path, DEFAULT_KEYWORD_MAP)
    if not isinstance(data, dict):
        return DEFAULT_KEYWORD_MAP
    normalized: dict[str, dict[str, Any]] = {}
    for keyword, meta in data.items():
        if isinstance(meta, str):
            normalized[str(keyword).lower()] = {"ticker": meta.upper(), "theme": "manual", "notes": ""}
        elif isinstance(meta, dict):
            normalized[str(keyword).lower()] = {
                "ticker": str(meta.get("ticker") or "").upper(),
                "theme": str(meta.get("theme") or "manual"),
                "notes": str(meta.get("notes") or ""),
            }
    return {key: value for key, value in normalized.items() if value.get("ticker")}


def load_observations(path: Path = OBSERVATIONS_FILE) -> list[dict[str, Any]]:
    data = _load_json(path, [])
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _matched_keyword(text: str, keyword_map: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    lowered = text.lower()
    for keyword, meta in keyword_map.items():
        if keyword in lowered:
            return keyword, meta
    return None


def _observation_weight(row: dict[str, Any]) -> float:
    views = _safe_float(row.get("views"))
    likes = _safe_float(row.get("likes"))
    comments = _safe_float(row.get("comments"))
    growth = max(_safe_float(row.get("growth_pct")), 0.0)
    # Compress engagement so one giant post cannot dominate the whole report.
    engagement = min((views / 100_000.0) + (likes / 10_000.0) + (comments / 1_000.0), 5.0)
    return round(1.0 + engagement + min(growth / 50.0, 3.0), 3)


def score_social_arbitrage(
    observations: list[dict[str, Any]],
    *,
    keyword_map: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    mapping = keyword_map or DEFAULT_KEYWORD_MAP
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "ticker": "",
        "theme": "",
        "keywords": set(),
        "sources": set(),
        "weight": 0.0,
        "examples": [],
    })
    for row in observations:
        text = " ".join(str(row.get(key) or "") for key in ("keyword", "caption", "title", "text"))
        match = _matched_keyword(text, mapping)
        if not match:
            continue
        keyword, meta = match
        ticker = str(meta.get("ticker") or "").upper()
        if not ticker:
            continue
        item = grouped[ticker]
        item["ticker"] = ticker
        item["theme"] = str(meta.get("theme") or "")
        item["keywords"].add(keyword)
        item["sources"].add(str(row.get("source") or row.get("platform") or "unknown").lower())
        item["weight"] += _observation_weight(row)
        if len(item["examples"]) < 3:
            item["examples"].append({
                "source": str(row.get("source") or row.get("platform") or "unknown"),
                "keyword": keyword,
                "observed_at": str(row.get("observed_at") or row.get("date") or ""),
                "views": _safe_float(row.get("views")),
                "url": str(row.get("url") or ""),
            })

    scored: list[dict[str, Any]] = []
    for item in grouped.values():
        sources = sorted(item["sources"])
        score = min(10.0, round(float(item["weight"]) + len(sources), 2))
        action = "paper_watch" if score >= MIN_SCORE_FOR_WATCH and len(sources) >= MIN_SOURCE_COUNT else "research_only"
        warnings: list[str] = []
        if len(sources) < MIN_SOURCE_COUNT:
            warnings.append("single-source trend; needs cross-platform confirmation")
        warnings.append("social attention is not a trade signal without price/volume confirmation")
        scored.append({
            "ticker": item["ticker"],
            "theme": item["theme"],
            "score": score,
            "action": action,
            "source_count": len(sources),
            "sources": sources,
            "keywords": sorted(item["keywords"]),
            "examples": item["examples"],
            "warnings": warnings,
        })
    return sorted(scored, key=lambda row: (row["score"], row["source_count"]), reverse=True)


def build_report(
    *,
    observations_path: Path = OBSERVATIONS_FILE,
    mapping_path: Path = MAPPING_FILE,
) -> dict[str, Any]:
    mapping = load_keyword_map(mapping_path)
    observations = load_observations(observations_path)
    ideas = score_social_arbitrage(observations, keyword_map=mapping)
    return {
        "provider": "social_arbitrage_watchlist",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "research_only",
        "execution_enabled": False,
        "observation_count": len(observations),
        "mapped_keyword_count": len(mapping),
        "idea_count": len(ideas),
        "ideas": ideas,
        "warnings": [
            "Research-only social trend scanner. No broker orders are wired.",
            "Requires cross-platform confirmation and market price/volume confirmation before any paper trade.",
            "Do not scrape private or restricted feeds; use public/manual observations only.",
        ],
    }


def write_report(report: dict[str, Any], path: Path = REPORT_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build read-only social arbitrage watchlist report.")
    parser.add_argument("--observations", type=Path, default=OBSERVATIONS_FILE, help="JSON list of public/manual social observations.")
    parser.add_argument("--mapping", type=Path, default=MAPPING_FILE, help="Keyword-to-ticker map JSON.")
    parser.add_argument("--out", type=Path, default=REPORT_FILE, help="JSON report output path.")
    parser.add_argument("--print", action="store_true", help="Print report JSON.")
    args = parser.parse_args(argv)

    report = build_report(observations_path=args.observations, mapping_path=args.mapping)
    write_report(report, args.out)
    if args.print:
        print(json.dumps(report, indent=2))
    else:
        print(f"Social arbitrage watchlist report written to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
