param([string]$PythonPath = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$WorkingDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = if ($PythonPath) { $PythonPath } else { (Get-Command python -ErrorAction Stop).Source }
$LogDir = Join-Path $HOME ".vibe-trading\logs"
$LogPath = Join-Path $LogDir "strategy-discovery-coverage.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $WorkingDir

& $Python "scripts\strategy_concept_coverage_audit.py" --print *>> $LogPath
if ($LASTEXITCODE -ne 0) { throw "concept coverage audit exited $LASTEXITCODE" }
& $Python "research\uncovered_concept_tournament.py" --print *>> $LogPath
if ($LASTEXITCODE -ne 0) { throw "uncovered concept tournament exited $LASTEXITCODE" }
& $Python "scripts\generate_dashboard.py" *>> $LogPath
if ($LASTEXITCODE -ne 0) { throw "dashboard refresh exited $LASTEXITCODE" }

