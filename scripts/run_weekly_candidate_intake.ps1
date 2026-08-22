Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"

$logDir = Join-Path $HOME ".vibe-trading\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "weekly-candidate-intake.log"

try {
    & python scripts\weekly_candidate_intake.py 2>&1 |
        Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) {
        throw "Weekly candidate intake exited $LASTEXITCODE"
    }
}
catch {
    "$(Get-Date -Format o) ERROR $($_.Exception.Message)" | Add-Content -LiteralPath $logPath
    throw
}
