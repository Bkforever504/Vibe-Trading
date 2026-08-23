param(
    [string]$PythonPath = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$StateDir = Join-Path $env:USERPROFILE ".vibe-trading"
$LogDir = Join-Path $StateDir "logs"
$LogPath = Join-Path $LogDir "pattern-grader-pipeline.log"
$Python = if ($PythonPath) { $PythonPath } else { (Get-Command python -ErrorAction Stop).Source }

New-Item -ItemType Directory -Force $LogDir | Out-Null
Set-Location $RepoRoot

if (-not $Force -and (Get-Date).DayOfWeek -in @("Saturday", "Sunday")) {
    "$(Get-Date -Format o) weekend skip; execution_enabled=false can_submit_orders=false" |
        Add-Content -LiteralPath $LogPath -Encoding utf8
    exit 0
}

& $Python "scripts\pattern_grader_scanner.py" --print *>> $LogPath
$Code = $LASTEXITCODE
if ($Code -ne 0) {
    "$(Get-Date -Format o) pattern grader failed exit=$Code" | Add-Content -LiteralPath $LogPath -Encoding utf8
    exit $Code
}

"$(Get-Date -Format o) pattern grader completed; execution_enabled=false can_submit_orders=false" |
    Add-Content -LiteralPath $LogPath -Encoding utf8
exit 0
