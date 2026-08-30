#!/usr/bin/env python3
"""Causal, shadow-only pairs/relative-value evidence scanner.

The linked KidQuant notebook is useful as an educational introduction, but its
same-sample pair selection and frictionless trading loop are not production
evidence.  This module keeps the reusable statistical-arbitrage idea while
enforcing a completed-bar formation/signal split, family-wise false-discovery
control, stability and mean-reversion gates, freshness labels, and no order
authority.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import requests
import statsmodels
import statsmodels.api as sm
from dotenv import load_dotenv
from statsmodels.stats.diagnostic import breaks_cusumolsresid, breaks_hansen
from statsmodels.tsa.stattools import adfuller, coint


SCHEMA_VERSION = 1
ALPACA_DATA_ORIGIN = "https://data.alpaca.markets"
ALPACA_BARS_PATH = "/v2/stocks/bars"
VIBE_HOME = Path.home() / ".vibe-trading"
DEFAULT_OUTPUT = VIBE_HOME / "reports" / "pairs-relative-value.json"
ROOT = Path(__file__).resolve().parents[1]

TIMEFRAME_POLICY: dict[str, dict[str, float | int]] = {
    "1Day": {
        "formation_bars": 252,
        "minimum_bars": 180,
        "maximum_age_seconds": 96 * 60 * 60,
        "minimum_half_life_bars": 2,
        "maximum_half_life_bars": 60,
    },
    "1Hour": {
        "formation_bars": 500,
        "minimum_bars": 300,
        "maximum_age_seconds": 6 * 60 * 60,
        "minimum_half_life_bars": 2,
        "maximum_half_life_bars": 80,
    },
}

ENTRY_Z = 2.0
EXIT_Z = 0.5
STOP_Z = 3.5
FDR_ALPHA = 0.05


@dataclass(frozen=True)
class PairSpec:
    pair_id: str
    left: str
    right: str
    economic_thesis: str


DEFAULT_PAIR_SPECS: tuple[PairSpec, ...] = (
    PairSpec("SPY_IVV", "SPY", "IVV", "funds tracking the S&P 500"),
    PairSpec("QQQ_QQQM", "QQQ", "QQQM", "funds tracking the Nasdaq-100"),
    PairSpec("IWM_VTWO", "IWM", "VTWO", "funds tracking the Russell 2000"),
    PairSpec("XLE_VDE", "XLE", "VDE", "US energy-sector equity funds"),
    PairSpec("XLF_VFH", "XLF", "VFH", "US financial-sector equity funds"),
    PairSpec("XLK_VGT", "XLK", "VGT", "US information-technology equity funds"),
    PairSpec("XLV_VHT", "XLV", "VHT", "US health-care equity funds"),
    PairSpec("XLI_VIS", "XLI", "VIS", "US industrial equity funds"),
    PairSpec("XLP_VDC", "XLP", "VDC", "US consumer-staples equity funds"),
    PairSpec("XLY_VCR", "XLY", "VCR", "US consumer-discretionary equity funds"),
    PairSpec("XLU_VPU", "XLU", "VPU", "US utilities equity funds"),
    PairSpec("XLB_VAW", "XLB", "VAW", "US materials equity funds"),
)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        normalized = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def benjamini_hochberg(
    pvalues: Mapping[str, float], *, family_size: int | None = None
) -> dict[str, float]:
    """Return monotone Benjamini-Hochberg adjusted p-values for one family."""
    clean = sorted(
        ((str(key), min(1.0, max(0.0, float(value)))) for key, value in pvalues.items()),
        key=lambda item: item[1],
    )
    total = family_size if family_size is not None else len(clean)
    if total < len(clean):
        raise ValueError("family_size cannot be smaller than the observed p-value count")
    adjusted: dict[str, float] = {}
    running = 1.0
    for rank, (key, pvalue) in reversed(list(enumerate(clean, start=1))):
        running = min(running, pvalue * total / rank)
        adjusted[key] = round(min(1.0, running), 8)
    return {key: adjusted[key] for key in pvalues}


def _aligned_closes(
    left_rows: Sequence[Mapping[str, Any]],
    right_rows: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
) -> tuple[list[datetime], np.ndarray, np.ndarray]:
    def normalize(rows: Sequence[Mapping[str, Any]]) -> dict[datetime, float]:
        output: dict[datetime, float] = {}
        for row in rows:
            timestamp = _parse_time(row.get("timestamp") or row.get("t"))
            close = _finite(row.get("close") if row.get("close") is not None else row.get("c"))
            if timestamp is not None and timestamp <= now and close is not None and close > 0:
                output[timestamp] = close
        return output

    left = normalize(left_rows)
    right = normalize(right_rows)
    timestamps = sorted(set(left).intersection(right))
    return (
        timestamps,
        np.asarray([left[stamp] for stamp in timestamps], dtype=float),
        np.asarray([right[stamp] for stamp in timestamps], dtype=float),
    )


def _ols_spread(left_log: np.ndarray, right_log: np.ndarray) -> tuple[float, float, np.ndarray]:
    design = np.column_stack([np.ones(len(right_log)), right_log])
    coefficients, *_ = np.linalg.lstsq(design, left_log, rcond=None)
    intercept, hedge_ratio = float(coefficients[0]), float(coefficients[1])
    return intercept, hedge_ratio, left_log - (intercept + hedge_ratio * right_log)


def _half_life(spread: np.ndarray) -> float | None:
    if len(spread) < 10:
        return None
    lagged = spread[:-1]
    changes = np.diff(spread)
    design = np.column_stack([np.ones(len(lagged)), lagged])
    coefficients, *_ = np.linalg.lstsq(design, changes, rcond=None)
    speed = float(coefficients[1])
    if not math.isfinite(speed) or speed >= 0:
        return None
    value = -math.log(2.0) / speed
    return float(value) if math.isfinite(value) and value > 0 else None


def _test_pvalues(left_log: np.ndarray, right_log: np.ndarray) -> tuple[float | None, float | None]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cointegration_pvalue = float(coint(left_log, right_log, trend="c", autolag="aic")[1])
            _, _, spread = _ols_spread(left_log, right_log)
            adf_pvalue = float(adfuller(spread, regression="c", autolag="AIC")[1])
    except (ValueError, np.linalg.LinAlgError):
        return None, None
    return cointegration_pvalue, adf_pvalue


def _stability_rate(left_log: np.ndarray, right_log: np.ndarray) -> float:
    size = len(left_log)
    windows = (
        (0, size // 2),
        (size // 4, 3 * size // 4),
        (size // 2, size),
    )
    passed = 0
    observed = 0
    for start, end in windows:
        if end - start < 60:
            continue
        cointegration_pvalue, adf_pvalue = _test_pvalues(left_log[start:end], right_log[start:end])
        if cointegration_pvalue is None or adf_pvalue is None:
            continue
        observed += 1
        if cointegration_pvalue <= 0.10 and adf_pvalue <= 0.10:
            passed += 1
    return passed / observed if observed else 0.0


def _missing_pair(spec: PairSpec, timeframe: str, blocker: str) -> dict[str, Any]:
    return {
        "pair_id": spec.pair_id,
        "symbols": [spec.left, spec.right],
        "economic_thesis": spec.economic_thesis,
        "timeframe": timeframe,
        "state": "blocked",
        "model": {},
        "current": {},
        "plan": {
            "signal_on_completed_bar": True,
            "earliest_manual_review": "next_bar",
            "entry_z": ENTRY_Z,
            "exit_z": EXIT_Z,
            "stop_z": STOP_Z,
        },
        "blockers": [blocker],
        "probability": {
            "value": None,
            "label": "No locally calibrated win probability",
            "ranking_eligible": False,
        },
        "main_candidate_ranking_eligible": False,
        "evidence_status": "unvalidated_shadow_hypothesis",
        "source_labels": [],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def evaluate_pair(
    spec: PairSpec,
    left_rows: Sequence[Mapping[str, Any]],
    right_rows: Sequence[Mapping[str, Any]],
    *,
    timeframe: str,
    now: datetime,
) -> dict[str, Any]:
    """Fit through t-1 and score only the latest completed bar at t."""
    if timeframe not in TIMEFRAME_POLICY:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    policy = TIMEFRAME_POLICY[timeframe]
    timestamps, left, right = _aligned_closes(left_rows, right_rows, now=now)
    minimum = int(policy["minimum_bars"])
    if len(timestamps) < minimum + 1:
        return _missing_pair(spec, timeframe, "insufficient_aligned_bars")

    formation_bars = min(int(policy["formation_bars"]), len(timestamps) - 1)
    left_formation = np.log(left[-formation_bars - 1 : -1])
    right_formation = np.log(right[-formation_bars - 1 : -1])
    intercept, hedge_ratio, formation_spread = _ols_spread(left_formation, right_formation)
    cointegration_pvalue, adf_pvalue = _test_pvalues(left_formation, right_formation)
    stability_rate = _stability_rate(left_formation, right_formation)
    half_life = _half_life(formation_spread)
    mean = float(np.mean(formation_spread))
    standard_deviation = float(np.std(formation_spread, ddof=1))
    current_spread = float(np.log(left[-1]) - (intercept + hedge_ratio * np.log(right[-1])))
    zscore = (current_spread - mean) / standard_deviation if standard_deviation > 0 else math.nan
    age_seconds = max(0.0, (now - timestamps[-1]).total_seconds())

    blockers: list[str] = []
    if cointegration_pvalue is None or adf_pvalue is None or not math.isfinite(zscore):
        blockers.append("statistical_model_unavailable")
    if not 0.2 <= hedge_ratio <= 5.0:
        blockers.append("unstable_or_nonpositive_hedge_ratio")
    if adf_pvalue is None or adf_pvalue > 0.05:
        blockers.append("residual_stationarity_failed")
    if stability_rate < 2 / 3:
        blockers.append("rolling_stability_failed")
    minimum_half_life = float(policy["minimum_half_life_bars"])
    maximum_half_life = float(policy["maximum_half_life_bars"])
    if half_life is None or not minimum_half_life <= half_life <= maximum_half_life:
        blockers.append("mean_reversion_half_life_out_of_range")
    if age_seconds > float(policy["maximum_age_seconds"]):
        blockers.append("stale_completed_bars")
    if math.isfinite(zscore) and abs(zscore) >= STOP_Z:
        blockers.append("spread_break_stop")

    direction = (
        f"short {spec.left} / long {hedge_ratio:.3f} {spec.right}"
        if zscore > 0
        else f"long {spec.left} / short {hedge_ratio:.3f} {spec.right}"
    )
    state = "blocked" if blockers else "entry_ready" if abs(zscore) >= ENTRY_Z else "watch"
    return {
        "pair_id": spec.pair_id,
        "symbols": [spec.left, spec.right],
        "economic_thesis": spec.economic_thesis,
        "timeframe": timeframe,
        "state": state,
        "as_of": _iso(timestamps[-1]),
        "freshness": {
            "age_seconds": round(age_seconds, 1),
            "status": "stale" if "stale_completed_bars" in blockers else "fresh",
        },
        "model": {
            "formation_end": _iso(timestamps[-2]),
            "formation_bars": formation_bars,
            "intercept": round(intercept, 8),
            "hedge_ratio": round(hedge_ratio, 8),
            "cointegration_pvalue": round(cointegration_pvalue, 8) if cointegration_pvalue is not None else None,
            "cointegration_qvalue": None,
            "residual_adf_pvalue": round(adf_pvalue, 8) if adf_pvalue is not None else None,
            "rolling_stability_pass_rate": round(stability_rate, 4),
            "half_life_bars": round(half_life, 2) if half_life is not None else None,
        },
        "current": {
            "left_close": round(float(left[-1]), 6),
            "right_close": round(float(right[-1]), 6),
            "spread": round(current_spread, 8),
            "zscore": round(float(zscore), 4) if math.isfinite(zscore) else None,
        },
        "plan": {
            "direction": direction,
            "entry_z": ENTRY_Z,
            "exit_z": EXIT_Z,
            "stop_z": STOP_Z,
            "expected_holding_bars": round(half_life, 2) if half_life is not None else None,
            "signal_on_completed_bar": True,
            "earliest_manual_review": "next_bar",
            "instruction": "Review both executable quotes; never leg into only one side.",
        },
        "blockers": blockers,
        "probability": {
            "value": None,
            "label": "No locally calibrated win probability",
            "ranking_eligible": False,
        },
        "main_candidate_ranking_eligible": False,
        "evidence_status": "unvalidated_shadow_hypothesis",
        "source_labels": [],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def build_report(
    bars_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    specs: Sequence[PairSpec] = DEFAULT_PAIR_SPECS,
    timeframe: str = "1Day",
    now: datetime | None = None,
    source_label: str = "alpaca_iex_completed_bars",
) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows: list[dict[str, Any]] = []
    for spec in specs:
        left = bars_by_symbol.get(spec.left)
        right = bars_by_symbol.get(spec.right)
        if not left or not right:
            row = _missing_pair(spec, timeframe, "missing_leg_bars")
        else:
            row = evaluate_pair(spec, left, right, timeframe=timeframe, now=now)
        row["source_labels"] = [source_label, "completed_bar_causal_model"] if left and right else [source_label]
        rows.append(row)

    raw_pvalues = {
        row["pair_id"]: float(row["model"]["cointegration_pvalue"])
        for row in rows
        if row.get("model", {}).get("cointegration_pvalue") is not None
    }
    adjusted = benjamini_hochberg(raw_pvalues)
    for row in rows:
        qvalue = adjusted.get(row["pair_id"])
        if row.get("model"):
            row["model"]["cointegration_qvalue"] = qvalue
        if row.get("model") and (qvalue is None or qvalue > FDR_ALPHA):
            if "cointegration_fdr_failed" not in row["blockers"]:
                row["blockers"].append("cointegration_fdr_failed")
        if row["blockers"]:
            row["state"] = "blocked"

    counts = {state: sum(row["state"] == state for row in rows) for state in ("entry_ready", "watch", "blocked")}
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "pairs_relative_value_scanner",
        "mode": "read_only_shadow_research",
        "generated_at": _iso(now),
        "timeframe": timeframe,
        "policy": {
            **TIMEFRAME_POLICY[timeframe],
            "entry_z": ENTRY_Z,
            "exit_z": EXIT_Z,
            "stop_z": STOP_Z,
            "fdr_method": "Benjamini-Hochberg",
            "fdr_alpha": FDR_ALPHA,
            "formation_excludes_signal_bar": True,
            "manual_review_no_earlier_than_next_bar": True,
        },
        "declared_family": [asdict(spec) for spec in specs],
        "summary": {
            "pair_count": len(rows),
            "statistically_qualified_count": sum(
                row.get("model", {}).get("cointegration_qvalue") is not None
                and row["model"]["cointegration_qvalue"] <= FDR_ALPHA
                for row in rows
            ),
            **{f"{key}_count": value for key, value in counts.items()},
            "evidence_status": "collecting_shadow_outcomes",
        },
        "pairs": rows,
        "warnings": [
            "Pair grades are not win probabilities.",
            "Cointegration can break; a stop or stability failure blocks review.",
            "Transaction costs, borrow, locate availability, and both-leg executable quotes must be checked manually.",
        ],
        "execution_enabled": False,
        "can_submit_orders": False,
    }


def fetch_alpaca_completed_bars(
    symbols: Iterable[str],
    *,
    timeframe: str,
    now: datetime,
    api_key: str,
    api_secret: str,
    feed: str = "iex",
) -> dict[str, list[dict[str, Any]]]:
    """Read fixed-host Alpaca bars with GET only; never expose credential values."""
    if timeframe not in TIMEFRAME_POLICY:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    clean_symbols = sorted({str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()})
    if not clean_symbols or len(clean_symbols) > 50:
        raise ValueError("symbol count must be between 1 and 50")
    if feed not in {"iex", "sip"}:
        raise ValueError("feed must be iex or sip")
    if not api_key or not api_secret:
        raise RuntimeError("existing Alpaca market-data credentials are unavailable")

    lookback = timedelta(days=540 if timeframe == "1Day" else 120)
    params: dict[str, Any] = {
        "symbols": ",".join(clean_symbols),
        "timeframe": timeframe,
        "start": _iso(now - lookback),
        "end": _iso(now),
        "limit": 10000,
        "adjustment": "all",
        "feed": feed,
        "sort": "asc",
    }
    headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}
    output: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in clean_symbols}
    next_page_token: str | None = None
    for _ in range(5):
        if next_page_token:
            params["page_token"] = next_page_token
        response = requests.get(
            ALPACA_DATA_ORIGIN + ALPACA_BARS_PATH,
            params=params,
            headers=headers,
            timeout=(5, 20),
        )
        if response.status_code != 200:
            raise RuntimeError(f"Alpaca market-data GET failed with HTTP {response.status_code}")
        payload = response.json()
        for symbol, bars in (payload.get("bars") or {}).items():
            if symbol in output and isinstance(bars, list):
                output[symbol].extend(
                    {"timestamp": row.get("t"), "close": row.get("c")}
                    for row in bars
                    if isinstance(row, dict)
                )
        next_page_token = payload.get("next_page_token")
        if not next_page_token:
            break
    return output


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, path)
    finally:
        try:
            Path(temporary_name).unlink(missing_ok=True)
        except OSError:
            pass


def _load_input(path: Path) -> dict[str, Sequence[Mapping[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    bars = payload.get("bars") if isinstance(payload, dict) else None
    if not isinstance(bars, dict):
        raise ValueError("input must contain a bars object keyed by symbol")
    return bars


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeframe", choices=tuple(TIMEFRAME_POLICY), default="1Day")
    parser.add_argument("--feed", choices=("iex", "sip"), default="iex")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)

    if args.input:
        bars = _load_input(args.input)
        source_label = f"completed_bars_file:{args.input.name}"
    else:
        load_dotenv(ROOT / "agent" / ".env", override=False)
        bars = fetch_alpaca_completed_bars(
            (symbol for spec in DEFAULT_PAIR_SPECS for symbol in (spec.left, spec.right)),
            timeframe=args.timeframe,
            now=now,
            api_key=os.getenv("APCA_API_KEY_ID", ""),
            api_secret=os.getenv("APCA_API_SECRET_KEY", ""),
            feed=args.feed,
        )
        source_label = f"alpaca_{args.feed}_completed_bars"
    report = build_report(bars, timeframe=args.timeframe, now=now, source_label=source_label)
    _atomic_json(args.output, report)
    if args.print_report:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            "pairs_relative_value "
            f"timeframe={args.timeframe} entry_ready={report['summary']['entry_ready_count']} "
            f"watch={report['summary']['watch_count']} blocked={report['summary']['blocked_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
