#!/usr/bin/env python3
"""Live shadow signal scanner: 1h NQ=F first-pullback strategy.

Paper/observation only. No orders. Fetches today's 1h bars, detects the
first-pullback-to-breakout signal using the best validated config from the
train/OOS sweep, logs to the shadow journal, and optionally notifies Discord.

Run hourly during RTH (10:30-15:30 ET) via Task Scheduler:
  python strategies/shadow_pullback_signal.py

Best config (train sweep top candidate, OOS exp=+$22.38, WR=75%, 4 trades):
  range_minutes=1, min_breakout_points=20.0, reward_risk=2.0
  pullback_stop_ticks=80 (20 NQ pts = $40 risk on MNQ)
  pullback_tolerance_ticks=8  (2 NQ pts — tightened from prior 16)
  opening_gap_bias=True       (only long on gap-up days, short on gap-down)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, time as dtime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import yfinance as yf
except ImportError:
    sys.exit("yfinance not installed. Run: pip install yfinance")

from strategies.shadow_ai_signals import ShadowSignal, append_shadow_signal
from strategies.topstep_prop_bot import (
    OpeningRangeConfig,
    build_first_pullback_signal,
)

ET = ZoneInfo("America/New_York")
RTH_START = dtime(9, 30)
RTH_END   = dtime(16, 0)

BEST_CONFIG = OpeningRangeConfig(
    range_minutes=1,
    min_breakout_points=20.0,
    reward_risk=2.0,
)
PULLBACK_STOP_TICKS = 80   # 20 NQ points = $40 risk on MNQ
PULLBACK_TOL_TICKS  = 8    # 2 NQ points tolerance (tightened — sweep top candidate)
VIX_MIN = 16.0
VIX_MAX = 24.0
DATA_SOURCE = os.getenv("MNQ_DATA_SOURCE", "yfinance").strip().lower()


def _load_dotenv() -> None:
    env_path = ROOT / "agent" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def fetch_today_1h(ticker: str = "NQ=F") -> tuple[list, float | None]:
    """Return (today_rth_candles, prior_trading_day_close).

    Uses the 5d fetch already needed for today's bars — prior close comes
    from the last RTH bar of the most recent completed trading day.
    """
    if os.getenv("MNQ_DATA_SOURCE", DATA_SOURCE).strip().lower() == "tradovate":
        return fetch_today_1h_tradovate(os.getenv("TRADOVATE_SYMBOL", "MNQ"))

    from strategies.topstep_prop_bot import Candle

    t = yf.Ticker(ticker)
    df = t.history(period="5d", interval="1h", auto_adjust=True)
    if df.empty:
        return [], None

    df.index = df.index.tz_convert(ET)
    today = datetime.now(ET).date()

    prior_close: float | None = None
    prior_df = df[df.index.map(lambda ts: ts.date() < today and RTH_START <= ts.time() < RTH_END)]
    if not prior_df.empty:
        prior_close = float(prior_df.iloc[-1]["Close"])

    today_df = df[df.index.map(lambda ts: ts.date() == today and RTH_START <= ts.time() < RTH_END)]
    if today_df.empty:
        return [], prior_close

    candles = []
    for ts, row in today_df.iterrows():
        candles.append(Candle(
            timestamp=ts.to_pydatetime().replace(tzinfo=None),
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=int(row["Volume"]),
        ))
    return candles, prior_close


def fetch_today_1h_tradovate(symbol: str = "MNQ") -> tuple[list, float | None]:
    """Return today's RTH 1h candles from Tradovate market data."""
    from strategies.topstep_prop_bot import Candle
    from strategies.tradovate_market_data import fetch_chart_candles, likely_contract_symbol

    contract_symbol = likely_contract_symbol(symbol)
    raw_candles = fetch_chart_candles(
        contract_symbol,
        bars=int(os.getenv("TRADOVATE_BARS", "120")),
        interval_minutes=60,
    )

    today = datetime.now(ET).date()
    et_candles = []
    for candle in raw_candles:
        ts_utc = candle.timestamp.replace(tzinfo=timezone.utc)
        ts_et = ts_utc.astimezone(ET).replace(tzinfo=None)
        et_candles.append(
            Candle(
                timestamp=ts_et,
                open=candle.open,
                high=candle.high,
                low=candle.low,
                close=candle.close,
                volume=candle.volume,
            )
        )

    prior = [c for c in et_candles if c.timestamp.date() < today and RTH_START <= c.timestamp.time() < RTH_END]
    prior_close = prior[-1].close if prior else None
    today_rth = [c for c in et_candles if c.timestamp.date() == today and RTH_START <= c.timestamp.time() < RTH_END]
    return today_rth, prior_close


def fetch_overnight_levels(ticker: str = "NQ=F") -> dict[str, float] | None:
    """Return overnight high/low for today's RTH session (pre-market bars, time < 09:30 ET)."""
    t = yf.Ticker(ticker)
    df = t.history(period="5d", interval="1h", auto_adjust=True, prepost=True)
    if df.empty:
        return None
    df.index = df.index.tz_convert(ET)
    today = datetime.now(ET).date()
    # Pre-market bars for today (time before RTH open)
    pre = df[df.index.map(lambda ts: ts.date() == today and ts.time() < RTH_START)]
    # After-hours bars from yesterday (part of today's overnight session)
    yesterday_ah = df[df.index.map(lambda ts: ts.date() < today and ts.time() >= RTH_END)]
    frames = []
    if not pre.empty:
        frames.append(pre)
    if not yesterday_ah.empty:
        frames.append(yesterday_ah.tail(8))  # last 8h of prior session
    if not frames:
        return None
    import pandas as pd
    combined = pd.concat(frames)
    return {
        "overnight_high": float(combined["High"].max()),
        "overnight_low":  float(combined["Low"].min()),
    }


def fetch_latest_vix(ticker: str = "^VIX") -> float | None:
    t = yf.Ticker(ticker)
    df = t.history(period="5d", interval="1d", auto_adjust=True)
    if df.empty:
        return None
    try:
        return float(df["Close"].dropna().iloc[-1])
    except (IndexError, KeyError, ValueError):
        return None


def _discord_notify(webhook_url: str, message: str) -> None:
    payload = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as exc:
        print(f"Discord notify failed: {exc}")


def _gap_allowed_side(prior_close: float | None, today_open: float) -> str | None:
    """Return allowed signal side from opening gap direction, or None to block."""
    if prior_close is None or prior_close <= 0:
        return None
    gap_pct = (today_open - prior_close) / prior_close
    if gap_pct > 0:
        return "buy"
    if gap_pct < 0:
        return "sell"
    return None


def _gap_pct(prior_close: float | None, today_open: float) -> float | None:
    if prior_close is None or prior_close <= 0:
        return None
    return (today_open - prior_close) / prior_close


def build_bar_diagnostics(
    candles: list,
    config: OpeningRangeConfig,
    *,
    prior_close: float | None,
    gap_side: str | None,
    vix_value: float | None,
) -> list[dict]:
    """Score each post-opening-range bar so missed signals are explainable."""
    if len(candles) <= config.range_minutes:
        return []

    from strategies.topstep_prop_bot import contract_for_symbol, session_vwap

    opening = candles[: config.range_minutes]
    range_high = max(c.high for c in opening)
    range_low = min(c.low for c in opening)
    contract = contract_for_symbol("MNQ")
    tolerance = PULLBACK_TOL_TICKS * contract.tick_size
    rows: list[dict] = []

    for idx in range(config.range_minutes, len(candles)):
        bar = candles[idx]
        vwap = session_vwap(candles[: idx + 1])
        long_breakout = bar.close >= range_high + config.min_breakout_points and bar.close > vwap
        short_breakout = bar.close <= range_low - config.min_breakout_points and bar.close < vwap
        direction = "buy" if long_breakout else "sell" if short_breakout else None
        gap_aligned = bool(direction and gap_side and direction == gap_side)
        pullback_touch = (
            abs(bar.low - range_high) <= tolerance
            if direction == "buy"
            else abs(bar.high - range_low) <= tolerance if direction == "sell" else False
        )

        score = 0
        reasons: list[str] = []
        if long_breakout:
            score += 3
            reasons.append("close above opening range high")
        if short_breakout:
            score += 3
            reasons.append("close below opening range low")
        if direction:
            score += 1
            reasons.append("VWAP confirms breakout")
        if gap_aligned:
            score += 2
            reasons.append("gap bias aligned")
        elif direction and gap_side:
            reasons.append(f"gap bias blocked {direction} vs {gap_side}")
        if vix_value is not None and VIX_MIN <= vix_value <= VIX_MAX:
            score += 1
            reasons.append("VIX in execution range")
        if pullback_touch:
            score += 2
            reasons.append("pullback touched breakout level")

        rows.append(
            {
                "bar_idx": idx,
                "timestamp": str(bar.timestamp),
                "open": round(bar.open, 2),
                "high": round(bar.high, 2),
                "low": round(bar.low, 2),
                "close": round(bar.close, 2),
                "vwap": round(vwap, 2),
                "opening_range_high": round(range_high, 2),
                "opening_range_low": round(range_low, 2),
                "long_breakout": long_breakout,
                "short_breakout": short_breakout,
                "direction": direction,
                "gap_side": gap_side,
                "gap_aligned": gap_aligned,
                "pullback_touch": pullback_touch,
                "prior_close": round(prior_close, 2) if prior_close is not None else None,
                "vix": round(vix_value, 2) if vix_value is not None else None,
                "score": min(score, 10),
                "reasons": reasons,
            }
        )
    return rows


def run_scanner(symbol: str = "MNQ", discord: bool = False) -> dict:
    _load_dotenv()
    candles, prior_close = fetch_today_1h()
    vix_value = fetch_latest_vix()
    overnight = fetch_overnight_levels()
    now_et = datetime.now(ET)
    today_str = now_et.date().isoformat()

    status = {
        "date": today_str,
        "scanned_at": now_et.isoformat(timespec="seconds"),
        "symbol": symbol,
        "bars_fetched": len(candles),
        "prior_close": prior_close,
        "vix": vix_value,
        "vix_min": VIX_MIN,
        "vix_max": VIX_MAX,
        "signal": None,
        "state": "no_data",
    }

    if vix_value is None:
        status["state"] = "vix_unavailable"
        print(f"[{now_et.strftime('%H:%M ET')}] VIX unavailable. Skipping.")
        return status

    if not (VIX_MIN <= vix_value <= VIX_MAX):
        status["state"] = "vix_out_of_range"
        print(f"[{now_et.strftime('%H:%M ET')}] VIX {vix_value:.2f} outside {VIX_MIN:.0f}-{VIX_MAX:.0f}. Skipping.")
        return status

    if not candles:
        print(f"[{now_et.strftime('%H:%M ET')}] No 1h bars for today yet.")
        return status

    if len(candles) < BEST_CONFIG.range_minutes + 1:
        state = f"waiting_for_bars (have {len(candles)}, need {BEST_CONFIG.range_minutes + 1})"
        status["state"] = state
        print(f"[{now_et.strftime('%H:%M ET')}] {state}")
        return status

    # Gap bias: only log signals that align with opening gap direction
    gap_side = _gap_allowed_side(prior_close, candles[0].open)
    gap_pct = _gap_pct(prior_close, candles[0].open)
    status["gap_side"] = gap_side
    status["gap_pct"] = gap_pct
    if gap_side is None:
        status["state"] = "gap_bias_no_direction"
        status["bar_diagnostics"] = build_bar_diagnostics(
            candles,
            BEST_CONFIG,
            prior_close=prior_close,
            gap_side=gap_side,
            vix_value=vix_value,
        )
        print(f"[{now_et.strftime('%H:%M ET')}] Gap bias: no clear direction (prior_close={prior_close}). Skipping.")
        return status

    status["bar_diagnostics"] = build_bar_diagnostics(
        candles,
        BEST_CONFIG,
        prior_close=prior_close,
        gap_side=gap_side,
        vix_value=vix_value,
    )

    result = build_first_pullback_signal(
        candles,
        BEST_CONFIG,
        symbol=symbol,
        pullback_tolerance_ticks=PULLBACK_TOL_TICKS,
        pullback_stop_ticks=PULLBACK_STOP_TICKS,
    )

    if result is None:
        # Check if breakout direction exists but no pullback yet
        from strategies.topstep_prop_bot import session_vwap
        opening = candles[:BEST_CONFIG.range_minutes]
        trigger = candles[BEST_CONFIG.range_minutes]
        rh = max(c.high for c in opening)
        rl = min(c.low for c in opening)
        vwap = session_vwap(candles[:BEST_CONFIG.range_minutes + 1])
        long_bo = trigger.close >= rh + BEST_CONFIG.min_breakout_points and trigger.close > vwap
        short_bo = trigger.close <= rl - BEST_CONFIG.min_breakout_points and trigger.close < vwap

        if long_bo or short_bo:
            direction = "LONG" if long_bo else "SHORT"
            state = f"breakout_confirmed_{direction.lower()}_waiting_pullback"
            status["state"] = state
            print(f"[{now_et.strftime('%H:%M ET')}] Breakout confirmed ({direction}) — waiting for pullback to {'%.2f' % rh if long_bo else '%.2f' % rl}")
        else:
            status["state"] = "no_breakout"
            print(f"[{now_et.strftime('%H:%M ET')}] No breakout. Range {rl:.2f}-{rh:.2f}, trigger close {trigger.close:.2f}")
        return status

    signal, entry_idx = result

    # Gap bias: block if signal direction doesn't match gap direction
    if signal.side != gap_side:
        status["state"] = f"gap_bias_blocked_{signal.side}_vs_{gap_side}"
        print(f"[{now_et.strftime('%H:%M ET')}] Gap bias blocked: signal={signal.side}, gap_direction={gap_side}")
        return status

    from strategies.topstep_prop_bot import contract_for_symbol
    contract = contract_for_symbol(symbol)
    risk_dollars = (signal.entry - signal.stop) * contract.point_value if signal.side == "buy" else (signal.stop - signal.entry) * contract.point_value

    sig_dict = {
        "side":              signal.side,
        "entry":             round(signal.entry, 2),
        "stop":              round(signal.stop, 2),
        "target":            round(signal.target, 2),
        "risk_points":       round(abs(signal.entry - signal.stop), 2),
        "risk_dollars_mnq":  round(risk_dollars, 2),
        "reward_dollars_mnq": round(risk_dollars * BEST_CONFIG.reward_risk, 2),
        "entry_bar_idx":     entry_idx,
        "opening_range_high": round(signal.opening_range_high, 2),
        "opening_range_low":  round(signal.opening_range_low, 2),
        "vwap":              signal.vwap,
        "confidence":        signal.confidence,
        "bars_used":         len(candles),
        "prior_close":       round(prior_close, 2) if prior_close is not None else None,
        "gap_side":          gap_side,
        "gap_pct":           round(gap_pct, 6) if gap_pct is not None else None,
        "vix":               round(vix_value, 2),
        "vix_min":           VIX_MIN,
        "vix_max":           VIX_MAX,
        "overnight_high":    round(overnight["overnight_high"], 2) if overnight else None,
        "overnight_low":     round(overnight["overnight_low"], 2) if overnight else None,
    }
    status["signal"] = sig_dict
    status["state"]  = "signal_fired"

    side_emoji = "🟢 LONG" if signal.side == "buy" else "🔴 SHORT"
    print(f"\n[{now_et.strftime('%H:%M ET')}] PULLBACK SIGNAL FIRED")
    print(f"  {side_emoji}  Entry: {signal.entry:.2f}  Stop: {signal.stop:.2f}  Target: {signal.target:.2f}")
    print(f"  Risk: ${risk_dollars:.2f} MNQ | Reward: ${risk_dollars * BEST_CONFIG.reward_risk:.2f} MNQ")
    print(f"  ORB: {signal.opening_range_low:.2f}-{signal.opening_range_high:.2f} | VWAP: {signal.vwap:.2f}")
    print(f"  [SHADOW ONLY — no orders]\n")

    shadow = ShadowSignal(
        symbol=symbol,
        strategy="first_pullback_1h",
        proposed_action=signal.side,  # type: ignore[arg-type]
        confidence=signal.confidence,
        thesis=(
            f"1h ORB pullback: {signal.side.upper()} after breakout of "
            f"{signal.opening_range_low:.2f}-{signal.opening_range_high:.2f} range. "
            f"Pullback to level at bar {entry_idx}. "
            f"Entry {signal.entry:.2f}, stop {signal.stop:.2f}, target {signal.target:.2f}."
        ),
        risk_notes=[
            f"Risk ${risk_dollars:.2f} per MNQ contract",
            "Shadow only — no live order",
            f"Gap bias confirmed: gap_side={gap_side}",
            "Config: tol=8ticks, stop=80ticks, gap_bias=True (OOS exp=+$22.38, WR=75%, 4 trades)",
        ],
        context=sig_dict,
    )
    append_shadow_signal(shadow)

    if discord:
        webhook = os.environ.get("DISCORD_WEBHOOK_URL", "")
        if webhook:
            msg = (
                f"**NQ Pullback Signal** {side_emoji}\n"
                f"Entry: `{signal.entry:.2f}` | Stop: `{signal.stop:.2f}` | Target: `{signal.target:.2f}`\n"
                f"Risk: **${risk_dollars:.2f}** MNQ | Reward: **${risk_dollars * BEST_CONFIG.reward_risk:.2f}** MNQ\n"
                f"_Shadow only — paper observation_"
            )
            _discord_notify(webhook, msg)
        else:
            print("DISCORD_WEBHOOK_URL not set — skipping notification")

    return status


def main() -> None:
    parser = argparse.ArgumentParser(description="Shadow pullback signal scanner (1h NQ=F)")
    parser.add_argument("--symbol", default="MNQ")
    parser.add_argument("--discord", action="store_true", help="Send Discord notification if signal fires")
    parser.add_argument("--json", action="store_true", help="Output full status as JSON")
    args = parser.parse_args()

    status = run_scanner(symbol=args.symbol, discord=args.discord)

    if args.json:
        print(json.dumps(status, indent=2, default=str))


if __name__ == "__main__":
    main()
