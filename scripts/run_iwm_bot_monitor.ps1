Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
$env:ENABLE_SHADOW_CONSENSUS_GATE = "true"
$env:OPTIONS_STRICT_SHADOW_CAUTION_GATE = "true"
Set-Location $repo
python strategies\iwm_options_bot.py --monitor-only
