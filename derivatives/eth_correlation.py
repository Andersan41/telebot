"""
derivatives/eth_correlation.py — ETH correlation filter.

Avoid SHORT if ETH is in strong impulsive move up.
Important for L2 tokens (OP, ARB) and DeFi tokens.
"""
from dataclasses import dataclass
from typing import Literal, Optional
from datetime import datetime, timezone

import pandas as pd
from loguru import logger

from config.settings import config
from data.exchange_client import exchange_client


ETH_CTX_TTL = 60 * 60  # 1 hour cache
_eth_ctx_cache: Optional[tuple] = None  # (ETHContext, timestamp)


def reset_eth_context_cache():
    """Reset ETH context cache (useful for testing)."""
    global _eth_ctx_cache
    _eth_ctx_cache = None


@dataclass
class ETHContext:
    price: float
    structure: Literal["bullish", "bearish", "ranging"]
    is_impulsive_up: bool
    momentum: float

    def allows_long(self, alt_symbol: str) -> bool:
        """Block LONG if ETH is bearish (FIX E1)."""
        if self.structure == "bearish":
            return False
        if self._is_eth_correlated(alt_symbol) and self.momentum < -2.0:
            return False
        return True

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
    """Fetch ETH OHLCV and detect impulsive moves.
    
    Results are cached for ETH_CTX_TTL (1 hour) to reduce API calls.
    """
    global _eth_ctx_cache
    
    # Check cache
    if _eth_ctx_cache is not None:
        cached_ctx, cached_time = _eth_ctx_cache
        age = (datetime.now(timezone.utc) - cached_time).total_seconds()
        if age < ETH_CTX_TTL:
            logger.debug(f"ETH context cache hit (age={age:.0f}s)")
            return cached_ctx
        logger.debug(f"ETH context cache expired (age={age:.0f}s)")
    
    eth_symbol = config.derivatives.eth_symbol

    try:
        df = await exchange_client.fetch_ohlcv(eth_symbol, "4h", limit=100)
        if df is None or len(df) < 30:
            logger.warning("Not enough ETH candles for context analysis")
            return None

        structure = _detect_structure(df)
        is_impulsive, momentum = _detect_impulsive_move(df)

        ctx = ETHContext(
            price=df["close"].iloc[-1],
            structure=structure,
            is_impulsive_up=is_impulsive,
            momentum=momentum,
        )
        _eth_ctx_cache = (ctx, datetime.now(timezone.utc))
        return ctx
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
