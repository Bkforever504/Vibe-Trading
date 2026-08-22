Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
$env:ALPACA_PAPER = "true"
$env:FLIP_LIVE_EXECUTION_ENABLED = "false"
$env:FLIP_MAX_CONTRACTS = "1"
$env:FLIP_MAX_OPEN_POSITIONS = "1"
$env:FLIP_OPTION_STREAM_FEED = "opra"
$env:FLIP_REQUIRE_OPRA_EXECUTION_QUOTES = "true"
$env:FLIP_EXECUTABLE_EV_GATE_ENABLED = "true"
Set-Location $repo
python scripts\flip_event_monitor.py
exit $LASTEXITCODE
