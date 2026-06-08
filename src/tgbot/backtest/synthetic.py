"""backtest/synthetic.py — Генерация синтетических OHLCV данных для бэктестинга."""

from __future__ import annotations

import numpy as np
import pandas as pd


def make_ohlcv(
    n: int = 300,
    base_price: float = 50000.0,
    trend: str = 'bullish',
    volatility: float = 0.01,
    rng_seed: int = 42,
) -> pd.DataFrame:
    rng = np.random.default_rng(rng_seed)

    if trend == 'bullish':
        drift = volatility * 0.3
    elif trend == 'bearish':
        drift = -volatility * 0.3
    else:
        drift = 0.0

    returns = rng.normal(drift, volatility, n)
    prices = base_price * np.cumprod(1 + returns)

    closes = prices
    highs = closes * (1 + np.abs(rng.normal(0, volatility * 0.5, n)))
    lows = closes * (1 - np.abs(rng.normal(0, volatility * 0.5, n)))
    opens = np.concatenate([[closes[0]], closes[:-1]])
    volumes = rng.uniform(800, 1200, n)

    return pd.DataFrame(
        {
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes,
            'volume': volumes,
        },
        index=pd.date_range('2024-01-01', periods=n, freq='h'),
    )


def make_trending_ohlcv(n: int = 300, rng_seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(rng_seed)
    base = 50000.0
    prices: list[float] = [base]
    for _i in range(1, n):
        change = base * 0.005 + rng.normal(0, base * 0.002)
        prices.append(prices[-1] + change)

    closes = np.array(prices)
    highs = closes * 1.003
    lows = closes * 0.997
    opens = np.concatenate([[closes[0]], closes[:-1]])
    volumes = rng.uniform(1000, 1500, n)

    return pd.DataFrame(
        {
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes,
            'volume': volumes,
        },
        index=pd.date_range('2024-01-01', periods=n, freq='h'),
    )


def make_ranging_ohlcv(n: int = 300, rng_seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(rng_seed)
    base = 50000.0
    prices: list[float] = [base]
    for _i in range(1, n):
        deviation = (prices[-1] - base) / base
        change = -deviation * base * 0.01 + rng.normal(0, base * 0.003)
        prices.append(prices[-1] + change)

    closes = np.array(prices)
    highs = closes * 1.002
    lows = closes * 0.998
    opens = np.concatenate([[closes[0]], closes[:-1]])
    volumes = rng.uniform(800, 1000, n)

    return pd.DataFrame(
        {
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes,
            'volume': volumes,
        },
        index=pd.date_range('2024-01-01', periods=n, freq='h'),
    )
