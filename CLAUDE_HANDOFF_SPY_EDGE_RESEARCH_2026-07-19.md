# Claude Code Handoff: SPY / Options Edge Research

Date: 2026-07-19

## Repository

`C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

The worktree is dirty and contains user/Codex/Claude work. Do not revert unrelated changes. Do not enable or modify live trading authority.

## Objective

Independently challenge and extend Codex's SPY edge research. The goal is reproducible net expectancy, not a high screenshot win rate. Any candidate remains shadow-only until it passes chronological holdout, realistic bid/ask costs, year/regime stability, and 30+ untouched forward signals.

## Research Sources

- ORB paper, 7,000+ stocks and relative-volume "stocks in play," not a SPY-specific claim: https://papers.ssrn.com/sol3/Delivery.cfm/4729284.pdf?abstractid=4729284&mirid=1
- SPY first-half-hour to last-half-hour momentum paper: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2440866
- Cboe options benchmark library: https://www.cboe.com/us/indices/benchmark_indices/
- Cboe put-write / volatility-risk-premium research: https://www.cboe.com/insights/posts/white-paper-shows-volatility-risk-premium-facilitated-higher-risk-adjusted-returns-for-put-index/
- Popular SPY 0DTE ORB claim, 303 trades: https://www.reddit.com/r/options/comments/1rkx5vr/0dte_opening_range_breakout_strategy_on_spy_full/
- ORB reproducibility and lookahead-bias criticism: https://www.reddit.com/r/algotrading/comments/1j9pxsr/backtest_results_for_the_opening_range_breakout/
- Recent 0DTE QuantConnect discussion: https://www.reddit.com/r/algotrading/comments/1t59fsz/my_0dte_spy_backtesting/
- YouTube critique/backtest lead: https://www.youtube.com/watch?v=UFjajYgJBHg
- Raw last30days output: `C:\Users\kenne\Documents\Last30Days\best-evidence-backed-spy-intraday-and-options-trading-edges-compatible-with-opening-range-breakout-raw-v3.md`

Treat social claims as hypotheses. The last30days engine had weak coverage this run: X returned 403 and YouTube transcripts were unavailable. Web research supplemented it.

## Code and Reports

- `research/spy_orb_edge_lab.py`
- `research/spy_orb_sensitivity.py`
- `research/spy_orb_candidate_validation.py`
- `agent/tests/test_spy_orb_edge_lab.py`
- `data/last30days_spy_edge_plan.json`
- `~/.vibe-trading/reports/spy-orb-edge-lab.json`
- `~/.vibe-trading/reports/spy-orb-sensitivity.json`
- `~/.vibe-trading/reports/spy-orb-candidate-validation.json`

Data: Alpaca IEX SPY one-minute bars, 2022-01-01 through current, cached at `data/spy_1m_edge_lab.parquet`. Entries use the next 5-minute open after a close-confirmed breakout. Daily ATR, SMA, and relative volume are shifted. Stop wins ties conservatively. Costs are 1 bp per side by default.

## Results

Plain 5-minute SPY ORB failed:

- Train: 781 trades, -0.0623R expectancy, PF 0.901
- Holdout: 336 trades, -0.1297R expectancy, PF 0.801

VWAP, gap alignment, daily trend, range/ATR, and Monday-Wednesday-Friday filters did not rescue it. The older academic first-half-hour/last-half-hour momentum effect also failed in this 2022-2026 sample after costs:

- Train: -1.919 bps/trade
- Holdout: -2.788 bps/trade

Only research candidate worth independent replication:

- SPY 15-minute ORB (09:30-09:44 ET)
- First close-confirmed breakout, next 5-minute open
- Entry cutoff 10:30 ET
- Opening 5-minute volume >= prior 20-session mean
- Opposite OR boundary stop, 1.5R target
- One trade/day

Candidate metrics:

- Train: 294 trades, +0.0759R expectancy, PF 1.144
- Holdout: 127 trades, +0.0594R expectancy, PF 1.123
- Holdout bootstrap 95% CI: -0.1317R to +0.2496R
- Probability bootstrap mean > 0: 72.76%
- 2025 expectancy: -0.0324R
- Double-slippage holdout: -0.0061R, PF 0.988
- Confidence: 5.5/10, shadow only

This is not ready for capital and must not be inserted as a live gate.

## Claude Priority Tasks

1. Audit `spy_orb_edge_lab.py` independently for resampling errors, session-boundary mistakes, lookahead, survivorship, and cost assumptions. Add tests for 15-minute range construction, next-bar entry, and same-bar stop/target ambiguity.
2. Reproduce the exact candidate on consolidated SIP or Polygon one-minute SPY data. Do not tune parameters. Report discrepancies against IEX.
3. Build true historical option quote replay. Use NBBO bid/ask, not underlying-price proxies or option midpoint fantasy fills. Compare 0DTE ATM, 0DTE 0.55-0.70 delta, 1DTE, and defined-risk debit spreads. Buy at ask or a documented limit-fill model; exit at bid. Include stale/missing quotes and contract liquidity vetoes.
4. Keep option-selling / volatility-risk-premium research separate from ORB. Evaluate cash-secured puts or defined-risk put spreads against Cboe PUT/WPUT benchmarks with tail drawdown, margin, taxes, and assignment modeled. Do not combine a slow premium strategy with the intraday ORB score.
5. Add an untouched forward logger for the exact 15-minute RVOL rules. Promotion gate: at least 30 new signals, positive net expectancy, PF >= 1.15, no risk-rule violations, and positive executable option-quote replay.
6. Independently research Reddit, YouTube, X, practitioner blogs, SSRN, Cboe, and QuantConnect. Prefer code/data that can be reproduced. Record failed replications as prominently as positive ones.

## Safety Contract

- Shadow/research only.
- No broker order placement, cancellation, or account mutation.
- No live confidence upgrade based on social proof.
- No parameter selection using holdout results.
- Preserve append-only logs and report every tested variant, including failures.

When done, write `CODEX_HANDOFF_SPY_EDGE_REPLICATION_2026-07-19.md` with code changes, exact commands, tests, data provenance, all results, and unresolved limitations.
