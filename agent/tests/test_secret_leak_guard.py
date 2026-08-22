from pathlib import Path

from scripts.secret_leak_guard import scan_paths


def test_secret_guard_reports_location_without_echoing_value(tmp_path: Path) -> None:
    path = tmp_path / "config.txt"
    secret = "super" + "secret" + "value" + "123456789"
    path.write_text(f"api_key={secret}\n", encoding="utf-8")
    findings = scan_paths([path])
    assert len(findings) == 1
    assert secret not in findings[0]
    assert "suspected_secret" in findings[0]


def test_secret_guard_allows_explicit_placeholders(tmp_path: Path) -> None:
    path = tmp_path / "config.example.txt"
    path.write_text("api_key=replace_with_placeholder_value\n", encoding="utf-8")
    assert scan_paths([path]) == []
