Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo

$reportDir = Join-Path $env:USERPROFILE ".vibe-trading\reports"
$logDir = Join-Path $env:USERPROFILE ".vibe-trading\logs"
New-Item -ItemType Directory -Force -Path $reportDir, $logDir | Out-Null

$inputPath = Join-Path $logDir "option-quote-samples.jsonl"
$outputPath = Join-Path $reportDir "options-feed-qualification.json"
& python scripts\options_feed_qualification.py --input $inputPath --output $outputPath
if ($LASTEXITCODE -ne 0) { throw "options_feed_qualification exited $LASTEXITCODE" }
