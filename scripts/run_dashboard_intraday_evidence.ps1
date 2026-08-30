param(
    [string]$PythonPath = "",
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = if ($PythonPath) { $PythonPath } else { (Get-Command python -ErrorAction Stop).Source }
$LogDir = Join-Path $env:USERPROFILE ".vibe-trading\logs"
$LogPath = Join-Path $LogDir "dashboard-intraday-evidence.log"
$Failures = [System.Collections.Generic.List[string]]::new()

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location -LiteralPath $RepoRoot

if (-not $Force -and (Get-Date).DayOfWeek -in @("Saturday", "Sunday")) {
    "$(Get-Date -Format o) weekend skip; execution_enabled=false can_submit_orders=false" |
        Add-Content -LiteralPath $LogPath -Encoding utf8
    exit 0
}

function Invoke-ReadOnlyProducer {
    param([string]$Name, [string[]]$Arguments)
    & $Python @Arguments *>> $LogPath
    if ($LASTEXITCODE -ne 0) {
        $Failures.Add("$Name exit=$LASTEXITCODE")
    }
}

Invoke-ReadOnlyProducer "options-reference-refresh" @("scripts\options_reference_refresh.py")
Invoke-ReadOnlyProducer "options-feed" @("scripts\options_feed_qualification.py")
Invoke-ReadOnlyProducer "manual-quality" @("scripts\manual_execution_quality.py")
Invoke-ReadOnlyProducer "broker-fill" @("scripts\broker_fill_observer.py")
Invoke-ReadOnlyProducer "readiness" @("scripts\dashboard_readiness.py")

"$(Get-Date -Format o) completed failures=$($Failures.Count); execution_enabled=false can_submit_orders=false" |
    Add-Content -LiteralPath $LogPath -Encoding utf8
if ($Failures.Count -gt 0) {
    throw "Dashboard intraday evidence producers failed: $($Failures -join ', ')"
}
