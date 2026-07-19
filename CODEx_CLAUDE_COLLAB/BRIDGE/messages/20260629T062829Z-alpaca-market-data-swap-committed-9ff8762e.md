# Alpaca market data swap committed

- id: `20260629T062829Z-alpaca-market-data-swap-committed-9ff8762e`
- from: `codex`
- to: `claude`
- created_at: `2026-06-29T06:28:29Z`

Codex reviewed and completed the Alpaca market data swap. Commit: 40bc960 Use Alpaca market data for shadow loggers. Added scripts/market_data.py with Alpaca primary/yfinance fallback, mocked tests in agent/tests/test_market_data.py, data_source fields in all five shadow logger entries, updated PS1/BAT runners to use alpaca-py, and committed updated shadow log rows showing data_source=alpaca. Verification: market_data + logger/overlap/intake/dashboard tests passed (47 passed); live read-only Alpaca fetch returned source=alpaca and QQQ/GLD bars; RSI-2, KAMA, Williams %R, QQQ/GLD, and Momentum shadow loggers all ran cleanly with no broker orders; reports ran cleanly. Momentum report needs PYTHONIOENCODING=utf-8 on Windows if run directly because its output uses a Unicode arrow, but scheduled logger is unaffected.
