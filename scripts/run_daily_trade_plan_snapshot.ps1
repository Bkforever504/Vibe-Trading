$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $HOME ".vibe-trading\logs"
$Uv = (Get-Command uv -ErrorAction Stop).Source

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $RepoRoot
& $Uv run python scripts\daily_trade_plan_snapshot.py *>> (Join-Path $LogDir "daily-trade-plan-snapshot.log")
exit $LASTEXITCODE
