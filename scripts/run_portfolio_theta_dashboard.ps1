Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$logDir = "C:\Users\kenne\.vibe-trading\logs"
$logPath = Join-Path $logDir "portfolio-theta-dashboard.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Push-Location $repo
try {
    python scripts\portfolio_theta_dashboard.py 2>&1 |
        Out-File -FilePath $logPath -Append -Encoding utf8
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
