#!/usr/bin/env python3
"""Estimate or fetch the credit-only MES trade-print discovery slice."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = "GLBX.MDP3"
SCHEMA = "trades"
SYMBOL = "MES.v.0"
START = "2025-10-01"
END = "2026-01-01"
MAX_COST_USD = 30.0
MIN_CREDIT_BUFFER_USD = 10.0
CACHE = ROOT / "data" / "databento" / "mes_v0_trades_2025-10-01_2026-01-01.dbn.zst"
MANIFEST = ROOT / "data" / "databento_trades_manifest.json"


def load_key() -> str:
    env_path = ROOT / "agent" / ".env"
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("DATABENTO_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("DATABENTO_API_KEY is not configured")


def request_kwargs() -> dict[str, str]:
    return {
        "dataset": DATASET,
        "schema": SCHEMA,
        "symbols": SYMBOL,
        "stype_in": "continuous",
        "start": START,
        "end": END,
    }


def credit_guard(
    estimate_usd: float,
    verified_credits_usd: float,
    *,
    max_cost_usd: float = MAX_COST_USD,
    minimum_buffer_usd: float = MIN_CREDIT_BUFFER_USD,
) -> dict[str, float]:
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
        "estimated_cost_usd": round(estimate_usd, 2),
        "verified_credits_usd": round(verified_credits_usd, 2),
        "estimated_remaining_credits_usd": round(remaining, 2),
        "minimum_credit_buffer_usd": round(minimum_buffer_usd, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--credit-only", action="store_true")
    parser.add_argument("--verified-credits", type=float)
    parser.add_argument("--max-cost", type=float, default=MAX_COST_USD)
    parser.add_argument("--minimum-credit-buffer", type=float, default=MIN_CREDIT_BUFFER_USD)
    args = parser.parse_args()

    import databento as db

    client = db.Historical(load_key())
    request = request_kwargs()
    estimate = float(client.metadata.get_cost(**request))
    preview = {
        "mode": "estimate",
        **request,
        "estimated_cost_usd": round(estimate, 2),
        "cache_exists": CACHE.exists(),
    }
    print(json.dumps(preview))
    if not args.download:
        print("Estimate only. Download requires --credit-only and --verified-credits.")
        return
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
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        client.timeseries.get_range(**request, path=CACHE)
    digest = hashlib.sha256(CACHE.read_bytes()).hexdigest().upper()
    manifest = {
        "mode": "credit_only_download",
        **request,
        **guard,
        "cache": CACHE.relative_to(ROOT).as_posix(),
        "bytes": CACHE.stat().st_size,
        "sha256": digest,
        "card_charge_authorized": False,
        "discovery_only": True,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
