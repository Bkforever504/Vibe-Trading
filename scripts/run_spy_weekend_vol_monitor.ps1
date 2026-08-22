Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$logDir = "C:\Users\kenne\.vibe-trading\logs"
$logPath = Join-Path $logDir "spy-weekend-vol-monitor.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Push-Location $repo
try {
    python strategies\spy_weekend_vol.py --check `
        --state "$repo\data\spy_weekend_vol_state.json" `
        --ledger "$repo\data\spy_weekend_vol_ledger.jsonl" `
        --out "$repo\data\spy_weekend_vol_decision.json" 2>&1 |
        Out-File -FilePath $logPath -Append -Encoding utf8
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
