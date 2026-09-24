"""
analytics/token_levels.py — Support/Resistance Level Calculation.

Calculates S/R levels from multiple sources:
1. Order Blocks (highest priority)
2. FVG boundaries
3. Swing Points
4. EMA levels
5. Round numbers (psychological levels)

Returns top 3 resistance + top 3 support per timeframe.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from liquidity.order_blocks import OrderBlock
from liquidity.fvg import FairValueGap
from market_structure.structure import SwingPoint


@dataclass
class SRLevels:
    """Support and Resistance levels for a single timeframe."""
    resistance: List[float]
    support: List[float]


def _round_number_levels(price: float) -> List[float]:
    """Generate round (psychological) price levels near current price."""
    levels = []

    if price < 0.001:
        steps = [0.0001, 0.0005, 0.001]
    elif price < 0.01:
        steps = [0.001, 0.005, 0.01]
    elif price < 0.10:
        steps = [0.01, 0.05, 0.10]
    elif price < 1.0:
        steps = [0.05, 0.10, 0.25, 0.50]
    elif price < 10.0:
        steps = [0.50, 1.0, 2.0, 5.0]
    elif price < 100.0:
        steps = [5.0, 10.0, 25.0, 50.0]
    elif price < 1000.0:
        steps = [50.0, 100.0, 250.0, 500.0]
    else:
        steps = [100.0, 500.0, 1000.0, 2500.0]

    for step in steps:
        base = int(price / step) * step
        for offset in [-2, -1, 0, 1, 2]:
            candidate = base + offset * step
            if candidate > 0:
                levels.append(round(candidate, 10))

    return sorted(set(levels))


def _merge_and_filter(
    candidates: List[float],
    current_price: float,
    side: str,
    max_levels: int = 3,
    min_distance_pct: float = 0.5,
) -> List[float]:
    """
    Filter and keep top N levels closest to current price.

    Args:
        candidates: raw price levels
        current_price: current market price
        side: "resistance" or "support"
        max_levels: number of levels to return
        min_distance_pct: minimum distance from price in %
    """
    if side == "resistance":
        candidates = [l for l in candidates if l > current_price * (1 + min_distance_pct / 100)]
        candidates.sort(key=lambda l: l - current_price)
    else:
        candidates = [l for l in candidates if l < current_price * (1 - min_distance_pct / 100)]
        candidates.sort(key=lambda l: current_price - l, reverse=True)

    # Remove duplicates (within 0.5% of each other)
    filtered = []
    for level in candidates:
        if not filtered:
            filtered.append(level)
        else:
            is_dup = False
            for existing in filtered:
                if abs(level - existing) / existing < 0.005:
                    is_dup = True
                    break
            if not is_dup:
                filtered.append(level)
        if len(filtered) >= max_levels:
            break

    return filtered


def calculate_levels(
    df_1h: pd.DataFrame,
    df_4h: pd.DataFrame,
    indicators_1h=None,
    indicators_4h=None,
    order_blocks_1h: Optional[List[OrderBlock]] = None,
    order_blocks_4h: Optional[List[OrderBlock]] = None,
    fvgs_1h: Optional[List[FairValueGap]] = None,
    fvgs_4h: Optional[List[FairValueGap]] = None,
    swing_points_1h: Optional[List[SwingPoint]] = None,
    swing_points_4h: Optional[List[SwingPoint]] = None,
) -> dict:
    """
    Calculate support/resistance levels from multiple sources.

    Returns dict with keys:
        - resistance_1h: [R1, R2, R3]
        - support_1h: [S1, S2, S3]
        - resistance_4h: [R1, R2, R3]
        - support_4h: [S1, S2, S3]
    """
    current_price = float(df_1h["close"].iloc[-1]) if len(df_1h) > 0 else 0.0

    result = {}
    for label, df, obs, fvgs, swings in [
        ("1h", df_1h, order_blocks_1h, fvgs_1h, swing_points_1h),
        ("4h", df_4h, order_blocks_4h, fvgs_4h, swing_points_4h),
    ]:
        resistance_candidates = []
        support_candidates = []

        # 1. Order Blocks (highest priority)
        if obs:
            for ob in obs:
                if ob.type == "bearish":
                    resistance_candidates.append(ob.high)
                else:
                    support_candidates.append(ob.low)

        # 2. FVG boundaries
        if fvgs:
            for fvg in fvgs:
                if fvg.is_active:
                    if fvg.type == "bearish":
                        resistance_candidates.append(fvg.top)
                    else:
                        support_candidates.append(fvg.bottom)

        # 3. Swing Points
        if swings:
            for sp in swings:
                if sp.type == "high":
                    resistance_candidates.append(sp.price)
                else:
                    support_candidates.append(sp.price)

        # 4. EMA levels (if available)
        if indicators_1h and label == "1h":
            resistance_candidates.append(indicators_1h.ema_slow)
            resistance_candidates.append(indicators_1h.ema_trend)
            support_candidates.append(indicators_1h.ema_slow)
            support_candidates.append(indicators_1h.ema_trend)
        elif indicators_4h and label == "4h":
            resistance_candidates.append(indicators_4h.ema_slow)
            resistance_candidates.append(indicators_4h.ema_trend)
            support_candidates.append(indicators_4h.ema_slow)
            support_candidates.append(indicators_4h.ema_trend)

        # 5. Round numbers
        round_levels = _round_number_levels(current_price)
        resistance_candidates.extend(round_levels)
        support_candidates.extend(round_levels)

        # Filter and keep top 3 each side
        resistance = _merge_and_filter(resistance_candidates, current_price, "resistance")
        support = _merge_and_filter(support_candidates, current_price, "support")

        result[f"resistance_{label}"] = resistance
        result[f"support_{label}"] = support

    return result


def _find_swing_points_from_df(df: pd.DataFrame, lookback: int = 50, swing_window: int = 5) -> List[SwingPoint]:
    """Extract swing points directly from DataFrame (without full structure analysis)."""
    from market_structure.structure import _find_swing_points
    return _find_swing_points(df, lookback=lookback, swing_window=swing_window)
