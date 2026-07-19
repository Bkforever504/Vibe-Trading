# Claude Handoff - Fable 5 Intelligence Upgrade

Date: 2026-07-04
Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## Mission

Codex implemented the five requested Fable 5 build-order tools as read-only intelligence/governance modules.

No live execution was enabled.
No risk thresholds were changed.
No guard behavior was loosened.

## What Shipped

### 1. Strategy Leak / Look-Ahead Audit

Files:
- `scripts/strategy_leak_audit.py`
- `scripts/run_strategy_leak_audit.ps1`

Purpose:
- Scans strategy code for common backtest leaks:
  - negative shift / future bars
  - Pine `lookahead_on`
  - centered rolling windows
  - full-dataset min/max normalization
  - same-bar high/low assumptions
  - unshifted signal warnings

Output:
- `data/strategy_leak_audit_log.jsonl`
- `~/.vibe-trading/reports/strategy-leak-audit.json`

Status:
- Governance/read-only.
- Critical finding means reject strategy until fixed.

### 2. HMM Regime Scanner

Files:
- `scripts/hmm_regime_scanner.py`
- `scripts/run_hmm_regime_scanner.ps1`

Purpose:
- HMM-style deterministic Gaussian-state approximation.
- Classifies market regime probabilities across SPY/QQQ/IWM:
  - `trend`
  - `chop`
  - `panic`

Output:
- `data/hmm_regime_log.jsonl`
- `~/.vibe-trading/reports/hmm-regime.json`

Important:
- This is a regime classifier, not a price predictor.
- Needs 30 trading days before any routing/gating discussion.

### 3. PCA Market Forces

Files:
- `scripts/pca_market_forces.py`
- `scripts/run_pca_market_forces.ps1`

Purpose:
- Compresses a liquid equity universe into principal return forces.
- Distinguishes:
  - broad-market force
  - sector/mega-cap force
  - idiosyncratic ticker residuals

Output:
- `data/pca_market_forces_log.jsonl`
- `~/.vibe-trading/reports/pca-market-forces.json`

Why it matters:
- Helps prevent chasing ticker screenshots that are actually just beta echoes.

### 4. Prediction Market Slow-News Watch

Files:
- `scripts/prediction_market_slow_news_watch.py`
- `scripts/run_prediction_market_slow_news_watch.ps1`

Purpose:
- Scans public Limitless markets for slower event-resolution windows:
  - CPI/inflation
  - FOMC/rates
  - jobs/payrolls
  - earnings
  - politics/policy

Output:
- `data/prediction_market_slow_news_log.jsonl`
- `~/.vibe-trading/reports/prediction-market-slow-news.json`

Hard line:
- No keys, no wallets, no orders.
- This only identifies markets to observe.

### 5. Agent Trade Debate Report

Files:
- `scripts/agent_trade_debate_report.py`
- `scripts/run_agent_trade_debate_report.ps1`

Purpose:
- Deterministic bull/bear/risk-manager debate.
- Reads available context from:
  - Market Force
  - Options Liquidity
  - Signal Health
  - HMM Regime
  - PCA Forces

Output:
- `data/agent_trade_debate_log.jsonl`
- `~/.vibe-trading/reports/agent-trade-debate.json`

Verdicts are always observe-only:
- `risk_veto_observe_only`
- `bull_case_leads_observe_only`
- `bear_case_leads_observe_only`
- `no_consensus_observe_only`

## Registry

Updated:
- `research/signal_registry.json`

New version:
- `2026-07-04`

Signal count:
- `69`

New IDs:
- `strategy_leak_audit`
- `hmm_regime_scanner`
- `pca_market_forces`
- `prediction_market_slow_news_watch`
- `agent_trade_debate_report`

All five have:
- `execution_enabled: false`
- `can_submit_orders: false`

## Tests / Verification

New tests:
- `agent/tests/test_fable5_intelligence_tools.py`

Focused test result:
- `10 passed`

Commands run:
```powershell
uv run --no-project --with pytest python -m pytest -q agent\tests\test_fable5_intelligence_tools.py
uv run --no-project python -m py_compile scripts\strategy_leak_audit.py scripts\hmm_regime_scanner.py scripts\pca_market_forces.py scripts\prediction_market_slow_news_watch.py scripts\agent_trade_debate_report.py
uv run --no-project python scripts\execution_gate_audit.py --print
python -m json.tool research\signal_registry.json
```

Execution audit:
- `passed=True`
- `signals=69`
- `issues=0`
- `warnings=1`

Known warning:
- `scripts/portfolio_concentration_monitor.py` reads Alpaca account/positions read-only. Existing expected warning.

## Notes For Claude

Do not schedule these yet unless Kenny explicitly asks.

Recommended next evaluation:
1. Run each script manually once after market data/network availability is confirmed.
2. Add Signal Stack Health entries only after Task Scheduler tasks are created.
3. Decide whether HMM/PCA should feed Market Force as context-only fields.
4. Do not let HMM/PCA affect execution until 30 trading days of logs exist.
5. For strategy intake, make `strategy_leak_audit.py` mandatory before any new Pine/YouTube/X strategy becomes a candidate.

## Suggested Next Build

Add a small orchestrator:
- `scripts/run_fable5_intelligence_stack.ps1`

It should run the five scripts in this order:
1. Strategy Leak Audit
2. HMM Regime Scanner
3. PCA Market Forces
4. Prediction Market Slow-News Watch
5. Agent Trade Debate Report

Keep it manual/read-only first. Schedule only after one clean manual run.
