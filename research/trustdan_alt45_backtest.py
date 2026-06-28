"""
Trustdan Alt45 event backtester: Dual-Momentum Confirmation.

Source:
research/pine_sources/trustdan-trend-following/pine-scripts/
seykota_alt45_dual_momentum_confirmation.pine

Alt45 vs Alt10 differences:
  1. RSI(14) > 50 required for long entries (dual-momentum gate)
  2. Age-based profit targets instead of fixed 3N/6N/9N:
       Young  (barsInPos <= youngAge=15): 4N / 7N / 10N
       Mature (barsInPos <= matureAge=30): 3N / 6N / 9N
       Aging  (barsInPos >  matureAge):   2N / 4N / 6N

Entry, pyramiding, stop mechanics identical to Alt10:
  Donchian 55-bar breakout, 4 units max, add every 0.5N,
  2N initial stop + 22-bar chandelier (3N) trailing stop.

Research only. No live execution wiring.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from research.pine_strategy_lab import BacktestMetrics


@dataclass(frozen=True)
class Alt45Config:
    entry_len: int = 55
    n_len: int = 20
    stop_n: float = 2.0
    trail_len: int = 22
    trail_n: float = 3.0
    add_step_n: float = 0.5
    max_units: int = 4
    risk_pct: float = 1.0
    use_rsi_filter: bool = True
    rsi_len: int = 14
    rsi_long_thresh: float = 50.0
    rsi_short_thresh: float = 50.0
    use_targets: bool = True
    young_age: int = 15
    mature_age: int = 30
    young_t1: float = 4.0
    young_t2: float = 7.0
    young_t3: float = 10.0
    std_t1: float = 3.0
    std_t2: float = 6.0
    std_t3: float = 9.0
    aging_t1: float = 2.0
    aging_t2: float = 4.0
    aging_t3: float = 6.0
    allow_long: bool = True
    allow_short: bool = True
    initial_capital: float = 100_000.0
    slippage_pct: float = 0.05
    commission_pct: float = 0.01


@dataclass(frozen=True)
class ClosedLeg:
    side: int
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    qty: float
    reason: str
    pnl: float
    pnl_pct: float


@dataclass(frozen=True)
class Alt45Result:
    metrics: BacktestMetrics
    equity_curve: pd.Series
    closed_legs: list[ClosedLeg]


@dataclass
class _Unit:
    side: int
    qty: float
    entry_price: float
    entry_date: str


def run_alt45_on_ohlcv(ohlcv: pd.DataFrame, config: Alt45Config = Alt45Config()) -> Alt45Result:
    df = _normalize_ohlcv(ohlcv)
    atr = _atr(df, config.n_len)
    rsi = _rsi(df["close"], config.rsi_len)
    don_hi_prev = df["high"].rolling(config.entry_len).max().shift(1)
    don_lo_prev = df["low"].rolling(config.entry_len).min().shift(1)
    trail_high = df["high"].rolling(config.trail_len).max()
    trail_low = df["low"].rolling(config.trail_len).min()

    realized = 0.0
    units: list[_Unit] = []
    n_entry: float | None = None
    entry_price: float | None = None
    last_add_long: float | None = None
    last_add_short: float | None = None
    targets_hit = [False, False, False]
    bars_in_pos = 0
    closed: list[ClosedLeg] = []
    equity_values: list[float] = []

    for ts, row in df.iterrows():
        close = float(row["close"])
        high = float(row["high"])
        low = float(row["low"])
        date = str(ts.date()) if hasattr(ts, "date") else str(ts)
        equity = config.initial_capital + realized + _unrealized(units, close)

        if units and n_entry and entry_price:
            bars_in_pos += 1
            side = units[0].side
            t1n, t2n, t3n = _age_targets(bars_in_pos, config)

            if side > 0:
                while (
                    len(units) < config.max_units
                    and last_add_long is not None
                    and high >= last_add_long + config.add_step_n * n_entry
                ):
                    qty = _unit_qty(equity, n_entry, config)
                    units.append(_Unit(1, qty, close, date))
                    last_add_long = close
                if config.use_targets:
                    realized += _hit_long_targets(
                        units, high, entry_price, n_entry,
                        targets_hit, date, closed, config, t1n, t2n, t3n,
                    )
                if units and _long_stop_hit(low, trail_high.loc[ts], n_entry, units, config):
                    stop = max(
                        _avg_entry(units) - config.stop_n * n_entry,
                        float(trail_high.loc[ts]) - config.trail_n * n_entry,
                    )
                    realized += _close_all(units, stop, date, "chandelier_stop", closed, config)
            else:
                while (
                    len(units) < config.max_units
                    and last_add_short is not None
                    and low <= last_add_short - config.add_step_n * n_entry
                ):
                    qty = _unit_qty(equity, n_entry, config)
                    units.append(_Unit(-1, qty, close, date))
                    last_add_short = close
                if config.use_targets:
                    realized += _hit_short_targets(
                        units, low, entry_price, n_entry,
                        targets_hit, date, closed, config, t1n, t2n, t3n,
                    )
                if units and _short_stop_hit(high, trail_low.loc[ts], n_entry, units, config):
                    stop = min(
                        _avg_entry(units) + config.stop_n * n_entry,
                        float(trail_low.loc[ts]) + config.trail_n * n_entry,
                    )
                    realized += _close_all(units, stop, date, "chandelier_stop", closed, config)

        if not units:
            bars_in_pos = 0
            n_entry = None
            entry_price = None
            last_add_long = None
            last_add_short = None
            targets_hit = [False, False, False]

            rsi_val = float(rsi.loc[ts]) if pd.notna(rsi.loc[ts]) else 50.0
            rsi_long_ok = (not config.use_rsi_filter) or (rsi_val > config.rsi_long_thresh)
            rsi_short_ok = (not config.use_rsi_filter) or (rsi_val < config.rsi_short_thresh)

            if _valid_inputs(atr.loc[ts], don_hi_prev.loc[ts], don_lo_prev.loc[ts]):
                if config.allow_long and rsi_long_ok and close > float(don_hi_prev.loc[ts]):
                    n_entry = float(atr.loc[ts])
                    entry_price = close
                    qty = _unit_qty(equity, n_entry, config)
                    units.append(_Unit(1, qty, close, date))
                    last_add_long = close
                    bars_in_pos = 1
                elif config.allow_short and rsi_short_ok and close < float(don_lo_prev.loc[ts]):
                    n_entry = float(atr.loc[ts])
                    entry_price = close
                    qty = _unit_qty(equity, n_entry, config)
                    units.append(_Unit(-1, qty, close, date))
                    last_add_short = close
                    bars_in_pos = 1

        equity_values.append(
            (config.initial_capital + realized + _unrealized(units, close)) / config.initial_capital
        )

    if units:
        final_date = str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1])
        realized += _close_all(units, float(df["close"].iloc[-1]), final_date, "end_of_test", closed, config)
        equity_values[-1] = (config.initial_capital + realized) / config.initial_capital

    equity_curve = pd.Series(equity_values, index=df.index, dtype=float)
    return Alt45Result(
        metrics=_metrics(equity_curve, closed),
        equity_curve=equity_curve,
        closed_legs=closed,
    )


def _age_targets(bars: int, cfg: Alt45Config) -> tuple[float, float, float]:
    if bars <= cfg.young_age:
        return cfg.young_t1, cfg.young_t2, cfg.young_t3
    if bars <= cfg.mature_age:
        return cfg.std_t1, cfg.std_t2, cfg.std_t3
    return cfg.aging_t1, cfg.aging_t2, cfg.aging_t3


def _normalize_ohlcv(ohlcv: pd.DataFrame) -> pd.DataFrame:
    df = ohlcv.copy()
    df.columns = [str(col).lower() for col in df.columns]
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def _atr(df: pd.DataFrame, length: int) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def _rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, float("inf"))
    return 100.0 - (100.0 / (1.0 + rs))


def _valid_inputs(*values: float) -> bool:
    return all(pd.notna(v) and float(v) > 0 for v in values)


def _unit_qty(equity: float, n_entry: float, config: Alt45Config) -> float:
    risk_dollars = equity * config.risk_pct / 100
    per_share_risk = max(config.stop_n * n_entry, 0.01)
    return max(1.0, risk_dollars / per_share_risk)


def _unrealized(units: list[_Unit], price: float) -> float:
    return sum(u.side * u.qty * (price - u.entry_price) for u in units)


def _avg_entry(units: list[_Unit]) -> float:
    qty = sum(u.qty for u in units)
    return sum(u.entry_price * u.qty for u in units) / qty if qty else 0.0


def _hit_long_targets(
    units: list[_Unit], high: float, entry_price: float, n_entry: float,
    targets_hit: list[bool], date: str, closed: list[ClosedLeg],
    config: Alt45Config, t1n: float, t2n: float, t3n: float,
) -> float:
    realized = 0.0
    for idx, tn in enumerate([t1n, t2n, t3n]):
        if units and not targets_hit[idx] and high >= entry_price + tn * n_entry:
            realized += _close_one(units, entry_price + tn * n_entry, date, f"target{idx+1}", closed, config)
            targets_hit[idx] = True
    return realized


def _hit_short_targets(
    units: list[_Unit], low: float, entry_price: float, n_entry: float,
    targets_hit: list[bool], date: str, closed: list[ClosedLeg],
    config: Alt45Config, t1n: float, t2n: float, t3n: float,
) -> float:
    realized = 0.0
    for idx, tn in enumerate([t1n, t2n, t3n]):
        if units and not targets_hit[idx] and low <= entry_price - tn * n_entry:
            realized += _close_one(units, entry_price - tn * n_entry, date, f"target{idx+1}", closed, config)
            targets_hit[idx] = True
    return realized


def _long_stop_hit(low: float, trail_high: float, n_entry: float, units: list[_Unit], config: Alt45Config) -> bool:
    if pd.isna(trail_high):
        return False
    stop = max(_avg_entry(units) - config.stop_n * n_entry, float(trail_high) - config.trail_n * n_entry)
    return low <= stop


def _short_stop_hit(high: float, trail_low: float, n_entry: float, units: list[_Unit], config: Alt45Config) -> bool:
    if pd.isna(trail_low):
        return False
    stop = min(_avg_entry(units) + config.stop_n * n_entry, float(trail_low) + config.trail_n * n_entry)
    return high >= stop


def _close_one(units: list[_Unit], price: float, date: str, reason: str, closed: list[ClosedLeg], config: Alt45Config) -> float:
    unit = units.pop(0)
    return _record_close(unit, price, date, reason, closed, config)


def _close_all(units: list[_Unit], price: float, date: str, reason: str, closed: list[ClosedLeg], config: Alt45Config) -> float:
    realized = 0.0
    while units:
        realized += _close_one(units, price, date, reason, closed, config)
    return realized


def _record_close(unit: _Unit, price: float, date: str, reason: str, closed: list[ClosedLeg], config: Alt45Config) -> float:
    gross = unit.side * unit.qty * (price - unit.entry_price)
    cost = unit.qty * unit.entry_price * (config.slippage_pct + config.commission_pct) / 100
    cost += unit.qty * price * (config.slippage_pct + config.commission_pct) / 100
    pnl = gross - cost
    pnl_pct = pnl / (unit.qty * unit.entry_price) * 100
    closed.append(ClosedLeg(
        side=unit.side,
        entry_date=unit.entry_date,
        exit_date=date,
        entry_price=round(unit.entry_price, 4),
        exit_price=round(price, 4),
        qty=round(unit.qty, 4),
        reason=reason,
        pnl=round(pnl, 2),
        pnl_pct=round(pnl_pct, 3),
    ))
    return pnl


def _metrics(equity: pd.Series, closed: list[ClosedLeg]) -> BacktestMetrics:
    total_return = float((equity.iloc[-1] - 1) * 100)
    dd = (equity - equity.cummax()) / equity.cummax()
    max_dd = float(abs(dd.min()) * 100)
    wins = [t.pnl for t in closed if t.pnl > 0]
    losses = [t.pnl for t in closed if t.pnl < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_win / gross_loss if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
    trade_count = len(closed)
    win_rate = len(wins) / trade_count * 100 if trade_count else 0.0
    avg_win = sum(t.pnl_pct for t in closed if t.pnl_pct > 0) / len(wins) if wins else 0.0
    avg_loss = sum(t.pnl_pct for t in closed if t.pnl_pct < 0) / len(losses) if losses else 0.0
    expectancy = sum(t.pnl_pct for t in closed) / trade_count if trade_count else 0.0
    returns = equity.pct_change().fillna(0)
    sharpe = float((returns.mean() / returns.std()) * (252 ** 0.5)) if len(returns) > 1 and returns.std() > 0 else 0.0
    return BacktestMetrics(
        total_return_pct=round(total_return, 2),
        profit_factor=round(min(profit_factor, 99.0), 3),
        max_drawdown_pct=round(max_dd, 3),
        trade_count=trade_count,
        out_of_sample_profit_factor=0.0,
        walk_forward_pass_rate=0.0,
        avg_win_pct=round(avg_win, 3),
        avg_loss_pct=round(avg_loss, 3),
        expectancy_pct=round(expectancy, 3),
        max_consecutive_losses=_max_consecutive_losses(closed),
        time_in_market_pct=0.0,
        sharpe_ratio=round(sharpe, 3),
        win_rate_pct=round(win_rate, 3),
        calmar_ratio=round(total_return / max_dd, 3) if max_dd > 0 else 0.0,
    )


def _max_consecutive_losses(closed: list[ClosedLeg]) -> int:
    current = 0
    longest = 0
    for t in closed:
        if t.pnl < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest
