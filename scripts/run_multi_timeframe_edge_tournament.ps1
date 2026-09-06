param([string]$PythonPath = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$WorkingDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = if ($PythonPath) { $PythonPath } else { (Get-Command python -ErrorAction Stop).Source }
$LogDir = Join-Path $HOME ".vibe-trading\logs"
$LogPath = Join-Path $LogDir "multi-timeframe-edge-tournament.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $WorkingDir

& $Python "research\multi_timeframe_edge_tournament.py" --print *>> $LogPath
if ($LASTEXITCODE -ne 0) { throw "multi-timeframe tournament exited $LASTEXITCODE" }
& $Python "scripts\generate_dashboard.py" *>> $LogPath
if ($LASTEXITCODE -ne 0) { throw "dashboard refresh exited $LASTEXITCODE" }

