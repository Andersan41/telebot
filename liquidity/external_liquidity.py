"""
liquidity/external_liquidity.py — External Liquidity TP Finder

Finds TP targets using external liquidity levels:
1. EQH/EQL (Equal Highs/Lows) — cluster of swing points
2. Single swing high/low
3. Fallback chain: opposing OB → active FVG → swing structure → ATR

Used by signal_engine to replace ATR-only TP with structure-based TP.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger


def find_swing_highs(df: pd.DataFrame, order: int = 5) -> List[Tuple[int, float]]:
    """Find local maxima in high column.

    Args:
        df: OHLCV DataFrame
        order: number of bars on each side to confirm swing

    Returns:
        List of (index, price) tuples
    """
    highs = df["high"].values
    swings = []
    for i in range(order, len(highs) - order):
        is_max = all(highs[i] >= highs[i - j] for j in range(1, order + 1))
        is_max &= all(highs[i] >= highs[i + j] for j in range(1, order + 1))
        if is_max:
            swings.append((i, float(highs[i])))
    return swings


def find_swing_lows(df: pd.DataFrame, order: int = 5) -> List[Tuple[int, float]]:
    """Find local minima in low column."""
    lows = df["low"].values
    swings = []
    for i in range(order, len(lows) - order):
        is_min = all(lows[i] <= lows[i - j] for j in range(1, order + 1))
        is_min &= all(lows[i] <= lows[i + j] for j in range(1, order + 1))
        if is_min:
            swings.append((i, float(lows[i])))
    return swings


def cluster_levels(
    levels: List[float], tolerance_pct: float = 0.3
) -> List[dict]:
    """Group price levels by proximity tolerance.

    Args:
        levels: list of price levels
        tolerance_pct: clustering tolerance in percent

    Returns:
        List of dicts with 'price', 'prices', 'touches'
    """
    if not levels:
        return []

    clusters = []
    for val in sorted(levels):
        found = False
        for cluster in clusters:
            if abs(val - cluster["price"]) / cluster["price"] < tolerance_pct / 100:
                cluster["prices"].append(val)
                cluster["price"] = float(np.mean(cluster["prices"]))
                cluster["touches"] += 1
                found = True
                break

        if not found:
            clusters.append({"price": val, "prices": [val], "touches": 1})

    return clusters


def find_external_liquidity(
    df: pd.DataFrame,
    side: str,
    entry: float,
    sl_distance: float,
    min_rr: float = 1.5,
    max_rr: float = 10.0,
    lookback: int = 100,
    tolerance_pct: float = 0.3,
) -> Tuple[Optional[float], str]:
    """Find TP target using external liquidity levels.

    Priority:
    1. EQH/EQL (2+ swing points clustered)
    2. Single swing high/low

    Args:
        df: OHLCV DataFrame
        side: 'long' or 'short'
        entry: entry price
        sl_distance: distance from entry to SL (absolute)
        min_rr: minimum R:R for TP
        max_rr: maximum R:R for TP
        lookback: number of bars to search
        tolerance_pct: clustering tolerance for EQH/EQL

    Returns:
        (tp_price, source) or (None, '')
    """
    if sl_distance <= 0:
        return None, ""

    data = df.iloc[-lookback:] if len(df) > lookback else df

    if side == "long":
        # EQH: swing highs with 2+ touches
        swings = find_swing_highs(data)
        levels = [price for _, price in swings if price > entry]
        clusters = cluster_levels(levels, tolerance_pct)

        # Try EQH first (2+ touches)
        eqhs = sorted(
            [c for c in clusters if c["touches"] >= 2], key=lambda x: x["price"]
        )
        for eqh in eqhs:
            rr = (eqh["price"] - entry) / sl_distance
            if min_rr <= rr <= max_rr:
                return eqh["price"], "eqh"

        # Fallback: single swing high
        singles = sorted(
            [c for c in clusters if c["touches"] == 1], key=lambda x: x["price"]
        )
        for sw in singles:
            rr = (sw["price"] - entry) / sl_distance
            if min_rr <= rr <= max_rr:
                return sw["price"], "swing_high"

    elif side == "short":
        # EQL: swing lows with 2+ touches
        swings = find_swing_lows(data)
        levels = [price for _, price in swings if price < entry]
        clusters = cluster_levels(levels, tolerance_pct)

        # Try EQL first
        eqls = sorted(
            [c for c in clusters if c["touches"] >= 2],
            key=lambda x: x["price"],
            reverse=True,
        )
        for eql in eqls:
            rr = (entry - eql["price"]) / sl_distance
            if min_rr <= rr <= max_rr:
                return eql["price"], "eql"

        # Fallback: single swing low
        singles = sorted(
            [c for c in clusters if c["touches"] == 1],
            key=lambda x: x["price"],
            reverse=True,
        )
        for sw in singles:
            rr = (entry - sw["price"]) / sl_distance
            if min_rr <= rr <= max_rr:
                return sw["price"], "swing_low"

    return None, ""
