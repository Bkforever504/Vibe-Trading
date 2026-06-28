Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
Set-Location $repo
uv run --no-project --with alpaca-py --with yfinance --with pandas --with numpy --with python-dotenv --with requests python strategies\iwm_options_bot.py --monitor-only
