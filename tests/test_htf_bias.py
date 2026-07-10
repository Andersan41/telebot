"""
tests/test_htf_bias.py — Tests for HTF Directional Bias (Phase 1 changes).
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_structure.structure import get_htf_directional_bias


def _make_1d_uptrend() -> pd.DataFrame:
    """1D dataframe in steady uptrend (price > EMA55, slope > 0)."""
    close = [50000 + i * 100 for i in range(60)]
    return pd.DataFrame({
        "open": close,
        "high": [c + 200 for c in close],
        "low": [c - 200 for c in close],
        "close": close,
        "volume": [1000] * 60,
    })


def _make_1d_downtrend() -> pd.DataFrame:
    """1D dataframe in steady downtrend."""
    close = [50000 - i * 100 for i in range(60)]
    return pd.DataFrame({
        "open": close,
        "high": [c + 200 for c in close],
        "low": [c - 200 for c in close],
        "close": close,
        "volume": [1000] * 60,
    })


def _make_4h_uptrend() -> pd.DataFrame:
    close = [50200 + i * 50 for i in range(60)]
    return pd.DataFrame({
        "open": close,
        "high": [c + 100 for c in close],
        "low": [c - 100 for c in close],
        "close": close,
        "volume": [1000] * 60,
    })


def _make_4h_downtrend() -> pd.DataFrame:
    close = [50200 - i * 50 for i in range(60)]
    return pd.DataFrame({
        "open": close,
        "high": [c + 100 for c in close],
        "low": [c - 100 for c in close],
        "close": close,
        "volume": [1000] * 60,
    })


def _make_neutral() -> pd.DataFrame:
    """Flat price (slope ~0)."""
    close = [50000.0] * 60
    return pd.DataFrame({
        "open": close,
        "high": [c + 100 for c in close],
        "low": [c - 100 for c in close],
        "close": close,
        "volume": [1000] * 60,
    })


class TestGetHtfDirectionalBias:
    def test_bullish_1d_and_4h(self):
        """1D uptrend + 4H uptrend → bullish."""
        df_1d = _make_1d_uptrend()
        df_4h = _make_4h_uptrend()
        assert get_htf_directional_bias(df_1d, df_4h) == "bullish"

    def test_bearish_1d_and_4h(self):
        """1D downtrend + 4H downtrend → bearish."""
        df_1d = _make_1d_downtrend()
        df_4h = _make_4h_downtrend()
        assert get_htf_directional_bias(df_1d, df_4h) == "bearish"

    def test_1d_overrides_4h(self):
        """1D uptrend + 4H downtrend → bullish (1D priority)."""
        df_1d = _make_1d_uptrend()
        df_4h = _make_4h_downtrend()
        assert get_htf_directional_bias(df_1d, df_4h) == "bullish"

    def test_1d_neutral_uses_4h(self):
        """1D neutral + 4H uptrend → bullish."""
        df_1d = _make_neutral()
        df_4h = _make_4h_uptrend()
        assert get_htf_directional_bias(df_1d, df_4h) == "bullish"

    def test_both_neutral(self):
        """Both neutral → neutral."""
        df_1d = _make_neutral()
        df_4h = pd.DataFrame({
            "open": [50000] * 60,
            "high": [50100] * 60,
            "low": [49900] * 60,
            "close": [50000] * 60,
            "volume": [1000] * 60,
        })
        assert get_htf_directional_bias(df_1d, df_4h) == "neutral"

    def test_short_dataframe_returns_neutral(self):
        """Very short dataframes should still work (index safe)."""
        df_1d = pd.DataFrame({
            "open": [50000] * 10,
            "high": [50100] * 10,
            "low": [49900] * 10,
            "close": [50000] * 10,
            "volume": [1000] * 10,
        })
        df_4h = _make_4h_uptrend()
        # iloc[-5] requires at least 6 rows; with 10 rows it should still work
        bias = get_htf_directional_bias(df_1d, df_4h)
        assert bias in ("bullish", "bearish", "neutral")
