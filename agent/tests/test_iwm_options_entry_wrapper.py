from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_context_stack_fails_when_any_required_refresh_fails() -> None:
    script = (ROOT / "scripts" / "run_options_context_stack.ps1").read_text(encoding="utf-8")

    assert "$failedSteps = @()" in script
    assert '$failedSteps += "garch_volatility_risk"' in script
    assert '$failedSteps += "options_liquidation_heatmap"' in script
    assert '$failedSteps += "adaptive_options_shadow_playbook"' in script
    assert '$failedSteps += "options_quant_risk_budget"' in script
    assert "if ($failedSteps.Count -gt 0)" in script
    assert "exit 1" in script


def test_entry_wrapper_aborts_before_bot_when_context_refresh_fails() -> None:
    script = (ROOT / "scripts" / "run_iwm_bot_entry.ps1").read_text(encoding="utf-8")
    context_call = '& "$repo\\scripts\\run_options_context_stack.ps1"'
    failure_guard = "if ($LASTEXITCODE -ne 0)"
    bot_call = "python strategies\\iwm_options_bot.py --strategy both"

    assert '$env:OPTIONS_REQUIRE_GARCH_REPORT = "true"' in script
    assert '$env:OPTIONS_REQUIRE_QUANT_RISK_REPORT = "true"' in script
    assert script.index(context_call) < script.index(failure_guard) < script.index(bot_call)
