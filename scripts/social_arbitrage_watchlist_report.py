#!/usr/bin/env python3
"""Generate the read-only social arbitrage watchlist report."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strategies.social_arbitrage_watchlist import main


if __name__ == "__main__":
    raise SystemExit(main())
