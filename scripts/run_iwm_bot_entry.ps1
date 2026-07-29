Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = "C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading"
$env:PYTHONPATH = $repo
$env:ALPACA_PAPER = "true"
$env:ENABLE_SHADOW_CONSENSUS_GATE = "true"
$env:OPTIONS_STRICT_SHADOW_CAUTION_GATE = "true"
$env:OPTIONS_REQUIRE_GARCH_REPORT = "true"
$env:OPTIONS_REQUIRE_QUANT_RISK_REPORT = "true"
Set-Location $repo
& "$repo\scripts\run_options_context_stack.ps1"
if ($LASTEXITCODE -ne 0) {
    Write-Warning "IWM options entry aborted because required context did not refresh cleanly."
    exit $LASTEXITCODE
}
python strategies\iwm_options_bot.py --strategy both
exit $LASTEXITCODE
