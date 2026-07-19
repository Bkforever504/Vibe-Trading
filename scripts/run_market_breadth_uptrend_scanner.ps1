$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
uv run --no-project --with alpaca-py --with pandas python scripts/market_breadth_uptrend_scanner.py --print
