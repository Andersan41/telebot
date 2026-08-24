import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.confirmation_engine import (
    ConfirmationResult,
    find_confirmation,
    _find_micro_bos,
    _find_zone_retest,
    _find_momentum,
)


def _make_5m_df(n: int = 60, seed: int = 42) -> pd.DataFrame:
    """Create standard 5m OHLCV data."""
    np.random.seed(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="5min", tz="UTC")
    close = np.linspace(100, 105, n) + np.random.randn(n) * 0.1
    df = pd.DataFrame(
        {
            "open": close + np.random.randn(n) * 0.05,
            "high": close + np.abs(np.random.randn(n)) * 0.3,
            "low": close - np.abs(np.random.randn(n)) * 0.3,
            "close": close,
            "volume": np.random.rand(n) * 1000 + 500,
        },
        index=idx,
    )
    df.index.name = "timestamp"
    return df


def _make_zone_retest_buy_df() -> pd.DataFrame:
    """5m DataFrame where price dips into a zone and closes above."""
    idx = pd.date_range("2024-01-01", periods=15, freq="5min", tz="UTC")
    prices = [
        101.0, 100.8, 100.6, 100.4, 100.2,  # dip into zone
        100.3, 100.5, 100.6, 100.7, 100.8,  # close above zone lower
        100.9, 101.0, 101.1, 101.2, 101.3,
    ]
    df = pd.DataFrame(
        {
            "open": [p + 0.02 for p in prices],
            "high": [p + 0.2 for p in prices],
            "low": [p - 0.2 for p in prices],
            "close": prices,
            "volume": [1000.0] * 15,
        },
        index=idx,
    )
    df.index.name = "timestamp"
    return df


def _make_momentum_buy_df() -> pd.DataFrame:
    """5m DataFrame with momentum close above zone upper."""
    idx = pd.date_range("2024-01-01", periods=10, freq="5min", tz="UTC")
    prices = [100.0, 100.1, 100.2, 100.3, 100.4, 100.5, 100.7, 100.9, 101.2, 101.5]
    df = pd.DataFrame(
        {
            "open": [p - 0.05 for p in prices],
            "high": [p + 0.2 for p in prices],
            "low": [p - 0.2 for p in prices],
            "close": prices,
            "volume": [1000.0] * 10,
        },
        index=idx,
    )
    df.index.name = "timestamp"
    return df


class TestZoneRetest:
    def test_buy_zone_retest(self):
        df = _make_zone_retest_buy_df()
        zone = (100.5, 100.0)  # (upper, lower)
        result = _find_zone_retest(df, zone, "BUY")
        assert result is not None
        assert result["price"] >= zone[1]

    def test_no_retest_price_not_in_zone(self):
        idx = pd.date_range("2024-01-01", periods=10, freq="5min", tz="UTC")
        df = pd.DataFrame(
            {
                "open": [102.0] * 10,
                "high": [102.5] * 10,
                "low": [101.5] * 10,
                "close": [102.0] * 10,
                "volume": [1000.0] * 10,
            },
            index=idx,
        )
        df.index.name = "timestamp"
        zone = (100.5, 100.0)
        result = _find_zone_retest(df, zone, "BUY")
        assert result is None

    def test_sell_zone_retest(self):
        idx = pd.date_range("2024-01-01", periods=10, freq="5min", tz="UTC")
        prices = [100.0, 100.2, 100.5, 101.0, 101.2, 100.8, 100.3, 100.0, 99.8, 99.5]
        df = pd.DataFrame(
            {
                "open": [p - 0.02 for p in prices],
                "high": [p + 0.3 for p in prices],
                "low": [p - 0.1 for p in prices],
                "close": prices,
                "volume": [1000.0] * 10,
            },
            index=idx,
        )
        df.index.name = "timestamp"
        zone = (101.0, 100.5)
        result = _find_zone_retest(df, zone, "SELL")
        assert result is not None

    def test_insufficient_data(self):
        df = _make_5m_df(n=1)
        result = _find_zone_retest(df, (101.0, 100.0), "BUY")
        assert result is None


class TestMomentum:
    def test_buy_momentum(self):
        df = _make_momentum_buy_df()
        zone = (101.0, 100.8)
        result = _find_momentum(df, zone, "BUY")
        assert result is not None
        assert result["price"] > zone[0]

    def test_no_momentum(self):
        idx = pd.date_range("2024-01-01", periods=5, freq="5min", tz="UTC")
        df = pd.DataFrame(
            {
                "open": [100.0] * 5,
                "high": [100.3] * 5,
                "low": [99.7] * 5,
                "close": [100.0] * 5,
                "volume": [1000.0] * 5,
            },
            index=idx,
        )
        df.index.name = "timestamp"
        zone = (101.0, 100.5)
        result = _find_momentum(df, zone, "BUY")
        assert result is None


class TestFindConfirmation:
    def test_zone_retest_used_when_no_micro_bos(self):
        """Zone retest used when micro-BOS is not found."""
        df = _make_zone_retest_buy_df()
        zone = (100.5, 100.0)
        result = find_confirmation(df, "BUY", entry_zone=zone)
        assert result.confirmed is True
        assert result.trigger_type == "ZONE_RETEST"
        assert 0.5 <= result.confidence <= 0.7

    def test_momentum_fallback(self):
        """Momentum used as last fallback."""
        df = _make_momentum_buy_df()
        # Use zone where no candle dips into zone (all lows above zone_upper)
        # so zone_retest won't match, and momentum close > zone_upper triggers
        zone = (99.0, 98.5)
        result = find_confirmation(df, "BUY", entry_zone=zone)
        assert result.confirmed is True
        assert result.trigger_type == "MOMENTUM"
        assert result.confidence == 0.5

    def test_micro_bos_priority_over_zone(self):
        """Micro-BOS should be preferred over zone retest when both available."""
        df = _make_zone_retest_buy_df()
        zone = (100.5, 100.0)
        fake_bos = {"price": 100.5, "timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc), "type": "bullish"}
        with patch("strategy.confirmation_engine._find_micro_bos", return_value=fake_bos):
            result = find_confirmation(df, "BUY", entry_zone=zone)
        assert result.confirmed is True
        assert result.trigger_type == "MICRO_BOS"
        assert result.confidence == 0.9

    def test_zone_retest_priority_over_momentum(self):
        """Zone retest preferred over momentum when micro-BOS not found."""
        df = _make_momentum_buy_df()
        zone = (101.0, 100.8)
        fake_retest = {"price": 100.5, "timestamp": datetime(2024, 1, 1, tzinfo=timezone.utc), "strength": "strong"}
        with patch("strategy.confirmation_engine._find_zone_retest", return_value=fake_retest):
            result = find_confirmation(df, "BUY", entry_zone=zone)
        assert result.confirmed is True
        assert result.trigger_type == "ZONE_RETEST"
        assert result.confidence == 0.7

    def test_no_confirmation(self):
        """No confirmation when price doesn't match any pattern."""
        idx = pd.date_range("2024-01-01", periods=30, freq="5min", tz="UTC")
        np.random.seed(99)
        close = 100.0 + np.random.randn(30) * 0.01
        df = pd.DataFrame(
            {
                "open": close,
                "high": close + 0.01,
                "low": close - 0.01,
                "close": close,
                "volume": [1000.0] * 30,
            },
            index=idx,
        )
        df.index.name = "timestamp"
        result = find_confirmation(df, "BUY", entry_zone=(110.0, 109.0))
        assert result.confirmed is False
        assert result.trigger_type == "NONE"

    def test_insufficient_data(self):
        df = _make_5m_df(n=2)
        result = find_confirmation(df, "BUY")
        assert result.confirmed is False

    def test_none_dataframe(self):
        result = find_confirmation(None, "BUY")
        assert result.confirmed is False

    def test_result_has_reasons(self):
        df = _make_zone_retest_buy_df()
        result = find_confirmation(df, "BUY", entry_zone=(100.5, 100.0))
        assert len(result.reasons) > 0
