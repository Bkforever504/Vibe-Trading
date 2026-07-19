$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir
$logDir = Join-Path $HOME ".vibe-trading\logs"
$logPath = Join-Path $logDir "liquid-options-edge-shadow.log"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Set-Location $projectRoot
uv run --no-project --python 3.12 --with alpaca-py --with pandas --with numpy --with pyarrow python scripts/liquid_options_edge_shadow.py *>> $logPath
