"""
market_structure/premium_discount.py — Discount/Premium Zone Detection (ICT).

ICT Optimal Trade Entry (OTE) zones:
- Discount zone: fib 0.5–0.79 (price retraced 50-79% from swing low → good for BUY)
- Premium zone: fib 0.21–0.5 (price retraced 21-50% from top → good for SELL)
- Equilibrium: outside OTE zones

fib_level = (price - swing_low) / (swing_high - swing_low)
- 0.0 = at swing low (deep discount)
- 1.0 = at swing high (deep premium)
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class ZoneType(Enum):
    PREMIUM = 'premium'
    DISCOUNT = 'discount'
    EQUILIBRIUM = 'equilibrium'


@dataclass
class ZoneResult:
    zone_type: ZoneType
    zone_price_low: float
    zone_price_high: float
    distance_to_premium_pct: float
    distance_to_discount_pct: float
    fib_level: float  # 0-1, где 0 = swing low, 1 = swing high


def classify_zone(
    df: pd.DataFrame,
    htf_bias: str,
    swing_high: float,
    swing_low: float,
    ote_fib_min: float = 0.5,
    ote_fib_max: float = 0.79,
) -> ZoneResult:
    """
    Classify current price zone using ICT OTE (Optimal Trade Entry).

    ICT OTE:
    - Discount zone: fib 0.5–0.79 (price in discount → good for BUY)
    - Premium zone: fib 0.21–0.5 (price in premium → good for SELL)
    - Equilibrium: outside OTE zones

    For BUY: price should be in Discount (fib 0.5–0.79)
    For SELL: price should be in Premium (fib 0.21–0.5)
    """
    price = df['close'].iloc[-1]

    range_size = swing_high - swing_low
    if range_size <= 0:
        return ZoneResult(
            ZoneType.EQUILIBRIUM, price, price, 0, 0, 0.5,
        )

    fib_level = (price - swing_low) / range_size

    # ICT OTE zones:
    # Discount (buy zone): fib 0.5–0.79 (price retraced 50-79% from low)
    # Premium (sell zone): fib 0.21–0.5 (price near top, good for shorts)
    if ote_fib_min <= fib_level <= ote_fib_max:
        zone_type = ZoneType.DISCOUNT
    elif (1.0 - ote_fib_max) <= fib_level <= (1.0 - ote_fib_min):
        zone_type = ZoneType.PREMIUM
    else:
        zone_type = ZoneType.EQUILIBRIUM

    if zone_type == ZoneType.DISCOUNT:
        zone_price_low = swing_low + range_size * ote_fib_min
        zone_price_high = swing_low + range_size * ote_fib_max
    elif zone_type == ZoneType.PREMIUM:
        zone_price_low = swing_low + range_size * (1.0 - ote_fib_max)
        zone_price_high = swing_low + range_size * (1.0 - ote_fib_min)
    else:
        zone_price_low = swing_low + range_size * (1.0 - ote_fib_max)
        zone_price_high = swing_low + range_size * ote_fib_max

    return ZoneResult(
        zone_type=zone_type,
        zone_price_low=zone_price_low,
        zone_price_high=zone_price_high,
        distance_to_premium_pct=(swing_high - price) / price * 100,
        distance_to_discount_pct=(price - swing_low) / price * 100,
        fib_level=fib_level,
    )


def get_entry_zone_quality(
    zone_result: ZoneResult,
    htf_bias: str,
    setup_type: str,
) -> float:
    """
    Evaluate entry zone quality based on ICT OTE.
    Returns: multiplier 0.5–1.5

    For BUY: Discount zone (OTE) = high quality, Premium = low quality
    For SELL: Premium zone (OTE) = high quality, Discount = low quality
    """
    if htf_bias == 'bullish':
        if zone_result.zone_type == ZoneType.DISCOUNT:
            return 1.3 if setup_type == 'reversal' else 1.1
        elif zone_result.zone_type == ZoneType.PREMIUM:
            return 0.6
        else:
            return 1.0
    elif htf_bias == 'bearish':
        if zone_result.zone_type == ZoneType.PREMIUM:
            return 1.3 if setup_type == 'reversal' else 1.1
        elif zone_result.zone_type == ZoneType.DISCOUNT:
            return 0.6
        else:
            return 1.0

    return 1.0
