from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import agent_reach_trading_research as research


ROOT = Path(__file__).resolve().parents[2]


def _completed(stdout: str = "", stderr: str = "", code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


def test_normalize_source_requires_rules_before_preregistration() -> None:
    lead = research.normalize_source({
        "platform": "x",
        "external_id": "1",
        "url": "https://x.com/t/status/1",
        "text": "$SPY calls went 400% today",
    })
    exact = research.normalize_source({
        "platform": "youtube",
        "external_id": "2",
        "url": "https://youtube.com/watch?v=2",
        "title": "SPY gap continuation",
        "text": (
            "On the 5 minute chart enter after the breakout retest, stop below VWAP, "
            "trim at the target. The backtest includes slippage and every losing trade."
        ),
        "transcript_status": "available",
    })

    assert lead["classification"] == "rejected_marketing_claim"
    assert lead["claim_risk"]["profit_claim"] is True
    assert exact["classification"] == "preregistration_candidate"
    assert exact["execution_enabled"] is False
    assert exact["can_submit_orders"] is False


def test_promotional_claim_is_rejected_without_reproducible_rules() -> None:
    row = research.normalize_source({
        "platform": "tiktok",
        "external_id": "claim",
        "url": "https://www.tiktok.com/@trader/video/1",
        "text": "This guaranteed trading bot made $39,000 and never loses.",
        "access_mode": "authenticated_browser_snapshot",
    })

    assert row["classification"] == "rejected_marketing_claim"
    assert "promotional_profit_claim_without_reproducible_rules" in row["promotion_blockers"]
    assert row["automatic_promotion"] is False

    written_percent = research.normalize_source({
        "platform": "instagram",
        "external_id": "written-percent",
        "url": "https://www.instagram.com/p/written-percent/",
        "text": "Ten winning trades produced roughly 100 percent total profit on margin.",
    })
    assert written_percent["classification"] == "rejected_marketing_claim"
    assert written_percent["claim_risk"]["profit_claim"] is True


def test_reviewed_snapshot_rejection_note_cannot_fake_rule_completeness() -> None:
    rows, errors = research.collect_configured_social_sources([{
        "platform": "threads",
        "url": "https://www.threads.com/@trader/post/1",
        "text": "Money-making machine. No exact entry, exit, risk, or 5 minute timeframe was supplied.",
        "access_mode": "authenticated_browser_snapshot",
    }])
    row = research.normalize_source(rows[0])

    assert errors == []
    assert row["classification"] == "rejected_marketing_claim"
    assert row["rule_features"]["reproducible_rules_disclosed"] is False
    assert row["rule_features"]["entry_rule_present"] is False
    assert row["rule_features"]["exit_rule_present"] is False
    assert row["rule_features"]["risk_rule_present"] is False
    assert row["rule_features"]["timeframe_present"] is False


def test_order_layout_without_objective_entry_condition_is_not_candidate() -> None:
    row = research.normalize_source({
        "platform": "youtube",
        "external_id": "layout",
        "url": "https://www.youtube.com/watch?v=layout",
        "title": "Exact options order layout",
        "text": (
            "Trade on the 1 minute chart. Buy at market to enter, use a 20 percent stop, "
            "and sell at market or the 50 percent target. Losing trades are shown."
        ),
        "transcript_status": "available",
    })

    assert row["rule_features"]["entry_rule_present"] is True
    assert row["rule_features"]["entry_condition_present"] is False
    assert row["classification"] == "research_lead"
    assert "incomplete_entry_exit_risk_or_timeframe" in row["promotion_blockers"]


def test_verified_rule_still_requires_external_replay() -> None:
    row = research.normalize_source({
        "platform": "reddit",
        "external_id": "verified-rule",
        "url": "https://www.reddit.com/r/algotrading/comments/example",
        "text": (
            "On the 15 minute chart enter after a breakout retest, stop below the retest, "
            "and exit at two times risk. Complete trade history was broker verified and "
            "the walk forward backtest includes fees, slippage, drawdown, and losses."
        ),
        "independent_verification": True,
        "complete_loss_history": True,
    })

    assert row["classification"] == "verified_preregistration_candidate"
    assert row["required_next_step"] == "write_exact_preregistration_and_cost_aware_replay"
    assert row["execution_enabled"] is False


def test_youtube_collection_uses_agent_reach_ytdlp_and_transcript(tmp_path: Path) -> None:
    ytdlp = tmp_path / "yt-dlp.exe"
    ytdlp.write_text("placeholder", encoding="utf-8")

    def runner(args: list[str], _timeout: int) -> subprocess.CompletedProcess[str]:
        if "--flat-playlist" in args:
            return _completed(json.dumps({"id": "abc", "title": "Exact SPY rules", "channel": "Trader"}))
        output_index = args.index("-o") + 1
        destination = Path(args[output_index].replace("%(id)s", "abc") + ".en.vtt")
        destination.write_text(
            "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nEnter on the 5 minute retest.\n",
            encoding="utf-8",
        )
        return _completed()

    rows, errors = research.collect_youtube(
        "SPY exact rules",
        limit=1,
        ytdlp=ytdlp,
        runner=runner,
    )

    assert errors == []
    assert rows[0]["query"] == "SPY exact rules"
    assert rows[0]["url"].endswith("watch?v=abc")
    assert rows[0]["transcript_status"] == "available"
    assert "5 minute retest" in rows[0]["text"]


def test_x_collection_fails_closed_without_dedicated_credentials(monkeypatch) -> None:
    monkeypatch.delenv("TWITTER_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("TWITTER_CT0", raising=False)
    rows, errors = research.collect_x("SPY options", limit=5, twitter_command="twitter")
    assert rows == []
    assert "dedicated-account cookies" in errors[0]


def test_web_collection_uses_agent_reach_jina_route() -> None:
    seen: list[str] = []

    def runner(args: list[str], _timeout: int) -> subprocess.CompletedProcess[str]:
        seen.extend(args)
        return _completed("Entry after retest. Exit at target. Risk one percent on the daily chart.")

    rows, errors = research.collect_web_source(
        {"title": "Official research", "url": "https://example.com/research"},
        curl_command="curl",
        runner=runner,
    )

    assert errors == []
    assert "https://r.jina.ai/https://example.com/research" in seen
    assert rows[0]["platform"] == "web"
    assert rows[0]["url"] == "https://example.com/research"


def test_append_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "research.jsonl"
    row = research.normalize_source({
        "platform": "youtube",
        "external_id": "abc",
        "url": "https://youtube.com/watch?v=abc",
        "title": "Rules",
    })
    assert research._append_jsonl(path, [row]) == 1
    assert research._append_jsonl(path, [row]) == 0
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_build_report_includes_reviewed_social_snapshots() -> None:
    config = {
        "schema_version": 2,
        "youtube_queries": [],
        "x_queries": [],
        "web_sources": [],
        "social_sources": [
            {
                "platform": "x",
                "url": "https://x.com/trader/status/1",
                "author": "trader",
                "access_mode": "authenticated_browser_snapshot",
                "text": "A bot was built quickly and made $400 today. No rules were supplied.",
            },
            {
                "platform": "threads",
                "url": "https://www.threads.com/@quant/post/1",
                "author": "quant",
                "access_mode": "authenticated_browser_snapshot",
                "text": "Open-source algorithmic trading system with risk controls.",
            },
        ],
        "limits": {"maximum_text_characters": 6000},
    }

    report, rows = research.build_report(config, include_transcripts=False)

    assert report["by_platform"] == {"threads": 1, "x": 1}
    assert report["channel_status"]["x"] == "collected_reviewed_snapshot"
    assert report["channel_status"]["threads"] == "collected_reviewed_snapshot"
    assert report["preregistration_candidates"] == []
    assert len(report["rejected_marketing_claims"]) == 1
    assert all(row["can_submit_orders"] is False for row in rows)


def test_nightly_research_integration_cannot_block_existing_loop() -> None:
    runner = (ROOT / "scripts" / "run_nightly_research_loop.ps1").read_text(encoding="utf-8")
    assert "run_agent_reach_trading_research.ps1" in runner
    assert "try {" in runner and "catch {" in runner
    assert "nightly_research_loop.py --print" in runner
