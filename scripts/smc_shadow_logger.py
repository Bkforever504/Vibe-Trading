"""
Daily shadow signal logger for Smart Money Concepts (SMC / ICT) strategy.

No trading. No Alpaca orders. Appends to data/smc_shadow_log.jsonl

Concepts (via smartmoneyconcepts package — MIT license, pip install smartmoneyconcepts):
  - Order Blocks (OB): Last bearish candle before a bullish impulse (bullish OB)
                       Last bullish candle before a bearish impulse (bearish OB)
                       → Institutional accumulation/distribution zones
  - Fair Value Gap (FVG): 3-candle gap where middle candle doesn't overlap neighbors
                          → Price tends to return and fill these gaps
  - Break of Structure (BOS): Price breaks a previous swing high/low with trend
  - Change of Character (CHoCH): Price breaks structure AGAINST the trend = reversal signal

Usage for our bots:
  - Bullish OB below current price = potential support zone for Flip Bot entries
  - FVG above price = upside target (price often fills gaps)
  - CHoCH bearish after bull run = Flip Bot exit signal or short setup
  - BOS confirms trend continuation = add-on entry zone

Primary:    QQQ daily
Comparison: SPY daily

Requires: pip install smartmoneyconcepts
Run daily at market close (15:20 ET).
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.market_data import fetch_ohlcv, data_source, fetch_vix_context
from scripts.shadow_alerts import maybe_send_shadow_alert

LOG_PATH = ROOT / "data" / "smc_shadow_log.jsonl"
PRIMARY_SYMBOL = "QQQ"
COMPARISON_SYMBOL = "SPY"
SWING_LOOKBACK = 5  # bars each side to detect swing highs/lows


def _import_smc():
    try:
        from smartmoneyconcepts import smc
        return smc
    except ImportError:
        raise ImportError(
            "smartmoneyconcepts required: uv add smartmoneyconcepts  "
            "OR  pip install smartmoneyconcepts"
        )


def _prep_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure lowercase column names matching smc package expectations."""
    out = df.copy()
    out.columns = [c.lower() for c in out.columns]
    required = ["open", "high", "low", "close"]
    if not all(c in out.columns for c in required):
        raise ValueError(f"Missing OHLC columns. Got: {list(out.columns)}")
    return out[required + [c for c in ["volume"] if c in out.columns]].dropna()


def _safe_list(df_or_none, max_items: int = 5) -> list[dict]:
    """Convert smc result DataFrame to list of dicts, limit to recent rows."""
    if df_or_none is None or not isinstance(df_or_none, pd.DataFrame) or df_or_none.empty:
        return []
    df = df_or_none.dropna(how="all")
    if df.empty:
        return []
    rows = []
    for idx, row in df.tail(max_items).iterrows():
        r = {"bar": str(idx)[:10]}
        for col in row.index:
            val = row[col]
            if pd.isna(val):
                continue
            r[col] = float(val) if isinstance(val, (int, float)) else str(val)
        rows.append(r)
    return rows


def _basic_smc_signals(df: pd.DataFrame, note: str) -> dict:
    """Fallback SMC approximation when the external package cannot be installed."""
    ohlc = _prep_ohlc(df)
    close = float(ohlc["close"].iloc[-1])

    # Simple fair value gap detection: current low above high two bars ago (bullish)
    # or current high below low two bars ago (bearish).
    active_fvgs: list[dict] = []
    for i in range(2, len(ohlc)):
        prev2 = ohlc.iloc[i - 2]
        row = ohlc.iloc[i]
        if float(row["low"]) > float(prev2["high"]):
            active_fvgs.append({
                "bar": str(ohlc.index[i])[:10],
                "type": "bullish",
                "top": round(float(row["low"]), 2),
                "bottom": round(float(prev2["high"]), 2),
            })
        elif float(row["high"]) < float(prev2["low"]):
            active_fvgs.append({
                "bar": str(ohlc.index[i])[:10],
                "type": "bearish",
                "top": round(float(prev2["low"]), 2),
                "bottom": round(float(row["high"]), 2),
            })

    lookback = max(SWING_LOOKBACK * 2, 10)
    recent = ohlc.tail(lookback)
    prior = ohlc.iloc[:-1].tail(lookback)
    prior_high = float(prior["high"].max()) if not prior.empty else close
    prior_low = float(prior["low"].min()) if not prior.empty else close
    last_high = float(ohlc["high"].iloc[-1])
    last_low = float(ohlc["low"].iloc[-1])

    structure_breaks: list[dict] = []
    if last_high > prior_high:
        structure_breaks.append({
            "bar": str(ohlc.index[-1])[:10],
            "type": "bullish_bos",
            "level": round(prior_high, 2),
        })
    elif last_low < prior_low:
        structure_breaks.append({
            "bar": str(ohlc.index[-1])[:10],
            "type": "bearish_bos",
            "level": round(prior_low, 2),
        })

    bullish_impulse = float(recent["close"].iloc[-1]) > float(recent["open"].iloc[-1])
    bearish_impulse = float(recent["close"].iloc[-1]) < float(recent["open"].iloc[-1])
    order_blocks: list[dict] = []
    if bullish_impulse:
        bearish_candles = recent[recent["close"] < recent["open"]]
        if not bearish_candles.empty:
            ob = bearish_candles.iloc[-1]
            order_blocks.append({
                "bar": str(bearish_candles.index[-1])[:10],
                "OB": "bullish",
                "Top": round(float(ob["high"]), 2),
                "Bottom": round(float(ob["low"]), 2),
            })
    if bearish_impulse:
        bullish_candles = recent[recent["close"] > recent["open"]]
        if not bullish_candles.empty:
            ob = bullish_candles.iloc[-1]
            order_blocks.append({
                "bar": str(bullish_candles.index[-1])[:10],
                "OB": "bearish",
                "Top": round(float(ob["high"]), 2),
                "Bottom": round(float(ob["low"]), 2),
            })

    last_bos = structure_breaks[-1] if structure_breaks else None
    action = str(last_bos["type"]) if last_bos else "watching"
    bull_obs = [o for o in order_blocks if o.get("OB") == "bullish" and o.get("Bottom", 0) < close]
    bear_obs = [o for o in order_blocks if o.get("OB") == "bearish" and o.get("Top", float("inf")) > close]

    return {
        "engine": "basic_fallback",
        "fallback_reason": note[:160],
        "current_close": close,
        "active_fvgs": active_fvgs[-5:],
        "fvg_count": len(active_fvgs),
        "order_blocks": order_blocks[-5:],
        "structure_breaks": structure_breaks,
        "nearest_bull_ob_below": bull_obs[-1] if bull_obs else None,
        "nearest_bear_ob_above": bear_obs[0] if bear_obs else None,
        "action": action,
        "last_structure_break": last_bos,
    }


def compute_smc_signals(df: pd.DataFrame) -> dict:
    ohlc = _prep_ohlc(df)
    try:
        smc = _import_smc()
    except ImportError as exc:
        return _basic_smc_signals(ohlc, str(exc))

    # Swing highs/lows (required input for most smc functions)
    try:
        swings = smc.swing_highs_lows(ohlc, swing_length=SWING_LOOKBACK)
    except Exception as exc:
        return {"error": f"swing_highs_lows failed: {exc}"}

    result: dict = {}

    # Fair Value Gaps
    try:
        fvg = smc.fvg(ohlc, join_consecutive=False)
        # Active FVGs = not mitigated
        active_fvg = []
        if isinstance(fvg, pd.DataFrame) and not fvg.empty:
            for idx, row in fvg.iterrows():
                if pd.isna(row.get("MitigatedIndex", float("nan"))):
                    active_fvg.append({
                        "bar": str(idx)[:10],
                        "type": str(row.get("FVG", "")),
                        "top": float(row.get("Top", 0)),
                        "bottom": float(row.get("Bottom", 0)),
                    })
        result["active_fvgs"] = active_fvg[-5:]  # last 5 unmitigated
        result["fvg_count"] = len(active_fvg)
    except Exception as exc:
        result["fvg_error"] = str(exc)[:100]

    # Order Blocks
    try:
        ob = smc.ob(ohlc, swings, close_mitigation=False)
        result["order_blocks"] = _safe_list(ob)
    except Exception as exc:
        result["ob_error"] = str(exc)[:100]

    # Break of Structure + Change of Character
    try:
        bos = smc.bos_choch(ohlc, swings, close_mitigation=False)
        if isinstance(bos, pd.DataFrame) and not bos.empty:
            recent = bos.dropna(how="all").tail(3)
            bos_list = []
            for idx, row in recent.iterrows():
                bos_type = str(row.get("BOS", "")) or str(row.get("CHOCH", ""))
                level = row.get("Level", None)
                bos_list.append({
                    "bar": str(idx)[:10],
                    "type": bos_type,
                    "level": float(level) if level and not pd.isna(level) else None,
                })
            result["structure_breaks"] = bos_list
        else:
            result["structure_breaks"] = []
    except Exception as exc:
        result["bos_error"] = str(exc)[:100]

    # Current price vs key levels
    close = float(ohlc["close"].iloc[-1])
    result["current_close"] = close

    # Nearest bullish OB below price (support)
    obs = result.get("order_blocks", [])
    bull_obs = [o for o in obs if "bull" in str(o.get("OB", "")).lower()]
    bull_obs_below = [o for o in bull_obs if o.get("Bottom", 0) < close]
    result["nearest_bull_ob_below"] = bull_obs_below[-1] if bull_obs_below else None

    # Nearest bearish OB above price (resistance)
    bear_obs = [o for o in obs if "bear" in str(o.get("OB", "")).lower()]
    bear_obs_above = [o for o in bear_obs if o.get("Top", float("inf")) > close]
    result["nearest_bear_ob_above"] = bear_obs_above[0] if bear_obs_above else None

    # Signal summary
    recent_bos = result.get("structure_breaks", [])
    last_bos = recent_bos[-1] if recent_bos else None
    is_choch = last_bos and "choch" in str(last_bos.get("type", "")).lower()
    is_bos_bull = last_bos and "bull" in str(last_bos.get("type", "")).lower()
    is_bos_bear = last_bos and "bear" in str(last_bos.get("type", "")).lower()

    if is_choch and is_bos_bear:
        action = "bearish_choch"
    elif is_choch and is_bos_bull:
        action = "bullish_choch"
    elif is_bos_bull:
        action = "bullish_bos"
    elif is_bos_bear:
        action = "bearish_bos"
    else:
        action = "watching"

    result["action"] = action
    result["last_structure_break"] = last_bos

    return result


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------

def load_last_entry(log_path: Path = LOG_PATH) -> dict | None:
    if not log_path.exists():
        return None
    for line in reversed(log_path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if line:
            return json.loads(line)
    return None


def log_entry(entry: dict, log_path: Path = LOG_PATH) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)

    entry_date = entry.get("date")
    deduped: list[dict] = []
    replaced = False
    for row in rows:
        if row.get("date") == entry_date:
            if not replaced:
                deduped.append(entry)
                replaced = True
            continue
        deduped.append(row)
    if not replaced:
        deduped.append(entry)

    log_path.write_text("".join(json.dumps(r) + "\n" for r in deduped), encoding="utf-8")


def compute_signal(primary_df: pd.DataFrame, comparison_df: pd.DataFrame) -> dict:
    today = date.today().isoformat()

    primary_smc = compute_smc_signals(primary_df)
    comparison_smc = compute_smc_signals(comparison_df)

    return {
        "date": today,
        "execution_mode": "shadow_only",
        "data_source": data_source(),
        "vix_context": fetch_vix_context(),
        "primary": {"symbol": PRIMARY_SYMBOL, **primary_smc},
        "comparison": {"symbol": COMPARISON_SYMBOL, **comparison_smc},
        "paper_rules": {
            "minimum_forward_days": 30,
            "minimum_signals_before_review": 10,
            "live_execution_allowed": False,
            "note": (
                "SMC: CHoCH = potential reversal signal. "
                "Bullish OB below price = support zone for long entries. "
                "FVG above price = upside target."
            ),
        },
    }


def print_report(entry: dict, prev: dict | None = None) -> None:
    print("\n" + "=" * 62)
    print(f"SMC Shadow Signal | {entry['date']}")
    print("=" * 62)
    for key in ("primary", "comparison"):
        s = entry[key]
        if s.get("error"):
            print(f"\n{s['symbol']}: ERROR — {s['error']}")
            continue
        print(f"\n{s['symbol']}: close=${s.get('current_close', '?'):.2f}  action={s.get('action')}")
        print(f"  Active FVGs: {s.get('fvg_count', 0)}  Order Blocks: {len(s.get('order_blocks', []))}")
        bull_ob = s.get("nearest_bull_ob_below")
        if bull_ob:
            bot = bull_ob.get("Bottom") or bull_ob.get("bottom") or "?"
            print(f"  Nearest bullish OB below: ${bot}")
        bear_ob = s.get("nearest_bear_ob_above")
        if bear_ob:
            top = bear_ob.get("Top") or bear_ob.get("top") or "?"
            print(f"  Nearest bearish OB above: ${top}")
        last_bos = s.get("last_structure_break")
        if last_bos:
            print(f"  Last structure break: {last_bos.get('type')} @ {last_bos.get('bar')}")
    vix = entry.get("vix_context", {})
    if vix.get("close"):
        print(f"\nVIX: {vix['close']} ({vix.get('regime')})")
    if prev:
        print(f"Previous: {prev.get('date')} primary={prev.get('primary', {}).get('action')}")
    print("\nMode: shadow_only — no orders, no broker calls\n")


def main() -> int:
    print("Fetching OHLCV data and computing SMC levels...")
    primary_df = fetch_ohlcv(PRIMARY_SYMBOL)
    comparison_df = fetch_ohlcv(COMPARISON_SYMBOL)
    entry = compute_signal(primary_df, comparison_df)
    prev = load_last_entry()
    print_report(entry, prev)
    maybe_send_shadow_alert("SMC Order Blocks", entry, prev)
    log_entry(entry)
    print(f"Logged to {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
