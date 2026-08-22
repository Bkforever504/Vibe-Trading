# Claude Handoff: Verified Trader Evidence Pipeline

Date: 2026-07-25
Repo: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`
Builder: Codex
Requested role: independent adversarial reviewer and next-stage builder

## Ultimate Goal

Collect complete, permissioned trader records and determine whether any external
trader or ensemble has repeatable expectancy after observation delay, spreads,
fees, slippage, outlier removal, and regime changes. Social claims can nominate
research but must never grant order authority.

This is not a promise to copy every profitable trader. The goal is a defensible
verified-trader intelligence network that can reject selective reporting and
survivorship bias.

## What Shipped

### Frozen evidence contract

- `research/VERIFIED_TRADER_EVIDENCE_PREREGISTRATION_2026-07-25.md`
- Fixed source tiers, consent rules, completeness and timeliness gates.
- One connected fill does not create a verified history.
- `execution_eligible` and `promotion_eligible` are always false.

### Canonical intake

- `scripts/verified_trader_intake.py`
- Append-only journal:
  `data/verified_trader_evidence_log.jsonl`
- Deterministic fingerprint deduplication.
- Recursive credential redaction.
- Explicit quarantine reasons.
- Adapters for:
  - paid X API research reports/logs
  - TradingView webhook JSON
  - Collective2-style JSON signals
  - SnapTrade activity JSON
  - broker CSV
  - consented manual exports
  - SEC Form 4 and CFTC COT context

### Evidence treatment

- X remains context-only even for verified authors.
- Broker and SnapTrade records require a consent reference.
- Timely TradingView/Collective2 alerts become replay candidates.
- They become live-shadow eligible only with a separately captured
  point-in-time market price.
- Thirty clean fill-derived outcomes establish count sufficiency only.
- Broker history remains unverified until the P0 completeness manifest proves
  full requested-period coverage.
- Non-broker sources cannot self-report outcomes into performance statistics.

### TradingView receiver

- `scripts/verified_trader_webhook.py`
- Opaque-token authenticated FastAPI endpoint.
- No broker or order client.
- Optional read-only Alpaca market join:
  - equity signals use latest IEX trade
  - option signals use the executable side of the indicative option quote
  - failed joins remain missing, never imputed

### Operations

- `scripts/run_verified_trader_webhook.ps1`
- `scripts/run_verified_trader_report.ps1`
- `scripts/register_verified_trader_report_task.ps1`
- Scheduled task:
  `\VibeTrade\VerifiedTraderEvidenceReport`
- Registered daily at 16:20 local.
- Manual test result: `LastTaskResult = 0`.
- Task performs no network access and places no orders.

### Examples and documentation

- `research/verified_trader_intake/README.md`
- `research/verified_trader_intake/broker_fills_template.csv`
- `research/verified_trader_intake/tradingview_payload.example.json`
- `research/verified_trader_intake/sources.example.json`

### Tests

- `agent/tests/test_verified_trader_intake.py`
- 20 direct tests.
- 80 focused tests pass when combined with:
  - X intake
  - copy-trader watchlist
  - consensus authority invariants
  - point-in-time quote capture
  - execution-gate audit
  - runtime scheduler
- `python scripts/execution_gate_audit.py` exits 0.
- `python -m py_compile` passes.
- Ruff was unavailable in the active Python environment.

## Live Migration Result

Existing `data/x_spy_research_intake_log.jsonl` was migrated:

- 180 source observations examined
- 163 unique records accepted
- 17 duplicates skipped
- 123 unique X accounts
- 0 quarantined
- 0 replay eligible
- 0 live-shadow eligible
- 0 execution eligible

That is the correct result. X is discovery evidence, not fill evidence.

Current report:

`C:\Users\kenne\.vibe-trading\reports\verified-trader-evidence.json`

Separate safe exports:

- `C:\Users\kenne\.vibe-trading\verified-trader-profiles.json`
- `C:\Users\kenne\.vibe-trading\verified-trader-signals.json`

The existing `copy-trader-profiles.json` and `copy-trader-signals.json` were
deliberately not overwritten.

## Verified Read-Only Market Test

The new Alpaca join successfully returned a timestamped latest SPY IEX trade.
No trading endpoint was imported or called. Do not record the observed test
price in documentation because it is time-sensitive.

## Claude's Required Adversarial Review

Attack these assumptions:

1. Find any path where a source can inflate its own evidence tier.
2. Find any option-direction inference from call/put right alone.
3. Find any way missing consent can enter statistics.
4. Find timestamp or timezone paths that create look-ahead.
5. Find deduplication collisions that hide losing records.
6. Find selective broker-export coverage that could masquerade as complete
   account history.
7. Find any raw-payload secret not caught by redaction.
8. Confirm the webhook cannot place orders and does not import trading clients.
9. Confirm live-shadow exports always carry a separately observed market price.
10. Confirm no generated report can overwrite production or legacy inputs by
    default.

## Next Builds, In Order

### P0: Account-history completeness proof

Create an immutable coverage manifest for broker/SnapTrade imports:

- requested date range
- returned date range
- account opening date where available
- row counts by activity type
- missing trading days
- deposits and withdrawals separated from P&L
- open positions and unrealized P&L
- checksums of sanitized source files

Do not label a history verified from outcome count alone when the exported date
range may be cherry-picked.

### P0: Outcome lifecycle join

Match signals, fills, and outcomes by stable position/trade identifiers.
Quarantine ambiguous joins. Add:

- observed entry price
- actual fill price
- source delay
- price drift
- fees and slippage
- MFE and MAE where market data exists
- strategy-specific exit rather than arbitrary fixed horizons

### P1: Commercial adapters

Build network clients only after Kenny approves any cost and supplies lawful
access:

- SnapTrade commercial read-only connection
- Collective2 data/AutoTrade fill feed

Never collect another trader's private data without explicit consent. Do not
accept shared brokerage passwords.

### P1: Public HTTPS webhook deployment

Before exposing TradingView receiver:

- TLS
- random token rotation
- request size and rate limits
- replay protection
- trusted reverse-proxy IP handling
- log redaction
- uptime monitoring

Do not deploy from this handoff without reviewing hosting and secrets.

### P2: Dashboard merge

Only after clean verified outcomes exist, add a read-only panel to the existing
copy-trader dashboard. The merge must remain explicit; do not replace the
legacy files automatically.

## Hard Boundaries

- Nothing live.
- No auto-promotion.
- No paid subscription without Kenny's approval.
- No credential sharing or unauthorized scraping.
- No retuning from the observed winners.
- MES task remains disabled.
- Human approval remains mandatory after independent adversarial review.
