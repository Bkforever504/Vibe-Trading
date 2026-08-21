# Claude Handoff: Dashboard 10/10 for Manual A+ Setup Selection

Date: 2026-08-20 America/Chicago
Owner: Claude (audit + blueprint) → Codex (implementation)
Status: Audit complete, blueprint frozen. No code written this session.

## 0. TL;DR for Codex

Kenny needs a dashboard that helps him pick 1-3 A+ trades per day by manual
review, while every bot and shadow logger stays in read-only shadow mode.
The React `TradingCockpit` at `frontend/src/pages/TradingCockpit.tsx` is the
canonical surface. The static `scripts/generate_dashboard.py` HTML is a
secondary all-history control room; it stays for offline glance but does not
carry the daily decision workflow.

Do NOT ship broker buttons, order authority, or execution controls. Every
backend flag remains `execution_enabled: false`, `can_submit_orders: false`.

Deliverable: a "Daily Decision Board" mode inside the existing React app,
built as new components + widened backend payload, staged in the phases at
§7. No signal_registry.json edits, no live-bot edits, no data mutations.

## 1. What exists today

### 1a. Two parallel surfaces (both live)

| Surface | Path | Purpose | Data |
|---|---|---|---|
| React app | `frontend/src/pages/TradingCockpit.tsx` (route `/`) | Live cockpit, poll every `refresh_seconds` (default 15s) | `GET /trading/dashboard` from `agent/api_server.py` |
| Static HTML | `~/.vibe-trading/dashboard.html` (118KB) | 27-section batch-generated glance page | `scripts/generate_dashboard.py` reads reports + JSONL logs |

React cockpit is the workflow. Static HTML is the retrospective / all-history
view. Both stay.

### 1b. React cockpit contents (already built)

Header: mode pill, order-authority pill, refresh button, 7 tab views:
`Daily Board / Stocks / Options / Futures / All Setups / Risk & Ops / Sources`.

Overview tab renders (in order):

1. Score/probability policy strip
2. **CommandCard** - primary read-only instruction card (state, symbol,
   direction, setup, grade+score, trigger/invalidation/target/instrument,
   confirmation, next action, no-trade zone, dealer-gamma quadrant)
3. **DecisionDesk** - 4 lanes: shadow_ready, wait, late_no_chase, invalid
4. **SimpleSignalBoard** - green/yellow/red price-action rows
5. Market-wide discovery coverage metrics
6. Best stock / best options / best futures PlanCards
7. 8-metric row (market/breadth/leadership/equity/open/paper/system/stale)
8. Top setup queue table + market forces + execution state

Stocks/Options/Futures tabs: 2-column PlanCard grid.
All Setups tab: filterable/searchable candidate table with expand.
Risk & Ops tab: account + bots + task schedule.
Sources tab: source inventory + raw JSON inspector.

### 1c. Backend `/trading/dashboard` payload (schema v5)

`scripts/live_trading_cockpit.py` builds one blob from 35 report files.
Payload sections:

- `authority` (execution/paper flags, message)
- `headline` (best_setup, state, message)
- `command_card` (single primary instruction)
- `dealer_regime` (gamma route, provenance-qualified only)
- `decision_desk` (4 lanes with counts + rows)
- `market` (regime, force score, breadth, sector leadership, high-impact
  days ahead, warnings)
- `account` + `portfolio` (equity, BP, day change, positions, integrity)
- `operations` (health, signal-stack summary, tasks, audit issues, blockers,
  stale sources)
- `evidence` (shadow_consensus, shadow_audit, bottom_reversal,
  scanner_leadership, exit_accountability, move_coverage)
- `discovery` (coverage, precision watches, move coverage)
- `simple_signals` (green/yellow/red price-action rows)
- `trade_board` (stocks/options/futures top-N)
- `candidates` (full flat list)
- `sources` (freshness + age per report)
- `warnings`

### 1d. Static HTML sections (27 total)

`overview, pnl, charts, risk, bots, flip, iwm, positions, health, edge,
mastery, heatmap, quant-risk, kronos, consensus, grades, hot, asymmetry,
learning, watchlist, alpha, closure, loops, mahoraga, openalice, incentive,
review`.

TradingView Lightweight Charts already wired for: account equity, bot
cumulative P/L, health+grade trend. Hot ticker native ranked bars. CDN
`unpkg.com/lightweight-charts@5.2.0`.

### 1e. Untapped report firepower

`~/.vibe-trading/reports/` holds 175+ JSON files. Dashboard backend maps 35.
Rich untapped material relevant to A+ selection:

- `daily-outcome-review.json`, `daily-eod-summary.json`,
  `closed-trade-postmortem.json`, `flip-decision-missed-banger-review.json`
- `weekly-hot-instruments.json`, `relative-volume-scan.json`,
  `distribution-day-scan.json`, `opening-range-breadth.json`
- `sec-insider-buying.json`, `moondev-liquidation-context.json`,
  `crowded-positioning-scanner.json`, `deep-liquid-universe-scan.json`
- `options-liquidation-heatmap.json`, `options-surface-intelligence.json`,
  `options-vol-premium.json`, `option-premium-levels.json`
- `market-catalyst-calendar.json`, `geopolitical-risk-context.json`
- `flip-equity-curve.json`, `flip-executable-edge.json`,
  `flip-exit-quality.json`, `flip-shadow-pnl-evaluator.json`
- `rejected-trade-intelligence.json`, `needs-review-queue.json`,
  `trade-lesson-ledger.json`, `regime-memory.json`
- `signal-stack-leaderboard.json`, `signal-stack-grades.json`
- `social-trending-symbols.json`, `public-social-intake.json`,
  `verified-trader-evidence.json`
- `mes_reopen_vix_holdout.json` (already surfaced as MES candidate)

## 2. Best-in-class references (feature extraction)

Extracted for the A+ manual workflow only. No execution-facing features.

| Product | Feature that matters here | Vibe-Trading equivalent |
|---|---|---|
| ThinkOrSwim | Docked layout: chart + watchlist + level II + option chain on one pane | Right-rail persistent watchlist + expandable chart drawer per row |
| TradingView | Sticky top ticker strip, chart-first layout, keyboard-driven symbol switch | Sticky ticker strip with top-N precision watches + hotkey `1..9` |
| Trade Ideas | Alert-based scanner where signal freshness matters more than universe size | DecisionDesk becomes primary; each row shows evidence age chip |
| TrendSpider | Multi-timeframe agreement panel and "why now" text per idea | PlanCard "why it ranks" chips + HTF map summary chip |
| Finviz Elite | Density-first dark scan grid, sortable numeric columns | tanstack/table for `All Setups`, sortable score/lane/R-left |
| Benzinga Pro | Real-time news ticker with per-symbol filtering, catalyst tags | Catalyst-calendar strip pinned above CommandCard |
| ThinkOrSwim | Position-sizing calculator co-located with each idea | PlanCard "risk budget" widget: contract → max-loss → % of equity |

Universal patterns worth stealing:

- One primary color for actionable, muted greys for context, sparing red for
  invalidation only. No rainbow. High density, low chrome.
- Every card carries a data-timestamp chip. Stale = greyscale + banner.
- Numeric columns are right-aligned tabular-nums.
- Keyboard shortcuts: `?` opens legend, `/` focuses search, `1..7` jumps
  tabs, `r` refreshes.
- Every setup card shows source, plan_id, and a one-click "raw evidence"
  drawer.

## 3. Gap analysis (current vs 10/10)

### 3a. Real gaps (missing / weak)

1. **No persistent watchlist.** Kenny cannot pin symbols to track through
   the day. Precision-watch list rotates each radar refresh.
2. **No news / catalyst ticker.** Backend already reads
   `market-catalyst-calendar.json` but only surfaces `high_impact_days_ahead`
   count. No feed. No per-symbol catalyst tag on candidate rows.
3. **No chart quick-look.** Static HTML has Lightweight Charts for equity
   and P/L; React cockpit has ZERO price charts. A trader picking a setup
   needs to eyeball a 5m / daily chart.
4. **No options flow panel.** `options-surface-intelligence.json`,
   `options-liquidation-heatmap.json`, `options-vol-premium.json` unused in
   the React app.
5. **No position-sizing helper.** PlanCard shows trigger/stop/target but
   never resolves to "trade N contracts, risk $X, X% of equity".
6. **No journal / rejection audit.** `rejected-trade-intelligence.json` and
   `trade-lesson-ledger.json` do not surface in the React app. Kenny cannot
   see WHY yesterday's setups were skipped and what lessons apply today.
7. **No alerts / toast layer.** `sonner` is installed; unused for cockpit
   events (new confirmed setup, stale-source warning, invalidation crossed).
8. **No end-of-day retro.** `daily-eod-summary.json` and
   `daily-outcome-review.json` unused.
9. **No keyboard shortcuts.** Every state change is mouse.
10. **No sticky top ticker.** Top setups scroll away when Kenny scrolls the
    Overview.
11. **No print / share view.** Can't print the daily board to PDF or paste
    to a partner.
12. **Mobile phone layout untested against the 10/10 bar.** Remote-tunnel
    exists (per handoff) but responsive breakpoints on CommandCard,
    DecisionDesk, and PlanCards are not audited to 375px.
13. **No error-boundary + graceful-degrade skeletons** on the cockpit view;
    a bad payload shows generic error card instead of last-known.
14. **No "why this is not actionable" summary** on stand-aside days. Kenny
    should see the top 3 blockers in plain English on the CommandCard when
    state = STAND_ASIDE.
15. **Static HTML is stale** (last generated 2026-07-28). Either kill it or
    put its generator on the scheduler (already exists as
    `VibeTradingDashboardServer` but check `LastRunTime`).

### 3b. Not gaps (already at bar)

- Read-only order authority contract - enforced end to end.
- Freshness / provenance discipline - CommandCard degrades to STAND_ASIDE
  on stale evidence.
- Rich payload with plan_id, dealer regime, decision desk, discovery.
- Design-system foundation (Tailwind tokens: `border`, `card`, `muted`,
  `success`, `warning`, `danger`, `info`, `primary`, `background`).
- Source inspector for raw JSON drill-down.

## 4. Design system

Keep the current Tailwind semantic tokens; formalize into a design-system
doc at `frontend/src/lib/design-tokens.ts` so both React app and any future
inlined React island in the static HTML can share.

### 4a. Palette (dark, already in use)

| Role | Hex (from static HTML root) | Semantic name |
|---|---|---|
| Canvas | `#0D1117` | `bg` |
| Surface | `#161B22` | `card` |
| Raised | `#1C2128` | `raised` |
| Border | `#30363D` | `border` |
| Border subtle | `#21262D` | `border-subtle` |
| Ink | `#E6EDF3` | `foreground` |
| Muted | `#7D8590` | `muted` |
| Dim | `#484F58` | `dim` |
| Success | `#3FB950` | `success` |
| Danger | `#F85149` | `danger` |
| Warning | `#D29922` | `warning` |
| Info / accent | `#58A6FF` | `info` / `primary` |

Green tinted panel `#0D2D1A`, red `#2D1215`, amber `#2B1F08`, blue
`#0D1F33` for lane backgrounds.

### 4b. Typography

- Sans: `Inter` 400/500/600/700 (already loaded).
- Mono: `JetBrains Mono` for all numerics, tickers, timestamps (already).
- Sizes: 10/11/12/13 for chrome, 14 body, 18 subhead, 24 stat, 32-48
  page-title-clamp.
- Every numeric uses `tabular-nums`.

### 4c. Spacing + density

- 4/8/12/16/20/24 px scale.
- Cockpit cards `p-3` (12px), section separators `py-4` (16px).
- Table rows `py-2.5` for scan density; row hover `bg-muted/30`.
- Max content width `1520px`.

### 4d. Motion

- Only refresh spinner + toast slide-in. No decorative animation. `framer-
  motion` is NOT required; keep bundle small. `sonner` covers toasts.

### 4e. Component library

- Keep `shadcn/ui` off the critical path for now; the cockpit already uses
  hand-rolled primitives (`StatusPill`, `GradeBadge`, `Metric`, `PlanCard`).
  Add shadcn incrementally per widget if a specific primitive (Command,
  Dialog, Tooltip, Sheet) needs it.
- **New required libs:**
  - `@tanstack/react-table` v8 - `All Setups` and future `Watchlist` /
    `Journal` tables. Small footprint, headless.
  - `lightweight-charts` v5 - price chart drawer + sparkline widget.
    Vendored via Vite import, not CDN.
  - `sonner` - already installed; wire it.
  - `cmdk` (optional, for command palette in phase 3).

## 5. Data feeds — what's needed vs available

| Need | Available today | Action |
|---|---|---|
| Watchlist symbols with live quotes | Alpaca quotes wired for bots, no cockpit REST | Add `GET /trading/quotes?symbols=...` proxying Alpaca last-quote; 5s TTL cache; degrade to `stale` on error |
| Intraday bars for chart drawer | Alpaca bars used by radar, no REST | Add `GET /trading/bars?symbol=&tf=5m&limit=200` proxying Alpaca IEX bars; 15s cache |
| News + catalyst per symbol | `market-catalyst-calendar.json` (macro only) | Add per-symbol catalyst rollup in report + expose via existing `/trading/dashboard/sources/market_catalyst_calendar` |
| Options flow / GEX | `options-surface-intelligence.json`, `options-liquidation-heatmap.json`, `options-vol-premium.json` present | Surface into `dealer_regime` payload extension; do NOT invent GEX if provenance missing (current rule) |
| SEC insider / dark-pool proxy | `sec-insider-buying.json` present | Add to `evidence` payload |
| Social flow (verified traders) | `verified-trader-evidence.json`, `public-social-intake.json`, `social-trending-symbols.json` present | Add to `evidence.social` sub-object |
| End-of-day retro | `daily-eod-summary.json`, `daily-outcome-review.json`, `closed-trade-postmortem.json` present | New `retro` payload block |
| Rejection / missed | `rejected-trade-intelligence.json`, `flip-decision-missed-banger-review.json`, `trade-lesson-ledger.json` present | New `journal` payload block |

Everything above is READ ONLY. No feed additions require new broker
credentials beyond what Alpaca already provides.

## 6. Prioritized upgrade list

Priority = user impact × implementation cost. All items are inside the
read-only contract.

### P0 (block on ship)

1. **Sticky top ticker strip** with top-5 precision watches + evidence-age
   chip. Above CommandCard. Always visible while scrolling.
2. **CommandCard blocker summary** on STAND_ASIDE: render top 3 blockers as
   plain English chips.
3. **Alerts / toast layer** via `sonner`: fire on state change
   (STAND_ASIDE → READY_TO_REVIEW), stale-source degrade, invalidation
   crossed on a tracked candidate.
4. **Persistent watchlist** stored in `localStorage` (schema-versioned);
   right-rail on Overview and dedicated tab. Poll `/trading/quotes` at 5s.
5. **Chart drawer** on every candidate row + every watchlist row: opens
   right-side `Sheet` with `lightweight-charts` 5m and daily view.
6. **Position-sizing widget** inside PlanCard: pulls account equity + user
   `risk_pct` (persisted in Settings, default 0.5%) → contracts, max loss,
   equity %.
7. **Retro tab** rendering EOD summary + outcome review + last 5 postmortems.
8. **Error boundary + skeleton loaders** for every top-level section.
9. **Kill or refresh static HTML** decision: verify
   `VibeTradingDashboardServer` scheduled task is producing fresh HTML; if
   yes, ship a "Static Report" nav link; if not, mark section deprecated.

### P1 (ship soon)

10. **Catalyst ticker** pinned under top ticker: today's high-impact
    events, macro + earnings, from `market-catalyst-calendar.json`.
11. **Per-symbol news / catalyst tag** on candidate rows.
12. **Options context panel** on Options tab: surface / vol-premium /
    liquidation-heatmap read-only. Provenance-gated identical to
    `dealer_regime`.
13. **Rejection + lesson journal tab**, driven by
    `rejected-trade-intelligence.json` + `trade-lesson-ledger.json` +
    `needs-review-queue.json`.
14. **Social evidence panel** on Overview right rail (below watchlist):
    `verified-trader-evidence.json` + `social-trending-symbols.json`,
    labeled "context only, not entry".
15. **Keyboard shortcuts** via a `useHotkeys` hook: `?`, `/`, `1..7`, `r`,
    `w` (watchlist), `n` (next candidate).
16. **Mobile audit at 375/414/768** for CommandCard, DecisionDesk, PlanCard,
    sticky ticker, chart drawer.

### P2 (nice to have)

17. **Command palette** (`cmdk`): jump to symbol, tab, or source.
18. **Print / share view** at `/board/print` - Overview only, high contrast.
19. **Diff view for CommandCard** across polls: highlight what changed in
    the last 60s.
20. **Historic dashboard replay** slider: scrub reports by timestamp.

## 7. Implementation blueprint for Codex

Suggested phases. Each phase is independent; ship P0 first, then iterate.

### Phase A - Backend payload widening (no frontend churn)

1. Extend `scripts/live_trading_cockpit.py`:
   - Add `evidence.retro` = `daily_eod`, `daily_outcome`,
     `closed_postmortem`, `missed_banger`.
   - Add `evidence.journal` = `rejected_intel`, `lesson_ledger`,
     `needs_review`.
   - Add `evidence.social` = `verified_trader`, `public_intake`,
     `trending_symbols`.
   - Add `evidence.catalysts_today` = filtered slice of
     `market_catalyst_calendar` for today + tomorrow.
   - Extend `dealer_regime` (or new `options_context`) with surface /
     heatmap / vol-premium fields, still provenance-gated.
   - Register new source names in `REPORT_FILES` and
     `_source_inventory`.
   - Bump `schema_version` to 6.
2. Extend `agent/api_server.py` with two new endpoints, both auth-gated:
   - `GET /trading/quotes?symbols=A,B,C` - Alpaca last-quote proxy, 5s
     LRU cache, returns `{symbol: {price, bid, ask, ts, stale}}`.
   - `GET /trading/bars?symbol=X&tf=5m&limit=200` - Alpaca IEX bars, 15s
     cache, returns lightweight-charts-shaped candles.
   - Both refuse write methods; both stamp `execution_enabled: false`.
3. Add tests:
   - `agent/tests/test_live_trading_cockpit.py` for schema v6 fields.
   - `agent/tests/test_trading_quotes_endpoint.py` and
     `test_trading_bars_endpoint.py`.
4. Frontend types in `frontend/src/lib/api.ts`:
   - Extend `TradingDashboard` interface for new evidence blocks + bump
     `schema_version: 6`.
   - Add `getTradingQuotes(symbols: string[])` and
     `getTradingBars(symbol, tf, limit)` methods.

### Phase B - New shared primitives + design tokens

5. New file `frontend/src/lib/design-tokens.ts`: export palette + spacing
   + font stacks as JS objects; use Tailwind config to reference them.
6. New component `frontend/src/components/trading/TickerStrip.tsx`
   (sticky, 5 slots, evidence-age chip, hotkey `1..5`).
7. New component `frontend/src/components/trading/CatalystStrip.tsx`
   (pinned under TickerStrip).
8. New component `frontend/src/components/trading/ChartDrawer.tsx`
   using vendored `lightweight-charts`, opens as right-side Sheet.
9. New component `frontend/src/components/trading/PositionSizer.tsx`
   (equity, risk_pct, contract → max-loss, % of equity).
10. New component `frontend/src/components/trading/BlockerChips.tsx`
    (for CommandCard STAND_ASIDE state).
11. Persist user prefs in new store
    `frontend/src/stores/dashboardPrefs.ts` (Zustand): `risk_pct`,
    `watchlist_symbols`, `hotkeys_enabled`, `theme` (dark only for now).

### Phase C - Rewire Overview tab (P0)

12. Wrap Overview in `<ErrorBoundary>` (already exists at
    `components/common/ErrorBoundary.tsx`) + skeleton via
    `components/common/Skeleton.tsx`.
13. Insert `<TickerStrip />` + `<CatalystStrip />` above
    `<CommandCard />`.
14. Inside `<CommandCard />`: render `<BlockerChips />` when
    `command.state === "STAND_ASIDE"`.
15. Inside `<PlanCard />`: render `<PositionSizer />` at the bottom of
    the numeric strip.
16. Add row action "Open chart" on `<CandidateRow />` → `<ChartDrawer />`.
17. Wire `sonner`: import in `Layout.tsx`, subscribe to command_card state
    changes via `useEffect` diff on `data.command_card.state`.

### Phase D - Watchlist tab (P0)

18. New page `frontend/src/pages/Watchlist.tsx`, route `/watchlist`.
19. Uses `dashboardPrefs.watchlist_symbols`, polls `getTradingQuotes` at
    5s, renders `@tanstack/react-table` grid with sparkline column (mini
    lightweight-chart).
20. Add "Pin" affordance on `<CandidateRow />` and `<PlanCard />`.

### Phase E - Retro + Journal tabs (P0/P1)

21. New page `frontend/src/pages/Retro.tsx`, route `/retro`. Renders
    `evidence.retro.daily_eod`, `daily_outcome`, top 5 `closed_postmortem`.
22. New page `frontend/src/pages/Journal.tsx`, route `/journal`. Renders
    `evidence.journal.rejected_intel`, `lesson_ledger`, `needs_review`.

### Phase F - Options context + social (P1)

23. Extend Options tab with `<OptionsContextPanel />` reading new
    `options_context` payload; identical provenance-gating rules as
    `<DealerGammaPanel />`.
24. Add `<SocialEvidencePanel />` to Overview right rail. Labeled
    "context only".

### Phase G - Keyboard + polish (P1)

25. New hook `frontend/src/hooks/useHotkeys.ts`. Wire in
    `TradingCockpit.tsx`.
26. Legend overlay via `?`.
27. Search focus via `/`.
28. Refresh via `r`.
29. Tab jump via `1..7`.
30. Mobile audit + adjust breakpoints.

### Phase H - Static HTML decision (P0 concurrent)

31. Verify `VibeTradingDashboardServer` scheduled-task status per
    handoff runbook.
32. Either:
    a. Keep, add a nav item "Static Report" pointing to it, or
    b. Deprecate: leave file in place, remove nav references, note in
       handoff.

### Phase I - Tests

33. Vitest coverage for every new component + hook + store.
34. Focused pytest for schema v6 in `test_live_trading_cockpit.py`.
35. `frontend/src/pages/__tests__/TradingCockpit.test.tsx` extension
    for TickerStrip/CommandCard-blocker/PositionSizer integration.

## 8. Constraints reminder (do not violate)

- Trading system state = suspended / shadow-only. NO order buttons.
- `execution_enabled` and `can_submit_orders` remain hardcoded false in
  every new payload block and endpoint.
- Do NOT edit `signal_registry.json` or any live-bot config.
- Do NOT fabricate GEX / probability / catalyst / target when the source
  is missing - degrade to "unavailable" like `_dealer_gamma_regime` does.
- New API endpoints must reject write methods and stay behind the
  existing auth boundary in `remote_dashboard_gateway.py`.
- Do NOT print secrets to logs or the HTML.
- Do NOT weaken the auth used by the remote tunnel.
- Follow preregistration culture: any new evidence surface must include
  freshness + source labels.

## 9. Edge status to render on the dashboard

Per `research/VERIFIABLE_EDGE_STATUS_2026-08-17.md` and the master handoff:

| Lane | Status | Dashboard treatment |
|---|---|---|
| MES reopen VIX-filter | supportive_shadow, currently `suspended` | Show in DecisionDesk with amber "supportive shadow, do not size" chip |
| GEX scanner | 11 usable SPY scans, context_only | Show in Options tab context panel, labeled "context only, 11 scans" |
| QQQ mean reversion | development-only | Do not show in DecisionDesk; expose in Journal tab only |
| MES overnight drift | suspended | Same as above |
| Volatility premium | suspended | Same |
| Trend participation | collecting | Show as data-collection card with `n=0 resolved` |
| Momentum ensemble | forward_shadow_candidate | Show in Journal only |
| Confirmed-momentum delayed | rejected | Journal only |
| MES intelligence meta-policy | rejected | Journal only |
| Event-gap continuation | shadow hypothesis (n=1) | Journal only; require n>=30, 20 dates before promotion |

## 10. Definition of done for a dashboard setup card

Every card on the daily board must expose all of these fields (mirrors the
master handoff's Definition of Done):

- as-of timestamp + completed-bar timestamp
- source freshness + completeness
- symbol + asset class
- direction + setup family
- trigger + required confirmation
- invalidation + defined max loss
- targets + reward/risk at current price
- lifecycle (wait / ready / no chase / invalid / stand aside)
- underlying + executable contract with bid/ask/size (or "pending chain")
- catalyst / event context
- market / sector / HTF structure
- liquidity + spread quality
- supporting + conflicting factors
- calibration cohort + sample size
- evidence label (research / shadow / paper review / approved)
- no implied guarantee, no hidden order authority

## 11. Test plan for Codex

Before marking a phase complete, run at minimum:

```powershell
Set-Location C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading
python -m pytest agent\tests\test_live_trading_cockpit.py agent\tests\test_intraday_opportunity_radar.py -q

Set-Location frontend
npm run test:run
npm run build
```

Focused test additions per phase:

- Phase A: `test_live_trading_cockpit.py` for schema v6; new endpoint tests.
- Phase B: unit tests for each new component; store tests for
  `dashboardPrefs`.
- Phase C: `TradingCockpit.test.tsx` extension.
- Phase D-G: page-level test each new route.

Manual smoke:

- Refresh cockpit; confirm STAND_ASIDE state renders blockers chip.
- Change `daily-outcome-review.json` mtime by touching it; confirm source
  freshness updates in Sources tab.
- Pin a symbol; confirm it survives reload (localStorage).
- Open chart drawer; confirm 5m and daily tabs render bars.
- Toggle a hotkey; confirm behavior.

## 12. What NOT to touch this cycle

- `strategies/*.py` (bot code)
- `signal_registry.json`
- `scripts/run_flip_bot_*.ps1`
- Scheduled task registrations
- Broker credentials, `.env`, `~/.vibe-trading/*.txt` secrets
- Live P/L or shadow ledger files under `data/`

## 13. Existing test surface (do NOT break)

Focused pytest suites to run green after Phase A + before any frontend edit:

**`agent/tests/test_generate_dashboard.py`** (384 lines, 8 tests) - static
HTML generator only. Covers flip stats split, options P/L estimate from
credit, chart cumulative series, loop closure, market mastery, daily edge,
kronos, static contract. Phase H (static kill/keep) must not regress this
until decision made. If deprecating static HTML, delete this file as part
of the same PR to keep the suite honest.

**`agent/tests/test_trading_dashboard.py`** (554 lines, 15 tests) - shared
panel builders (options group summary, tradingview context, polymarket,
fed whale, social arbitrage, strategy intake, momentum shadow, daily
shadow, portfolio guard, operations control room). Phase A schema-v6
additions must not touch the underlying panel builders; new fields ride
alongside.

**`agent/tests/test_options_grouped_dashboard.py`** (177 lines, 2 tests) -
options open-P/L grouping + manual-review flagging. Phase F options
context panel additions must preserve grouping shape.

**`agent/tests/test_live_trading_cockpit.py`** (referenced by master
handoff, 26 tests passing per verification) - CANONICAL for React cockpit
payload. Every Phase A schema-v6 field needs a test here before frontend
consumes it.

**`agent/tests/test_intraday_opportunity_radar.py`** - discovery source
tests; leave alone unless the discovery payload extension in Phase A
touches radar fields.

Frontend: `frontend/src/pages/__tests__/TradingCockpit.test.tsx` (1
passing test). Extend for TickerStrip/BlockerChips/PositionSizer.

Baseline screenshot: `output/playwright/trading-dashboard-restored.png`
predates current 7-tab layout (shows 4-tab version: Overview / Setups /
Risk & Ops / Sources with left sidebar). Do NOT restore that layout.
Current React code with 7 tabs (Daily Board / Stocks / Options / Futures /
All Setups / Risk & Ops / Sources) is the new baseline. Screenshot is
historical reference only.

## 14. Handoff to Codex

Read this doc. Read the master handoff (2026-08-20) alongside. Start with
Phase A. Confirm every test in §13 stays green after schema-v6 extension
before touching the frontend. Ship P0 (Phases A-E, H) before P1. Report
cost early and often per `CLAUDE.md`.

End.
