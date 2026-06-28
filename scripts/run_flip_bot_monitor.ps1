Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
Set-Location $repo
uv run --no-project --with yfinance --with python-dotenv --with requests python strategies\flip_bot.py --monitor
