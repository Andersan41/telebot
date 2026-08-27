"""
tests/test_premium_discount.py — Tests for ICT OTE Zone Detection.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_structure.premium_discount import (
    ZoneType,
    ZoneResult,
    classify_zone,
    get_entry_zone_quality,
)


def _make_df(close: float, swing_high: float, swing_low: float, n: int = 60) -> pd.DataFrame:
    """Create a simple OHLCV DataFrame with given close price."""
    closes = [close] * n
    return pd.DataFrame({
        "open": closes,
        "high": [swing_high] * n,
        "low": [swing_low] * n,
        "close": closes,
        "volume": [1000] * n,
    })


class TestClassifyZone:
    def test_discount_zone(self):
        """Price at fib 0.6 (within ICT OTE 0.5-0.79) = discount for BUY."""
        df = _make_df(close=108, swing_high=120, swing_low=90)  # fib=0.6
        result = classify_zone(df, 'bullish', 120, 90)
        assert result.zone_type == ZoneType.DISCOUNT
        assert 0.5 <= result.fib_level <= 0.79

    def test_premium_zone(self):
        """Price at fib 0.4 (within ICT OTE 0.21-0.5) = premium for SELL."""
        df = _make_df(close=102, swing_high=120, swing_low=90)  # fib=0.4
        result = classify_zone(df, 'bearish', 120, 90)
        assert result.zone_type == ZoneType.PREMIUM
        assert 0.21 <= result.fib_level <= 0.5

    def test_equilibrium_zone(self):
        """Price at fib 0.2 (below OTE) = equilibrium."""
        df = _make_df(close=96, swing_high=120, swing_low=90)  # fib=0.2
        result = classify_zone(df, 'bullish', 120, 90)
        assert result.zone_type == ZoneType.EQUILIBRIUM

    def test_deep_discount(self):
        """Price at fib 0.15 (below OTE) = equilibrium (too deep)."""
        df = _make_df(close=94.5, swing_high=120, swing_low=90)  # fib=0.15
        result = classify_zone(df, 'bullish', 120, 90)
        assert result.zone_type == ZoneType.EQUILIBRIUM

    def test_deep_premium(self):
        """Price at fib 0.85 (above OTE) = equilibrium (too high)."""
        df = _make_df(close=115.5, swing_high=120, swing_low=90)  # fib=0.85
        result = classify_zone(df, 'bearish', 120, 90)
        assert result.zone_type == ZoneType.EQUILIBRIUM

    def test_zero_range_returns_equilibrium(self):
        """When swing_high == swing_low, return equilibrium."""
        df = _make_df(close=100, swing_high=100, swing_low=100)
        result = classify_zone(df, 'bullish', 100, 100)
        assert result.zone_type == ZoneType.EQUILIBRIUM

    def test_distance_metrics(self):
        """distance_to_premium_pct and distance_to_discount_pct should be positive."""
        df = _make_df(close=108, swing_high=120, swing_low=90)
        result = classify_zone(df, 'bullish', 120, 90)
        assert result.distance_to_premium_pct > 0
        assert result.distance_to_discount_pct > 0

    def test_custom_ote_fib_levels(self):
        """OTE zones should respect custom fib levels."""
        df = _make_df(close=103.5, swing_high=120, swing_low=90)  # fib=0.45
        result = classify_zone(df, 'bullish', 120, 90,
                               ote_fib_min=0.45, ote_fib_max=0.75)
        assert result.zone_type == ZoneType.DISCOUNT


class TestGetEntryZoneQuality:
    def test_long_from_discount_reversal(self):
        """Long from discount + reversal = 1.3x (best)."""
        zone = ZoneResult(ZoneType.DISCOUNT, 105, 113.7, 5, 10, 0.6)
        quality = get_entry_zone_quality(zone, 'bullish', 'reversal')
        assert quality == 1.3

    def test_long_from_discount_continuation(self):
        """Long from discount + continuation = 1.1x."""
        zone = ZoneResult(ZoneType.DISCOUNT, 105, 113.7, 5, 10, 0.6)
        quality = get_entry_zone_quality(zone, 'bullish', 'continuation')
        assert quality == 1.1

    def test_long_from_premium(self):
        """Long from premium = 0.6x (chasing)."""
        zone = ZoneResult(ZoneType.PREMIUM, 96.3, 105, 15, 5, 0.4)
        quality = get_entry_zone_quality(zone, 'bullish', 'continuation')
        assert quality == 0.6

    def test_long_from_equilibrium(self):
        """Long from equilibrium = 1.0x (neutral)."""
        zone = ZoneResult(ZoneType.EQUILIBRIUM, 96.3, 113.7, 5, 5, 0.5)
        quality = get_entry_zone_quality(zone, 'bullish', 'continuation')
        assert quality == 1.0

    def test_short_from_premium_reversal(self):
        """Short from premium + reversal = 1.3x (best)."""
        zone = ZoneResult(ZoneType.PREMIUM, 96.3, 105, 15, 5, 0.4)
        quality = get_entry_zone_quality(zone, 'bearish', 'reversal')
        assert quality == 1.3

    def test_short_from_premium_continuation(self):
        """Short from premium + continuation = 1.1x."""
        zone = ZoneResult(ZoneType.PREMIUM, 96.3, 105, 15, 5, 0.4)
        quality = get_entry_zone_quality(zone, 'bearish', 'continuation')
        assert quality == 1.1

    def test_short_from_discount(self):
        """Short from discount = 0.6x (bad)."""
        zone = ZoneResult(ZoneType.DISCOUNT, 105, 113.7, 5, 10, 0.6)
        quality = get_entry_zone_quality(zone, 'bearish', 'continuation')
        assert quality == 0.6

    def test_neutral_bias_returns_one(self):
        """Neutral HTF bias → no zone quality adjustment."""
        zone = ZoneResult(ZoneType.DISCOUNT, 105, 113.7, 5, 10, 0.6)
        quality = get_entry_zone_quality(zone, 'neutral', 'reversal')
        assert quality == 1.0

    def test_short_from_equilibrium(self):
        """Short from equilibrium = 1.0x."""
        zone = ZoneResult(ZoneType.EQUILIBRIUM, 96.3, 113.7, 5, 5, 0.5)
        quality = get_entry_zone_quality(zone, 'bearish', 'continuation')
        assert quality == 1.0
