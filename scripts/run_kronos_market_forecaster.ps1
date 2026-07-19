$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

Set-Location $projectRoot
$kronosRoot = Join-Path $projectRoot "research\external_repos\Kronos"
$kronosPython = Join-Path $HOME ".vibe-trading\kronos-venv\Scripts\python.exe"
$python = if (Test-Path -LiteralPath $kronosPython) { $kronosPython } else { "python" }

& $python scripts/kronos_market_forecaster.py --kronos-repo-path $kronosRoot
