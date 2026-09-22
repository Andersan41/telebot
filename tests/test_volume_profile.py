"""Tests for liquidity.volume_profile module."""
import numpy as np
import pandas as pd
import pytest

from liquidity.volume_profile import VolumeProfileResult, compute_volume_profile


def _make_df(n=200, seed=42):
    """Create synthetic OHLCV DataFrame with realistic price movement."""
    rng = np.random.RandomState(seed)
    close = 50000 + np.cumsum(rng.randn(n) * 100)
    high = close + rng.uniform(50, 200, n)
    low = close - rng.uniform(50, 200, n)
    open_ = close + rng.randn(n) * 50
    volume = rng.uniform(100, 1000, n)
    dates = pd.date_range("2026-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)


class TestComputeVolumeProfile:
    def test_returns_result(self):
        df = _make_df()
        result = compute_volume_profile(df)
        assert result is not None
        assert isinstance(result, VolumeProfileResult)

    def test_poc_in_range(self):
        df = _make_df()
        result = compute_volume_profile(df)
        assert result.poc >= df["low"].min()
        assert result.poc <= df["high"].max()

    def test_val_below_poc_below_vah(self):
        df = _make_df()
        result = compute_volume_profile(df)
        assert result.val < result.poc < result.vah

    def test_empty_df_returns_none(self):
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        assert compute_volume_profile(df) is None

    def test_short_df_returns_none(self):
        df = _make_df(n=5)
        assert compute_volume_profile(df) is None

    def test_lookback(self):
        df = _make_df(n=200)
        full = compute_volume_profile(df)
        partial = compute_volume_profile(df, lookback=50)
        assert full is not None
        assert partial is not None
        # Partial profile may differ from full
        assert partial.is_valid

    def test_is_valid(self):
        df = _make_df()
        result = compute_volume_profile(df)
        assert result.is_valid

    def test_midpoint(self):
        df = _make_df()
        result = compute_volume_profile(df)
        midpoint = (result.vah + result.val) / 2
        assert abs(result.midpoint - midpoint) < 0.01

    def test_price_in_value_area(self):
        df = _make_df()
        result = compute_volume_profile(df)
        # Price at POC should be in value area
        assert result.price_in_value_area(result.poc)
        # Price way above VAH should not be in value area
        assert not result.price_in_value_area(result.vah * 2)
        # Price way below VAL should not be in value area
        assert not result.price_in_value_area(result.val * 0.5)

    def test_distance_from_price(self):
        df = _make_df()
        result = compute_volume_profile(df)
        dist = result.distance_from_price(result.poc)
        assert dist == 0.0  # distance from POC to itself is 0

    def test_value_area_captures_majority_of_volume(self):
        df = _make_df()
        result = compute_volume_profile(df, value_area_pct=0.70)
        # Value area should capture ~70% of volume
        assert result.value_area_pct >= 60  # allow some tolerance

    def test_volume_at_price_not_empty(self):
        df = _make_df()
        result = compute_volume_profile(df)
        assert len(result.volume_at_price) > 0

    def test_constant_price_returns_none(self):
        """All candles at same price → zero range → None."""
        df = pd.DataFrame({
            "open": [100.0] * 50,
            "high": [100.0] * 50,
            "low": [100.0] * 50,
            "close": [100.0] * 50,
            "volume": [1000.0] * 50,
        })
        result = compute_volume_profile(df)
        assert result is None
