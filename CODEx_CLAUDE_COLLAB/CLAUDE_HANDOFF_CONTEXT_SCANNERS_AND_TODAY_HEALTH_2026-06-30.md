# Claude Handoff - Context Scanners + 2026-06-30 Bot Health

Project:
`C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## What Codex Built

Three new read-only scanners were added. They do not place orders and do not
change execution gates.

### 1. Relative Volume Scanner

Files:
- `scripts/relative_volume_scanner.py`
- `scripts/run_relative_volume_scanner.ps1`

Output:
- `data/relative_volume_scan_log.jsonl`
- `~/.vibe-trading/reports/relative-volume-scan.json`

Purpose:
- Compares latest daily volume to prior 20-session average.
- Flags `context_signal=true` when relative volume is >= 2.0.
- Uses `scripts.market_data.fetch_ohlcv`, so Alpaca is primary and yfinance is fallback.

Smoke result:
- Ran on `SPY,QQQ,IWM,NVDA,TSLA`.
- Source: Alpaca.
- Unusual count: 0.

### 2. Opening Range Breadth Scanner

Files:
- `scripts/opening_range_breadth_scanner.py`
- `scripts/run_opening_range_breadth_scanner.ps1`

Output:
- `data/opening_range_breadth_log.jsonl`
- `~/.vibe-trading/reports/opening-range-breadth.json`

Purpose:
- Uses Alpaca IEX intraday bars.
- Computes 9:30-9:34 ET opening range.
- Classifies each symbol as above/below/inside opening range.
- Aggregates breadth bias.

Important fix:
- Initial run hit Alpaca SIP restriction.
- Patched scanner to request `DataFeed.IEX`, which works with the free Alpaca data plan.

Smoke result:
- Ran on `SPY,QQQ,IWM,NVDA,TSLA`.
- Bias: `bullish_breadth`.
- Above: SPY, QQQ, TSLA.
- Inside: IWM, NVDA.

### 3. SEC Insider Buying Scanner

Files:
- `scripts/sec_insider_buying_scanner.py`
- `scripts/run_sec_insider_buying_scanner.ps1`

Output:
- `data/sec_insider_buying_log.jsonl`
- `~/.vibe-trading/reports/sec-insider-buying.json`

Purpose:
- Uses public SEC EDGAR APIs.
- Maps ticker to CIK via `company_tickers.json`.
- Fetches recent Form 4 filings.
- Parses raw Form 4 XML for open-market acquisitions.

Important fix:
- SEC `primaryDocument` can include `xslF345X06/...xml`, which returns transformed HTML.
- Scanner now strips the transform folder and pulls the raw XML document.
- Parser also detects transformed HTML and errors clearly if it appears again.

Smoke result:
- Ran on `NVDA,TSLA,PLTR,COIN,HOOD`.
- No recent insider-buy signals in 14-day lookback.
- Clean run after patch.

## Reporting Integration

Updated:
- `scripts/signal_stack_health_report.py`
- `scripts/signal_stack_leaderboard.py`
- `scripts/export_daily_bot_activity_csv.py`

New sources are included in:
- Signal health JSON
- Signal leaderboard JSON
- Daily bot activity CSV

Refreshed:
- `~/.vibe-trading/reports/signal-stack-health.json`
- `~/.vibe-trading/reports/signal-stack-leaderboard.json`
- `~/.vibe-trading/reports/daily-bot-activity-2026-06-30.csv`

## Tests

New:
- `agent/tests/test_new_context_scanners.py`

Verification:
```powershell
uv run --no-project --with pytest --with pandas --with numpy python -m pytest agent\tests\test_new_context_scanners.py agent\tests\test_signal_stack_health_report.py agent\tests\test_signal_stack_leaderboard.py agent\tests\test_export_daily_bot_activity_csv.py -q
```

Result:
- 15 passed.

Focused scanner tests after SEC/ORB patches:
- 7 passed.

Compile:
```powershell
uv run --no-project python -m py_compile scripts\relative_volume_scanner.py scripts\sec_insider_buying_scanner.py scripts\opening_range_breadth_scanner.py scripts\signal_stack_health_report.py scripts\signal_stack_leaderboard.py scripts\export_daily_bot_activity_csv.py
```

Result:
- Passed.

## Task Scheduler

Registered:
- `\VibeTrade\OpeningRangeBreadthScanner`
  - Weekdays 08:40 local
  - Next run: 2026-07-01 08:40
- `\VibeTrade\RelativeVolumeScanner`
  - Weekdays 15:30 local
  - Next run: 2026-06-30 15:30
- `\VibeTrade\SECInsiderBuyingScanner`
  - Weekdays 19:05 local
  - Next run: 2026-06-30 19:05

All three are `Ready`.

## Health Report After Build

`scripts/signal_stack_health_report.py`

Result:
- OK: 5
- Stale: 0
- Missing: 3
- Error: 0

OK:
- GEX Scanner
- IVR Scanner
- Opening Range
- Relative Volume
- SEC Insider

Missing:
- TTM Squeeze
- WaveTrend
- SMC

Those are expected because their first close-time runs are scheduled for 15:20 local on 2026-06-30.

## 2026-06-30 Bot Health

Scheduled task status:
- `Flip-Bot-Entry`: ran 08:35, result 0.
- `Flip-Bot-Monitor`: ran 08:45, result 0.
- `VibeTrading-Portfolio-Monitor`: ran 08:50, result 0.
- `GEXScanner`: ran 08:35, result 0.
- `IVRScanner`: ran 08:35, result 0.
- `PreOpenSentimentLogger`: ran 08:25, result 0.
- `SocialTrendingSymbolsScanner`: ran 08:20, result 0.

Flip Bot 08:35:
- Fetched Alpaca equity: about `$88,750`.
- Bear/bull trend skipped due insufficient bars (`6 < 55`).
- 0DTE skipped: no catalyst, no gap, no ORB break.
- No flip setup today at that time.

Portfolio monitor:
- P&L today: `$+0.00`.
- Equity: about `$88,762` by 08:50.
- Soft/hard/emergency thresholds read correctly:
  - soft: `-$500`
  - hard: `-$750`
  - emergency: `-$1500`
- No portfolio kill switch file present.

IWM bot:
- Next 2026-06-30 entry run was still pending at 09:45 when Codex checked.
- Existing open trade from 2026-06-29:
  - `Put Spread [IWM]`
  - Legs: `IWM260709P00289000`, `IWM260709P00286000`
  - Credit: `$0.52`
  - Qty: 3
  - Status: open
  - Stop loss pct: `-1.0` (fixed -100% of credit behavior)
  - Last monitored 2026-06-29 15:00: P&L about `+$24`, `+15.4% of credit`

## Operational Notes

- The new scanners are context-only. Do not wire them into execution gates yet.
- Opening-range breadth is the most immediately useful for diagnosing trend days.
- Relative volume should be interpreted after close or with persistence; intraday daily volume may be incomplete.
- SEC insider buying is a slower swing context and should not affect 0DTE decisions.
- The worktree is dirty from prior sessions; Codex did not commit to avoid mixing unrelated changes.

## Recommended Next Claude Actions

1. After 15:20 local, run:
   ```powershell
   uv run --no-project python scripts\signal_stack_health_report.py
   ```
   Confirm TTM/WaveTrend/SMC no longer show missing.

2. After 19:25 local, inspect:
   ```powershell
   Get-Content C:\Users\kenne\.vibe-trading\reports\daily-bot-activity-2026-06-30.csv -Tail 20
   ```

3. Do not add any execution gate from these scanners until at least 30 days of logs.

