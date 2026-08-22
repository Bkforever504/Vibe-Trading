#!/usr/bin/env python3
"""Static and runtime order-authority invariant for dashboard surfaces."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SURFACES = (
    ROOT / "scripts" / "live_trading_cockpit.py",
    ROOT / "agent" / "api_server.py",
    ROOT / "agent" / "remote_dashboard_gateway.py",
)
TRUE_PATTERN = re.compile(r"(?:execution_enabled|can_submit_orders)[\"']?\s*[:=]\s*(?:True|true)\b")


def runtime_violations(value: Any, path: str = "$") -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {"execution_enabled", "can_submit_orders"} and child is not False:
                violations.append(child_path)
            violations.extend(runtime_violations(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(runtime_violations(child, f"{path}[{index}]"))
    return violations


def static_violations(paths: tuple[Path, ...] = SURFACES) -> list[str]:
    violations: list[str] = []
    for path in paths:
        try:
            content = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        for line_number, line in enumerate(content.splitlines(), 1):
            if TRUE_PATTERN.search(line):
                violations.append(f"{path}:{line_number}")
    return violations


def main() -> int:
    violations = static_violations()
    for violation in violations:
        print(f"order_authority_violation:{violation}")
    print(f"order_authority_guard violations={len(violations)}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
