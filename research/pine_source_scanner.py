from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from research.pine_strategy_lab import parse_pine_strategy, scan_pine_red_flags


@dataclass(frozen=True)
class PineSourceRow:
    relative_path: str
    name: str
    script_type: str
    license: str
    version: str
    category: str
    indicators: list[str]
    critical_flags: list[str]
    warning_flags: list[str]

    @property
    def is_clean(self) -> bool:
        return not self.critical_flags and not self.warning_flags


@dataclass(frozen=True)
class PineSourceSummary:
    root: Path
    rows: list[PineSourceRow]

    @property
    def total_files(self) -> int:
        return len(self.rows)

    @property
    def strategy_files(self) -> int:
        return sum(1 for row in self.rows if row.script_type == "strategy")

    @property
    def indicator_files(self) -> int:
        return sum(1 for row in self.rows if row.script_type in {"study", "indicator"})

    @property
    def critical_files(self) -> int:
        return sum(1 for row in self.rows if row.critical_flags)

    @property
    def warning_files(self) -> int:
        return sum(1 for row in self.rows if row.warning_flags)

    @property
    def clean_files(self) -> int:
        return sum(1 for row in self.rows if row.is_clean)


def _first_match(source: str, pattern: str) -> str:
    match = re.search(pattern, source, flags=re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else ""


def _script_type(source: str) -> str:
    if re.search(r"\bstrategy\s*\(", source):
        return "strategy"
    if re.search(r"\bindicator\s*\(", source):
        return "indicator"
    if re.search(r"\bstudy\s*\(", source):
        return "study"
    return "unknown"


def _script_name(source: str, fallback: str) -> str:
    for pattern in [
        r"\bstrategy\s*\(\s*(?:title\s*=\s*)?['\"]([^'\"]+)",
        r"\bindicator\s*\(\s*(?:title\s*=\s*)?['\"]([^'\"]+)",
        r"\bstudy\s*\(\s*(?:title\s*=\s*)?['\"]([^'\"]+)",
    ]:
        name = _first_match(source, pattern)
        if name:
            return name
    return fallback


def scan_pine_source_dir(root: Path) -> PineSourceSummary:
    rows: list[PineSourceRow] = []
    for path in sorted(root.rglob("*.pine")):
        source = path.read_text(encoding="utf-8", errors="ignore")
        idea = parse_pine_strategy(source)
        flags = scan_pine_red_flags(source)
        rel = path.relative_to(root).as_posix()
        parts = path.relative_to(root).parts
        rows.append(
            PineSourceRow(
                relative_path=rel,
                name=_script_name(source, path.stem.replace("_", " ")),
                script_type=_script_type(source),
                license=idea.license,
                version=_first_match(source, r"//@version\s*=\s*(\d+)") or "unknown",
                category=parts[0] if len(parts) > 1 else "",
                indicators=idea.indicators,
                critical_flags=[flag.flag_id for flag in flags.critical_flags],
                warning_flags=[flag.flag_id for flag in flags.warning_flags],
            )
        )
    return PineSourceSummary(root=root, rows=rows)


def write_pine_source_report(summary: PineSourceSummary, path: Path) -> None:
    clean_rows = [row for row in summary.rows if row.is_clean]
    clean_rows = sorted(
        clean_rows,
        key=lambda row: (
            row.script_type != "strategy",
            row.category,
            row.relative_path,
        ),
    )

    lines = [
        "# Pine Source Scan Report",
        "",
        f"Root: `{summary.root}`",
        "",
        "| Metric | Count |",
        "|---|---:|",
        f"| Pine files | {summary.total_files} |",
        f"| Indicators/studies | {summary.indicator_files} |",
        f"| Strategies | {summary.strategy_files} |",
        f"| Clean files | {summary.clean_files} |",
        f"| Warning files | {summary.warning_files} |",
        f"| Critical repaint files | {summary.critical_files} |",
        "",
        "## Translation Queue",
        "",
        "Clean files below have no current scanner warnings. They are not approved strategies; they are candidates for manual translation and backtesting.",
        "",
        "| File | Name | Type | Category | Version | License | Tags |",
        "|---|---|---|---|---:|---|---|",
    ]
    for row in clean_rows[:40]:
        tags = ", ".join(row.indicators) if row.indicators else "-"
        lines.append(
            f"| `{row.relative_path}` | {row.name} | {row.script_type} | {row.category} | {row.version} | {row.license} | {tags} |"
        )

    flagged = [row for row in summary.rows if row.critical_flags or row.warning_flags]
    lines.extend([
        "",
        "## Flagged Files",
        "",
        "| File | Critical | Warnings |",
        "|---|---|---|",
    ])
    for row in flagged[:80]:
        critical = ", ".join(row.critical_flags) if row.critical_flags else "-"
        warnings = ", ".join(row.warning_flags) if row.warning_flags else "-"
        lines.append(f"| `{row.relative_path}` | {critical} | {warnings} |")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
