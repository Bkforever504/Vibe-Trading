param(
    [Parameter(Mandatory = $true)]
    [string]$PythonPath
)

$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location -LiteralPath $repo

$log = Join-Path $env:USERPROFILE ".vibe-trading\logs\daily-aplus-review.log"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null

try {
    if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
        throw "Configured Python executable is missing: $PythonPath"
    }
    $output = & $PythonPath scripts\daily_aplus_review.py --print 2>&1
    $exitCode = $LASTEXITCODE
    [System.IO.File]::AppendAllText(
        $log,
        (($output | Out-String) + [Environment]::NewLine),
        [System.Text.UTF8Encoding]::new($false)
    )
    if ($exitCode -ne 0) {
        throw "Daily A+ review exited with code $exitCode."
    }
}
catch {
    $_ | Out-String | Add-Content -LiteralPath $log
    throw
}
