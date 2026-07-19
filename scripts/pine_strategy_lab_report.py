from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.pine_strategy_lab import load_manifest_evaluations, write_candidate_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Rank Pine strategy ideas using honest backtest metrics.")
    parser.add_argument("--manifest", required=True, type=Path, help="JSON manifest with pine_file and metrics entries.")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "research" / "pine_strategy_lab" / "candidate_report.md",
        help="Markdown report path.",
    )
    args = parser.parse_args()

    evaluations = load_manifest_evaluations(args.manifest)
    write_candidate_report(evaluations, args.out)
    rejected = sum(1 for item in evaluations if item.status == "rejected")
    promoted = len(evaluations) - rejected
    print(f"Wrote {args.out}")
    print(f"Candidates: {len(evaluations)} | paper_candidate: {promoted} | rejected: {rejected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
