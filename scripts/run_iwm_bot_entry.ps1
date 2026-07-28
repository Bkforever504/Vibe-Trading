Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
$env:ENABLE_SHADOW_CONSENSUS_GATE = "true"
$env:OPTIONS_STRICT_SHADOW_CAUTION_GATE = "true"
Set-Location $repo
& "$repo\scripts\run_options_context_stack.ps1"
python strategies\iwm_options_bot.py --strategy both
