$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
uv run --no-project --with alpaca-py python scripts/portfolio_concentration_monitor.py --print
