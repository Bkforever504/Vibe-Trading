Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"

$logDir = Join-Path $HOME ".vibe-trading\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logPath = Join-Path $logDir "opportunity-intelligence-pipeline.log"

try {
    $command = @(
        "uv run --no-project"
        "--with pandas"
        "--with numpy"
        "--with pyarrow"
        "--with databento"
        "--with yfinance"
        "python scripts\opportunity_intelligence_pipeline.py"
        "2>&1"
    ) -join " "
    & cmd.exe /d /c $command |
        Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) {
        throw "Opportunity intelligence pipeline exited $LASTEXITCODE"
    }

    & python scripts\monthly_algo_evidence_packet.py 2>&1 |
        Tee-Object -FilePath $logPath -Append
    if ($LASTEXITCODE -ne 0) {
        throw "Monthly algo evidence packet exited $LASTEXITCODE"
    }
}
catch {
    "$(Get-Date -Format o) ERROR $($_.Exception.Message)" | Add-Content -LiteralPath $logPath
    throw
}
