#!/usr/bin/env python3
"""Audit that read-only/shadow signals have not gained execution wiring.

This is governance, not trading. It scans registered scripts for dangerous
patterns and fails if a non-order-capable component appears able to submit
orders or enable live execution.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "research" / "signal_registry.json"
REPORT_PATH = Path.home() / ".vibe-trading" / "reports" / "execution-gate-audit.json"
LOG_PATH = ROOT / "data" / "execution_gate_audit_log.jsonl"

ORDER_PATTERNS = [
    (re.compile(r"/v2/orders"), "alpaca_orders_endpoint"),
    (re.compile(r"\bsubmit_order\b"), "submit_order_call"),
    (re.compile(r"\bplace_order\b"), "place_order_call"),
    (re.compile(r"\bcreate_order\b"), "create_order_call"),
    (re.compile(r"\bOrderRequest\b"), "order_request"),
    (re.compile(r"\b_post_order_with_retry\b"), "alpaca_post_order_helper"),
    (re.compile(r"\b_submit_spread\b"), "spread_submit_helper"),
    (re.compile(r"\b_submit\("), "submit_helper"),
]

LIVE_PATTERNS = [
    (re.compile(r"execution_enabled[\"']?\s*[:=]\s*True"), "execution_enabled_true_python"),
    (re.compile(r"execution_enabled[\"']?\s*:\s*true", re.IGNORECASE), "execution_enabled_true_json"),
    (re.compile(r"LIVE_EXECUTION_ENABLED\s*=\s*True"), "live_execution_enabled_true"),
    (re.compile(r"^\s*(?:export\s+)?KALSHI_LIVE_EXECUTION_ENABLED\s*=\s*true\s*$", re.IGNORECASE | re.MULTILINE), "kalshi_live_enabled_true_literal"),
]

READ_ONLY_BROKER_PATTERNS = [
    (re.compile(r"\bTradingClient\b"), "alpaca_trading_client_import_or_use"),
    (re.compile(r"\bget_all_positions\b"), "alpaca_positions_read"),
    (re.compile(r"\bget_account\b"), "alpaca_account_read"),
]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload.get("signals"), list):
        raise ValueError("signal_registry.json must contain a signals list")
    return payload


def _scan_text(text: str, patterns: list[tuple[re.Pattern[str], str]]) -> list[str]:
    return [label for pattern, label in patterns if pattern.search(text)]


def _path_for(script: str) -> Path:
    path = Path(script)
    return path if path.is_absolute() else ROOT / path


def audit_registry(registry: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    known_order_capable = set(registry.get("policy", {}).get("known_order_capable_scripts", []))
    known_read_only_order_history = set(registry.get("policy", {}).get("known_read_only_order_history_scripts", []))
    registered_scripts = {signal.get("script") for signal in registry["signals"] if signal.get("script")}

    for signal in registry["signals"]:
        script = str(signal.get("script") or "")
        if not script:
            issues.append({"id": signal.get("id"), "severity": "error", "issue": "missing_script"})
            continue
        path = _path_for(script)
        if not path.exists():
            warnings.append({"id": signal.get("id"), "script": script, "severity": "warning", "issue": "script_missing"})
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        order_hits = _scan_text(text, ORDER_PATTERNS)
        live_hits = _scan_text(text, LIVE_PATTERNS)
        broker_read_hits = _scan_text(text, READ_ONLY_BROKER_PATTERNS)
        can_submit = bool(signal.get("can_submit_orders"))
        can_read_order_history = bool(signal.get("can_read_order_history")) or script in known_read_only_order_history
        execution_enabled = bool(signal.get("execution_enabled"))

        order_hits_are_read_history_only = order_hits == ["alpaca_orders_endpoint"] and can_read_order_history
        if order_hits and not can_submit and not order_hits_are_read_history_only and script != "scripts/execution_gate_audit.py":
            issues.append({
                "id": signal.get("id"),
                "script": script,
                "severity": "error",
                "issue": "order_patterns_in_non_execution_signal",
                "patterns": order_hits,
            })
        if live_hits and not can_submit:
            issues.append({
                "id": signal.get("id"),
                "script": script,
                "severity": "error",
                "issue": "live_execution_literal_in_non_execution_signal",
                "patterns": live_hits,
            })
        if execution_enabled and not can_submit:
            issues.append({
                "id": signal.get("id"),
                "script": script,
                "severity": "error",
                "issue": "registry_execution_enabled_but_cannot_submit",
            })
        if can_submit and script not in known_order_capable:
            issues.append({
                "id": signal.get("id"),
                "script": script,
                "severity": "error",
                "issue": "order_capable_script_not_in_policy_allowlist",
            })
        if broker_read_hits and not can_submit:
            warnings.append({
                "id": signal.get("id"),
                "script": script,
                "severity": "warning",
                "issue": "broker_client_present_verify_read_only",
                "patterns": broker_read_hits,
            })

    for folder in ("scripts", "strategies"):
        for path in (root / folder).glob("*.py"):
            rel = path.relative_to(root).as_posix()
            if rel in registered_scripts:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            order_hits = _scan_text(text, ORDER_PATTERNS)
            if (
                order_hits
                and rel not in known_order_capable
                and rel not in known_read_only_order_history
                and rel not in {"strategies/execution_guard.py", "scripts/execution_gate_audit.py"}
            ):
                issues.append({
                    "id": "unregistered",
                    "script": rel,
                    "severity": "error",
                    "issue": "unregistered_script_contains_order_patterns",
                    "patterns": order_hits,
                })

    return {
        "date": datetime.now(timezone.utc).date().isoformat(),
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provider": "execution_gate_audit",
        "mode": "read_only",
        "execution_enabled": False,
        "registered_signal_count": len(registry["signals"]),
        "issue_count": len(issues),
        "warning_count": len(warnings),
        "passed": not issues,
        "issues": issues,
        "warnings": warnings,
    }


def append_log(report: dict[str, Any], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, separators=(",", ":"), default=str) + "\n")


def write_report(report: dict[str, Any], path: Path = REPORT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def print_report(report: dict[str, Any]) -> None:
    print("\nExecution Gate Audit | read-only")
    print("=" * 72)
    print(
        f"passed={report['passed']} signals={report['registered_signal_count']} "
        f"issues={report['issue_count']} warnings={report['warning_count']}"
    )
    for issue in report["issues"][:12]:
        print(f"ERROR {issue.get('script')}: {issue.get('issue')} {issue.get('patterns', '')}")
    for warning in report["warnings"][:8]:
        print(f"WARN  {warning.get('script')}: {warning.get('issue')} {warning.get('patterns', '')}")
    print(f"JSON: {REPORT_PATH}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--log-path", type=Path, default=LOG_PATH)
    parser.add_argument("--report-path", type=Path, default=REPORT_PATH)
    parser.add_argument("--print", action="store_true", dest="print_output")
    parser.add_argument("--fail-on-issues", action="store_true")
    args = parser.parse_args()
    report = audit_registry(load_registry(args.registry))
    append_log(report, args.log_path)
    write_report(report, args.report_path)
    if args.print_output:
        print_report(report)
    if args.fail_on_issues and not report["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
