#!/usr/bin/env python3
"""Fetch MES 1-second BBO data from Databento with a hard cost guard.

Approved by Kenny 2026-07-19: bbo-1s 2024-01-01..2026-07-19, ~$66 in signup
credits. Estimate-only unless --download. Reuses cache, never redownloads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "bbo-1s"
DATASET = "GLBX.MDP3"
SYMBOL = "MES.v.0"
START = "2024-01-01"
END = "2026-07-19"
CACHE = ROOT / "data" / "databento" / "mes_v0_bbo1s_2024-01-01_2026-07-19.dbn.zst"
MANIFEST = ROOT / "data" / "databento_bbo_manifest.json"


def load_key() -> str:
    for line in (ROOT / "agent" / ".env").read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("DATABENTO_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("DATABENTO_API_KEY is not configured")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--max-cost", type=float, default=70.0)
    args = parser.parse_args()

    import databento as db

    client = db.Historical(load_key())
    request = dict(dataset=DATASET, schema=SCHEMA, symbols=SYMBOL, stype_in="continuous", start=START, end=END)
    cost = float(client.metadata.get_cost(**request))
    print(json.dumps({"schema": SCHEMA, "start": START, "end": END, "estimated_cost_usd": round(cost, 2)}))
    if not args.download:
        print("Estimate only. Re-run with --download to purchase.")
        return
    if CACHE.exists():
        print("Cache exists; not downloading again.")
    else:
        if cost > args.max_cost:
            raise RuntimeError(f"Estimated cost ${cost:.2f} exceeds --max-cost ${args.max_cost:.2f}")
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        client.timeseries.get_range(**request, path=CACHE)
    digest = hashlib.sha256(CACHE.read_bytes()).hexdigest().upper()
    manifest = {
        "schema": SCHEMA,
        "dataset": DATASET,
        "symbol": SYMBOL,
        "start": START,
        "end": END,
        "estimated_cost_usd": round(cost, 2),
        "cache": str(CACHE),
        "bytes": CACHE.stat().st_size,
        "sha256": digest,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
