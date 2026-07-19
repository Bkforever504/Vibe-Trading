# Codex Handoff: Kalshi Weather Bot Adapter

**Date:** 2026-07-15 CT
**Repository:** `C:\Users\kenne\Desktop\MAILK-Repos\Vibe-Trading`

## Objective

Build a Kalshi venue adapter for the weather bot. Polymarket is geoblocked for
US users (`{"blocked": true, "country": "US", "region": "TX"}`). Kalshi is
CFTC-regulated, US-legal, and runs daily temperature prediction markets
(KXHIGH / KXLOW) that are direct equivalents to the Polymarket weather markets
we have been paper trading.

Keep the existing `strategies/polymarket_weather_bot.py` running unchanged for
paper evidence. The Kalshi bot is a new parallel paper lane, not a replacement.

## Codex Reconciliation (completed 2026-07-15 CT)

This handoff was reviewed against Kalshi's current production API before
implementation. Several assumptions below were stale and were not copied into
the bot:

- Kalshi currently exposes 13 active daily-high series used by the scanner,
  not only the seven-city table below.
- Dallas `KXHIGHTDAL` settles from the NWS Dallas/Fort Worth CLI (`DFW`), not
  Dallas Love Field (`DAL`).
- Current series tickers are city-specific (`KXHIGHNY`, `KXHIGHCHI`,
  `KXHIGHTDAL`, and so on); a generic `KXHIGH` query is not the implemented
  discovery path.
- Trading fees are calculated from the current Kalshi quadratic fee schedule,
  not treated as a flat $0.02 per contract.
- Current `_fp` / `_dollars` market and orderbook fields and the bulk-orderbook
  endpoint are used instead of removed legacy integer-cent fields.

All 13 configured mappings were checked directly against
`GET /trade-api/v2/series/{series_ticker}`. Their settlement sources resolve to
the expected NWS CLI issued-by identifiers: NYC, MDW, MIA, AUS, BOS, DEN, ATL,
MSP, PHX, DFW, HOU, SEA, and OKC. This is the contract-specific authoritative
source; the general help article does not publish a complete coordinate table.

The completed implementation is documented in
`CODEx_CLAUDE_COLLAB/CLAUDE_CODE_HANDOFF_2026-07-15_KALSHI_WEATHER_BOT.md`.
The Kalshi paper task is active and healthy; the Polymarket scheduled task was
disabled because it cannot be a US execution target. No live Kalshi order path
is connected to the scheduled paper bot. The separate authenticated adapter is
dormant and fail-closed.

## What Kalshi Offers

- **Market series:** KXHIGH (daily high temperature) and KXLOW (daily low
  temperature) for 7 US cities: NYC, LA, Chicago, Miami, Dallas, Houston,
  Phoenix.
- **Settlement:** NWS official report, released the following morning. Each
  market settles against one specific ASOS weather station - not "the city"
  generically.
- **Contracts:** Binary YES/NO at integer degree Fahrenheit thresholds. Example:
  `kxhighny` = "Highest temperature in NYC today above X°F?"
- **Fee:** $0.02 per contract.
- **API:** Free for all verified Kalshi accounts. REST + WebSocket.
- **Auth:** RSA-PSS signature on every request (not a Bearer token). You
  generate an API Key ID and a private key from Kalshi dashboard → Settings →
  API.

## Research Findings

### Key edge source: ASOS station precision

The #1 exploitable pricing gap is that most traders model "the city" while
Kalshi settles on one exact ASOS station. A forecast at city center can be
~1°F off the settlement station. Since brackets are integer °F, ~1°F flips
contract outcomes. The bot must request Open-Meteo forecasts at the exact
station coordinates below.

### Kalshi KXHIGH settlement stations (map these exactly)

| Kalshi ticker prefix | City | Settlement ASOS station | Lat | Lon |
|---|---|---|---|---|
| `kxhighny` | New York | KNYC (Central Park) | 40.7789 | -73.9692 |
| `kxhighlax` | Los Angeles | KCQT (Downtown LA) | 34.0195 | -118.2878 |
| `kxhighchi` | Chicago | KMDW (Midway) | 41.7868 | -87.7522 |
| `kxhighmia` | Miami | KMIA | 25.7959 | -80.2870 |
| `kxhighdfw` | Dallas | KDAL (Love Field) | 32.8473 | -96.8515 |
| `kxhighhou` | Houston | KHOU | 29.6454 | -95.2789 |
| `kxhighphx` | Phoenix | KPHX | 33.4373 | -112.0078 |

**Important:** Verify these against `help.kalshi.com/en/articles/13823837-weather-markets`
before finalizing. Kalshi's help docs specify the exact settlement station per
market. If the doc disagrees with the table above, trust the doc.

### OSS reference implementations

- `suislanchez/polymarket-kalshi-weather-bot` - Most relevant. Trades KXHIGH
  on Kalshi using 31-member GFS ensemble from Open-Meteo. Kelly formula:
  `kelly = (win_prob * odds - lose_prob) / odds`, position = `kelly * 0.15 *
  bankroll`, capped at $100/trade. Edge threshold: 8%. Study its Kalshi API
  client and market parsing for auth pattern reference.
- `ryanfrigo/kalshi-ai-trading-bot` - RSA-PSS signing implementation in Python.
  Study for auth client only; do not copy strategy logic.
- `cpratim/Kalshi-Weather-Trading` - Station-to-ticker mapping reference.

## Files to Create

### 1. `strategies/kalshi_weather_bot.py`

Paper-only weather bot for Kalshi KXHIGH/KXLOW. Mirrors the structure of
`strategies/polymarket_weather_bot.py` but with:

**Constants (preserve these from Polymarket bot):**
```python
MIN_EDGE = 0.10                          # do not lower
MAX_SPREAD = 0.10
MIN_ENSEMBLE_MEMBERS = 20
MAX_MODEL_PROBABILITY_DISAGREEMENT = 0.20
MIN_HOURS_TO_END = 2.0
MAX_RISK_PER_POSITION = 5.0
MAX_DAILY_NEW_RISK = 25.0
MAX_OPEN_POSITIONS = 5
TAKE_PROFIT_POINTS = 0.15
STOP_LOSS_POINTS = 0.10
KELLY_FRACTION_CAP = 0.25               # do not increase
REQUIRED_MODEL_FAMILIES = ("gfs_gefs", "ecmwf_ifs", "icon_eu")  # 3-model gate
```

**Kalshi-specific constants:**
```python
KALSHI_FEE_PER_CONTRACT = 0.02
KALSHI_BASE_URL = "https://trading-api.kalshi.com/trade-api/v2"
GEOBLOCK_URL = "https://kalshi.com/api/geoblock"  # verify this endpoint exists
```

**Station table:** Use the 7-city ASOS table from this handoff. Each entry
needs code, lat, lon, timezone - same `Station` dataclass shape as the
Polymarket bot.

**API client (`KalshiClient`):**

```python
import base64
import time
import hashlib
import hmac
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

class KalshiClient:
    def __init__(self, api_key_id: str, private_key_pem: str) -> None:
        self._key_id = api_key_id
        self._private_key = serialization.load_pem_private_key(
            private_key_pem.encode(), password=None
        )

    def _sign(self, method: str, path: str, ts: str) -> str:
        msg = ts + method.upper() + path
        sig = self._private_key.sign(
            msg.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return base64.b64encode(sig).decode()

    def request(self, method: str, path: str, **kwargs) -> dict:
        ts = str(int(time.time() * 1000))
        sig = self._sign(method, path, ts)
        headers = {
            "KALSHI-ACCESS-KEY": self._key_id,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
        }
        response = requests.request(
            method,
            KALSHI_BASE_URL + path,
            headers=headers,
            timeout=10,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()
```

**Market parser (`parse_kalshi_markets`):**

Fetch active KXHIGH / KXLOW markets from:
`GET /markets?series_ticker=KXHIGH&status=open`

Each market has `ticker`, `yes_ask`, `yes_bid`, `no_ask`, `no_bid`,
`close_time`, `subtitle` (contains the threshold and city). Parse the subtitle
to extract:
- temperature threshold (integer °F)
- direction (above / below)
- city → map to ASOS station

Same `TemperatureBucket` + `parse_bucket()` pattern as the Polymarket bot.

**Forecast fetching:**

Reuse the exact same Open-Meteo ensemble API call as the Polymarket bot but
query at ASOS station lat/lon (not city center). Required model families:
`gfs_seamless,ecmwf_ifs025,icon_seamless`. Same 3-model validation gate.

**Paper trading logic:**

Same pattern as Polymarket bot:
- `evaluate_opportunity()` → returns edge, model probability, contracts
- `open_paper_position()` → writes to state file
- `close_paper_position()` → resolves YES/NO against NWS settlement
- State file: `~/.vibe-trading/kalshi-weather-paper-state.json`
- Report: `~/.vibe-trading/reports/kalshi-weather-bot.json`
- Log: `data/kalshi_weather_log.jsonl`

**Execution gate:**

```python
KALSHI_LIVE_EXECUTION_ENABLED = os.getenv("KALSHI_LIVE_EXECUTION_ENABLED", "false").lower() == "true"
```

The bot has NO order submission code in this phase. Live orders require:
1. `KALSHI_LIVE_EXECUTION_ENABLED=true`
2. `KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY_PEM` in env
3. Separate human review of the order adapter
4. 200 promotion-grade paper closures (same standard as Polymarket)

The `KalshiClient` class is built but only used for READ operations (market
fetch, orderbook). No `place_order`, `cancel_order`, or position methods in
this phase.

**Jurisdiction check:**

```python
def _check_jurisdiction() -> dict:
    try:
        r = requests.get("https://kalshi.com/api/geoblock", timeout=5)
        data = r.json()
        return {"checked": True, "blocked": data.get("blocked", True), ...}
    except Exception as exc:
        return {"checked": False, "blocked": True, "error": str(exc)}
```

If the endpoint does not exist at that URL, check `https://trading-api.kalshi.com/trade-api/v2/health`
or skip the geoblock check and note it in the report (Kalshi is US-legal so
this is belt-and-suspenders, not a hard gate like Polymarket was).

### 2. `scripts/run_kalshi_weather_bot.ps1`

Mirror of `scripts/run_polymarket_weather_bot.ps1`. Runs
`strategies/kalshi_weather_bot.py` with a 15-minute Task Scheduler cadence.

### 3. `scripts/kalshi_weather_live_readiness.py`

Mirror of `scripts/polymarket_weather_live_readiness.py`. Readiness gate:
- Jurisdiction not blocked
- At least 200 promotion-grade paper closures
- At least 30 distinct target dates
- Positive net P&L
- Profit factor >= 1.25
- Max drawdown <= 25% of accumulated risk
- `KALSHI_LIVE_EXECUTION_ENABLED` not yet set
- Human enablement explicitly required

### 4. `agent/tests/test_kalshi_weather_bot.py`

Cover at minimum:
- `parse_kalshi_markets()` with fixture market list → correct bucket extraction
- `evaluate_opportunity()` with mocked forecast → correct edge calculation
- 3-model gate blocks when one model family missing
- Edge threshold blocks when edge < 0.10
- Paper position open/close/state round-trip
- `KalshiClient._sign()` produces deterministic output for known key+message
- Execution gate blocks live orders when env flag is false
- Jurisdiction check returns correct structure

## Files NOT to Modify

- `strategies/polymarket_weather_bot.py` - keep running unchanged
- `scripts/polymarket_weather_live_readiness.py` - unchanged
- Any Flip bot file
- Any existing scheduled task

## Environment Variables (agent/.env additions)

```
# Kalshi - paper phase, keys not required yet
KALSHI_API_KEY_ID=
KALSHI_PRIVATE_KEY_PEM=
KALSHI_LIVE_EXECUTION_ENABLED=false
```

Leave the values empty for now. The bot operates in read-only paper mode
without credentials. Add a comment in the env file noting credentials are
required only when live execution is enabled.

## Dependency

Add `cryptography` to requirements if not already present (needed for RSA-PSS
signing). Check `requirements.txt` first - it may already be there.

## Safety Invariants (do not weaken)

- `MIN_EDGE = 0.10` - do not lower to match OSS 8% baseline
- `KELLY_FRACTION_CAP = 0.25` - do not raise
- `REQUIRED_MODEL_FAMILIES` - all 3 must agree, no exceptions
- `MAX_RISK_PER_POSITION = 5.0` - do not raise
- `MAX_DAILY_NEW_RISK = 25.0` - do not raise
- No live order path without explicit human enablement
- `execution_enabled: false, can_submit_orders: false` on all reports
- 200 paper closures required before live readiness evaluates true
- ASOS station coordinates must be verified against Kalshi help docs before
  trading - wrong station means wrong model probability

## Verification Commands

```powershell
# Compile
python -m py_compile strategies/kalshi_weather_bot.py scripts/kalshi_weather_live_readiness.py

# Tests
python -m pytest agent/tests/test_kalshi_weather_bot.py -v

# Dry run (no credentials required)
python strategies/kalshi_weather_bot.py --print --no-trade

# Live readiness (should show not ready, 0 paper closures)
python scripts/kalshi_weather_live_readiness.py --print

# Full suite regression (should not break existing tests)
python -m pytest agent/tests/test_polymarket_weather_bot.py agent/tests/test_flip_bot_safety.py -q
```

## Hard Stops

- Do not enable Kalshi live orders in this phase
- Do not lower the 3-model requirement to unblock markets
- Do not use wrong station coordinates - verify against Kalshi help docs
- Do not copy strategy logic from OSS repos - adapt only the auth/API client
- Do not modify the Polymarket bot
- If `cryptography` package is not in requirements and adding it breaks other
  tests, stop and report
- If Kalshi's geoblock API does not exist at the expected URL, note it in the
  report and proceed without hard-blocking (Kalshi is US-legal by design)
- Do not create a Task Scheduler entry for the new bot - report the PowerShell
  command for the user to register manually

## Expected Deliverables

1. `strategies/kalshi_weather_bot.py` - paper bot, no live order path
2. `scripts/run_kalshi_weather_bot.ps1` - scheduler runner
3. `scripts/kalshi_weather_live_readiness.py` - readiness gate
4. `agent/tests/test_kalshi_weather_bot.py` - test suite
5. Handoff back with: compile clean, test count, first paper scan output,
   readiness report output, station coordinates verified or flagged
