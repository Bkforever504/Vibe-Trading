$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
Set-Location $repo

uv run --no-project --with alpaca-py --with pandas --with yfinance python scripts\realized_implied_vol_scanner.py --print
