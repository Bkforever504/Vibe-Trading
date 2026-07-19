# Codex Handoff — Sector Rotation Ranker

Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
Date: 2026-06-30

## Source Idea

Evaluated `oopslink/trading-skills`.

Verdict:

- Not useful as a direct dependency because it is Tushare/China A-share focused.
- Useful architecture/pattern: alpha ranking and sector rotation workflow.
- Built a US/Alpaca equivalent instead.

## What Shipped

New read-only scanner:

- `scripts/sector_rotation_ranker.py`
- `scripts/run_sector_rotation_ranker.ps1`
- `agent/tests/test_sector_rotation_ranker.py`

Outputs:

- `data/sector_rotation_rank_log.jsonl`
- `~/.vibe-trading/reports/sector-rotation-rank.json`

Universe:

- Benchmarks: `SPY`, `QQQ`, `IWM`, `SMH`
- Sectors: `XLK`, `XLF`, `XLE`, `XLV`, `XLY`, `XLP`, `XLU`, `XLI`, `XLB`, `XLRE`
- Defensive assets: `GLD`, `TLT`

Metrics:

- 1-day return
- 5-day return
- 20-day return
- relative strength vs SPY
- above/below 50DMA
- risk-on vs defensive top-5 leadership

Leadership outputs:

- `risk_on_leadership`
- `risk_on_lean`
- `defensive_rotation`
- `defensive_lean`
- `mixed`

## Integrations

Market Force:

- Added `sector_rotation` source path.
- Added `sector_rotation_force()`.
- Market Force now has 8 possible forces:
  1. trend
  2. levels/GEX
  3. momentum
  4. volatility
  5. narrative
  6. institutional/distribution
  7. breadth
  8. sector rotation

Reports:

- `scripts/signal_stack_health_report.py`
- `scripts/signal_stack_leaderboard.py`
- `scripts/export_daily_bot_activity_csv.py`

## Schedule

Created:

- `\VibeTrade\SectorRotationRanker`
  - Weekdays at 15:33 CT
  - Runs after breadth/distribution and before Market Force.
  - Status: Ready

## Verification

Focused test command:

```powershell
uv run --no-project --with pytest --with pandas --with numpy python -m pytest agent\tests\test_sector_rotation_ranker.py agent\tests\test_market_force_score.py agent\tests\test_signal_stack_health_report.py agent\tests\test_signal_stack_leaderboard.py agent\tests\test_export_daily_bot_activity_csv.py -q
```

Result:

```text
20 passed
```

Compile check passed.

## Live Smoke — 2026-06-30

Sector ranker:

```text
leadership=risk_on_leadership
force=1.5
risk_on_top5=3
defensive_top5=2
source=alpaca
top5: XLV, XLI, XLU, XLF, SMH
bottom5: XLB, XLK, XLY, XLE, GLD
```

Market Force after adding sector rotation:

```text
classification=bullish_lean
score=2.25
confidence=9.25
coverage=7/8
trend +2.0
gex 0.0
momentum missing
volatility 0.0
narrative +1.0
institutional -2.0
breadth -0.25
sector_rotation +1.5
```

Interpretation:

- Sector leadership improved the tape from mixed to bullish_lean.
- Severe distribution and breadth pressure still prevent full bullish confirmation.
- This is good behavior: smarter, not louder.

## Notes

Exposure Coach already ran before this new force was added. Its next scheduled run will incorporate the updated Market Force state automatically.

This remains read-only context. Do not wire to execution until 30-day outcome evidence exists.

