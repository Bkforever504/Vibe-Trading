#!/usr/bin/env python3
"""Estimate or fetch one credit-capped MES market-by-order discovery session."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = "GLBX.MDP3"
SCHEMA = "mbo"
SYMBOL = "MES.v.0"
DEFAULT_SESSION = "2026-07-15"
DEFAULT_MAX_COST_USD = 5.0
DEFAULT_MIN_CREDIT_BUFFER_USD = 15.0


def load_key() -> str:
    key = os.getenv("DATABENTO_API_KEY", "").strip()
    if key:
        return key
    env_path = ROOT / "agent" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("DATABENTO_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("DATABENTO_API_KEY is not configured")


def request_kwargs(session: str) -> dict[str, str]:
    session_date = date.fromisoformat(session)
    if session_date.weekday() >= 5:
        raise ValueError("session must be a weekday")
    start = datetime.combine(session_date, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return {
        "dataset": DATASET,
        "schema": SCHEMA,
        "symbols": SYMBOL,
        "stype_in": "continuous",
        "start": start.isoformat().replace("+00:00", "Z"),
        "end": end.isoformat().replace("+00:00", "Z"),
    }


def credit_guard(
    estimate_usd: float,
    verified_credits_usd: float,
    *,
    max_cost_usd: float = DEFAULT_MAX_COST_USD,
    minimum_buffer_usd: float = DEFAULT_MIN_CREDIT_BUFFER_USD,
) -> dict[str, float]:
    if estimate_usd < 0:
        raise ValueError("estimate_usd cannot be negative")
    if estimate_usd > max_cost_usd:
        raise RuntimeError(
            f"Estimated cost ${estimate_usd:.2f} exceeds hard cap ${max_cost_usd:.2f}"
        )
    remaining = verified_credits_usd - estimate_usd
    if remaining < minimum_buffer_usd:
        raise RuntimeError(
            f"Verified credits ${verified_credits_usd:.2f} do not cover estimate "
            f"${estimate_usd:.2f} plus ${minimum_buffer_usd:.2f} safety buffer"
        )
    return {
        "estimated_cost_usd": round(estimate_usd, 4),
        "verified_credits_usd": round(verified_credits_usd, 2),
        "estimated_remaining_credits_usd": round(remaining, 2),
        "minimum_credit_buffer_usd": round(minimum_buffer_usd, 2),
    }


def cache_path(session: str) -> Path:
    return ROOT / "data" / "databento" / f"mes_v0_mbo_{session}.dbn.zst"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default=DEFAULT_SESSION)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--credit-only", action="store_true")
    parser.add_argument("--verified-credits", type=float)
    parser.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST_USD)
    parser.add_argument(
        "--minimum-credit-buffer",
        type=float,
        default=DEFAULT_MIN_CREDIT_BUFFER_USD,
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
    )
    args = parser.parse_args()

    import databento as db

    request = request_kwargs(args.session)
    output = cache_path(args.session)
    client = db.Historical(load_key())
    estimate = float(client.metadata.get_cost(**request))
    preview = {
        "mode": "estimate",
        **request,
        "estimated_cost_usd": round(estimate, 4),
        "cache": str(output),
        "cache_exists": output.exists(),
        "execution_enabled": False,
        "can_submit_orders": False,
    }
    print(json.dumps(preview, indent=2))
    if not args.download:
        print("Estimate only. Download requires --credit-only and --verified-credits.")
        return 0
    if not args.credit_only:
        raise RuntimeError("Download refused: --credit-only acknowledgement is required")
    if args.verified_credits is None:
        raise RuntimeError("Download refused: --verified-credits is required")

    guard = credit_guard(
        estimate,
        args.verified_credits,
        max_cost_usd=args.max_cost,
        minimum_buffer_usd=args.minimum_credit_buffer,
    )
    if not output.exists() or output.stat().st_size == 0:
        output.parent.mkdir(parents=True, exist_ok=True)
        partial = output.with_suffix(output.suffix + ".partial")
        partial.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        client.timeseries.get_range(**request, path=partial)
        if not partial.exists() or partial.stat().st_size == 0:
            raise RuntimeError("Databento download returned an empty cache")
        partial.replace(output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest().upper()
    manifest = {
        **preview,
        "mode": "credit_only_download",
        "cache_exists": True,
        **guard,
        "bytes": output.stat().st_size,
        "sha256": digest,
        "card_charge_authorized": False,
        "research_only": True,
        "protocol": "MES_MBO_DISCOVERY_PREREGISTRATION_2026-08-12",
    }
    manifest_path = args.manifest or ROOT / "data" / f"databento_mbo_manifest_{args.session}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
