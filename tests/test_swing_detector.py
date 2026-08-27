"""Tests for market_structure/swing_detector.py — unified swing detection."""
import pandas as pd
import numpy as np
import pytest
from market_structure.swing_detector import (
    detect_swings, filter_significant_swings, SwingPoint, SwingType,
)


def _make_df(highs, lows, closes=None, atrs=None):
    """Create minimal OHLCV DataFrame for testing."""
    n = len(highs)
    if closes is None:
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    data = {
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [1000] * n,
    }
    if atrs is not None:
        data["atr"] = atrs
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    return pd.DataFrame(data, index=idx)


class TestDetectSwingsStrict:
    """Tests for strict 2-neighbor mode (sweep.py behavior)."""

    def test_classic_5bar_fractal_high(self):
        """Classic Bill Williams fractal: high is max of 5 bars."""
        highs = [10, 11, 12, 11, 10, 9, 8]
        lows = [5, 6, 7, 6, 5, 4, 3]
        df = _make_df(highs, lows)
        swings = detect_swings(df, left_bars=2, right_bars=2, strict=True)
        highs_found = [s for s in swings if s.swing_type == SwingType.HIGH]
        assert len(highs_found) == 1
        assert highs_found[0].price == 12.0
        assert highs_found[0].index == 2

    def test_classic_5bar_fractal_low(self):
        """Classic fractal low."""
        highs = [20, 19, 18, 19, 20, 21, 22]
        lows = [15, 14, 13, 14, 15, 16, 17]
        df = _make_df(highs, lows)
        swings = detect_swings(df, left_bars=2, right_bars=2, strict=True)
        lows_found = [s for s in swings if s.swing_type == SwingType.LOW]
        assert len(lows_found) == 1
        assert lows_found[0].price == 13.0
        assert lows_found[0].index == 2

    def test_no_swing_when_neighbor_equal(self):
        """Strict mode: equal neighbor means no swing."""
        highs = [10, 12, 12, 12, 10, 9, 8]
        lows = [5, 6, 7, 6, 5, 4, 3]
        df = _make_df(highs, lows)
        swings = detect_swings(df, left_bars=2, right_bars=2, strict=True)
        highs_found = [s for s in swings if s.swing_type == SwingType.HIGH]
        assert len(highs_found) == 0

    def test_multiple_swings(self):
        """Two distinct swing highs."""
        highs = [10, 11, 12, 11, 10, 11, 12, 11, 10]
        lows = [5, 6, 7, 6, 5, 6, 7, 6, 5]
        df = _make_df(highs, lows)
        swings = detect_swings(df, left_bars=2, right_bars=2, strict=True)
        highs_found = [s for s in swings if s.swing_type == SwingType.HIGH]
        assert len(highs_found) == 2
        assert highs_found[0].price == 12.0
        assert highs_found[1].price == 12.0

    def test_empty_df(self):
        """Empty DataFrame returns empty list."""
        df = _make_df([], [])
        swings = detect_swings(df, left_bars=2, right_bars=2, strict=True)
        assert swings == []

    def test_too_short_df(self):
        """DataFrame shorter than left+right+1 returns empty."""
        df = _make_df([10, 11, 12], [5, 6, 7])
        swings = detect_swings(df, left_bars=2, right_bars=2, strict=True)
        assert swings == []

    def test_timestamp_extracted(self):
        """SwingPoint includes timestamp from DataFrame index."""
        highs = [10, 11, 12, 11, 10, 9, 8]
        lows = [5, 6, 7, 6, 5, 4, 3]
        df = _make_df(highs, lows)
        swings = detect_swings(df, left_bars=2, right_bars=2, strict=True)
        assert len(swings) > 0
        assert swings[0].timestamp is not None


class TestDetectSwingsRolling:
    """Tests for rolling window mode (order_blocks/structure behavior)."""

    def test_rolling_window_high(self):
        """Candidate is max of 11-bar window (left=5, right=5)."""
        # High at index 7 must be max of [2..12]
        highs = [10, 11, 10, 11, 10, 11, 10, 15, 10, 11, 10, 11, 10]
        lows = [5, 6, 5, 6, 5, 6, 5, 8, 5, 6, 5, 6, 5]
        df = _make_df(highs, lows)
        swings = detect_swings(df, left_bars=5, right_bars=5, strict=False)
        highs_found = [s for s in swings if s.swing_type == SwingType.HIGH]
        assert len(highs_found) >= 1
        assert highs_found[0].price == 15.0

    def test_rolling_allows_ties(self):
        """Rolling mode: tied max still counts as swing."""
        # Three equal highs at indices 5,6,7 — all are max of their windows
        highs = [10, 11, 10, 11, 10, 12, 12, 12, 10, 11, 10, 11, 10]
        lows = [5, 6, 5, 6, 5, 6, 6, 6, 5, 6, 5, 6, 5]
        df = _make_df(highs, lows)
        swings = detect_swings(df, left_bars=5, right_bars=5, strict=False)
        highs_found = [s for s in swings if s.swing_type == SwingType.HIGH]
        # Rolling mode: all three 12s are max of their window
        assert len(highs_found) >= 1

    def test_strict_vs_rolling_difference(self):
        """Strict rejects ties, rolling accepts them."""
        highs = [10, 11, 12, 12, 11, 10, 9]
        lows = [5, 6, 7, 6, 5, 4, 3]
        df = _make_df(highs, lows)
        strict_swings = detect_swings(df, left_bars=2, right_bars=2, strict=True)
        rolling_swings = detect_swings(df, left_bars=2, right_bars=2, strict=False)
        strict_highs = [s for s in strict_swings if s.swing_type == SwingType.HIGH]
        rolling_highs = [s for s in rolling_swings if s.swing_type == SwingType.HIGH]
        assert len(strict_highs) == 0  # tied, strict rejects
        assert len(rolling_highs) >= 1  # rolling accepts


class TestSwingPoint:
    """Test SwingPoint dataclass."""

    def test_backward_compat_properties(self):
        """SwingPoint has .type and .candle_index for backward compat."""
        sp = SwingPoint(index=5, price=100.0, swing_type=SwingType.HIGH)
        assert sp.type == "high"
        assert sp.candle_index == 5

    def test_frozen(self):
        """SwingPoint is immutable."""
        sp = SwingPoint(index=0, price=10.0, swing_type=SwingType.LOW)
        with pytest.raises(AttributeError):
            sp.price = 20.0


class TestFilterSignificantSwings:
    """Test noise filter."""

    def test_filters_small_moves(self):
        """Swings with small amplitude relative to ATR are filtered."""
        # Create swings: big move, tiny move, big move
        swings = [
            SwingPoint(index=0, price=100.0, swing_type=SwingType.HIGH),
            SwingPoint(index=5, price=100.5, swing_type=SwingType.LOW),  # tiny
            SwingPoint(index=10, price=110.0, swing_type=SwingType.HIGH),
        ]
        # ATR = 2.0, min_atr_multiple = 0.5 → threshold = 1.0
        df = _make_df(
            [100] * 15, [98] * 15,
            atrs=[2.0] * 15,
        )
        result = filter_significant_swings(swings, df, min_atr_multiple=0.5)
        # The tiny move (0.5 < 1.0 threshold) should be filtered
        assert len(result) == 2
        assert result[0].price == 100.0
        assert result[1].price == 110.0

    def test_keeps_large_moves(self):
        """Swings with large amplitude are kept."""
        swings = [
            SwingPoint(index=0, price=100.0, swing_type=SwingType.HIGH),
            SwingPoint(index=5, price=95.0, swing_type=SwingType.LOW),  # big
            SwingPoint(index=10, price=110.0, swing_type=SwingType.HIGH),
        ]
        df = _make_df(
            [100] * 15, [94] * 15,
            atrs=[2.0] * 15,
        )
        result = filter_significant_swings(swings, df, min_atr_multiple=0.5)
        assert len(result) == 3

    def test_empty_swings(self):
        """Empty input returns empty."""
        result = filter_significant_swings([], _make_df([], []))
        assert result == []

    def test_single_swing(self):
        """Single swing returned as-is."""
        sp = SwingPoint(index=0, price=100.0, swing_type=SwingType.HIGH)
        result = filter_significant_swings([sp], _make_df([100], [98]))
        assert len(result) == 1

    def test_no_atr_column(self):
        """When ATR column missing, all swings kept (no filtering)."""
        swings = [
            SwingPoint(index=0, price=100.0, swing_type=SwingType.HIGH),
            SwingPoint(index=5, price=100.1, swing_type=SwingType.LOW),
        ]
        df = _make_df([100] * 10, [98] * 10)  # no ATR column
        result = filter_significant_swings(swings, df, min_atr_multiple=0.5)
        assert len(result) == 2
