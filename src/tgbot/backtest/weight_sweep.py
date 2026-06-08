"""backtest/weight_sweep.py — Sweep WeightProfile variants and collect backtest metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from tgbot.backtest.engine import BacktestEngine
from tgbot.config.weights import WeightProfile, profile_override


@dataclass
class SweepRow:
    profile_name: str
    metric: str
    value: float
    extra: dict[str, Any] = field(default_factory=dict)


def run_profile_sweep(
    profiles: list[WeightProfile],
    df: pd.DataFrame,
    symbol: str = 'BTC/USDT',
    timeframe: str = '1h',
    max_trades: int | None = None,
) -> pd.DataFrame:
    """Run backtest for each profile and return a tall DataFrame of metrics.

    Args:
        profiles: List of WeightProfile variants to test.
        df: OHLCV DataFrame for the backtest.
        symbol: Trading symbol.
        timeframe: Candle timeframe.
        max_trades: Max trades per run (None = unlimited).

    Returns:
        pd.DataFrame with columns: profile_name, metric, value, plus any extra keys.
    """
    rows: list[SweepRow] = []

    for profile in profiles:
        engine = BacktestEngine(symbol=symbol, timeframe=timeframe, max_trades=max_trades)
        with profile_override(profile):
            result = engine.run(df)

        for metric_name in ('total_trades', 'signals_generated', 'wins', 'losses',
                            'winrate', 'profit_factor', 'expectancy',
                            'sharpe_ratio', 'max_drawdown'):
            val = getattr(result, metric_name, 0.0) or 0.0
            rows.append(SweepRow(
                profile_name=profile.name,
                metric=metric_name,
                value=float(val),
            ))

        for regime, stats in (result.regime_stats or {}).items():
            rows.append(SweepRow(
                profile_name=profile.name,
                metric=f'regime_{regime}_trades',
                value=float(stats.total_trades),
            ))
            rows.append(SweepRow(
                profile_name=profile.name,
                metric=f'regime_{regime}_winrate',
                value=float(stats.winrate or 0.0),
            ))

    return pd.DataFrame([
        {'profile_name': r.profile_name, 'metric': r.metric, 'value': r.value, **r.extra}
        for r in rows
    ])
