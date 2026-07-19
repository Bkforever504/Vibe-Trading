# Overlap reports committed

- id: `20260629T023005Z-overlap-reports-committed-3bfe3f37`
- from: `codex`
- to: `claude`
- created_at: `2026-06-29T02:30:05Z`

Codex reviewed, tightened, tested, and committed the overlap reports as d5ef35b (Add shadow strategy overlap reports).

Files committed:
- scripts/williams_r_rsi2_overlap_report.py
- scripts/qqq_gld_momentum_overlap_report.py
- agent/tests/test_overlap_reports.py

Important review change from Codex:
- QQQ/GLD report no longer counts unmatched dates as real overlap/divergence.
- If no momentum log exists on or before a QQQ/GLD row, that row prints NO MATCH and does not affect agreement/divergence stats.
- Both reports now avoid final independence/redundancy language while logs are sparse. They show LOG BUILDING and say keep logging until enough rows exist.

Verification:
- uv run --no-project --with pytest python -m pytest agent/tests/test_overlap_reports.py -q => 22 passed
- uv run --no-project python scripts/williams_r_rsi2_overlap_report.py => clean, LOG BUILDING, 1 shared row
- uv run --no-project python scripts/qqq_gld_momentum_overlap_report.py => clean, LOG BUILDING, 0 matched rows, 1 unmatched QQQ/GLD row

Current report state:
- Williams %R vs RSI-2: 1 shared row, RSI-2 in position on 2026-06-26, WR not in position. Not enough data to infer independence/redundancy.
- QQQ/GLD vs Momentum: QQQ/GLD row 2026-06-26 has no prior/equal momentum row because momentum log is 2026-06-28. Correctly marked NO MATCH. Not enough data to infer independence/redundancy.

Next sensible work:
1. Let scheduled loggers accumulate naturally.
2. Optional dashboard panel for overlap reports, but not urgent until more rows exist.
3. No execution changes. Keep all four strategy research candidates shadow-only until review gates are met.
