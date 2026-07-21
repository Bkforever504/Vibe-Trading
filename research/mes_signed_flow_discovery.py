#!/usr/bin/env python3
"""Outcome-blind MES signed-flow feature validation.

This is Phase A of the protocol frozen in
research/MES_SIGNED_FLOW_ABSORPTION_DISCOVERY_2026-07-21.md. It reports only
data quality and contemporaneous feature distributions. It must not calculate
future returns, trade outcomes, or strategy P&L.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TRADES = ROOT / "data" / "databento" / "mes_v0_trades_2025q4.parquet"
QUOTES = ROOT / "data" / "databento" / "mes_v0_bbo1s_rth.parquet"
OHLC_MANIFEST = ROOT / "data" / "databento_futures_manifest.json"
WINDOWS = ROOT / "data" / "databento" / "mes_signed_flow_windows_2025q4.parquet"
REPORT = ROOT / "data" / "mes_signed_flow_discovery.json"

MIN_COMPLETE_SESSIONS = 40
MIN_QUOTE_MATCH_RATE = 0.95
MIN_SIGNED_VOLUME_RATE = 0.90
MAX_QUOTE_AGE_SECONDS = 2.0
DEGRADED_SESSION = "2025-11-28"
FORBIDDEN_REPORT_KEYS = ("return", "pnl", "profit", "target", "stop", "future", "outcome")


def excluded_sessions() -> set[str]:
    manifest = json.loads(OHLC_MANIFEST.read_text(encoding="utf-8"))
    result = manifest["results"][0]
    excluded = set(result.get("roll_sessions_excluded", []))
    excluded.update(result.get("dataset_condition_dates_excluded", {}).keys())
    excluded.add(DEGRADED_SESSION)
    return {date for date in excluded if "2025-10-01" <= date < "2026-01-01"}


def classify_sign(price: float, bid: float, ask: float, prior_sign: int = 0) -> int:
    """Classify one matched print using quote test then prior-tick carry."""
    if price >= ask:
        return 1
    if price <= bid:
        return -1
    return prior_sign if prior_sign in (-1, 1) else 0


def quality_gates(*, sessions: int, quote_match_rate: float, signed_volume_rate: float) -> dict[str, Any]:
    gates = {
        "complete_sessions": sessions >= MIN_COMPLETE_SESSIONS,
        "quote_match_rate": quote_match_rate >= MIN_QUOTE_MATCH_RATE,
        "signed_volume_rate": signed_volume_rate >= MIN_SIGNED_VOLUME_RATE,
        "excluded_sessions_removed": True,
    }
    return {**gates, "all_pass": all(gates.values())}


def validate_outcome_blind(report: dict[str, Any]) -> None:
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                lowered = str(key).lower()
                if any(term in lowered for term in FORBIDDEN_REPORT_KEYS):
                    raise ValueError(f"Phase A report contains forbidden key: {key}")
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(report)


def _sql_dates(dates: set[str]) -> str:
    return ", ".join(f"DATE '{date}'" for date in sorted(dates))


def _quantiles(connection: Any, column: str) -> dict[str, float | None]:
    values = connection.execute(
        f"""
        SELECT
          quantile_cont({column}, 0.10), quantile_cont({column}, 0.25),
          quantile_cont({column}, 0.50), quantile_cont({column}, 0.75),
          quantile_cont({column}, 0.90), quantile_cont({column}, 0.95),
          avg({column}), stddev_samp({column})
        FROM windows
        """
    ).fetchone()
    keys = ("p10", "p25", "p50", "p75", "p90", "p95", "mean", "stddev")
    return {key: None if value is None else round(float(value), 6) for key, value in zip(keys, values)}


def run_phase_a() -> dict[str, Any]:
    import duckdb

    if not TRADES.exists() or not QUOTES.exists():
        raise FileNotFoundError("Trade and BBO parquet caches are required")

    exclusions = excluded_sessions()
    exclusion_sql = _sql_dates(exclusions)
    connection = duckdb.connect()
    connection.execute("SET TimeZone='America/New_York'")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute(
        f"""
        CREATE TEMP TABLE trades_rth AS
        SELECT
          ts_recv,
          timezone('America/New_York', ts_recv) AS local_ts,
          CAST(timezone('America/New_York', ts_recv) AS DATE) AS session_date,
          instrument_id,
          price,
          CAST(size AS BIGINT) AS size
        FROM read_parquet('{TRADES.as_posix()}')
        WHERE CAST(timezone('America/New_York', ts_recv) AS DATE)
                  NOT IN ({exclusion_sql})
          AND CAST(timezone('America/New_York', ts_recv) AS TIME)
                  >= TIME '09:35:00'
          AND CAST(timezone('America/New_York', ts_recv) AS TIME)
                  < TIME '15:30:00'
          AND dayofweek(timezone('America/New_York', ts_recv)) BETWEEN 1 AND 5;

        CREATE TEMP TABLE quotes_rth AS
        SELECT ts_recv, instrument_id, bid_px_00 AS bid, ask_px_00 AS ask
        FROM read_parquet('{QUOTES.as_posix()}')
        WHERE CAST(timezone('America/New_York', ts_recv) AS DATE)
                  NOT IN ({exclusion_sql})
          AND CAST(timezone('America/New_York', ts_recv) AS TIME)
                  >= TIME '09:34:58'
          AND CAST(timezone('America/New_York', ts_recv) AS TIME)
                  < TIME '15:30:00'
          AND bid_px_00 > 0 AND ask_px_00 > bid_px_00;

        CREATE TEMP TABLE joined AS
        SELECT
          t.*,
          q.ts_recv AS quote_ts,
          q.bid,
          q.ask,
          epoch(t.ts_recv - q.ts_recv) AS quote_age_seconds,
          CASE
            WHEN q.ts_recv IS NULL OR epoch(t.ts_recv - q.ts_recv) > {MAX_QUOTE_AGE_SECONDS} THEN NULL
            WHEN t.price >= q.ask THEN 1
            WHEN t.price <= q.bid THEN -1
            ELSE NULL
          END AS raw_sign
        FROM trades_rth t
        ASOF LEFT JOIN quotes_rth q
          ON t.instrument_id = q.instrument_id AND t.ts_recv >= q.ts_recv;

        CREATE TEMP TABLE signed AS
        SELECT
          *,
          CASE
            WHEN quote_ts IS NULL OR quote_age_seconds > {MAX_QUOTE_AGE_SECONDS} THEN 0
            ELSE COALESCE(
              raw_sign,
              last_value(raw_sign IGNORE NULLS) OVER (
                PARTITION BY session_date ORDER BY ts_recv
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
              ),
              0
            )
          END AS trade_sign
        FROM joined;

        CREATE TEMP TABLE windows AS
        SELECT
          session_date,
          date_trunc('minute', local_ts) AS window_start,
          sum(CASE WHEN trade_sign = 1 THEN size ELSE 0 END) AS aggressive_buy_volume,
          sum(CASE WHEN trade_sign = -1 THEN size ELSE 0 END) AS aggressive_sell_volume,
          sum(CASE WHEN trade_sign != 0 THEN size ELSE 0 END) AS total_aggressive_volume,
          CASE WHEN sum(CASE WHEN trade_sign != 0 THEN size ELSE 0 END) > 0
            THEN sum(trade_sign * size)::DOUBLE /
                 sum(CASE WHEN trade_sign != 0 THEN size ELSE 0 END)
            ELSE 0 END AS signed_imbalance,
          last((bid + ask) / 2 ORDER BY ts_recv) -
            first((bid + ask) / 2 ORDER BY ts_recv) AS mid_displacement,
          count(*) AS print_count,
          sum(size) AS print_volume,
          avg(CASE WHEN quote_ts IS NOT NULL AND quote_age_seconds <= {MAX_QUOTE_AGE_SECONDS}
                   THEN 1.0 ELSE 0.0 END) AS quote_match_rate
        FROM signed
        GROUP BY session_date, date_trunc('minute', local_ts);
        """
    )

    WINDOWS.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(f"COPY windows TO '{WINDOWS.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")

    counts = connection.execute(
        f"""
        SELECT
          count(*) AS prints,
          count(DISTINCT session_date) AS sessions,
          avg(CASE WHEN quote_ts IS NOT NULL AND quote_age_seconds <= {MAX_QUOTE_AGE_SECONDS}
                   THEN 1.0 ELSE 0.0 END) AS match_rate,
          sum(CASE WHEN quote_ts IS NOT NULL AND quote_age_seconds <= {MAX_QUOTE_AGE_SECONDS}
                   THEN size ELSE 0 END) AS matched_volume,
          sum(CASE WHEN trade_sign != 0 THEN size ELSE 0 END) AS signed_volume
        FROM signed
        """
    ).fetchone()
    complete_sessions = connection.execute(
        """
        SELECT count(*) FROM (
          SELECT session_date
          FROM windows
          GROUP BY session_date
          HAVING min(CAST(window_start AS TIME)) <= TIME '09:36:00'
             AND max(CAST(window_start AS TIME)) >= TIME '15:28:00'
             AND count(*) >= 330
        )
        """
    ).fetchone()[0]
    matched_volume = int(counts[3] or 0)
    signed_volume = int(counts[4] or 0)
    quote_match_rate = float(counts[2] or 0.0)
    signed_volume_rate = signed_volume / matched_volume if matched_volume else 0.0

    report = {
        "protocol": "MES_SIGNED_FLOW_ABSORPTION_DISCOVERY_2026-07-21",
        "phase": "A_outcome_blind",
        "routing_authority": False,
        "source": {
            "dataset": "GLBX.MDP3",
            "schema": "trades_joined_to_bbo-1s",
            "symbol": "MES.v.0",
            "start": "2025-10-01",
            "end": "2026-01-01",
            "excluded_sessions": sorted(exclusions),
        },
        "coverage": {
            "prints": int(counts[0]),
            "observed_sessions": int(counts[1]),
            "complete_sessions": int(complete_sessions),
            "windows": int(connection.execute("SELECT count(*) FROM windows").fetchone()[0]),
            "quote_match_rate": round(quote_match_rate, 6),
            "matched_volume": matched_volume,
            "signed_volume": signed_volume,
            "signed_volume_rate": round(signed_volume_rate, 6),
        },
        "feature_distributions": {
            "total_aggressive_volume": _quantiles(connection, "total_aggressive_volume"),
            "absolute_signed_imbalance": _quantiles(connection, "abs(signed_imbalance)"),
            "absolute_mid_displacement": _quantiles(connection, "abs(mid_displacement)"),
            "print_count": _quantiles(connection, "print_count"),
            "window_quote_match_rate": _quantiles(connection, "quote_match_rate"),
        },
        "quality_gates": quality_gates(
            sessions=int(complete_sessions),
            quote_match_rate=quote_match_rate,
            signed_volume_rate=signed_volume_rate,
        ),
        "next_boundary": "freeze_phase_b_before_opening_strategy_results",
    }
    validate_outcome_blind(report)
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    print(json.dumps(run_phase_a(), indent=2))


if __name__ == "__main__":
    main()
