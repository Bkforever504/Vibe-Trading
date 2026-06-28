from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re


OPEN_SOURCE_LICENSES = {
    "apache-2.0",
    "bsd",
    "bsd-2-clause",
    "bsd-3-clause",
    "gpl",
    "gpl-3.0",
    "lgpl",
    "mit",
    "mpl-2.0",
    "unlicense",
}

_LICENSE_PATTERNS = [
    re.compile(r"@licen[sc]e\s+([A-Za-z0-9_.\-]+)", re.IGNORECASE),
    re.compile(r"//\s*licen[sc]e\s*[=:]\s*['\"]?([A-Za-z0-9_.\-]+)['\"]?", re.IGNORECASE),
]
_LICENSE_FULL_TEXT = [
    (re.compile(r"mozilla\s+public\s+license\s+2\.0", re.IGNORECASE), "mpl-2.0"),
    (re.compile(r"apache\s+license.*?2\.0", re.IGNORECASE), "apache-2.0"),
    (re.compile(r"gnu\s+general\s+public\s+license.*?3", re.IGNORECASE), "gpl-3.0"),
    (re.compile(r"\bmit\s+license\b", re.IGNORECASE), "mit"),
]


def _extract_license(source: str) -> str:
    for pattern in _LICENSE_PATTERNS:
        m = pattern.search(source)
        if m:
            return m.group(1).strip()
    for pattern, normalized in _LICENSE_FULL_TEXT:
        if pattern.search(source):
            return normalized
    return "unknown"


INDICATOR_PATTERNS = {
    "EMA": re.compile(r"\bta\.ema\b|\bema\b", re.IGNORECASE),
    "SMA": re.compile(r"\bta\.sma\b|\bsma\b", re.IGNORECASE),
    "RSI": re.compile(r"\bta\.rsi\b|\brsi\b", re.IGNORECASE),
    "VWAP": re.compile(r"\bta\.vwap\b|\bvwap\b", re.IGNORECASE),
    "ORB": re.compile(r"\borb\b|opening\s+range", re.IGNORECASE),
    "MACD": re.compile(r"\bta\.macd\b|\bmacd\b", re.IGNORECASE),
    "ATR": re.compile(r"\bta\.atr\b|\batr\b", re.IGNORECASE),
}


@dataclass(frozen=True)
class PineStrategyIdea:
    name: str
    license: str = "unknown"
    source_url: str | None = None
    indicators: list[str] = field(default_factory=list)

    @property
    def is_open_source(self) -> bool:
        normalized = self.license.strip().lower()
        return normalized in OPEN_SOURCE_LICENSES


@dataclass(frozen=True)
class BacktestMetrics:
    total_return_pct: float
    profit_factor: float
    max_drawdown_pct: float
    trade_count: int
    out_of_sample_profit_factor: float
    walk_forward_pass_rate: float


@dataclass(frozen=True)
class CandidateEvaluation:
    idea: PineStrategyIdea
    metrics: BacktestMetrics
    status: str
    confidence_score: float
    reject_reasons: list[str]


def parse_pine_strategy(source: str) -> PineStrategyIdea:
    name = _first_match(source, r"strategy\s*\(\s*['\"]([^'\"]+)['\"]") or "Unnamed Pine Strategy"
    license_name = _extract_license(source)
    source_url = _first_match(source, r"source\s*:\s*(https?://\S+)")
    logic_source = "\n".join(line for line in source.splitlines() if "strategy(" not in line.lower())
    indicators = [name for name, pattern in INDICATOR_PATTERNS.items() if pattern.search(logic_source)]
    return PineStrategyIdea(name=name, license=license_name, source_url=source_url, indicators=indicators)


def evaluate_candidate(idea: PineStrategyIdea, metrics: BacktestMetrics) -> CandidateEvaluation:
    reject_reasons: list[str] = []

    if not idea.is_open_source:
        reject_reasons.append("unknown or non-open-source license")
    if metrics.trade_count < 30:
        reject_reasons.append("too few trades")
    if metrics.profit_factor > 10:
        reject_reasons.append("profit factor is suspiciously high")
    if metrics.max_drawdown_pct > 25:
        reject_reasons.append("drawdown exceeds research limit")
    if metrics.out_of_sample_profit_factor < 1.15:
        reject_reasons.append("weak out-of-sample profit factor")
    if metrics.walk_forward_pass_rate < 0.6:
        reject_reasons.append("weak walk-forward pass rate")

    score = 4.0
    score += min(metrics.profit_factor, 2.0) * 1.2
    score += min(metrics.out_of_sample_profit_factor, 1.8) * 1.1
    score += min(metrics.walk_forward_pass_rate, 1.0) * 1.8
    score += min(metrics.trade_count / 200, 1.0) * 0.9
    score -= min(metrics.max_drawdown_pct / 20, 2.0)
    score -= len(reject_reasons) * 1.15
    score = round(max(0.0, min(10.0, score)), 1)

    status = "rejected" if reject_reasons else "paper_candidate"
    return CandidateEvaluation(idea=idea, metrics=metrics, status=status, confidence_score=score, reject_reasons=reject_reasons)


def write_candidate_report(evaluations: list[CandidateEvaluation], path: Path) -> None:
    rows = sorted(evaluations, key=lambda item: item.confidence_score, reverse=True)
    lines = [
        "# Pine Strategy Lab Candidate Report",
        "",
        "This report is a research filter only. No strategy should be promoted to live execution without paper-forward validation and execution guard review.",
        "",
        "| Strategy | Status | Confidence | PF | OOS PF | Trades | Max DD | Reject Reasons |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in rows:
        reasons = ", ".join(item.reject_reasons) if item.reject_reasons else "-"
        lines.append(
            "| "
            + " | ".join(
                [
                    item.idea.name,
                    item.status,
                    f"{item.confidence_score:.1f}",
                    f"{item.metrics.profit_factor:.2f}",
                    f"{item.metrics.out_of_sample_profit_factor:.2f}",
                    str(item.metrics.trade_count),
                    f"{item.metrics.max_drawdown_pct:.1f}%",
                    reasons,
                ]
            )
            + " |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_manifest_evaluations(manifest_path: Path) -> list[CandidateEvaluation]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    evaluations: list[CandidateEvaluation] = []
    for row in manifest:
        pine_path = manifest_path.parent / row["pine_file"]
        idea = parse_pine_strategy(pine_path.read_text(encoding="utf-8"))
        metrics = BacktestMetrics(**row["metrics"])
        evaluations.append(evaluate_candidate(idea, metrics))
    return evaluations


def _first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else None
