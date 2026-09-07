"""Shared feature-fabric schemas with a dependency-light validation surface.

Pandera models are exposed when Pandera is installed. The manual validators are
always active so missing optional packages can never turn validation into a
silent pass.
"""
from __future__ import annotations

import json
import math
from typing import Any, Iterable, Mapping

import pandas as pd


class ContractError(ValueError):
    pass


OHLCV_COLUMNS = ("ticker", "timestamp", "open", "high", "low", "close", "volume")
SCANNER_COLUMNS = ("ticker", "ts", "scanner_id", "score", "side", "features_json")


def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def validate_ohlcv(rows: Iterable[Mapping[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))
    missing = [name for name in OHLCV_COLUMNS if name not in frame.columns]
    if missing:
        raise ContractError(f"ohlcv_missing_columns:{','.join(missing)}")
    if frame.empty:
        raise ContractError("ohlcv_empty")
    if frame["ticker"].isna().any() or frame["ticker"].astype(str).str.strip().eq("").any():
        raise ContractError("ohlcv_invalid_ticker")
    stamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    if stamps.isna().any() or frame.assign(_t=stamps).duplicated(["ticker", "_t"]).any():
        raise ContractError("ohlcv_invalid_or_duplicate_timestamp")
    numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or not numeric.map(_finite).all().all():
        raise ContractError("ohlcv_non_finite")
    if (numeric[["open", "high", "low", "close"]] <= 0).any().any() or (numeric["volume"] < 0).any():
        raise ContractError("ohlcv_non_positive_price_or_negative_volume")
    if (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1)).any() or (numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)).any():
        raise ContractError("ohlcv_impossible_range")
    output = frame.copy()
    output["timestamp"] = stamps
    output[list(numeric.columns)] = numeric
    return output.sort_values(["ticker", "timestamp"]).reset_index(drop=True)


def validate_scanner_output(rows: Iterable[Mapping[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))
    missing = [name for name in SCANNER_COLUMNS if name not in frame.columns]
    if missing:
        raise ContractError(f"scanner_missing_columns:{','.join(missing)}")
    if frame.empty:
        return frame
    stamps = pd.to_datetime(frame["ts"], utc=True, errors="coerce")
    scores = pd.to_numeric(frame["score"], errors="coerce")
    if stamps.isna().any() or scores.isna().any() or ((scores < 0) | (scores > 1)).any():
        raise ContractError("scanner_invalid_timestamp_or_score")
    if not frame["side"].astype(str).str.upper().isin({"LONG", "SHORT", "ABSTAIN"}).all():
        raise ContractError("scanner_invalid_side")
    for raw in frame["features_json"]:
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError as exc:
            raise ContractError("scanner_invalid_features_json") from exc
        if not isinstance(value, dict):
            raise ContractError("scanner_features_not_object")
    output = frame.copy()
    output["ts"], output["score"] = stamps, scores
    return output


try:  # Optional typed documentation surface.
    import pandera.pandas as pa
    from pandera.typing import Series

    class OHLCVBar(pa.DataFrameModel):
        ticker: Series[str]
        timestamp: Series[pd.Timestamp]
        open: Series[float] = pa.Field(gt=0)
        high: Series[float] = pa.Field(gt=0)
        low: Series[float] = pa.Field(gt=0)
        close: Series[float] = pa.Field(gt=0)
        volume: Series[float] = pa.Field(ge=0)

    class ScannerOutput(pa.DataFrameModel):
        ticker: Series[str]
        ts: Series[pd.Timestamp]
        scanner_id: Series[str]
        score: Series[float] = pa.Field(ge=0, le=1)
        side: Series[str] = pa.Field(isin=["LONG", "SHORT", "ABSTAIN"])
        features_json: Series[str]
except ImportError:  # Manual validation above remains mandatory.
    OHLCVBar = ScannerOutput = None
