$ErrorActionPreference = "Stop"

$Repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$LogDir = "C:\Users\kenne\.vibe-trading\logs"
$LogPath = Join-Path $LogDir "nightly-options-nbbo-evidence.latest.log"
$MaxCost = if ($env:OPTIONS_NBBO_NIGHTLY_MAX_COST) {
    [double]$env:OPTIONS_NBBO_NIGHTLY_MAX_COST
} else {
    0.05
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Push-Location $Repo
try {
    $Output = & "scripts\run_databento_options_nbbo_curriculum.ps1" `
        --incremental `
        --download `
        --max-cost $MaxCost 2>&1
    $ExitCode = $LASTEXITCODE
    $Output | Set-Content -LiteralPath $LogPath -Encoding utf8
    if ($ExitCode -ne 0) {
        Write-Error "Nightly options NBBO evidence failed with exit code $ExitCode. See $LogPath"
        exit $ExitCode
    }
    exit 0
}
finally {
    Pop-Location
}
