$ErrorActionPreference = "Stop"

$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$venv = Join-Path $env:USERPROFILE ".agent-reach-venv\Scripts"
$python = Join-Path $venv "python.exe"
$ytDlp = Join-Path $venv "yt-dlp.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Agent-Reach isolated environment is missing: $python"
}

$env:Path = "$venv;$env:Path"
Set-Location $repo
& $python scripts\agent_reach_trading_research.py --yt-dlp $ytDlp --print
exit $LASTEXITCODE
