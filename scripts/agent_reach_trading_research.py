#!/usr/bin/env python3
"""Collect and normalize public trading research through Agent-Reach tools.

Agent-Reach is a capability router. This module calls its selected upstream
tools, stores source material as research evidence, and extracts deterministic
rule-completeness fields. It cannot promote strategies or submit orders.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_CONFIG = ROOT / "research" / "agent_reach_trading_sources.json"
DEFAULT_LOG = ROOT / "data" / "agent_reach_trading_research_log.jsonl"
DEFAULT_REPORT = VIBE_HOME / "reports" / "agent-reach-trading-research.json"
DEFAULT_YTDLP = Path.home() / ".agent-reach-venv" / "Scripts" / "yt-dlp.exe"

ENTRY_TERMS = ("entry", "enter", "buy at", "sell at", "breakout", "retest", "trigger")
ENTRY_CONDITION_TERMS = (
    "enter after", "enter when", "entry trigger", "after the breakout", "after a breakout",
    "breakout retest", "break and retest", "closes above", "closes below", "crosses above",
    "crosses below", "liquidity sweep", "opening range", "mean reversion", "gap continuation",
)
EXIT_TERMS = ("exit", "target", "take profit", "close at", "trim", "trailing")
RISK_TERMS = ("stop", "risk", "max loss", "invalidation", "position size")
TIMEFRAME_TERMS = ("1 minute", "5 minute", "15 minute", "30 minute", "1 hour", "daily", "weekly", "dte")
FRICTION_TERMS = ("slippage", "bid ask", "bid/ask", "commission", "fees", "transaction cost")
LOSS_TERMS = ("loss", "losing", "stopped", "drawdown", "failed trade")
BACKTEST_TERMS = ("backtest", "out of sample", "walk forward", "holdout", "monte carlo")
VERIFICATION_TERMS = (
    "audited", "broker verified", "independently verified", "myfxbook", "darwinex",
    "complete trade history", "all trades", "losing months",
)
PROMOTIONAL_TERMS = (
    "printing money", "money-making machine", "hasn't missed", "hasnt missed",
    "never loses", "guaranteed", "insane returns", "retired today", "no stress",
    "no guesswork", "made $", "turned $", "daily profit",
)
PROFIT_CLAIM_RE = re.compile(
    r"(?:"
    r"\+\d+(?:\.\d+)?%|"
    r"\$\s?\d[\d,]*(?:\.\d+)?|"
    r"made\s+\$?\s?\d|"
    r"(?:went|hit|returned)\s+\+?\d+(?:\.\d+)?%|"
    r"(?:profit\w*|return\w*|gain\w*|up)\s*(?:of|was|is|:)?\s*\+?\d+(?:\.\d+)?\s*(?:%|percent)|"
    r"\d+(?:\.\d+)?\s*(?:%|percent)(?:\s+\w+){0,2}\s+(?:profit|return|gain|result)"
    r")",
    re.IGNORECASE,
)
DIRECT_SOCIAL_PLATFORMS = {
    "x", "tiktok", "reddit", "instagram", "threads", "bluesky", "truthsocial",
}
STRATEGY_TAGS = {
    "gap_continuation": ("gap continuation", "gap and go", "gap hold"),
    "breakout_retest": ("breakout retest", "break and retest", "retest"),
    "volatility_risk_premium": ("implied volatility", "realized volatility", "volatility risk premium"),
    "opening_range": ("opening range", "orb"),
    "mean_reversion": ("mean reversion", "fade", "reversal"),
    "trend_following": ("trend following", "trend continuation", "momentum"),
    "market_structure": ("liquidity sweep", "fair value gap", "order block", "market structure"),
}
CASHTAG_RE = re.compile(r"\$([A-Z][A-Z0-9.]{0,7})\b", re.IGNORECASE)
PLAIN_SYMBOL_RE = re.compile(r"\b(SPY|SPX|QQQ|MES|ES|MNQ|NQ|AAPL|MSFT|NVDA|TSLA|META|AMZN|SMCI)\b", re.IGNORECASE)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("schema_version") not in {1, 2}:
        raise ValueError("unsupported Agent-Reach trading source schema")
    return payload


def _append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: set[str] = set()
    if path.exists():
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            source_id = str(row.get("source_id") or "")
            if source_id:
                existing.add(source_id)
    added = 0
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            if row["source_id"] in existing:
                continue
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")
            existing.add(row["source_id"])
            added += 1
    return added


def _run_command(args: list[str], timeout: int = 90) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _parse_json_documents(text: str) -> list[dict[str, Any]]:
    stripped = str(text or "").strip()
    if not stripped:
        return []
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("results", "posts", "tweets", "items"):
            nested = payload.get(key)
            if isinstance(nested, list):
                return [row for row in nested if isinstance(row, dict)]
        return [payload]
    rows: list[dict[str, Any]] = []
    for raw in stripped.splitlines():
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _clean_vtt(text: str) -> str:
    lines: list[str] = []
    previous = ""
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line == "WEBVTT" or "-->" in line or line.isdigit():
            continue
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line and line != previous:
            lines.append(line)
            previous = line
    return " ".join(lines)


def _youtube_transcript(
    ytdlp: str,
    url: str,
    *,
    runner: Callable[[list[str], int], subprocess.CompletedProcess[str]] = _run_command,
) -> tuple[str, str | None]:
    with tempfile.TemporaryDirectory(prefix="vibe-agent-reach-") as temp_dir:
        template = str(Path(temp_dir) / "%(id)s")
        result = runner(
            [
                ytdlp,
                "--write-sub",
                "--write-auto-sub",
                "--sub-langs",
                "en",
                "--sub-format",
                "vtt",
                "--skip-download",
                "--no-warnings",
                "-o",
                template,
                url,
            ],
            120,
        )
        if result.returncode != 0:
            return "", (result.stderr or result.stdout or "subtitle_fetch_failed")[-500:]
        files = sorted(Path(temp_dir).glob("*.vtt"))
        if not files:
            return "", "subtitle_unavailable"
        return _clean_vtt(files[0].read_text(encoding="utf-8", errors="replace")), None


def collect_youtube(
    query: str,
    *,
    limit: int,
    ytdlp: Path = DEFAULT_YTDLP,
    include_transcripts: bool = True,
    runner: Callable[[list[str], int], subprocess.CompletedProcess[str]] = _run_command,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not ytdlp.exists() and not shutil.which(str(ytdlp)):
        return [], ["youtube: yt-dlp unavailable"]
    result = runner(
        [str(ytdlp), "--flat-playlist", "--dump-json", "--no-warnings", f"ytsearch{limit}:{query}"],
        120,
    )
    if result.returncode != 0:
        return [], [f"youtube search failed: {(result.stderr or result.stdout)[-500:]}"]
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for item in _parse_json_documents(result.stdout)[:limit]:
        video_id = str(item.get("id") or "").strip()
        url = str(item.get("webpage_url") or item.get("url") or "").strip()
        if video_id and not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={video_id}"
        transcript = ""
        transcript_error = None
        if include_transcripts and url:
            transcript, transcript_error = _youtube_transcript(str(ytdlp), url, runner=runner)
            if transcript_error:
                errors.append(f"youtube {video_id or url}: {transcript_error}")
        rows.append({
            "platform": "youtube",
            "query": query,
            "external_id": video_id or url,
            "url": url,
            "author": item.get("channel") or item.get("uploader") or item.get("channel_id"),
            "title": item.get("title"),
            "published_at": item.get("upload_date") or item.get("timestamp"),
            "view_count": item.get("view_count"),
            "like_count": item.get("like_count"),
            "comment_count": item.get("comment_count"),
            "text": "\n".join(part for part in (str(item.get("description") or ""), transcript) if part),
            "transcript_status": "available" if transcript else "unavailable",
        })
    return rows, errors


def collect_x(
    query: str,
    *,
    limit: int,
    twitter_command: str | None = None,
    runner: Callable[[list[str], int], subprocess.CompletedProcess[str]] = _run_command,
) -> tuple[list[dict[str, Any]], list[str]]:
    command = twitter_command or shutil.which("twitter")
    if not command:
        return [], ["x: twitter-cli unavailable"]
    if not os.getenv("TWITTER_AUTH_TOKEN") or not os.getenv("TWITTER_CT0"):
        return [], ["x: dedicated-account cookies not configured in process environment"]
    result = runner([command, "search", query, "-n", str(limit), "--json"], 90)
    if result.returncode != 0:
        return [], [f"x search failed: {(result.stderr or result.stdout)[-500:]}"]
    rows: list[dict[str, Any]] = []
    for item in _parse_json_documents(result.stdout)[:limit]:
        author = item.get("username") or item.get("author_username") or item.get("screen_name")
        external_id = item.get("id") or item.get("tweet_id") or item.get("rest_id")
        url = item.get("url")
        if not url and author and external_id:
            url = f"https://x.com/{author}/status/{external_id}"
        rows.append({
            "platform": "x",
            "query": query,
            "external_id": str(external_id or url or ""),
            "url": url,
            "author": author,
            "title": None,
            "published_at": item.get("created_at") or item.get("timestamp"),
            "view_count": item.get("views") or item.get("view_count"),
            "like_count": item.get("likes") or item.get("favorite_count"),
            "comment_count": item.get("replies") or item.get("reply_count"),
            "text": item.get("text") or item.get("full_text") or item.get("content") or "",
            "transcript_status": "not_applicable",
        })
    return rows, []


def collect_web_source(
    source: dict[str, Any],
    *,
    curl_command: str | None = None,
    runner: Callable[[list[str], int], subprocess.CompletedProcess[str]] = _run_command,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Read an explicit public page through Agent-Reach's Jina route."""
    url = str(source.get("url") or "").strip()
    if not url.startswith(("https://", "http://")):
        return [], [f"web: invalid source URL {url!r}"]
    command = curl_command or shutil.which("curl")
    if not command:
        return [], ["web: curl unavailable"]
    result = runner(
        [command, "-L", "-sS", "--max-time", "45", f"https://r.jina.ai/{url}"],
        60,
    )
    if result.returncode != 0 or not str(result.stdout or "").strip():
        return [], [f"web {url}: {(result.stderr or result.stdout or 'reader_failed')[-500:]}"]
    return [{
        "platform": "web",
        "query": None,
        "external_id": url,
        "url": url,
        "author": source.get("author"),
        "title": source.get("title") or url,
        "published_at": source.get("published_at"),
        "view_count": None,
        "like_count": None,
        "comment_count": None,
        "text": str(result.stdout),
        "transcript_status": "not_applicable",
    }], []


def collect_configured_social_sources(
    sources: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Normalize reviewed browser/API snapshots without re-fetching user sessions."""
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(f"social_sources[{index}]: expected object")
            continue
        platform = str(source.get("platform") or "").strip().lower()
        url = str(source.get("url") or "").strip()
        text = str(source.get("text") or "").strip()
        if platform not in DIRECT_SOCIAL_PLATFORMS:
            errors.append(f"social_sources[{index}]: unsupported platform {platform!r}")
            continue
        if not url.startswith(("https://", "http://")) or not text:
            errors.append(f"social_sources[{index}]: URL and text are required")
            continue
        rows.append({
            "platform": platform,
            "query": source.get("query"),
            "external_id": source.get("external_id") or url,
            "url": url,
            "author": source.get("author"),
            "title": source.get("title"),
            "published_at": source.get("published_at"),
            "view_count": source.get("view_count"),
            "like_count": source.get("like_count"),
            "comment_count": source.get("comment_count"),
            "text": text,
            "transcript_status": source.get("transcript_status") or "not_applicable",
            "access_mode": source.get("access_mode") or "reviewed_snapshot",
            "reproducible_rules_disclosed": bool(source.get("reproducible_rules_disclosed", False)),
            "independent_verification": bool(source.get("independent_verification")),
            "complete_loss_history": bool(source.get("complete_loss_history")),
        })
    return rows, errors


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def normalize_source(raw: dict[str, Any], *, max_text_characters: int = 6000) -> dict[str, Any]:
    platform = str(raw.get("platform") or "unknown").lower()
    url = str(raw.get("url") or "").strip()
    external_id = str(raw.get("external_id") or url or "").strip()
    title = str(raw.get("title") or "").strip()
    text = re.sub(r"\s+", " ", str(raw.get("text") or "")).strip()[:max_text_characters]
    combined = f"{title} {text}".lower()
    symbols = sorted({match.upper() for match in CASHTAG_RE.findall(f"{title} {text}")})
    symbols.extend(symbol for symbol in PLAIN_SYMBOL_RE.findall(f"{title} {text}") if symbol.upper() not in symbols)
    symbols = sorted({str(symbol).upper() for symbol in symbols})
    tags = sorted(
        tag for tag, terms in STRATEGY_TAGS.items() if any(term in combined for term in terms)
    )
    features = {
        "entry_rule_present": _contains_any(combined, ENTRY_TERMS),
        "entry_condition_present": _contains_any(combined, ENTRY_CONDITION_TERMS),
        "exit_rule_present": _contains_any(combined, EXIT_TERMS),
        "risk_rule_present": _contains_any(combined, RISK_TERMS),
        "timeframe_present": _contains_any(combined, TIMEFRAME_TERMS),
        "friction_discussed": _contains_any(combined, FRICTION_TERMS),
        "losses_discussed": _contains_any(combined, LOSS_TERMS),
        "backtest_discussed": _contains_any(combined, BACKTEST_TERMS),
        "verification_discussed": _contains_any(combined, VERIFICATION_TERMS),
        "independent_verification": bool(raw.get("independent_verification")),
        "complete_loss_history": bool(raw.get("complete_loss_history")),
        "transcript_available": raw.get("transcript_status") == "available",
        "reproducible_rules_disclosed": raw.get("reproducible_rules_disclosed") is not False,
    }
    if raw.get("reproducible_rules_disclosed") is False:
        for key in (
            "entry_rule_present", "entry_condition_present", "exit_rule_present",
            "risk_rule_present", "timeframe_present",
        ):
            features[key] = False
    weighted = {
        "entry_rule_present": 1.5,
        "entry_condition_present": 1.5,
        "exit_rule_present": 1.5,
        "risk_rule_present": 1.5,
        "timeframe_present": 1.0,
        "friction_discussed": 1.5,
        "losses_discussed": 1.0,
        "backtest_discussed": 1.0,
        "verification_discussed": 1.0,
        "independent_verification": 1.5,
        "complete_loss_history": 1.0,
        "transcript_available": 1.0,
        "reproducible_rules_disclosed": 0.0,
    }
    completeness = round(sum(weighted[key] for key, present in features.items() if present), 2)
    canonical = f"{platform}|{external_id}|{url}|{title}".encode("utf-8")
    source_id = hashlib.sha256(canonical).hexdigest()[:24]
    core_rules_present = all(
        features[key]
        for key in (
            "entry_rule_present", "entry_condition_present", "exit_rule_present",
            "risk_rule_present", "timeframe_present",
        )
    )
    validation_present = any(
        features[key]
        for key in (
            "friction_discussed", "losses_discussed", "backtest_discussed",
            "verification_discussed", "independent_verification", "complete_loss_history",
        )
    )
    promotional_claim = _contains_any(combined, PROMOTIONAL_TERMS)
    profit_claim = bool(PROFIT_CLAIM_RE.search(combined))
    promotional_only = bool((promotional_claim or profit_claim) and not core_rules_present)
    exact_rule_candidate = bool(core_rules_present and validation_present)
    if exact_rule_candidate and features["independent_verification"]:
        classification = "verified_preregistration_candidate"
        evidence_tier = "independently_verified_rule_claim"
    elif exact_rule_candidate:
        classification = "preregistration_candidate"
        evidence_tier = "reproducible_social_rule_claim"
    elif promotional_only:
        classification = "rejected_marketing_claim"
        evidence_tier = "promotional_claim_only"
    else:
        classification = "research_lead"
        evidence_tier = "educational_or_process_claim"
    blockers: list[str] = []
    if not core_rules_present:
        blockers.append("incomplete_entry_exit_risk_or_timeframe")
    if not validation_present:
        blockers.append("no_cost_loss_backtest_or_verification_evidence")
    if not features["independent_verification"]:
        blockers.append("no_independent_track_record_verification")
    if promotional_only:
        blockers.append("promotional_profit_claim_without_reproducible_rules")
    return {
        "schema_version": 2,
        "source_id": source_id,
        "observed_at": _now_utc().isoformat().replace("+00:00", "Z"),
        "platform": platform,
        "query": raw.get("query"),
        "external_id": external_id,
        "url": url,
        "author": raw.get("author"),
        "title": title,
        "published_at": raw.get("published_at"),
        "engagement": {
            "views": raw.get("view_count"),
            "likes": raw.get("like_count"),
            "comments": raw.get("comment_count"),
        },
        "symbols": symbols,
        "strategy_tags": tags,
        "text_excerpt": text,
        "rule_features": features,
        "rule_completeness_score": completeness,
        "classification": classification,
        "evidence_tier": evidence_tier,
        "access_mode": raw.get("access_mode") or "provider_collection",
        "claim_risk": {
            "promotional_language": promotional_claim,
            "profit_claim": profit_claim,
            "promotional_only": promotional_only,
        },
        "promotion_blockers": blockers,
        "source_evidence_role": "social_or_educational_claim",
        "automatic_promotion": False,
        "execution_enabled": False,
        "can_submit_orders": False,
        "required_next_step": "write_exact_preregistration_and_cost_aware_replay",
    }


def build_report(
    config: dict[str, Any],
    *,
    ytdlp: Path = DEFAULT_YTDLP,
    include_transcripts: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    limits = config.get("limits") if isinstance(config.get("limits"), dict) else {}
    max_text = int(limits.get("maximum_text_characters") or 6000)
    raw_rows: list[dict[str, Any]] = []
    errors: list[str] = []
    channel_status = {"youtube": "not_run", "x": "not_run", "web": "not_run"}
    for query in config.get("youtube_queries") or []:
        rows, problems = collect_youtube(
            str(query),
            limit=int(limits.get("youtube_results_per_query") or 2),
            ytdlp=ytdlp,
            include_transcripts=include_transcripts,
        )
        raw_rows.extend(rows)
        errors.extend(problems)
    channel_status["youtube"] = "collected" if any(row.get("platform") == "youtube" for row in raw_rows) else "unavailable"
    for query in config.get("x_queries") or []:
        rows, problems = collect_x(str(query), limit=int(limits.get("x_results_per_query") or 10))
        raw_rows.extend(rows)
        errors.extend(problems)
    channel_status["x"] = "collected" if any(row.get("platform") == "x" for row in raw_rows) else "awaiting_dedicated_account_configuration"
    for source in config.get("web_sources") or []:
        if not isinstance(source, dict):
            continue
        rows, problems = collect_web_source(source)
        raw_rows.extend(rows)
        errors.extend(problems)
    channel_status["web"] = "collected" if any(row.get("platform") == "web" for row in raw_rows) else "unavailable"
    configured_rows, configured_errors = collect_configured_social_sources(config.get("social_sources") or [])
    raw_rows.extend(configured_rows)
    errors.extend(configured_errors)
    for platform in sorted(DIRECT_SOCIAL_PLATFORMS):
        if any(row.get("platform") == platform and row.get("access_mode") for row in configured_rows):
            channel_status[platform] = "collected_reviewed_snapshot"
        elif platform not in channel_status:
            channel_status[platform] = "not_configured"
    normalized = [normalize_source(row, max_text_characters=max_text) for row in raw_rows]
    by_platform: dict[str, int] = {}
    by_classification: dict[str, int] = {}
    for row in normalized:
        by_platform[row["platform"]] = by_platform.get(row["platform"], 0) + 1
        classification = str(row["classification"])
        by_classification[classification] = by_classification.get(classification, 0) + 1
    candidates = [
        row for row in normalized
        if row["classification"] in {"preregistration_candidate", "verified_preregistration_candidate"}
    ]
    report = {
        "schema_version": 2,
        "provider": "agent_reach_trading_research",
        "generated_at": _now_utc().isoformat().replace("+00:00", "Z"),
        "agent_reach_version": "1.5.0",
        "agent_reach_commit": "93ae1d18c37b707dec053c7c4f9d91cd8ef8943d",
        "mode": "research_intake_only",
        "channel_status": channel_status,
        "source_count": len(normalized),
        "by_platform": by_platform,
        "by_classification": by_classification,
        "preregistration_candidates": [
            row["source_id"] for row in candidates
        ],
        "candidate_summaries": [
            {
                "source_id": row["source_id"],
                "platform": row["platform"],
                "title": row["title"],
                "url": row["url"],
                "strategy_tags": row["strategy_tags"],
                "rule_completeness_score": row["rule_completeness_score"],
            }
            for row in candidates
        ],
        "rejected_marketing_claims": [
            row["source_id"] for row in normalized if row["classification"] == "rejected_marketing_claim"
        ],
        "errors": sorted(set(errors)),
        "governance": {
            "social_claims_are_edge_evidence": False,
            "engagement_is_edge_evidence": False,
            "screenshots_are_track_record_verification": False,
            "browser_snapshots_are_research_provenance_only": True,
            "requires_exact_preregistration": True,
            "requires_cost_aware_replay": True,
            "requires_out_of_sample_validation": True,
            "automatic_promotion": False,
            "execution_enabled": False,
            "can_submit_orders": False,
        },
    }
    return report, normalized


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--yt-dlp", type=Path, default=DEFAULT_YTDLP)
    parser.add_argument("--no-transcripts", action="store_true")
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args(argv)
    report, rows = build_report(
        _read_json(args.config),
        ytdlp=args.yt_dlp,
        include_transcripts=not args.no_transcripts,
    )
    report["new_source_count"] = _append_jsonl(args.log, rows)
    report["cumulative_source_count"] = sum(
        1 for line in args.log.read_text(encoding="utf-8-sig").splitlines() if line.strip()
    ) if args.log.exists() else 0
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
