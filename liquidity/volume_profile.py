"""
liquidity/volume_profile.py — Volume Profile (POC/VAH/VAL).

ICT concept: Volume Profile identifies price levels with the highest
traded volume (POC) and the value area boundaries (VAH/VAL) where
70% of volume was traded. These act as strong S/R levels.

For OHLCV data (no tick data), volume is distributed across each
candle's price range uniformly.

POC = price level with highest volume concentration
VAH = upper boundary of value area (70% of volume centered on POC)
VAL = lower boundary of value area
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class VolumeProfileResult:
    """Volume profile analysis result."""
    poc: float               # Point of Control — highest volume price
    vah: float               # Value Area High — upper 70% volume boundary
    val: float               # Value Area Low — lower 70% volume boundary
    poc_volume: float        # Volume at POC
    total_volume: float      # Total volume in profile
    value_area_pct: float    # % of total volume in value area (target: 70%)
    price_range_pct: float   # VAH-VAL as % of POC
    bins: int                # number of price bins used
    volume_at_price: dict    # {price_level: volume} for top N levels

    @property
    def is_valid(self) -> bool:
        return self.poc > 0 and self.vah > self.val

    @property
    def midpoint(self) -> float:
        return (self.vah + self.val) / 2 if self.vah > self.val else self.poc

    def distance_from_price(self, price: float) -> float:
        """Distance of price from POC as % of POC."""
        if self.poc == 0:
            return 0.0
        return abs(price - self.poc) / self.poc * 100

    def price_in_value_area(self, price: float) -> bool:
        """Check if price is within the value area (VAL <= price <= VAH)."""
        return self.val <= price <= self.vah

    def price_above_value_area(self, price: float) -> bool:
        return price > self.vah

    def price_below_value_area(self, price: float) -> bool:
        return price < self.val


def compute_volume_profile(
    df: pd.DataFrame,
    bins: int = 50,
    value_area_pct: float = 0.70,
    lookback: Optional[int] = None,
) -> Optional[VolumeProfileResult]:
    """Compute volume profile from OHLCV data.

    Args:
        df: DataFrame with open, high, low, close, volume columns.
        bins: number of price bins for volume distribution.
        value_area_pct: fraction of volume for value area (default 0.70 = 70%).
        lookback: use only last N candles (None = all).

    Returns:
        VolumeProfileResult or None if data is insufficient.
    """
    if df is None or len(df) < 10:
        return None

    data = df.tail(lookback) if lookback else df
    if len(data) < 10:
        return None

    high = data["high"].astype(float).values
    low = data["low"].astype(float).values
    close = data["close"].astype(float).values
    volume = data["volume"].astype(float).values

    price_min = float(np.min(low))
    price_max = float(np.max(high))

    if price_max <= price_min or np.sum(volume) == 0:
        return None

    # Create price bins
    bin_edges = np.linspace(price_min, price_max, bins + 1)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    bin_width = bin_edges[1] - bin_edges[0]

    # Distribute each candle's volume across its price range
    volume_at_price = np.zeros(bins)

    for i in range(len(data)):
        candle_high = high[i]
        candle_low = low[i]
        candle_vol = volume[i]

        if candle_vol <= 0 or candle_high <= candle_low:
            continue

        # Find which bins this candle's range overlaps
        for j in range(bins):
            bin_low = bin_edges[j]
            bin_high = bin_edges[j + 1]

            # Overlap between candle range and bin range
            overlap_low = max(candle_low, bin_low)
            overlap_high = min(candle_high, bin_high)

            if overlap_high > overlap_low:
                # Proportion of candle range that falls in this bin
                candle_range = candle_high - candle_low
                proportion = (overlap_high - overlap_low) / candle_range
                volume_at_price[j] += candle_vol * proportion

    total_volume = float(np.sum(volume_at_price))
    if total_volume == 0:
        return None

    # POC: bin with highest volume
    poc_idx = int(np.argmax(volume_at_price))
    poc = float(bin_centers[poc_idx])
    poc_volume = float(volume_at_price[poc_idx])

    # Value area: expand from POC until we capture value_area_pct of total volume
    target_volume = total_volume * value_area_pct
    accumulated = volume_at_price[poc_idx]
    va_low_idx = poc_idx
    va_high_idx = poc_idx

    while accumulated < target_volume and (va_low_idx > 0 or va_high_idx < bins - 1):
        # Expand toward the side with more volume
        expand_up = volume_at_price[va_high_idx + 1] if va_high_idx < bins - 1 else 0
        expand_down = volume_at_price[va_low_idx - 1] if va_low_idx > 0 else 0

        if expand_up == 0 and expand_down == 0:
            break

        if expand_up >= expand_down and va_high_idx < bins - 1:
            va_high_idx += 1
            accumulated += volume_at_price[va_high_idx]
        elif va_low_idx > 0:
            va_low_idx -= 1
            accumulated += volume_at_price[va_low_idx]
        else:
            va_high_idx += 1
            accumulated += volume_at_price[va_high_idx]

    vah = float(bin_edges[va_high_idx + 1])  # upper edge of highest VA bin
    val = float(bin_edges[va_low_idx])        # lower edge of lowest VA bin

    # Build top volume levels for output
    top_n = min(10, bins)
    top_indices = np.argsort(volume_at_price)[-top_n:][::-1]
    top_levels = {
        float(bin_centers[idx]): float(volume_at_price[idx])
        for idx in top_indices
        if volume_at_price[idx] > 0
    }

    actual_va_pct = accumulated / total_volume * 100 if total_volume > 0 else 0
    price_range_pct = (vah - val) / poc * 100 if poc > 0 else 0

    return VolumeProfileResult(
        poc=poc,
        vah=vah,
        val=val,
        poc_volume=poc_volume,
        total_volume=total_volume,
        value_area_pct=actual_va_pct,
        price_range_pct=price_range_pct,
        bins=bins,
        volume_at_price=top_levels,
    )
