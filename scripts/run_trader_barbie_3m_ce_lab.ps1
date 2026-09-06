param([string]$PythonPath = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$WorkingDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = if ($PythonPath) { $PythonPath } else { (Get-Command python -ErrorAction Stop).Source }
$LogDir = Join-Path $HOME ".vibe-trading\logs"
$LogPath = Join-Path $LogDir "trader-barbie-3m-ce-lab.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $WorkingDir

& $Python "research\trader_barbie_3m_ce_lab.py" --print *>> $LogPath
if ($LASTEXITCODE -ne 0) { throw "Trader Barbie 3m CE lab exited $LASTEXITCODE" }
& $Python "scripts\generate_dashboard.py" *>> $LogPath
if ($LASTEXITCODE -ne 0) { throw "dashboard refresh exited $LASTEXITCODE" }

