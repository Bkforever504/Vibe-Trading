#!/usr/bin/env python3
"""Shadow-only AI signal journal.

This module records proposed signals for review. It never submits orders and
marks every record as non-executable so downstream tools cannot confuse a
signal note with trade authorization.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

DEFAULT_JOURNAL = Path(os.path.expanduser(r"~\.vibe-trading\shadow-ai-signals.jsonl"))
Action = Literal["buy", "sell", "hold", "close", "skip"]


@dataclass(frozen=True)
class ShadowSignal:
    symbol: str
    strategy: str
    proposed_action: Action
    confidence: float
    thesis: str
    risk_notes: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def signal_record(signal: ShadowSignal) -> dict[str, Any]:
    confidence = min(1.0, max(0.0, float(signal.confidence)))
    return {
        "created_at": _utc_now(),
        "mode": "shadow_only",
        "executable": False,
        "symbol": signal.symbol.upper(),
        "strategy": signal.strategy,
        "proposed_action": signal.proposed_action,
        "confidence": confidence,
        "thesis": signal.thesis,
        "risk_notes": list(signal.risk_notes),
        "context": dict(signal.context),
    }


def append_shadow_signal(signal: ShadowSignal, journal: Path = DEFAULT_JOURNAL) -> dict[str, Any]:
    record = signal_record(signal)
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return record
