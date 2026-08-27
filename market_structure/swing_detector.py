"""
market_structure/swing_detector.py — Unified swing point detection.

Replaces duplicated logic in:
- liquidity/sweep.py (strict 2-neighbor)
- liquidity/order_blocks.py (rolling window=5)
- market_structure/structure.py (rolling window=5)

Two modes:
- strict: all neighbors must be strictly less/greater (sweep.py behavior)
- rolling: candidate must be max/min of the window (order_blocks/structure behavior)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Literal

import pandas as pd


class SwingType(str, Enum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True)
class SwingPoint:
    """Unified swing point representation."""
    index: int           # position in df (absolute index)
    price: float
    swing_type: SwingType
    strength: int = 2    # number of confirming bars on each side
    timestamp: pd.Timestamp | None = None

    # Backward compat: provide .type and .candle_index like old SwingPoint
    @property
    def type(self) -> str:
        return self.swing_type.value

    @property
    def candle_index(self) -> int:
        return self.index


def detect_swings(
    df: pd.DataFrame,
    left_bars: int = 2,
    right_bars: int = 2,
    strict: bool = True,
    price_col_high: str = "high",
    price_col_low: str = "low",
) -> List[SwingPoint]:
    """
    Unified swing point detection.

    Args:
        df: OHLCV DataFrame (last candle already removed by caller).
        left_bars: bars to the left for confirmation.
        right_bars: bars to the right for confirmation.
        strict: if True, all neighbors must be strictly less/greater (sweep.py mode).
                if False, candidate must be max/min of window (order_blocks/structure mode).
        price_col_high: column name for high prices.
        price_col_low: column name for low prices.

    Returns:
        List of SwingPoint, sorted by index.
    """
    if len(df) < left_bars + right_bars + 1:
        return []

    swings: List[SwingPoint] = []
    end = len(df) - right_bars

    for i in range(left_bars, end):
        h = df[price_col_high].iloc[i]
        l = df[price_col_low].iloc[i]

        # ── Swing High ──
        if strict:
            # Strict: all 4 neighbors must be strictly less
            left_ok = all(df[price_col_high].iloc[i - j] < h for j in range(1, left_bars + 1))
            right_ok = all(df[price_col_high].iloc[i + j] < h for j in range(1, right_bars + 1))
            is_high = left_ok and right_ok
        else:
            # Rolling: candidate must be max of window
            window = df[price_col_high].iloc[i - left_bars: i + right_bars + 1]
            is_high = h == window.max()

        if is_high:
            ts = _extract_timestamp(df, i)
            swings.append(SwingPoint(
                index=i,
                price=float(h),
                swing_type=SwingType.HIGH,
                strength=min(left_bars, right_bars),
                timestamp=ts,
            ))

        # ── Swing Low ──
        if strict:
            left_ok = all(df[price_col_low].iloc[i - j] > l for j in range(1, left_bars + 1))
            right_ok = all(df[price_col_low].iloc[i + j] > l for j in range(1, right_bars + 1))
            is_low = left_ok and right_ok
        else:
            window = df[price_col_low].iloc[i - left_bars: i + right_bars + 1]
            is_low = l == window.min()

        if is_low:
            ts = _extract_timestamp(df, i)
            swings.append(SwingPoint(
                index=i,
                price=float(l),
                swing_type=SwingType.LOW,
                strength=min(left_bars, right_bars),
                timestamp=ts,
            ))

    swings.sort(key=lambda s: s.index)
    return swings


def filter_significant_swings(
    swings: List[SwingPoint],
    df: pd.DataFrame,
    min_atr_multiple: float = 0.5,
    atr_col: str = "atr",
) -> List[SwingPoint]:
    """
    Filter insignificant swing points (noise).

    Keeps only swings where the amplitude from the previous swing
    of the same or opposite type >= min_atr_multiple * ATR at that point.
    """
    if not swings or len(swings) < 2:
        return swings

    has_atr = atr_col in df.columns
    result: List[SwingPoint] = [swings[0]]

    for i in range(1, len(swings)):
        prev = result[-1]
        curr = swings[i]

        amplitude = abs(curr.price - prev.price)

        # Get ATR at current swing point
        if has_atr and curr.index < len(df):
            atr_val = df[atr_col].iloc[curr.index]
            if pd.isna(atr_val) or atr_val <= 0:
                atr_val = 0.0
        else:
            atr_val = 0.0

        threshold = atr_val * min_atr_multiple

        if amplitude >= threshold or atr_val == 0:
            result.append(curr)

    return result


def _extract_timestamp(df: pd.DataFrame, i: int):
    """Extract timestamp from DataFrame index at position i."""
    ts = df.index[i]
    if isinstance(ts, (int, float)):
        from datetime import datetime, timezone
        ts = datetime.fromtimestamp(ts, tz=timezone.utc)
    elif hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        from datetime import timezone
        ts = ts.replace(tzinfo=timezone.utc)
    return ts
