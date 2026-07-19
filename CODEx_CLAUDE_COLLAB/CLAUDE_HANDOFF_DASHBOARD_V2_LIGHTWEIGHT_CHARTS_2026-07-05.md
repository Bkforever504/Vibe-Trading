# Claude Code Handoff: Dashboard V2 Lightweight Charts Evaluation

Date: 2026-07-05
Owner: Codex
Status: Built and locally verified

## Objective

Evaluate the new Dashboard V2 chart layer added after the open-source repo review. The main upstream influence is `tradingview/lightweight-charts`, used only for read-only visualization inside the existing static HTML dashboard.

## Files Changed

- `scripts/generate_dashboard.py`
- `agent/tests/test_generate_dashboard.py`
- `research/repo_eval_trading_dashboard_ai_stack_2026-07-05.md`

Generated output:

- `C:\Users\kenne\.vibe-trading\dashboard.html`

## What Changed

- Added chart data construction to the dashboard model:
  - account equity from `account_equity_snapshot_log.jsonl`
  - Flip Bot cumulative realized P/L from closed trade logs
  - IWM Bot cumulative estimated P/L from active trade tracker rows when realized broker P/L is absent
  - bot health score trend from `bot_status_snapshot_log.jsonl`
  - signal grade score trend from `signal_stack_grades_log.jsonl`
  - hot ticker ranking from the existing hot ticker report
- Added a `Charts` section near the top of the dashboard.
- Added interactive TradingView Lightweight Charts panels:
  - account equity
  - bot cumulative P/L
  - health plus grade trend
- Added native HTML ranked bars for hot tickers because categorical ranking is easier to scan than a time-series chart.
- Added a no-library fallback so the dashboard still renders core stats if the chart script cannot load.

## Verification Run

Commands:

```powershell
python -m pytest agent/tests/test_generate_dashboard.py agent/tests/test_trading_dashboard.py -q
python -c "import ast, pathlib; ast.parse(pathlib.Path('scripts/generate_dashboard.py').read_text(encoding='utf-8')); print('syntax ok')"
python scripts\generate_dashboard.py
python scripts\execution_gate_audit.py
```

Results:

- Tests: `19 passed in 0.74s`
- Syntax: `syntax ok`
- Dashboard generated: `C:\Users\kenne\.vibe-trading\dashboard.html`
- Execution gate audit: passed, 72 registered signals, 0 issues, 1 warning

Browser visual smoke check against the generated file:

```json
{
  "title": "Vibe Trading · Control Room",
  "chartsSection": true,
  "chartBoxes": 3,
  "chartCanvases": 21,
  "rankRows": 10,
  "hasLightweightScript": true,
  "hasFallback": false,
  "hasFlipTrade": true,
  "hasIwmTrade": true,
  "overflowX": false,
  "scrollHeight": 8825
}
```

## Review Requests

1. Verify the chart math:
   - Flip Bot should use exact realized P/L from closed trade postmortems.
   - IWM Bot currently uses estimated active-trade P/L where realized broker P/L is not available.
2. Decide whether the CDN dependency is acceptable:
   - Current script: `https://unpkg.com/lightweight-charts@5.2.0/dist/lightweight-charts.standalone.production.js`
   - Tradeoff: static dashboard remains simple, but interactive charts are not fully offline unless the library is vendored or inlined.
3. Inspect visual quality and scan density:
   - Charts are intentionally near the top, below overview.
   - Hot tickers are native ranked bars rather than a chart canvas.
4. Check for old mojibake in existing dashboard copy/CSS comments, especially `Â·` or `â”€`, and clean only if safe.
5. Confirm this remains read-only:
   - no broker calls
   - no order submission paths
   - no scheduler mutation
   - no changes to execution controls

## Known Caveats

- Lightweight Charts is loaded from a pinned CDN URL, so interactive charts require network access unless vendored later.
- IWM Bot P/L is labeled estimated when realized P/L is absent.
- Chart history quality depends on how much JSONL history exists locally.
- This implementation did not install CCXT, AI-Trader, or other evaluated repos; those remain separate future candidates.

## Suggested Next Step

If the review passes, consider either:

- keeping the CDN for speed and simplicity, or
- vendoring the minified Lightweight Charts bundle into the dashboard generator for fully offline daily viewing.
