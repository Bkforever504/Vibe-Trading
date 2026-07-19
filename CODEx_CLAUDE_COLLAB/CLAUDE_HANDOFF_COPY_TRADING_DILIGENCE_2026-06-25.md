# Claude Handoff - Copy-Trading Diligence Layer

Date: 2026-06-25
Project: `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## Objective

Kenny wanted the Reddit/Coinpilot-style Polymarket copy-trading process implemented, plus similar resource research, while keeping everything paper-only and risk-controlled.

Core principle remains unchanged:

- Do not enable live execution.
- Do not copy raw whale sizing.
- Only trust verified public wallet history or exported broker/platform history.
- Social screenshots are research leads only, not copy signals.

## Research Inputs

Reddit thread reviewed:

- `https://old.reddit.com/r/PredictionsMarkets/comments/1u7o6kh/copytrading_has_never_been_this_easy_up_124_in_3/`
- Claimed approach: use Coinpilot Predict / AI picks, search for linear PnL curves, month-over-month green performance, mock-copy before live, and fixed copy size by profile.
- Important warning from comments: claims like 12% in 3 days are not durable proof; treat as a paper-test idea, not an edge.

Similar resources/repos found:

- `https://github.com/Obsidian-Trades/polymarket-copy-trading-bot`
- `https://github.com/radioman/polymarket-arbitrage-trading-bot`
- `https://github.com/dexorynlabs/polymarket-trading-bot-python`
- `https://github.com/TradeSEB/polymarket-copytrading-bot`
- `https://github.com/eliancheng/polymarket-copy-trading-bot`
- `https://github.com/pselamy/polymarket-insider-tracker`
- `https://github.com/Xyryllium/polymarket-tracker-bot`
- `https://github.com/polyalerth/polymarket-wallet-tracker`
- `https://github.com/FuckFiat/polymarket-whale-tracker`
- `https://github.com/Rebadged/polymarket-alpha`
- `https://github.com/kalkiai-trade/kalshi-copy-trading-bot`
- `https://github.com/Longbridges/polymarket-kalshi-arbitrage-bot`
- `https://github.com/suislanchez/polymarket-kalshi-weather-bot`
- `https://github.com/HarrierOnChain/Prediction-Markets-Trading-Bot-Toolkits`
- `https://github.com/OctagonAI/kalshi-trading-bot-cli`

Verdict: repos are useful for ideas and adapters, but many are thin or execution-first. Our best path is a platform-neutral watchlist/scoring layer first.

## Implemented

Files changed:

- `strategies/copy_trader_watchlist.py`
- `strategies/trading_dashboard.py`
- `agent/tests/test_copy_trader_watchlist.py`
- Runtime seed data updated: `C:\Users\kenne\.vibe-trading\copy-trader-profiles.json`
- Report regenerated: `C:\Users\kenne\.vibe-trading\reports\copy-trader-watchlist.json`

### New TraderProfile fields

Added diligence fields:

- `pnl_smoothness`
- `green_months`
- `monthly_consistency`
- `worst_month_pct`
- `avg_edge_per_trade`
- `fee_adjusted_return`
- `trade_frequency`

These load through `profile_from_dict()` and default safely to zero / unknown.

### New ScoredTrader fields

Added:

- `conviction_score`
- `suggested_copy_size`

Suggested copy size is intentionally small and paper-only:

- `15.0` when high conviction and selective cadence
- `5.0` for other approved paper-watch profiles
- `0.0` for review/reject

### Scoring behavior

Rewards:

- Smooth PnL curve
- 5+ green months
- Consistent month-to-month PnL
- Worst month no worse than -10%
- Avg edge and fee-adjusted return high enough to survive friction
- Selective or moderate trade cadence

Flags / blocks:

- Choppy PnL curve
- Too few green months
- Weak monthly consistency
- Large losing month
- Edge too small after fees
- Hyperactive/high-frequency copy risk

The diligence layer can only add a small boost, but negative diligence flags can block a trader from `paper_watch`.

### Dashboard

`copy_watchlist_panel()` now displays:

- Confidence
- Conviction
- Suggested copy size
- Status
- Risk flags

This makes the copy decision visible in the dashboard instead of buried in JSON.

## Runtime Report State

Current regenerated paper report:

- `execution_enabled=false`
- `watched_count=4`
- `paper_signal_count=4`

Current examples:

- `example_polymarket_wallet`: confidence 10, conviction 10, suggested copy size `$15`, paper_watch
- `example_solana_whale_wallet`: confidence 10, conviction 10, suggested copy size `$5`, paper_watch
- `example_kalshi_weather_trader`: confidence 10, conviction 10, suggested copy size `$15`, paper_watch
- `invo_social_clip_example`: confidence 0, conviction 0, suggested copy size `$0`, reject

Invo/social screenshot example is rejected due:

- unverified social data
- sample too small
- large drawdown
- high leverage
- choppy pnl curve
- too few green months
- weak month-to-month consistency
- large losing month
- edge too small after fees
- overtrading risk

## Tests

TDD was followed. New tests failed first before implementation.

Final verification:

```powershell
uv run --no-project --with pytest --with requests --with python-dotenv --with yfinance python -m pytest C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\agent\tests\test_copy_trader_watchlist.py C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\agent\tests\test_kalshi_prediction_bot.py C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\agent\tests\test_trading_dashboard.py C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\agent\tests\test_tradingview_validation_report.py C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\agent\tests\test_flip_bear_trend.py C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading\agent\tests\test_flip_bot_safety.py -q
```

Result:

```text
30 passed in 3.24s
```

## Next Best Tasks For Claude

1. Build an importer for Coinpilot/Kreo/Polymarket wallet exports.
   - Input should be CSV/JSON.
   - Output should append/update `C:\Users\kenne\.vibe-trading\copy-trader-profiles.json`.
   - Keep it read-only and paper-only.

2. Add monthly-stat derivation.
   - Given a list of historical trades, calculate:
     - `pnl_smoothness`
     - `green_months`
     - `monthly_consistency`
     - `worst_month_pct`
     - `avg_edge_per_trade`
     - `fee_adjusted_return`
     - `trade_frequency`
   - Do not rely on user-entered metrics once raw history is available.

3. Add Polymarket public wallet tracker adapter.
   - Start read-only.
   - Prefer public APIs/subgraphs if available.
   - No private keys.
   - No order placement.

4. Add Kalshi exported-history importer.
   - This complements the separate `Kalshi-Weather-Bot`.
   - Track prediction accuracy and realized return separately.

5. Add report section: "Why rejected".
   - Keep Kenny from being seduced by viral screenshots.
   - Show the exact flags and what proof would be needed to reconsider.

6. Only after 30+ paper copy signals:
   - Compute hit rate.
   - Compute paper P&L by profile and category.
   - Compare copy signal latency/drift.
   - Consider live only with explicit manual approval and tiny sizing.

## Safety Reminder

This system is a copy-trading lab, not an execution bot. All current outputs are paper-only. Do not wire live copy orders or private keys unless Kenny explicitly asks later, and even then require proof from a forward-test sample first.
