from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.pine_source_scanner import scan_pine_source_dir, write_pine_source_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan a Pine Script source repo for repaint risk and translation candidates.")
    parser.add_argument("root", type=Path, help="Directory containing .pine files.")
    parser.add_argument("--out", type=Path, default=Path("research/pine_sources/source_scan_report.md"))
    args = parser.parse_args()

    summary = scan_pine_source_dir(args.root)
    write_pine_source_report(summary, args.out)
    print(f"Wrote {args.out.resolve()}")
    print(
        f"files={summary.total_files} indicators={summary.indicator_files} "
        f"strategies={summary.strategy_files} clean={summary.clean_files} "
        f"warnings={summary.warning_files} critical={summary.critical_files}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
