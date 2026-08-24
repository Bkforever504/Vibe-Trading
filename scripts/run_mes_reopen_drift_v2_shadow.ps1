param(
    [ValidateSet("entry", "resolve")]
    [string]$Mode = "entry"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"

uv run --no-project --with yfinance --with pandas --with numpy python scripts\mes_reopen_drift_v2_shadow.py --mode $Mode
uv run --no-project --with pandas --with numpy python scripts\shadow_outcome_resolver.py
