#!/usr/bin/env python3
"""Run the research-only WorldQuant Alpha Lab."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.worldquant_alpha_lab import ALPHAS, DEFAULT_SYMBOLS, run_alpha_lab, write_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--alphas", default=",".join(ALPHAS.keys()))
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2026-01-01")
    parser.add_argument("--top-n", type=int, default=2)
    parser.add_argument("--long-only", action="store_true", help="Disable short leg; still research-only.")
    parser.add_argument("--out", type=Path, default=Path("research/worldquant_alpha_lab/report.md"))
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    alphas = [item.strip() for item in args.alphas.split(",") if item.strip()]
    results = run_alpha_lab(
        symbols=symbols,
        start=args.start,
        end=args.end,
        alpha_ids=alphas,
        top_n=args.top_n,
        dollar_neutral=not args.long_only,
    )
    write_report(results, args.out)

    print(f"Wrote {args.out.resolve()}")
    print(f"Alpha rows: {len(results)}")
    for result in results[:10]:
        m = result.metrics
        print(
            f"{result.alpha_id} status={result.status} conf={result.confidence_score:.1f} "
            f"pf={m.profit_factor:.2f} oos={m.out_of_sample_profit_factor:.2f} "
            f"wf={m.walk_forward_pass_rate:.2f} dd={m.max_drawdown_pct:.1f}%"
        )
    print("Research only. No orders placed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
