from pathlib import Path


def test_pattern_grader_registration_exposes_explicit_start_when_available_opt_in():
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "register_pattern_grader_tasks.ps1").read_text(encoding="utf-8")
    assert "[switch]$StartWhenAvailable" in script
    assert "if ($StartWhenAvailable)" in script
    assert "$Task.Settings.StartWhenAvailable = $true" in script


def test_pattern_grader_runner_preserves_weekend_fail_closed_guard():
    root = Path(__file__).resolve().parents[2]
    script = (root / "scripts" / "run_pattern_grader_pipeline.ps1").read_text(encoding="utf-8")
    assert 'DayOfWeek -in @("Saturday", "Sunday")' in script
    assert "execution_enabled=false can_submit_orders=false" in script
