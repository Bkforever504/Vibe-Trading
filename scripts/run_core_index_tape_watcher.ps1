param(
    [string]$PythonPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$logPath = "C:\Users\kenne\.vibe-trading\logs\core-index-tape-watcher.log"
Set-Location -LiteralPath $repo

if (Test-Path -LiteralPath (Join-Path $repo "KILL_SWITCH")) {
    Write-Warning "KILL_SWITCH present. Core-index tape watcher skipped."
    exit 0
}

. (Join-Path $repo "scripts\resolve_vibe_python.ps1")
$python = Get-VibePython -PythonPath $PythonPath
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $logPath) | Out-Null
$started = Get-Date -Format o
"$started START shadow_only=true" | Out-File -LiteralPath $logPath -Append -Encoding utf8
& $python scripts\core_index_tape_watcher.py --alert --print 2>&1 | Out-File -LiteralPath $logPath -Append -Encoding utf8
$code = $LASTEXITCODE
"$(Get-Date -Format o) END exit_code=$code" | Out-File -LiteralPath $logPath -Append -Encoding utf8
exit $code
