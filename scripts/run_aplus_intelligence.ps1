param([string]$PythonPath = "")

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$WorkingDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = if ($PythonPath) { $PythonPath } else { (Get-Command python -ErrorAction Stop).Source }
$LogDir = Join-Path $HOME ".vibe-trading\logs"
$LogPath = Join-Path $LogDir "aplus-intelligence.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $WorkingDir

function Invoke-FailOpen([string[]]$Arguments) {
    & $Python @Arguments *>> $LogPath
    if ($LASTEXITCODE -ne 0) { "$(Get-Date -Format o) WARN $($Arguments -join ' ') exit=$LASTEXITCODE (fail-closed artifact retained)" | Add-Content -LiteralPath $LogPath }
}

# Each producer is shadow-only and fail-closed. Missing entitlements/inputs
# must produce an unavailable artifact, never a guessed executable setup.
Invoke-FailOpen @("scripts\aplus_contract_feasibility.py")
Invoke-FailOpen @("scripts\economic_ranking_regret.py")
Invoke-FailOpen @("scripts\footprint_evidence_shadow.py")
& $Python "scripts\aplus_spotlight.py" --tier all --print *>> $LogPath
if ($LASTEXITCODE -ne 0) { throw "A+ spotlight exited $LASTEXITCODE" }
& $Python "scripts\generate_dashboard.py" *>> $LogPath
if ($LASTEXITCODE -ne 0) { throw "dashboard refresh exited $LASTEXITCODE" }
