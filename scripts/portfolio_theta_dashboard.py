"""Portfolio theta dashboard — aggregate daily theta across all shadow positions.

Reads all open shadow state files and computes:
  - Total daily theta (dollars/day)
  - As % of account (target: 0.06-0.10%)
  - Per-position breakdown
  - Status: under/on_target/over

Run manually or schedule daily at market open.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ACCOUNT_SIZE = float(os.getenv("PAPER_ACCOUNT_SIZE", "10000.0"))
THETA_TARGET_LOW = float(os.getenv("THETA_TARGET_LOW_PCT", "0.0006"))   # 0.06%
THETA_TARGET_HIGH = float(os.getenv("THETA_TARGET_HIGH_PCT", "0.0010"))  # 0.10%

# Map state file → how to extract theta estimate
STATE_CONFIGS = [
    {
        "name": "theta_harvester",
        "path": ROOT / "data" / "theta_harvester_state.json",
        "type": "put_spread",
        "active_phases": ["open_shadow"],
    },
    {
        "name": "0dte_pm_spread",
        "path": ROOT / "data" / "spy_0dte_pm_state.json",
        "type": "put_spread_0dte",
        "active_phases": ["open_shadow"],
    },
    {
        "name": "iron_condor",
        "path": ROOT / "data" / "spy_iron_condor_state.json",
        "type": "iron_condor",
        "active_phases": ["open_shadow"],
    },
    {
        "name": "fomc_iv_crush",
        "path": ROOT / "data" / "spy_fomc_iv_crush_state.json",
        "type": "put_spread",
        "active_phases": ["open_shadow"],
    },
    {
        "name": "wheel_spy",
        "path": ROOT / "data" / "spy_wheel_state.json",
        "type": "wheel",
        "active_phases": ["csp_open", "cc_open"],
    },
]


def _credit_decay_proxy(credit: float, dte: int) -> float:
    """Rough daily theta estimate: credit × sqrt(2/pi) / sqrt(DTE)."""
    if dte <= 0:
        return round(max(0.0, credit) * 100, 2)
    return round(max(0.0, credit) * 100 / dte, 2)


def _position_theta(config: dict, state: dict, *, account_size: float) -> dict[str, Any]:
    name = config["name"]
    active = state.get("status") in config["active_phases"] or state.get("phase") in config["active_phases"]
    if not active:
        return {"name": name, "active": False, "daily_theta": 0.0}

    pos_type = config["type"]
    dte = state.get("dte") or state.get("days_to_fomc") or 1

    if pos_type == "put_spread":
        credit = state.get("entry_credit", 0)
        theta = _credit_decay_proxy(float(credit), int(dte))
        return {"name": name, "active": True, "type": pos_type,
                "credit": credit, "dte": dte, "daily_theta": theta}

    elif pos_type == "put_spread_0dte":
        credit = state.get("entry_credit", 0)
        return {"name": name, "active": True, "type": pos_type,
                "credit": credit, "dte": 0, "daily_theta": round(float(credit) * 100, 2)}

    elif pos_type == "iron_condor":
        credit = state.get("total_credit", 0)
        theta = _credit_decay_proxy(float(credit), int(dte))
        return {"name": name, "active": True, "type": pos_type,
                "credit": credit, "dte": dte, "daily_theta": theta}

    elif pos_type == "wheel":
        credit = state.get("leg_entry_credit") or 0
        strike = float(state.get("leg_strike") or 0.0)
        cash_requirement = strike * 100.0 if state.get("phase") == "csp_open" else 0.0
        if cash_requirement > account_size:
            return {
                "name": name,
                "active": False,
                "daily_theta": 0.0,
                "phase": state.get("phase"),
                "note": "excluded_insufficient_cash_secured_collateral",
                "cash_requirement": round(cash_requirement, 2),
                "account_size": account_size,
            }
        leg_expiry = state.get("leg_expiry")
        if leg_expiry:
            dte = max((date.fromisoformat(leg_expiry) - date.today()).days, 1)
        theta = _credit_decay_proxy(float(credit), int(dte))
        return {"name": name, "active": True, "type": pos_type,
                "credit": credit, "dte": dte, "daily_theta": theta,
                "phase": state.get("phase")}

    return {"name": name, "active": False, "daily_theta": 0.0}


def run_dashboard(*, account_size: float = ACCOUNT_SIZE) -> dict[str, Any]:
    positions = []
    for config in STATE_CONFIGS:
        if not config["path"].exists():
            positions.append({"name": config["name"], "active": False, "daily_theta": 0.0,
                               "note": "no_state_file"})
            continue
        try:
            state = json.loads(config["path"].read_text())
            pos = _position_theta(config, state, account_size=account_size)
            positions.append(pos)
        except Exception as exc:
            positions.append({"name": config["name"], "active": False, "daily_theta": 0.0,
                               "error": str(exc)})

    total_theta = sum(p["daily_theta"] for p in positions)
    theta_pct = total_theta / account_size if account_size > 0 else 0.0
    target_low_dollars = account_size * THETA_TARGET_LOW
    target_high_dollars = account_size * THETA_TARGET_HIGH

    if theta_pct < THETA_TARGET_LOW:
        theta_status = "under_target"
        recommendation = "Below the diagnostic range. Do not add risk from this proxy alone."
    elif theta_pct > THETA_TARGET_HIGH:
        theta_status = "over_target"
        recommendation = "Above the diagnostic range. Review collateral and portfolio Greeks before adding risk."
    else:
        theta_status = "on_target"
        recommendation = f"On target. ${total_theta:.2f}/day theta ({theta_pct:.3%} of account)."

    active_count = sum(1 for p in positions if p.get("active"))
    return {
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "account_size": account_size,
        "total_daily_theta": round(total_theta, 2),
        "metric_name": "linear_credit_decay_proxy",
        "metric_quality": "diagnostic_only_not_option_theta_or_expected_profit",
        "theta_pct_of_account": round(theta_pct, 6),
        "target_range_pct": f"{THETA_TARGET_LOW:.3%}-{THETA_TARGET_HIGH:.3%}",
        "target_range_dollars": f"${target_low_dollars:.0f}-${target_high_dollars:.0f}/day",
        "theta_status": theta_status,
        "recommendation": recommendation,
        "active_positions": active_count,
        "positions": positions,
        "execution_enabled": False,
        "can_submit_orders": False,
        "orders_submitted": 0,
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Portfolio theta dashboard")
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "portfolio_theta_dashboard.json")
    parser.add_argument("--account", type=float, default=ACCOUNT_SIZE)
    args = parser.parse_args()

    result = run_dashboard(account_size=args.account)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"\n{'='*50}")
    print(f"PORTFOLIO THETA DASHBOARD  {date.today()}")
    print(f"{'='*50}")
    print(f"Account:      ${result['account_size']:,.0f}")
    print(f"Daily theta:  ${result['total_daily_theta']:.2f}/day ({result['theta_pct_of_account']:.3%})")
    print(f"Target:       {result['target_range_dollars']}")
    print(f"Status:       {result['theta_status'].upper()}")
    print(f"Positions:    {result['active_positions']} active")
    print()
    for p in result["positions"]:
        if p.get("active"):
            print(f"  {p['name']:25s} ${p['daily_theta']:6.2f}/day  dte={p.get('dte','?')}")
    print()
    print(f">> {result['recommendation']}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
