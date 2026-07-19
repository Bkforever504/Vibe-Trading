---
name: vibe-trading-dashboard
description: Use when updating generate_dashboard.py, dashboard.html, bot health sections, P/L views, trade tables, scanner status, or dashboard design.
---

# Vibe-Trading Dashboard

## Key Files
- Generator: `scripts/generate_dashboard.py`
- Output: `~/.vibe-trading/dashboard.html` (static, no server)
- Tests: `agent/tests/test_generate_dashboard.py`

## Regenerate
```powershell
python scripts/generate_dashboard.py
# → Wrote C:\Users\kenne\.vibe-trading\dashboard.html
```

## Design System (dark cockpit theme)
- `--bg: #0D1117`, `--surface: #161B22`, `--raised: #1C2128`
- `--green: #3FB950`, `--red: #F85149`, `--amber: #D29922`, `--blue: #58A6FF`
- Fonts: Inter (body) + JetBrains Mono (numbers)
- Sticky nav, section IDs for anchor scroll, collapsible `<details>` for trade tables

## Nav Sections (in order)
`#overview` → `#pnl` → `#charts` → `#risk` → `#bots` → `#flip` → `#iwm` → `#positions` → `#health` → `#grades` → `#hot` → `#review`

## Section: Daily P/L by Symbol (`#pnl`)
- First section after Overview — highest-priority view
- Groups all closed trades by date (newest first)
- Shows day-header subtotal rows + per-trade rows with bot, symbol, P/L, detail
- Data from `model["flip_trades"]` (realized) + `model["options_state"]["trades"]` (estimated)

## Charts Section
- TradingView Lightweight Charts `@5.2.0` via CDN (`unpkg.com`)
- JSON data embedded in `<script id="chart-data" type="application/json">`
- Panels: account equity, bot cumulative P/L, health/grade trend, hot ticker bars
- CDN-only: charts need internet. Core stats render without charts.

## When Adding a New Section
1. Add `render_<section>(model)` function
2. Add nav link in `render_html()` nav_links list
3. Add `<div id="<id>" class="section">` in body
4. Add test assertion in `agent/tests/test_generate_dashboard.py`
5. Run `python -m pytest agent/tests/test_generate_dashboard.py -q` — must pass

## Verification
```powershell
python scripts/generate_dashboard.py
python -m pytest agent/tests/test_generate_dashboard.py -q
```
Check HTML: no `/v2/orders`, no broker calls, `No execution controls` in footer.
