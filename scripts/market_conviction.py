#!/usr/bin/env python3
"""Shared conviction scorer for bullish call debit spread shadow lanes.

Stacks 6 idle context signals into a 0-6 score. Shadow-only — output
is measurement data, not an execution gate.

Signals (each +1):
  1. distribution_day   — regime not severe/high
  2. market_breadth     — >55% stocks above 20 DMA
  3. hmm_regime         — HMM state == "trend"
  4. hurst_regime       — Hurst regime == "persistent_trend"
  5. sector_rotation    — leadership == "risk_on_leadership"
  6. gex_regime         — net GEX < 0 (dealers short gamma, amplify moves)
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_NY = ZoneInfo("America/New_York")
_STALE_DAYS = 3

_REPORTS = Path.home() / ".vibe-trading" / "reports"
_ROOT = Path(__file__).resolve().parents[1]

DIST_PATH    = _REPORTS / "distribution-day-scan.json"
BREADTH_PATH = _REPORTS / "market-breadth-uptrend.json"
HMM_PATH     = _REPORTS / "hmm-regime.json"
HURST_PATH   = _REPORTS / "hurst-regime.json"
SECTOR_PATH  = _REPORTS / "sector-rotation-rank.json"
GEX_LOG_PATH = _ROOT / "data" / "gex_scan_log.jsonl"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _report_date(report: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(report.get("date") or ""))
    except ValueError:
        return None


def _is_fresh(report: dict[str, Any], today: date | None = None) -> bool:
    rdate = _report_date(report)
    if rdate is None:
        return False
    ref = today or datetime.now(_NY).date()
    return (ref - rdate).days <= _STALE_DAYS


def _latest_gex() -> dict[str, Any]:
    rows = _read_jsonl(GEX_LOG_PATH)
    return rows[-1] if rows else {}


def score_conviction(symbol: str, today: date | None = None) -> dict[str, Any]:
    """Return conviction score and per-signal breakdown.

    Each signal is 'ok:...' (scored), 'blocked:/weak:/neutral:...' (not scored),
    'stale:...' (report too old — not scored), or 'unavailable:...' (no data).
    """
    score = 0
    signals: dict[str, str] = {}
    stale: list[str] = []

    # 1. Distribution day — want regime not severe/high
    dist = _read_json(DIST_PATH)
    if not _is_fresh(dist, today):
        signals["distribution_day"] = f"stale:{dist.get('date', 'unknown')}"
        stale.append("distribution_day")
    else:
        regime = str((dist.get("aggregate") or {}).get("regime") or "unknown")
        if regime not in {"severe", "high"}:
            score += 1
            signals["distribution_day"] = f"ok:{regime}"
        else:
            signals["distribution_day"] = f"blocked:{regime}"

    # 2. Market breadth — want >55% above 20 DMA
    breadth = _read_json(BREADTH_PATH)
    if not _is_fresh(breadth, today):
        signals["market_breadth"] = f"stale:{breadth.get('date', 'unknown')}"
        stale.append("market_breadth")
    else:
        pct = float((breadth.get("breadth") or {}).get("pct_above_20dma") or 0)
        if pct > 55.0:
            score += 1
            signals["market_breadth"] = f"ok:{pct:.1f}%_above_20dma"
        else:
            signals["market_breadth"] = f"weak:{pct:.1f}%_above_20dma"

    # 3. HMM regime — want "trend"
    hmm = _read_json(HMM_PATH)
    if not _is_fresh(hmm, today):
        signals["hmm_regime"] = f"stale:{hmm.get('date', 'unknown')}"
        stale.append("hmm_regime")
    else:
        state = str((hmm.get("aggregate") or {}).get("state") or "unknown")
        if state == "trend":
            score += 1
            signals["hmm_regime"] = f"ok:{state}"
        else:
            signals["hmm_regime"] = f"neutral:{state}"

    # 4. Hurst regime — want "persistent_trend"
    hurst = _read_json(HURST_PATH)
    if not _is_fresh(hurst, today):
        signals["hurst_regime"] = f"stale:{hurst.get('date', 'unknown')}"
        stale.append("hurst_regime")
    else:
        hr = str((hurst.get("aggregate") or {}).get("regime") or "unknown")
        if hr == "persistent_trend":
            score += 1
            signals["hurst_regime"] = f"ok:{hr}"
        else:
            signals["hurst_regime"] = f"neutral:{hr}"

    # 5. Sector rotation — want risk_on leadership
    sector = _read_json(SECTOR_PATH)
    if not _is_fresh(sector, today):
        signals["sector_rotation"] = f"stale:{sector.get('date', 'unknown')}"
        stale.append("sector_rotation")
    else:
        leadership = str((sector.get("rotation") or {}).get("leadership") or "unknown")
        if leadership == "risk_on_leadership":
            score += 1
            signals["sector_rotation"] = f"ok:{leadership}"
        else:
            signals["sector_rotation"] = f"neutral:{leadership}"

    # 6. GEX — want net_gex < 0 (dealers short gamma → amplify moves)
    gex = _latest_gex()
    gex_scans = gex.get("scans") or []
    sym_gex = next((s for s in gex_scans if s.get("symbol") == symbol), {})
    net_gex = sym_gex.get("net_gex")
    if net_gex is not None and float(net_gex) < 0:
        score += 1
        signals["gex_regime"] = f"ok:negative_gex:{net_gex}"
    elif net_gex is None:
        signals["gex_regime"] = "unavailable:no_gex_data"
    else:
        signals["gex_regime"] = f"neutral:positive_gex:{net_gex}"

    return {
        "conviction_score": score,
        "conviction_max": 6,
        "signals": signals,
        "stale_signals": stale,
    }
