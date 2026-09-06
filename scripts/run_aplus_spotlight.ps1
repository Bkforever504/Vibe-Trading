param(
    [string]$PythonPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$WorkingDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = if ($PythonPath) { $PythonPath } else { (Get-Command python -ErrorAction Stop).Source }
$LogDir = Join-Path $HOME ".vibe-trading\logs"
$LogPath = Join-Path $LogDir "aplus-spotlight.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $WorkingDir

try {
    # Refresh exact-contract feasibility first; empty inputs fail closed and still emit a report.
    & $Python "scripts\aplus_contract_feasibility.py" --print *>> $LogPath
    if ($LASTEXITCODE -ne 0) { throw "contract feasibility exited $LASTEXITCODE" }
    & $Python "scripts\aplus_spotlight.py" --tier all --print *>> $LogPath
    if ($LASTEXITCODE -ne 0) { throw "A+ spotlight exited $LASTEXITCODE" }
    & $Python "scripts\generate_dashboard.py" *>> $LogPath
    if ($LASTEXITCODE -ne 0) { throw "dashboard refresh exited $LASTEXITCODE" }
} catch {
    "$(Get-Date -Format o) ERROR $($_.Exception.Message)" | Add-Content -LiteralPath $LogPath
    throw
}
