param(
    [ValidateSet("entry", "resolve", "cycle")]
    [string]$Mode = "cycle",
    [switch]$Smoke
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"

$smokeArgument = if ($Smoke) { "--smoke" } else { "" }
uv run --no-project --with yfinance --with pandas --with numpy --with purgedcv==0.1.6 python scripts\mnq_smt_family_runner.py --mode $Mode $smokeArgument
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
