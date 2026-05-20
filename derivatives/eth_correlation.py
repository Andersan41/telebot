"""
derivatives/eth_correlation.py — ETH correlation filter.

Avoid SHORT if ETH is in strong impulsive move up.
Important for L2 tokens (OP, ARB) and DeFi tokens.
"""
from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd
from loguru import logger

from config.settings import config
from data.exchange_client import exchange_client


@dataclass
class ETHContext:
    price: float
    structure: Literal["bullish", "bearish", "ranging"]
    is_impulsive_up: bool
    momentum: float

    def allows_short(self, alt_symbol: str) -> bool:
        if self.is_impulsive_up:
            return False
        if self._is_eth_correlated(alt_symbol) and self.structure == "bullish":
            return False
        return True

    def _is_eth_correlated(self, alt_symbol: str) -> bool:
        correlated = config.derivatives.eth_correlation_symbols
        if not correlated:
            return False
        return alt_symbol.upper() in [s.upper() for s in correlated]


async def fetch_eth_context() -> Optional[ETHContext]:
    """Fetch ETH OHLCV and detect impulsive moves."""
    eth_symbol = config.derivatives.eth_symbol

    try:
        df = await exchange_client.fetch_ohlcv(eth_symbol, "4h", limit=100)
        if df is None or len(df) < 30:
            logger.warning("Not enough ETH candles for context analysis")
            return None

        structure = _detect_structure(df)
        is_impulsive, momentum = _detect_impulsive_move(df)

        return ETHContext(
            price=df["close"].iloc[-1],
            structure=structure,
            is_impulsive_up=is_impulsive,
            momentum=momentum,
        )
    except Exception as e:
        logger.warning(f"ETH context fetch failed: {e}")
        return None


def _detect_structure(df: pd.DataFrame, lookback: int = 20) -> str:
    closes = df["close"].tail(lookback).values
    if len(closes) < 4:
        return "ranging"

    hh = 0
    ll = 0
    for i in range(2, len(closes)):
        if closes[i] > closes[i - 1] and closes[i - 1] > closes[i - 2]:
            hh += 1
        elif closes[i] < closes[i - 1] and closes[i - 1] < closes[i - 2]:
            ll += 1

    if hh > ll + 2:
        return "bullish"
    elif ll > hh + 2:
        return "bearish"
    return "ranging"


def _detect_impulsive_move(df: pd.DataFrame, lookback: int = 5) -> tuple[bool, float]:
    """Detect strong impulsive upward move in ETH.

    An impulsive move is defined as:
    - Consecutive bullish candles (close > open)
    - Total price change > 3% over the lookback period
    """
    recent = df.tail(lookback)
    closes = recent["close"].values
    opens = recent["open"].values

    if len(closes) < 3:
        return False, 0.0

    price_change_pct = (closes[-1] - closes[0]) / closes[0] * 100

    bullish_count = sum(1 for c, o in zip(closes, opens) if c > o)
    bullish_ratio = bullish_count / len(closes)

    is_impulsive = price_change_pct > 3.0 and bullish_ratio >= 0.6

    return is_impulsive, price_change_pct
