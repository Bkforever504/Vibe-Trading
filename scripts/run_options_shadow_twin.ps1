$ErrorActionPreference = "Stop"

$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$LogDir = "C:\Users\kenne\.vibe-trading\logs"
$LogPath = Join-Path $LogDir "options-shadow-twin.log"
$Python = (Get-Command python -ErrorAction Stop).Source
$env:ALPACA_OPTIONS_FEED = "indicative"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Push-Location $Repo
try {
    $failedSteps = @()
    & $Python "scripts/options_shadow_twin.py" 2>&1 |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        $failedSteps += "options_shadow_twin"
    }
    & $Python "scripts/options_vol_premium_report.py" 2>&1 |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        $failedSteps += "options_vol_premium_report"
    }
    & $Python "scripts/options_evidence_factory.py" 2>&1 |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        $failedSteps += "options_evidence_factory"
    }
    & $Python "scripts/options_edge_attribution_report.py" 2>&1 |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        $failedSteps += "options_edge_attribution_report"
    }
    & $Python "scripts/options_observation_journal.py" 2>&1 |
        Out-File -FilePath $LogPath -Append -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        $failedSteps += "options_observation_journal"
    }
    if ($failedSteps.Count -gt 0) {
        Write-Error "Options shadow reporting failed: $($failedSteps -join ', ')"
        exit 1
    }
    exit 0
}
finally {
    Pop-Location
}
