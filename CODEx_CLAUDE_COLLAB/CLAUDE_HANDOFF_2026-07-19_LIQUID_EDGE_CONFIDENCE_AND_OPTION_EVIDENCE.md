# Claude Code Handoff - Liquid Edge Confidence and Option Evidence

Date: 2026-07-19
Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## Read First

1. `research/LIQUID_MARKET_EDGE_CONFIDENCE_2026-07-19.md`
2. `research/liquid_universe_orb_replication.py`
3. `research/liquid_universe_retest_lab.py`
4. `research/momentum_rotation_forward_extension.py`
5. `scripts/liquid_options_edge_shadow.py`

Do not enable execution or edit any broker order path. The working tree contains extensive user and agent work; do not revert or clean unrelated files.

## Current Verdict

- Lead: frozen ten-ETF, 12-month, weekly top-two momentum rotation. 2025+ return 51.08%, PF 3.456, Sharpe 1.572, max drawdown 12.20%; doubled switch cost 49.01%.
- Continue shadow: QQQ RSI2 prior-high with elevated volume.
- Continue restricted shadow: TQQQ first-five-minute RVOL, short side only; 2026 is negative.
- Continue hypothesis logging only: QQQ OR15 EMA + RVOL retest; development period is negative.
- Reject: SPY ORB and SPY retest variants.
- No candidate is live-ready or at 9/10 confidence.

## Independent Tasks

### P0 - Audit for false confidence

Review all three research scripts for:

- lookahead or same-bar leakage;
- incorrect session boundaries or timezone handling;
- split/corporate-action artifacts;
- optimistic switching cost or trade-count accounting;
- duplicated signals across long and short searches;
- bootstrap misuse and small-sample exaggeration.

Write findings first. Do not silently refactor before documenting behavioral impact.

### P0 - Complete option lifecycle evidence

Extend `scripts/liquid_options_edge_shadow.py` with monitor and exit outcome joining. Requirements:

- append-only records keyed by `signal_id`;
- actual contemporaneous bid/ask marks only;
- no midpoint substitution when either quote side is missing;
- report option P&L separately from underlying P&L;
- show IV, theta, and spread attribution where data exists;
- fail closed on stale or indicative-only quotes;
- no trading imports or order authority.

### P1 - Independent momentum replication

Replicate the frozen momentum rule with an independent provider or raw Alpaca daily data. Preserve the exact universe, 12-month lookback, five-day rebalance, top-two selection, next-bar position shift, and cash rule. Compare adjusted-return assumptions and report 2025 and 2026 separately.

### P1 - Volatility risk premium feasibility

Ingest official Cboe PutWrite benchmark history and compare it with SPY buy-and-hold on return, drawdown, downside deviation, and crisis months. Then define a capped-risk local shadow candidate. Do not infer naked-put safety from win rate.

### P2 - Scheduler and market-calendar hardening

Replace weekend-only checks with the repo's official market-calendar helper if one exists. Verify the registered task remains read-only and deduplicates repeated morning scans.

## Verification Already Run

```powershell
uv run --no-project --python 3.12 --with pytest --with pandas --with numpy --with pyarrow --with alpaca-py --with yfinance pytest -q agent/tests/test_liquid_universe_orb_replication.py agent/tests/test_liquid_universe_retest_lab.py agent/tests/test_liquid_options_edge_shadow.py agent/tests/test_momentum_rotation_forward_extension.py test_momentum_rotation_backtest.py agent/tests/test_point_in_time_quotes.py agent/tests/test_flip_contract_ranker.py
```

Result: 27 passed.

Scheduled path:

- Task: `\VibeTrade\LiquidOptionsEdgeShadow`
- Last test result: 0
- Closed-market response: `status=market_closed`, zero signals, execution disabled.

## Deliverable

Return a severity-ordered review, tests added, exact commands run, changed files, and an updated honest confidence score. A score below 9 keeps every strategy shadow-only.
