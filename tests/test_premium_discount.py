"""
tests/test_premium_discount.py — Tests for Discount/Premium Zone Detection.
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
        """Price near swing low = discount (fib < 0.3)."""
        df = _make_df(close=95, swing_high=120, swing_low=90)
        result = classify_zone(df, 'bullish', 120, 90)
        assert result.zone_type == ZoneType.DISCOUNT
        assert result.fib_level < 0.3

    def test_premium_zone(self):
        """Price near swing high = premium (fib > 0.7)."""
        df = _make_df(close=115, swing_high=120, swing_low=90)
        result = classify_zone(df, 'bearish', 120, 90)
        assert result.zone_type == ZoneType.PREMIUM
        assert result.fib_level > 0.7

    def test_equilibrium_zone(self):
        """Price in the middle = equilibrium."""
        df = _make_df(close=105, swing_high=120, swing_low=90)
        result = classify_zone(df, 'bullish', 120, 90)
        assert result.zone_type == ZoneType.EQUILIBRIUM
        assert 0.3 <= result.fib_level <= 0.7

    def test_exact_boundary_discount(self):
        """Price at exactly fib 0.3 = discount boundary (<= 0.3)."""
        df = _make_df(close=99, swing_high=120, swing_low=90)
        result = classify_zone(df, 'bullish', 120, 90)
        assert result.zone_type == ZoneType.DISCOUNT
        assert abs(result.fib_level - 0.3) < 0.01

    def test_exact_boundary_premium(self):
        """Price at exactly fib 0.7 = premium boundary (>= 0.7)."""
        df = _make_df(close=111, swing_high=120, swing_low=90)
        result = classify_zone(df, 'bearish', 120, 90)
        assert result.zone_type == ZoneType.PREMIUM
        assert abs(result.fib_level - 0.7) < 0.01

    def test_zero_range_returns_equilibrium(self):
        """When swing_high == swing_low, return equilibrium."""
        df = _make_df(close=100, swing_high=100, swing_low=100)
        result = classify_zone(df, 'bullish', 100, 100)
        assert result.zone_type == ZoneType.EQUILIBRIUM

    def test_distance_metrics(self):
        """distance_to_premium_pct and distance_to_discount_pct should be positive."""
        df = _make_df(close=95, swing_high=120, swing_low=90)
        result = classify_zone(df, 'bullish', 120, 90)
        assert result.distance_to_premium_pct > 0
        assert result.distance_to_discount_pct > 0


class TestGetEntryZoneQuality:
    def test_long_from_discount_reversal(self):
        """Long from discount + reversal = 1.3x (best)."""
        zone = ZoneResult(ZoneType.DISCOUNT, 90, 100, 10, 5, 0.85)
        quality = get_entry_zone_quality(zone, 'bullish', 'reversal')
        assert quality == 1.3

    def test_long_from_discount_continuation(self):
        """Long from discount + continuation = 1.1x."""
        zone = ZoneResult(ZoneType.DISCOUNT, 90, 100, 10, 5, 0.85)
        quality = get_entry_zone_quality(zone, 'bullish', 'continuation')
        assert quality == 1.1

    def test_long_from_premium(self):
        """Long from premium = 0.6x (chasing)."""
        zone = ZoneResult(ZoneType.PREMIUM, 110, 120, 2, 10, 0.15)
        quality = get_entry_zone_quality(zone, 'bullish', 'continuation')
        assert quality == 0.6

    def test_long_from_equilibrium(self):
        """Long from equilibrium = 1.0x (neutral)."""
        zone = ZoneResult(ZoneType.EQUILIBRIUM, 100, 110, 5, 5, 0.5)
        quality = get_entry_zone_quality(zone, 'bullish', 'continuation')
        assert quality == 1.0

    def test_short_from_premium_reversal(self):
        """Short from premium + reversal = 1.3x (best)."""
        zone = ZoneResult(ZoneType.PREMIUM, 110, 120, 2, 10, 0.15)
        quality = get_entry_zone_quality(zone, 'bearish', 'reversal')
        assert quality == 1.3

    def test_short_from_premium_continuation(self):
        """Short from premium + continuation = 1.1x."""
        zone = ZoneResult(ZoneType.PREMIUM, 110, 120, 2, 10, 0.15)
        quality = get_entry_zone_quality(zone, 'bearish', 'continuation')
        assert quality == 1.1

    def test_short_from_discount(self):
        """Short from discount = 0.6x (bad)."""
        zone = ZoneResult(ZoneType.DISCOUNT, 90, 100, 10, 5, 0.85)
        quality = get_entry_zone_quality(zone, 'bearish', 'continuation')
        assert quality == 0.6

    def test_neutral_bias_returns_one(self):
        """Neutral HTF bias → no zone quality adjustment."""
        zone = ZoneResult(ZoneType.DISCOUNT, 90, 100, 10, 5, 0.85)
        quality = get_entry_zone_quality(zone, 'neutral', 'reversal')
        assert quality == 1.0

    def test_short_from_equilibrium(self):
        """Short from equilibrium = 1.0x."""
        zone = ZoneResult(ZoneType.EQUILIBRIUM, 100, 110, 5, 5, 0.5)
        quality = get_entry_zone_quality(zone, 'bearish', 'continuation')
        assert quality == 1.0
