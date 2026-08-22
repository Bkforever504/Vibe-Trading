#!/usr/bin/env python3
"""Purchase the frozen MES reopen BBO holdout with a strict cost cap."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = "GLBX.MDP3"
SCHEMA = "bbo-1s"
SYMBOL = "MES.v.0"
START = "2026-07-18"
END = "2026-08-17T15:00:00Z"
CACHE = ROOT / "data" / "databento" / "mes_v0_bbo1s_2026-07-18_2026-08-17.dbn.zst"
MANIFEST = ROOT / "data" / "databento_mes_reopen_holdout_manifest.json"


def load_key() -> str:
    env_path = ROOT / "agent" / ".env"
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("DATABENTO_API_KEY="):
            key = line.split("=", 1)[1].strip()
            if key:
                return key
    raise RuntimeError("DATABENTO_API_KEY is not configured")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--max-cost", type=float, default=3.0)
    args = parser.parse_args()

    import databento as db

    request = {
        "dataset": DATASET,
        "schema": SCHEMA,
        "symbols": SYMBOL,
        "stype_in": "continuous",
        "start": START,
        "end": END,
    }
    client = db.Historical(load_key())
    estimate = float(client.metadata.get_cost(**request))
    conditions = client.metadata.get_dataset_condition(
        dataset=DATASET,
        start_date="2026-07-18",
        end_date="2026-08-17",
    )
    degraded_dates = [
        row["date"] for row in conditions if row.get("condition") != "available"
    ]
    preview = {
        "dataset": DATASET,
        "schema": SCHEMA,
        "symbol": SYMBOL,
        "start": START,
        "end": END,
        "estimated_cost_usd": round(estimate, 4),
        "hard_cost_cap_usd": args.max_cost,
        "cache": str(CACHE),
        "already_cached": CACHE.exists() and CACHE.stat().st_size > 0,
        "non_available_dataset_dates": degraded_dates,
    }
    print(json.dumps(preview, indent=2))
    if estimate > args.max_cost:
        raise RuntimeError(
            f"estimated cost ${estimate:.4f} exceeds hard cap ${args.max_cost:.2f}"
        )
    if not args.download:
        print("Estimate only; pass --download to use authorized credits.")
        return 0

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if not CACHE.exists() or CACHE.stat().st_size == 0:
        partial = CACHE.with_suffix(CACHE.suffix + ".partial")
        partial.unlink(missing_ok=True)
        client.timeseries.get_range(**request, path=partial)
        if not partial.exists() or partial.stat().st_size == 0:
            raise RuntimeError("Databento returned an empty holdout file")
        partial.replace(CACHE)

    digest = hashlib.sha256(CACHE.read_bytes()).hexdigest().upper()
    manifest = {
        **preview,
        "downloaded": True,
        "bytes": CACHE.stat().st_size,
        "sha256": digest,
        "dataset_conditions": conditions,
        "research_only": True,
        "execution_enabled": False,
        "can_submit_orders": False,
        "preregistration": (
            "research/TOPSTEP_MES_REOPEN_WEEKDAY_BBO_HOLDOUT_2026-08-17.md"
        ),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
