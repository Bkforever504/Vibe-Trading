"""Research-only WorldQuant-style cross-sectional alpha lab.

The 101 Formulaic Alphas are cross-sectional ranking ideas, not execution
signals. This lab tests a small, transparent subset on an ETF universe and
outputs research metrics only. Nothing here submits orders or changes bot gates.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import warnings

import pandas as pd

from research.pine_strategy_lab import BacktestMetrics, PineStrategyIdea, evaluate_candidate
from research.pine_strategy_sweep import estimate_pbo_score


DEFAULT_SYMBOLS = ["SPY", "QQQ", "IWM", "SMH", "XLK", "XLV", "XLF", "XLE", "XLI", "GLD"]


@dataclass(frozen=True)
class AlphaResult:
    alpha_id: str
    description: str
    symbols: list[str]
    start: str
    end: str
    params: dict
    metrics: BacktestMetrics
    status: str
    confidence_score: float
    reject_reasons: list[str]


def fetch_universe(symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError("yfinance required: uv run --no-project --with yfinance ...") from exc

    out: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = yf.download(symbol, start=start, end=end, progress=False, auto_adjust=True)
        if df.empty:
            continue
        df.columns = [col.lower() if isinstance(col, str) else col[0].lower() for col in df.columns]
        out[symbol] = df[["open", "high", "low", "close", "volume"]].copy()
    if len(out) < 4:
        raise ValueError(f"Need at least 4 symbols with data, got {len(out)}")
    return out


def panel(universe: dict[str, pd.DataFrame], field: str) -> pd.DataFrame:
    frames = {symbol: df[field] for symbol, df in universe.items() if field in df}
    return pd.DataFrame(frames).dropna(how="all").sort_index().ffill()


def cs_rank(df: pd.DataFrame) -> pd.DataFrame:
    return df.rank(axis=1, pct=True)


def ts_rank(df: pd.DataFrame, window: int) -> pd.DataFrame:
    def _rank_last(values) -> float:
        s = pd.Series(values)
        return float(s.rank(pct=True).iloc[-1])

    return df.rolling(window).apply(_rank_last, raw=False)


def rolling_corr(a: pd.DataFrame, b: pd.DataFrame, window: int) -> pd.DataFrame:
    return a.rolling(window).corr(b)


def alpha_002(open_: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """-corr(rank(delta(log(volume),2)), rank((close-open)/open), 6)."""
    del high, low
    log_vol_delta = volume.replace(0, pd.NA).apply(
        lambda col: col.map(lambda x: math.log(float(x)) if pd.notna(x) and x > 0 else pd.NA)
    ).diff(2)
    intraday_return = (close - open_) / open_
    return -rolling_corr(cs_rank(log_vol_delta), cs_rank(intraday_return), 6)


def alpha_003(open_: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """-corr(rank(open), rank(volume), 10)."""
    del high, low, close
    return -rolling_corr(cs_rank(open_), cs_rank(volume), 10)


def alpha_004(open_: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """-ts_rank(rank(low), 9)."""
    del open_, high, close, volume
    return -ts_rank(cs_rank(low), 9)


def alpha_006(open_: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """-corr(open, volume, 10)."""
    del high, low, close
    return -rolling_corr(open_, volume, 10)


def alpha_012(open_: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """sign(delta(volume,1)) * -delta(close,1)."""
    del open_, high, low
    vol_sign = volume.diff(1).apply(lambda col: col.map(lambda x: 1 if x > 0 else (-1 if x < 0 else 0)))
    return vol_sign * -close.diff(1)


ALPHAS = {
    "alpha_002": (alpha_002, "Volume acceleration vs intraday return divergence"),
    "alpha_003": (alpha_003, "Open-price rank vs volume rank divergence"),
    "alpha_004": (alpha_004, "Low-price time-series rank reversal"),
    "alpha_006": (alpha_006, "Open/volume rolling correlation reversal"),
    "alpha_012": (alpha_012, "Volume-change sign times negative price delta"),
}


def alpha_scores(universe: dict[str, pd.DataFrame], alpha_id: str) -> pd.DataFrame:
    if alpha_id not in ALPHAS:
        raise KeyError(f"Unknown alpha_id {alpha_id!r}")
    open_ = panel(universe, "open")
    high = panel(universe, "high")
    low = panel(universe, "low")
    close = panel(universe, "close")
    volume = panel(universe, "volume")
    common = open_.index
    for df in (high, low, close, volume):
        common = common.intersection(df.index)
    raw = ALPHAS[alpha_id][0](
        open_.reindex(common),
        high.reindex(common),
        low.reindex(common),
        close.reindex(common),
        volume.reindex(common),
    )
    return raw.replace([math.inf, -math.inf], pd.NA).dropna(how="all")


def portfolio_returns(
    scores: pd.DataFrame,
    close: pd.DataFrame,
    *,
    top_n: int = 2,
    dollar_neutral: bool = True,
    slippage_pct: float = 0.05,
    commission_pct: float = 0.01,
) -> tuple[pd.Series, pd.DataFrame]:
    returns = close.pct_change().reindex(scores.index).fillna(0)
    weights = pd.DataFrame(0.0, index=scores.index, columns=scores.columns)
    for idx, row in scores.iterrows():
        valid = pd.to_numeric(row, errors="coerce").dropna()
        if len(valid) < top_n * (2 if dollar_neutral else 1):
            continue
        longs = valid.nlargest(top_n).index
        weights.loc[idx, longs] = 1.0 / top_n
        if dollar_neutral:
            shorts = valid.nsmallest(top_n).index
            weights.loc[idx, shorts] = -1.0 / top_n
    shifted = weights.shift(1).fillna(0)
    turnover = shifted.diff().abs().sum(axis=1).fillna(0)
    cost = turnover * (slippage_pct + commission_pct) / 100
    port_ret = (shifted * returns).sum(axis=1) - cost
    return port_ret, weights


def metrics_from_returns(returns: pd.Series, weights: pd.DataFrame) -> BacktestMetrics:
    returns = returns.dropna()
    if returns.empty:
        return BacktestMetrics(0, 0, 0, 0, 0, 0)
    equity = (1 + returns).cumprod()
    total_return = float((equity.iloc[-1] - 1) * 100)
    dd = (equity - equity.cummax()) / equity.cummax()
    max_dd = float(abs(dd.min()) * 100)
    gains = returns[returns > 0]
    losses = returns[returns < 0]
    gross_win = float(gains.sum())
    gross_loss = float(abs(losses.sum()))
    pf = gross_win / gross_loss if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)
    win_rate = float(len(gains) / len(returns) * 100) if len(returns) else 0.0
    sharpe = float((returns.mean() / returns.std()) * math.sqrt(252)) if len(returns) > 2 and returns.std() else 0.0
    trade_count = int((weights.diff().abs().sum(axis=1) > 0).sum())
    avg_win = float(gains.mean() * 100) if len(gains) else 0.0
    avg_loss = float(losses.mean() * 100) if len(losses) else 0.0
    expectancy = float(returns.mean() * 100)
    calmar = total_return / max_dd if max_dd > 0 else 0.0
    return BacktestMetrics(
        total_return_pct=round(total_return, 3),
        profit_factor=round(min(pf, 99.0), 3),
        max_drawdown_pct=round(max_dd, 3),
        trade_count=trade_count,
        out_of_sample_profit_factor=0.0,
        walk_forward_pass_rate=0.0,
        avg_win_pct=round(avg_win, 4),
        avg_loss_pct=round(avg_loss, 4),
        expectancy_pct=round(expectancy, 4),
        max_consecutive_losses=_max_consecutive_losses(returns.tolist()),
        time_in_market_pct=round(float((weights.abs().sum(axis=1) > 0).mean() * 100), 3),
        sharpe_ratio=round(sharpe, 3),
        win_rate_pct=round(win_rate, 3),
        calmar_ratio=round(calmar, 3),
    )


def _max_consecutive_losses(values: list[float]) -> int:
    longest = 0
    current = 0
    for value in values:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def evaluate_alpha(
    alpha_id: str,
    universe: dict[str, pd.DataFrame],
    *,
    start: str,
    end: str,
    top_n: int = 2,
    dollar_neutral: bool = True,
    oos_split: float = 0.20,
    wf_folds: int = 5,
) -> AlphaResult:
    scores = alpha_scores(universe, alpha_id)
    close = panel(universe, "close").reindex(scores.index).ffill()
    split = int(len(scores) * (1 - oos_split))
    is_scores, oos_scores = scores.iloc[:split], scores.iloc[split:]
    is_ret, is_weights = portfolio_returns(is_scores, close, top_n=top_n, dollar_neutral=dollar_neutral)
    oos_ret, oos_weights = portfolio_returns(oos_scores, close, top_n=top_n, dollar_neutral=dollar_neutral)
    metrics = metrics_from_returns(is_ret, is_weights)
    oos_metrics = metrics_from_returns(oos_ret, oos_weights)
    wf_rate = walk_forward_pass_rate(scores, close, top_n=top_n, dollar_neutral=dollar_neutral, folds=wf_folds, oos_split=oos_split)
    metrics = BacktestMetrics(
        **{**metrics.__dict__, "out_of_sample_profit_factor": oos_metrics.profit_factor, "walk_forward_pass_rate": wf_rate}
    )
    idea = PineStrategyIdea(name=alpha_id, license="mit")
    evaluation = evaluate_candidate(idea, metrics)
    return AlphaResult(
        alpha_id=alpha_id,
        description=ALPHAS[alpha_id][1],
        symbols=list(universe.keys()),
        start=start,
        end=end,
        params={"top_n": top_n, "dollar_neutral": dollar_neutral},
        metrics=metrics,
        status=evaluation.status,
        confidence_score=evaluation.confidence_score,
        reject_reasons=evaluation.reject_reasons,
    )


def walk_forward_pass_rate(
    scores: pd.DataFrame,
    close: pd.DataFrame,
    *,
    top_n: int,
    dollar_neutral: bool,
    folds: int,
    oos_split: float,
) -> float:
    if len(scores) < folds * 30:
        return 0.0
    fold_size = len(scores) // folds
    passed = 0
    valid = 0
    for i in range(folds):
        fold = scores.iloc[i * fold_size:(i + 1) * fold_size]
        split = int(len(fold) * (1 - oos_split))
        oos = fold.iloc[split:]
        if len(oos) < 20:
            continue
        ret, weights = portfolio_returns(oos, close, top_n=top_n, dollar_neutral=dollar_neutral)
        m = metrics_from_returns(ret, weights)
        valid += 1
        if m.profit_factor > 1.0:
            passed += 1
    return round(passed / valid, 3) if valid else 0.0


def run_alpha_lab(
    symbols: list[str] | None = None,
    start: str = "2018-01-01",
    end: str = "2026-01-01",
    alpha_ids: list[str] | None = None,
    top_n: int = 2,
    dollar_neutral: bool = True,
    universe: dict[str, pd.DataFrame] | None = None,
) -> list[AlphaResult]:
    symbols = symbols or DEFAULT_SYMBOLS
    alpha_ids = alpha_ids or list(ALPHAS)
    universe = universe or fetch_universe(symbols, start, end)
    results = [
        evaluate_alpha(alpha_id, universe, start=start, end=end, top_n=top_n, dollar_neutral=dollar_neutral)
        for alpha_id in alpha_ids
    ]
    pbo = estimate_pbo_score([result.metrics for result in results])
    updated: list[AlphaResult] = []
    for result in results:
        metrics = BacktestMetrics(**{**result.metrics.__dict__, "pbo_score": pbo})
        ev = evaluate_candidate(PineStrategyIdea(name=result.alpha_id, license="mit"), metrics)
        updated.append(AlphaResult(
            alpha_id=result.alpha_id,
            description=result.description,
            symbols=result.symbols,
            start=result.start,
            end=result.end,
            params=result.params,
            metrics=metrics,
            status=ev.status,
            confidence_score=ev.confidence_score,
            reject_reasons=ev.reject_reasons,
        ))
    return sorted(updated, key=lambda r: (r.confidence_score, r.metrics.out_of_sample_profit_factor, r.metrics.profit_factor), reverse=True)


def write_report(results: list[AlphaResult], path) -> None:
    lines = [
        "# WorldQuant Alpha Lab Report",
        "",
        "Research only. These are cross-sectional factor tests, not bot signals and not execution gates.",
        "",
        "| Alpha | Status | Conf | PF | OOS PF | WF | PBO | Sharpe | Trades | Max DD | Description | Reject Reasons |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for result in results:
        m = result.metrics
        reasons = ", ".join(result.reject_reasons) if result.reject_reasons else "-"
        lines.append(
            "| "
            + " | ".join([
                result.alpha_id,
                result.status,
                f"{result.confidence_score:.1f}",
                f"{m.profit_factor:.2f}",
                f"{m.out_of_sample_profit_factor:.2f}",
                f"{m.walk_forward_pass_rate:.2f}",
                f"{m.pbo_score:.2f}",
                f"{m.sharpe_ratio:.2f}",
                str(m.trade_count),
                f"{m.max_drawdown_pct:.1f}%",
                result.description,
                reasons,
            ])
            + " |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
