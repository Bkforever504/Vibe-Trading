param(
    [string]$PythonPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$logPath = "C:\Users\kenne\.vibe-trading\logs\discord-alert-chart-review.log"
Set-Location -LiteralPath $repo

. (Join-Path $repo "scripts\resolve_vibe_python.ps1")
$python = Get-VibePython -PythonPath $PythonPath
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $logPath) | Out-Null
"$(Get-Date -Format o) START read_only=true" | Out-File -LiteralPath $logPath -Append -Encoding utf8
& $python scripts\discord_alert_chart_review.py --print 2>&1 | Out-File -LiteralPath $logPath -Append -Encoding utf8
$reviewCode = $LASTEXITCODE
if ($reviewCode -eq 0) {
    & $python scripts\latency_budget_scorecard.py 2>&1 | Out-File -LiteralPath $logPath -Append -Encoding utf8
    $latencyCode = $LASTEXITCODE
    # Delayed SIP reference research is separate from live IEX observations.
    # Intraday runs defer; unchanged completed-session inputs do not refetch.
    & $python research\scanner_feed_reference_study.py --if-needed 2>&1 | Out-File -LiteralPath $logPath -Append -Encoding utf8
    $referenceCode = $LASTEXITCODE
    & $python scripts\scanner_evidence_snapshot.py 2>&1 | Out-File -LiteralPath $logPath -Append -Encoding utf8
    $evidenceCode = $LASTEXITCODE
    & $python scripts\generate_dashboard.py 2>&1 | Out-File -LiteralPath $logPath -Append -Encoding utf8
    $dashboardCode = $LASTEXITCODE
    if ($latencyCode -ne 0) { $dashboardCode = $latencyCode }
    if ($evidenceCode -ne 0) { $dashboardCode = $evidenceCode }
    if ($referenceCode -ne 0) { $dashboardCode = $referenceCode }
} else {
    $dashboardCode = 0
}
$code = if ($reviewCode -ne 0) { $reviewCode } else { $dashboardCode }
"$(Get-Date -Format o) END exit_code=$code" | Out-File -LiteralPath $logPath -Append -Encoding utf8
exit $code
