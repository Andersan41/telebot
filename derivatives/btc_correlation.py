"""
derivatives/btc_correlation.py — BTC correlation engine.

Blocks LONG if BTC is below 4H EMA200 or in bearish structure.
Blocks SHORT if BTC is in strong bullish breakout.
"""
from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd
from loguru import logger

from config.settings import config
from data.exchange_client import exchange_client


@dataclass
class BTCContext:
    price: float
    ema200_4h: float
    above_ema200: bool
    structure: Literal["bullish", "bearish", "ranging"]
    is_breakout: bool
    breakout_direction: Optional[Literal["bullish", "bearish"]]

    def allows_long(self) -> bool:
        if not self.above_ema200:
            return False
        if self.structure == "bearish":
            return False
        return True

    def allows_short(self) -> bool:
        if self.is_breakout and self.breakout_direction == "bullish":
            return False
        return True


async def fetch_btc_context() -> Optional[BTCContext]:
    """Fetch BTC OHLCV and compute EMA200 + structure + breakout detection."""
    btc_symbol = config.derivatives.btc_symbol
    tf = config.derivatives.btc_ema200_timeframe

    try:
        df = await exchange_client.fetch_ohlcv(btc_symbol, tf, limit=250)
        if df is None or len(df) < 200:
            logger.warning(f"Not enough BTC candles for EMA200 on {tf}")
            return None

        ema200 = df["close"].ewm(span=200, adjust=False).mean().iloc[-1]
        current_price = df["close"].iloc[-1]
        above_ema200 = current_price > ema200

        structure = _detect_structure(df)
        is_breakout, breakout_dir = _detect_breakout(df)

        return BTCContext(
            price=current_price,
            ema200_4h=ema200,
            above_ema200=above_ema200,
            structure=structure,
            is_breakout=is_breakout,
            breakout_direction=breakout_dir,
        )
    except Exception as e:
        logger.warning(f"BTC context fetch failed: {e}")
        return None


def _detect_structure(df: pd.DataFrame, lookback: int = 20) -> str:
    """Simple structure detection via higher highs / lower lows."""
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


def _detect_breakout(df: pd.DataFrame, lookback: int = 20) -> tuple[bool, Optional[str]]:
    """Detect if BTC is breaking out of recent range."""
    recent = df.tail(lookback)
    high_20 = recent["high"].max()
    low_20 = recent["low"].min()
    current = df["close"].iloc[-1]

    range_size = (high_20 - low_20) / low_20 * 100

    if current > high_20 and range_size < 5:
        return True, "bullish"
    elif current < low_20 and range_size < 5:
        return True, "bearish"
    return False, None
