Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ReportDir = Join-Path $env:USERPROFILE ".vibe-trading\reports"
$SessionDate = Get-Date -Format "yyyy-MM-dd"
$CompactDate = Get-Date -Format "yyyyMMdd"
$Output = Join-Path $RepoRoot "data\move_ground_truth_$CompactDate.json"
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
Set-Location -LiteralPath $RepoRoot
& python scripts\build_move_ground_truth.py --date $SessionDate --production-alpaca --feed iex --output $Output
$Code = $LASTEXITCODE
if (Test-Path -LiteralPath $Output) {
    Copy-Item -LiteralPath $Output -Destination (Join-Path $ReportDir "move-ground-truth-summary.json") -Force
}
if ($Code -notin @(0, 2)) { throw "build_move_ground_truth exited $Code" }
