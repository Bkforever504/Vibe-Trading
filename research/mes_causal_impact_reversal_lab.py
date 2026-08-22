#!/usr/bin/env python3
"""Preregistered MES causal impact-replenishment divergence diagnostic.

Research only. This module has no broker client and cannot submit orders.
"""
from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
RAW_QUOTES = ROOT / "data" / "databento" / "mes_v0_bbo1s_rth.parquet"
SECOND_CACHE = ROOT / "data" / "databento" / "mes_bbo_valid_1s_2024_2026.parquet"
FEATURE_CACHE = ROOT / "data" / "databento" / "mes_bbo_ofi_30s_2024_2026.parquet"
MANIFEST = ROOT / "data" / "databento_futures_manifest.json"
OUTPUT = ROOT / "data" / "mes_causal_impact_reversal_results.json"
PREREGISTRATION = "research/MES_CAUSAL_IMPACT_REVERSAL_PREREGISTRATION_2026-08-10.md"

TICK = 0.25
POINT_USD = 5.0
BASE_COMMISSION = 2.48
STRESS_COMMISSION = 4.96
MAX_RAW_SPREAD = 4 * TICK
ROLLING_BUCKETS = 60
Z_THRESHOLD = 2.5
MIN_EXPECTED_MOVE = 0.50
MAX_REALIZED_FRACTION = 0.25
OPPOSING_QUOTE_IMBALANCE = 0.10
CONFIRM_SECONDS = 10
CONFIRM_MOVE = TICK
MAX_CONFIRM_EXTENSION = 2 * TICK
TARGET_TICKS = 12
STOP_TICKS = 8
HOLD_SECONDS = 300
MAX_TRADES_DAY = 2
MIN_COMPLETE_BUCKETS = 700


@dataclass(frozen=True)
class Candidate:
    candidate_id: int
    session_date: str
    instrument_id: int
    signal_ts: str
    entry_ts: str
    direction: int
    entry_bid: float
    entry_ask: float
    flow_z: float
    expected_move: float
    realized_fraction: float
    ending_quote_imbalance: float


@dataclass(frozen=True)
class Trade:
    session_date: str
    entry_ts: str
    exit_ts: str
    direction: int
    exit_reason: str
    base_pnl: float
    stress_pnl: float


def cont_ofi(
    *,
    bid: float,
    bid_size: float,
    ask: float,
    ask_size: float,
    previous_bid: float,
    previous_bid_size: float,
    previous_ask: float,
    previous_ask_size: float,
) -> float:
    """Cont-style top-of-book order-flow imbalance for one quote update."""
    bid_flow = (bid_size if bid >= previous_bid else 0.0) - (
        previous_bid_size if bid <= previous_bid else 0.0
    )
    ask_flow = (ask_size if ask <= previous_ask else 0.0) - (
        previous_ask_size if ask >= previous_ask else 0.0
    )
    return float(bid_flow - ask_flow)


def qualifies_impact_failure(
    *,
    flow_z: float,
    beta: float,
    expected_move: float,
    realized_fraction: float,
    flow_sign: int,
    quote_imbalance: float,
    spread: float,
) -> bool:
    return bool(
        flow_sign in (-1, 1)
        and beta > 0
        and abs(flow_z) >= Z_THRESHOLD
        and abs(expected_move) >= MIN_EXPECTED_MOVE
        and 0 <= realized_fraction <= MAX_REALIZED_FRACTION
        and flow_sign * quote_imbalance <= -OPPOSING_QUOTE_IMBALANCE
        and 0 < spread <= TICK + 1e-9
    )


def confirmation_passes(
    *,
    flow_sign: int,
    signal_mid: float,
    confirm_mid: float,
    adverse_extreme_mid: float,
    confirm_quote_imbalance: float,
    entry_spread: float,
) -> bool:
    opposite_move = flow_sign * (confirm_mid - signal_mid)
    adverse_extension = flow_sign * (adverse_extreme_mid - signal_mid)
    return bool(
        opposite_move <= -CONFIRM_MOVE
        and adverse_extension <= MAX_CONFIRM_EXTENSION
        and flow_sign * confirm_quote_imbalance <= 0
        and 0 < entry_spread <= TICK + 1e-9
    )


def _excluded_sessions() -> set[str]:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    result = payload["results"][0]
    excluded = set(result.get("roll_sessions_excluded", []))
    excluded.update(result.get("dataset_condition_dates_excluded", {}).keys())
    return {value for value in excluded if value >= "2024-01-01"}


def _date_sql(values: Iterable[str]) -> str:
    return ", ".join(f"DATE '{value}'" for value in sorted(values)) or "DATE '1900-01-01'"


def build_feature_caches(*, force: bool = False) -> None:
    import duckdb

    if not RAW_QUOTES.exists():
        raise FileNotFoundError(RAW_QUOTES)
    exclusions = _date_sql(_excluded_sessions())
    connection = duckdb.connect()
    connection.execute("SET TimeZone='America/New_York'")
    connection.execute("SET preserve_insertion_order=false")

    if force or not SECOND_CACHE.exists():
        SECOND_CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SECOND_CACHE.with_suffix(".tmp.parquet")
        tmp.unlink(missing_ok=True)
        connection.execute(
            f"""
            COPY (
              WITH valid AS (
                SELECT
                  timezone('America/New_York', ts_recv) AS local_ts,
                  CAST(timezone('America/New_York', ts_recv) AS DATE) AS session_date,
                  instrument_id,
                  ts_recv,
                  bid_px_00 AS bid,
                  ask_px_00 AS ask,
                  CAST(bid_sz_00 AS DOUBLE) AS bid_size,
                  CAST(ask_sz_00 AS DOUBLE) AS ask_size
                FROM read_parquet('{RAW_QUOTES.as_posix()}')
                WHERE ts_recv IS NOT NULL
                  AND CAST(timezone('America/New_York', ts_recv) AS DATE) >= DATE '2024-01-01'
                  AND CAST(timezone('America/New_York', ts_recv) AS DATE) NOT IN ({exclusions})
                  AND dayofweek(timezone('America/New_York', ts_recv)) BETWEEN 1 AND 5
                  AND CAST(timezone('America/New_York', ts_recv) AS TIME) >= TIME '09:35:00'
                  AND CAST(timezone('America/New_York', ts_recv) AS TIME) < TIME '15:30:00'
                  AND bid_px_00 > 0 AND ask_px_00 > bid_px_00
                  AND ask_px_00 - bid_px_00 <= {MAX_RAW_SPREAD}
                  AND bid_sz_00 > 0 AND ask_sz_00 > 0
              )
              SELECT
                session_date,
                instrument_id,
                date_trunc('second', local_ts) AS local_ts,
                arg_max(bid, ts_recv) AS bid,
                arg_max(ask, ts_recv) AS ask,
                arg_max(bid_size, ts_recv) AS bid_size,
                arg_max(ask_size, ts_recv) AS ask_size
              FROM valid
              GROUP BY session_date, instrument_id, date_trunc('second', local_ts)
            ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        tmp.replace(SECOND_CACHE)

    if force or not FEATURE_CACHE.exists():
        tmp = FEATURE_CACHE.with_suffix(".tmp.parquet")
        tmp.unlink(missing_ok=True)
        connection.execute(
            f"""
            COPY (
              WITH lagged AS (
                SELECT
                  *,
                  lag(bid) OVER w AS previous_bid,
                  lag(ask) OVER w AS previous_ask,
                  lag(bid_size) OVER w AS previous_bid_size,
                  lag(ask_size) OVER w AS previous_ask_size
                FROM read_parquet('{SECOND_CACHE.as_posix()}')
                WINDOW w AS (
                  PARTITION BY session_date, instrument_id ORDER BY local_ts
                )
              ), events AS (
                SELECT
                  *,
                  (bid + ask) / 2.0 AS mid,
                  time_bucket(INTERVAL '30 seconds', local_ts) AS bucket_start,
                  CASE WHEN previous_bid IS NULL THEN 0.0 ELSE
                    (CASE WHEN bid >= previous_bid THEN bid_size ELSE 0.0 END)
                    - (CASE WHEN bid <= previous_bid THEN previous_bid_size ELSE 0.0 END)
                    - (CASE WHEN ask <= previous_ask THEN ask_size ELSE 0.0 END)
                    + (CASE WHEN ask >= previous_ask THEN previous_ask_size ELSE 0.0 END)
                  END AS ofi
                FROM lagged
              )
              SELECT
                session_date,
                instrument_id,
                bucket_start,
                first(mid ORDER BY local_ts) AS start_mid,
                last(mid ORDER BY local_ts) AS end_mid,
                last(bid ORDER BY local_ts) AS end_bid,
                last(ask ORDER BY local_ts) AS end_ask,
                last(bid_size ORDER BY local_ts) AS end_bid_size,
                last(ask_size ORDER BY local_ts) AS end_ask_size,
                sum(ofi) AS ofi,
                avg(bid_size + ask_size) AS average_depth,
                count(*) AS quote_seconds,
                last(local_ts ORDER BY local_ts) FILTER (
                  WHERE epoch(local_ts - bucket_start) < {CONFIRM_SECONDS}
                ) AS first10_end_ts,
                last(mid ORDER BY local_ts) FILTER (
                  WHERE epoch(local_ts - bucket_start) < {CONFIRM_SECONDS}
                ) AS first10_end_mid,
                min(mid) FILTER (
                  WHERE epoch(local_ts - bucket_start) < {CONFIRM_SECONDS}
                ) AS first10_min_mid,
                max(mid) FILTER (
                  WHERE epoch(local_ts - bucket_start) < {CONFIRM_SECONDS}
                ) AS first10_max_mid,
                last(bid ORDER BY local_ts) FILTER (
                  WHERE epoch(local_ts - bucket_start) < {CONFIRM_SECONDS}
                ) AS first10_end_bid,
                last(ask ORDER BY local_ts) FILTER (
                  WHERE epoch(local_ts - bucket_start) < {CONFIRM_SECONDS}
                ) AS first10_end_ask,
                last(bid_size ORDER BY local_ts) FILTER (
                  WHERE epoch(local_ts - bucket_start) < {CONFIRM_SECONDS}
                ) AS first10_end_bid_size,
                last(ask_size ORDER BY local_ts) FILTER (
                  WHERE epoch(local_ts - bucket_start) < {CONFIRM_SECONDS}
                ) AS first10_end_ask_size
              FROM events
              GROUP BY session_date, instrument_id, bucket_start
              HAVING count(*) >= 20
            ) TO '{tmp.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)
            """
        )
        tmp.replace(FEATURE_CACHE)
    connection.close()


def _eligible_sessions(connection: Any) -> list[str]:
    rows = connection.execute(
        f"""
        SELECT session_date
        FROM read_parquet('{FEATURE_CACHE.as_posix()}')
        GROUP BY session_date
        HAVING count(*) >= {MIN_COMPLETE_BUCKETS}
           AND count(DISTINCT instrument_id) = 1
        ORDER BY session_date
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def _candidate_rows(connection: Any, eligible: list[str]) -> list[Candidate]:
    if not eligible:
        return []
    eligible_sql = _date_sql(eligible)
    rows = connection.execute(
        f"""
        WITH base AS (
          SELECT
            *,
            ofi / nullif(average_depth, 0) AS x,
            end_mid - start_mid AS y,
            (end_bid_size - end_ask_size) /
              nullif(end_bid_size + end_ask_size, 0) AS quote_imbalance,
            end_ask - end_bid AS spread
          FROM read_parquet('{FEATURE_CACHE.as_posix()}')
          WHERE session_date IN ({eligible_sql})
        ), rolling_stats AS (
          SELECT
            *,
            count(*) OVER w AS history_count,
            avg(x) OVER w AS x_mean,
            stddev_samp(x) OVER w AS x_std,
            sum(x * y) OVER w / nullif(sum(x * x) OVER w, 0) AS beta
          FROM base
          WINDOW w AS (
            PARTITION BY session_date, instrument_id ORDER BY bucket_start
            ROWS BETWEEN {ROLLING_BUCKETS} PRECEDING AND 1 PRECEDING
          )
        ), scored AS (
          SELECT
            *,
            (x - x_mean) / nullif(x_std, 0) AS flow_z,
            beta * x AS expected_move,
            sign(x)::INTEGER AS flow_sign,
            sign(x) * y / nullif(abs(beta * x), 0) AS realized_fraction
          FROM rolling_stats
        ), failures AS (
          SELECT *
          FROM scored
          WHERE history_count = {ROLLING_BUCKETS}
            AND beta > 0
            AND abs(flow_z) >= {Z_THRESHOLD}
            AND abs(expected_move) >= {MIN_EXPECTED_MOVE}
            AND realized_fraction BETWEEN 0 AND {MAX_REALIZED_FRACTION}
            AND flow_sign * quote_imbalance <= -{OPPOSING_QUOTE_IMBALANCE}
            AND spread > 0 AND spread <= {TICK}
            AND CAST(bucket_start AS TIME) >= TIME '10:05:00'
            AND CAST(bucket_start AS TIME) < TIME '15:20:00'
        ), confirmed AS (
          SELECT
            f.*,
            n.first10_end_ts AS entry_ts,
            n.first10_end_mid AS confirm_mid,
            CASE WHEN f.flow_sign > 0
              THEN n.first10_max_mid ELSE n.first10_min_mid END AS adverse_extreme_mid,
            n.first10_end_bid AS entry_bid,
            n.first10_end_ask AS entry_ask,
            (n.first10_end_bid_size - n.first10_end_ask_size) /
              nullif(n.first10_end_bid_size + n.first10_end_ask_size, 0)
              AS confirm_quote_imbalance
          FROM failures f
          JOIN base n
            ON n.session_date = f.session_date
           AND n.instrument_id = f.instrument_id
           AND n.bucket_start = f.bucket_start + INTERVAL '30 seconds'
        )
        SELECT
          row_number() OVER (ORDER BY session_date, entry_ts) AS candidate_id,
          session_date,
          instrument_id,
          bucket_start + INTERVAL '30 seconds' AS signal_ts,
          entry_ts,
          -flow_sign AS direction,
          entry_bid,
          entry_ask,
          flow_z,
          expected_move,
          realized_fraction,
          quote_imbalance
        FROM confirmed
        WHERE flow_sign * (confirm_mid - end_mid) <= -{CONFIRM_MOVE}
          AND flow_sign * (adverse_extreme_mid - end_mid) <= {MAX_CONFIRM_EXTENSION}
          AND flow_sign * confirm_quote_imbalance <= 0
          AND entry_ask - entry_bid > 0
          AND entry_ask - entry_bid <= {TICK}
        ORDER BY session_date, entry_ts
        """
    ).fetchall()
    return [
        Candidate(
            candidate_id=int(row[0]),
            session_date=str(row[1]),
            instrument_id=int(row[2]),
            signal_ts=str(row[3]),
            entry_ts=str(row[4]),
            direction=int(row[5]),
            entry_bid=float(row[6]),
            entry_ask=float(row[7]),
            flow_z=float(row[8]),
            expected_move=float(row[9]),
            realized_fraction=float(row[10]),
            ending_quote_imbalance=float(row[11]),
        )
        for row in rows
    ]


def _fetch_paths(connection: Any, candidates: list[Candidate]) -> dict[int, list[tuple[str, float, float]]]:
    if not candidates:
        return {}
    connection.execute(
        """CREATE OR REPLACE TEMP TABLE stage_candidates(
        candidate_id BIGINT, session_date DATE, instrument_id BIGINT,
        entry_ts TIMESTAMP
        )"""
    )
    connection.executemany(
        "INSERT INTO stage_candidates VALUES (?, CAST(? AS DATE), ?, CAST(? AS TIMESTAMP))",
        [(c.candidate_id, c.session_date, c.instrument_id, c.entry_ts) for c in candidates],
    )
    rows = connection.execute(
        f"""
        SELECT c.candidate_id, q.local_ts, q.bid, q.ask
        FROM stage_candidates c
        JOIN read_parquet('{SECOND_CACHE.as_posix()}') q
          ON q.session_date = c.session_date
         AND q.instrument_id = c.instrument_id
         AND q.local_ts > c.entry_ts
         AND q.local_ts <= c.entry_ts + INTERVAL {HOLD_SECONDS} SECOND
        ORDER BY c.candidate_id, q.local_ts
        """
    ).fetchall()
    paths: dict[int, list[tuple[str, float, float]]] = defaultdict(list)
    for candidate_id, timestamp, bid, ask in rows:
        paths[int(candidate_id)].append((str(timestamp), float(bid), float(ask)))
    return dict(paths)


def simulate_trade(candidate: Candidate, path: list[tuple[str, float, float]]) -> Trade | None:
    if not path:
        return None
    entry = candidate.entry_ask if candidate.direction > 0 else candidate.entry_bid
    target = entry + candidate.direction * TARGET_TICKS * TICK
    stop = entry - candidate.direction * STOP_TICKS * TICK
    exit_ts, exit_price, reason = path[-1][0], None, "time"
    for timestamp, bid, ask in path:
        if candidate.direction > 0:
            if bid <= stop:
                exit_ts, exit_price, reason = timestamp, min(bid, stop), "stop"
                break
            if bid >= target:
                exit_ts, exit_price, reason = timestamp, target, "target"
                break
        else:
            if ask >= stop:
                exit_ts, exit_price, reason = timestamp, max(ask, stop), "stop"
                break
            if ask <= target:
                exit_ts, exit_price, reason = timestamp, target, "target"
                break
    if exit_price is None:
        exit_price = path[-1][1] if candidate.direction > 0 else path[-1][2]
    gross = candidate.direction * (exit_price - entry) * POINT_USD
    base = gross - BASE_COMMISSION
    stress = gross - (2 * TICK * POINT_USD) - STRESS_COMMISSION
    return Trade(
        session_date=candidate.session_date,
        entry_ts=candidate.entry_ts,
        exit_ts=exit_ts,
        direction=candidate.direction,
        exit_reason=reason,
        base_pnl=round(base, 4),
        stress_pnl=round(stress, 4),
    )


def _non_overlapping_trades(
    candidates: list[Candidate], paths: dict[int, list[tuple[str, float, float]]]
) -> list[Trade]:
    trades: list[Trade] = []
    count_by_day: dict[str, int] = defaultdict(int)
    busy_until: dict[str, str] = {}
    for candidate in sorted(candidates, key=lambda value: (value.session_date, value.entry_ts)):
        if count_by_day[candidate.session_date] >= MAX_TRADES_DAY:
            continue
        if candidate.entry_ts <= busy_until.get(candidate.session_date, ""):
            continue
        trade = simulate_trade(candidate, paths.get(candidate.candidate_id, []))
        if trade is None:
            continue
        trades.append(trade)
        count_by_day[candidate.session_date] += 1
        busy_until[candidate.session_date] = trade.exit_ts
    return trades


def _max_drawdown(values: list[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def metrics(trades: list[Trade], field: str) -> dict[str, Any]:
    values = [float(getattr(trade, field)) for trade in trades]
    if not values:
        return {"trades": 0}
    gains = sum(value for value in values if value > 0)
    losses = -sum(value for value in values if value <= 0)
    daily: dict[str, float] = defaultdict(float)
    for trade, value in zip(trades, values):
        daily[trade.session_date] += value
    return {
        "trades": len(values),
        "total_pnl": round(sum(values), 2),
        "expectancy": round(sum(values) / len(values), 4),
        "win_rate": round(sum(value > 0 for value in values) / len(values), 4),
        "profit_factor": round(gains / losses, 4) if losses else None,
        "max_drawdown": round(_max_drawdown(values), 2),
        "worst_day": round(min(daily.values()), 2),
        "best_day": round(max(daily.values()), 2),
    }


def _daily_values(trades: list[Trade], dates: list[str], field: str) -> list[float]:
    daily: dict[str, float] = defaultdict(float)
    for trade in trades:
        daily[trade.session_date] += float(getattr(trade, field))
    return [daily.get(date, 0.0) for date in dates]


def positive_mean_bootstrap_probability(
    daily_values: list[float], *, simulations: int = 5_000, block_size: int = 5,
    seed: int = 20260810,
) -> float:
    if not daily_values:
        return 0.0
    rng = random.Random(seed)
    positive = 0
    size = len(daily_values)
    for _ in range(simulations):
        sampled: list[float] = []
        while len(sampled) < size:
            start = rng.randrange(size)
            sampled.extend(daily_values[(start + offset) % size] for offset in range(block_size))
        if sum(sampled[:size]) > 0:
            positive += 1
    return round(positive / simulations, 4)


def _quarter_stability(trades: list[Trade], dates: list[str]) -> dict[str, Any]:
    boundaries = [round(len(dates) * index / 4) for index in range(5)]
    totals = []
    for index in range(4):
        subset = set(dates[boundaries[index]:boundaries[index + 1]])
        totals.append(round(sum(t.stress_pnl for t in trades if t.session_date in subset), 2))
    return {"stressed_subperiod_pnl": totals, "positive_subperiods": sum(value > 0 for value in totals)}


def _stage_result(trades: list[Trade], dates: list[str], *, development: bool) -> dict[str, Any]:
    base = metrics(trades, "base_pnl")
    stress = metrics(trades, "stress_pnl")
    result: dict[str, Any] = {
        "sessions": len(dates),
        "base": base,
        "stress": stress,
    }
    minimum_trades = 40 if development else 20
    common = bool(
        base.get("trades", 0) >= minimum_trades
        and base.get("expectancy", 0) > 0
        and stress.get("expectancy", 0) > 0
        and (base.get("profit_factor") or 0) >= 1.20
        and stress.get("max_drawdown", math.inf) <= 500
    )
    if development:
        stability = _quarter_stability(trades, dates)
        result["stability"] = stability
        result["pass"] = common and stability["positive_subperiods"] >= 3
    else:
        probability = positive_mean_bootstrap_probability(
            _daily_values(trades, dates, "stress_pnl")
        )
        result["positive_mean_bootstrap_probability"] = probability
        result["pass"] = common and probability >= 0.95
    return result


def _split_sessions(sessions: list[str]) -> tuple[list[str], list[str], list[str]]:
    development_end = int(len(sessions) * 0.60)
    selection_end = int(len(sessions) * 0.80)
    return (
        sessions[:development_end],
        sessions[development_end:selection_end],
        sessions[selection_end:],
    )


def _evaluate_stage(
    connection: Any, candidates: list[Candidate], dates: list[str], *, development: bool
) -> tuple[dict[str, Any], list[Trade]]:
    allowed = set(dates)
    stage_candidates = [value for value in candidates if value.session_date in allowed]
    paths = _fetch_paths(connection, stage_candidates)
    trades = _non_overlapping_trades(stage_candidates, paths)
    result = _stage_result(trades, dates, development=development)
    result["candidates"] = len(stage_candidates)
    result["exit_reasons"] = {
        reason: sum(trade.exit_reason == reason for trade in trades)
        for reason in ("target", "stop", "time")
    }
    return result, trades


def run(*, force_cache: bool = False) -> dict[str, Any]:
    import duckdb

    build_feature_caches(force=force_cache)
    connection = duckdb.connect()
    connection.execute("SET TimeZone='America/New_York'")
    sessions = _eligible_sessions(connection)
    development_dates, selection_dates, final_dates = _split_sessions(sessions)
    candidates = _candidate_rows(connection, sessions)

    development, _ = _evaluate_stage(
        connection, candidates, development_dates, development=True
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "experiment": "mes_causal_impact_replenishment_divergence",
        "preregistration": PREREGISTRATION,
        "mode": "consumed_history_diagnostic",
        "evidence_status": "not_independent_validation",
        "novelty_claim": "bespoke_repository_hypothesis_global_novelty_not_asserted",
        "execution_enabled": False,
        "can_submit_orders": False,
        "source": {
            "dataset": "GLBX.MDP3",
            "schema": "bbo_snapshot_to_cont_ofi",
            "raw_quotes": str(RAW_QUOTES),
            "first_session": sessions[0] if sessions else None,
            "last_session": sessions[-1] if sessions else None,
            "eligible_sessions": len(sessions),
        },
        "parameters": {
            "bucket_seconds": 30,
            "trailing_buckets": ROLLING_BUCKETS,
            "z_threshold": Z_THRESHOLD,
            "minimum_expected_move_points": MIN_EXPECTED_MOVE,
            "maximum_realized_fraction": MAX_REALIZED_FRACTION,
            "opposing_quote_imbalance": OPPOSING_QUOTE_IMBALANCE,
            "confirmation_seconds": CONFIRM_SECONDS,
            "target_ticks": TARGET_TICKS,
            "stop_ticks": STOP_TICKS,
            "hold_seconds": HOLD_SECONDS,
            "maximum_trades_per_day": MAX_TRADES_DAY,
        },
        "candidate_count": len(candidates),
        "split_sessions": {
            "development": len(development_dates),
            "selection": len(selection_dates),
            "final": len(final_dates),
        },
        "development": development,
        "selection_opened": False,
        "final_opened": False,
        "promotion": {
            "ready": False,
            "decision": "rejected_or_forward_shadow_only",
            "maximum_authority_if_all_historical_gates_pass": "forward_shadow_only",
        },
        "orders_submitted": 0,
    }
    if development["pass"]:
        selection, _ = _evaluate_stage(
            connection, candidates, selection_dates, development=False
        )
        report["selection_opened"] = True
        report["selection"] = selection
        if selection["pass"]:
            final, final_trades = _evaluate_stage(
                connection, candidates, final_dates, development=False
            )
            report["final_opened"] = True
            report["final"] = final
            if final["pass"]:
                from strategies.topstep_combine_simulator import (
                    CombineRules,
                    bootstrap_combine,
                )

                final_daily = _daily_values(final_trades, final_dates, "stress_pnl")
                rules = CombineRules(max_sessions=252)
                report["topstep_diagnostic"] = [
                    bootstrap_combine(
                        final_daily,
                        contracts=contracts,
                        rules=rules,
                        simulations=5_000,
                        block_size=20,
                    )
                    for contracts in (1, 2)
                ]
                report["promotion"]["decision"] = "eligible_for_frozen_forward_shadow"
    connection.close()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force-cache", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = run(force_cache=args.force_cache)
    if args.output != OUTPUT:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
