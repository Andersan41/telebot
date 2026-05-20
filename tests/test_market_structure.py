import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from market_structure.structure import (
    SwingPoint,
    BOS,
    CHoCH,
    StructureState,
    MTFAlignmentResult,
    analyze_structure,
    check_mtf_alignment,
    _parse_timeframe_to_seconds,
)
from market_structure.distance_filter import (
    DistanceFilterResult,
    check_distance_filter,
)
from market_structure.tp_path import (
    Obstacle,
    TPEvaluation,
    evaluate_tp_path,
)


def _make_ohlcv_trending(
    n: int = 100,
    trend: str = "bullish",
    seed: int = 42,
) -> pd.DataFrame:
    """Create OHLCV data with a clear trend."""
    np.random.seed(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")

    if trend == "bullish":
        close = np.linspace(100, 150, n) + np.random.randn(n) * 0.5
    elif trend == "bearish":
        close = np.linspace(150, 100, n) + np.random.randn(n) * 0.5
    else:
        close = np.linspace(120, 125, n) + np.random.randn(n) * 2

    df = pd.DataFrame(
        {
            "open": close + np.random.randn(n) * 0.3,
            "high": close + np.abs(np.random.randn(n)) * 1.5,
            "low": close - np.abs(np.random.randn(n)) * 1.5,
            "close": close,
            "volume": np.random.rand(n) * 1000 + 500,
        },
        index=idx,
    )
    df.index.name = "timestamp"
    return df


class TestParseTimeframe:
    def test_minutes(self):
        assert _parse_timeframe_to_seconds("5m") == 300
        assert _parse_timeframe_to_seconds("15m") == 900

    def test_hours(self):
        assert _parse_timeframe_to_seconds("1h") == 3600
        assert _parse_timeframe_to_seconds("4h") == 14400

    def test_days(self):
        assert _parse_timeframe_to_seconds("1d") == 86400

    def test_weeks(self):
        assert _parse_timeframe_to_seconds("1w") == 604800


class TestAnalyzeStructure:
    def test_bullish_trend(self):
        df = _make_ohlcv_trending(n=100, trend="bullish")
        state = analyze_structure(df, lookback=50, swing_window=3)
        assert state.trend in ("bullish", "ranging")
        assert len(state.swing_points) > 0

    def test_bearish_trend(self):
        df = _make_ohlcv_trending(n=100, trend="bearish")
        state = analyze_structure(df, lookback=50, swing_window=3)
        assert state.trend in ("bearish", "ranging")
        assert len(state.swing_points) > 0

    def test_ranging_market(self):
        df = _make_ohlcv_trending(n=100, trend="ranging")
        state = analyze_structure(df, lookback=50, swing_window=3)
        assert len(state.swing_points) > 0

    def test_empty_dataframe(self):
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        state = analyze_structure(df, lookback=50)
        assert state.trend == "ranging"
        assert state.last_bos is None
        assert state.last_choch is None
        assert len(state.swing_points) == 0

    def test_short_dataframe(self):
        np.random.seed(42)
        idx = pd.date_range("2024-01-01", periods=10, freq="1h", tz="UTC")
        df = pd.DataFrame(
            {
                "open": np.random.rand(10) * 100,
                "high": np.random.rand(10) * 100 + 100,
                "low": np.random.rand(10) * 100,
                "close": np.random.rand(10) * 100 + 50,
                "volume": np.random.rand(10) * 1000,
            },
            index=idx,
        )
        df.index.name = "timestamp"
        state = analyze_structure(df, lookback=50)
        assert state.trend == "ranging"
        assert len(state.swing_points) == 0


class TestDistanceFilter:
    def _make_levels(self, resistance=None, support=None):
        return {
            "1h": {
                "resistance": resistance or [],
                "support": support or [],
            }
        }

    def test_long_blocked_near_resistance(self):
        levels = self._make_levels(resistance=[50500.0])
        result = check_distance_filter(
            direction="long",
            entry_price=50000.0,
            sr_levels=levels,
            threshold_pct=1.5,
        )
        assert result.blocked is True
        assert result.nearest_level == 50500.0
        assert result.distance_pct == 1.0

    def test_long_not_blocked_far_from_resistance(self):
        levels = self._make_levels(resistance=[52000.0])
        result = check_distance_filter(
            direction="long",
            entry_price=50000.0,
            sr_levels=levels,
            threshold_pct=1.5,
        )
        assert result.blocked is False

    def test_short_blocked_near_support(self):
        levels = self._make_levels(support=[49500.0])
        result = check_distance_filter(
            direction="short",
            entry_price=50000.0,
            sr_levels=levels,
            threshold_pct=1.5,
        )
        assert result.blocked is True
        assert result.nearest_level == 49500.0
        assert result.distance_pct == 1.0

    def test_short_not_blocked_far_from_support(self):
        levels = self._make_levels(support=[48000.0])
        result = check_distance_filter(
            direction="short",
            entry_price=50000.0,
            sr_levels=levels,
            threshold_pct=1.5,
        )
        assert result.blocked is False

    def test_no_levels_not_blocked(self):
        levels = {"1h": {"resistance": [], "support": []}}
        result = check_distance_filter(
            direction="long",
            entry_price=50000.0,
            sr_levels=levels,
        )
        assert result.blocked is False

    def test_multiple_timeframes(self):
        levels = {
            "1h": {"resistance": [51000.0], "support": []},
            "4h": {"resistance": [50300.0], "support": []},
        }
        result = check_distance_filter(
            direction="long",
            entry_price=50000.0,
            sr_levels=levels,
            threshold_pct=1.5,
        )
        assert result.blocked is True
        assert result.nearest_level == 50300.0

    def test_uses_config_default(self):
        levels = self._make_levels(resistance=[50100.0])
        result = check_distance_filter(
            direction="long",
            entry_price=50000.0,
            sr_levels=levels,
        )
        assert result.threshold_pct == 1.5


class TestTPPathQuality:
    def _make_levels(self, resistance=None, support=None):
        return {
            "1h": {
                "resistance": resistance or [],
                "support": support or [],
            }
        }

    def test_clear_path_long(self):
        levels = self._make_levels(resistance=[55000.0])
        result = evaluate_tp_path(
            direction="long",
            entry_price=50000.0,
            tp_price=52000.0,
            sr_levels=levels,
        )
        assert result.score == 15
        assert result.blocked is False
        assert len(result.obstacles) == 0

    def test_obstacle_between_entry_and_tp_long(self):
        levels = self._make_levels(resistance=[51000.0])
        result = evaluate_tp_path(
            direction="long",
            entry_price=50000.0,
            tp_price=52000.0,
            sr_levels=levels,
        )
        assert len(result.obstacles) >= 1
        assert result.score in (5, -20, -10)

    def test_clear_path_short(self):
        levels = self._make_levels(support=[45000.0])
        result = evaluate_tp_path(
            direction="short",
            entry_price=50000.0,
            tp_price=48000.0,
            sr_levels=levels,
        )
        assert result.score == 15
        assert result.blocked is False

    def test_obstacle_between_entry_and_tp_short(self):
        levels = self._make_levels(support=[49000.0])
        result = evaluate_tp_path(
            direction="short",
            entry_price=50000.0,
            tp_price=48000.0,
            sr_levels=levels,
        )
        assert len(result.obstacles) >= 1

    def test_tp_near_support_long_reject(self):
        levels = self._make_levels(support=[52000.0])
        result = evaluate_tp_path(
            direction="long",
            entry_price=50000.0,
            tp_price=52050.0,
            sr_levels=levels,
            threshold_pct=1.5,
        )
        assert len(result.obstacles) >= 1
        assert any(o.strength == "strong" for o in result.obstacles)

    def test_tp_near_resistance_short_reject(self):
        levels = self._make_levels(resistance=[48000.0])
        result = evaluate_tp_path(
            direction="short",
            entry_price=50000.0,
            tp_price=48050.0,
            sr_levels=levels,
            threshold_pct=1.5,
        )
        assert len(result.obstacles) >= 1
        assert any(o.strength == "strong" for o in result.obstacles)

    def test_invalid_tp_long(self):
        result = evaluate_tp_path(
            direction="long",
            entry_price=50000.0,
            tp_price=49000.0,
            sr_levels={},
        )
        assert result.blocked is True
        assert result.score == 0

    def test_invalid_tp_short(self):
        result = evaluate_tp_path(
            direction="short",
            entry_price=50000.0,
            tp_price=51000.0,
            sr_levels={},
        )
        assert result.blocked is True
        assert result.score == 0


class TestMTFAlignment:
    @pytest.mark.asyncio
    async def test_no_higher_timeframes(self):
        mock_client = AsyncMock()
        result = await check_mtf_alignment(
            symbol="BTC/USDT",
            direction="bullish",
            primary_tf="1d",
            exchange_client=mock_client,
            required_alignment=2,
            timeframes=["1h"],
        )
        assert result.aligned is True
        assert result.states == {}
        assert result.alignment_state == "bullish_aligned"

    @pytest.mark.asyncio
    async def test_all_aligned(self):
        state = StructureState(trend="bullish")
        df = _make_ohlcv_trending(n=100, trend="bullish", seed=99)
        mock_client = AsyncMock()
        mock_client.fetch_ohlcv = AsyncMock(return_value=df)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("market_structure.structure.analyze_structure", lambda *a, **k: state)
            result = await check_mtf_alignment(
                symbol="BTC/USDT",
                direction="bullish",
                primary_tf="1h",
                exchange_client=mock_client,
                required_alignment=1,
                timeframes=["4h"],
            )
        assert result.aligned is True
        assert result.alignment_state == "bullish_aligned"

    @pytest.mark.asyncio
    async def test_not_aligned(self):
        state = StructureState(trend="bearish")
        df = _make_ohlcv_trending(n=100, trend="bearish", seed=99)
        mock_client = AsyncMock()
        mock_client.fetch_ohlcv = AsyncMock(return_value=df)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("market_structure.structure.analyze_structure", lambda *a, **k: state)
            result = await check_mtf_alignment(
                symbol="BTC/USDT",
                direction="bullish",
                primary_tf="1h",
                exchange_client=mock_client,
                required_alignment=1,
                timeframes=["4h"],
            )
        assert result.aligned is False

    @pytest.mark.asyncio
    async def test_fetch_error(self):
        mock_client = AsyncMock()
        mock_client.fetch_ohlcv = AsyncMock(side_effect=Exception("network error"))

        result = await check_mtf_alignment(
            symbol="BTC/USDT",
            direction="bullish",
            primary_tf="1h",
            exchange_client=mock_client,
            required_alignment=1,
            timeframes=["4h"],
        )
        assert result.aligned is False

    @pytest.mark.asyncio
    async def test_none_data(self):
        mock_client = AsyncMock()
        mock_client.fetch_ohlcv = AsyncMock(return_value=None)

        result = await check_mtf_alignment(
            symbol="BTC/USDT",
            direction="bullish",
            primary_tf="1h",
            exchange_client=mock_client,
            required_alignment=1,
            timeframes=["4h"],
        )
        assert result.aligned is False

    @pytest.mark.asyncio
    async def test_ranging_not_counted_as_aligned(self):
        """Range ≠ aligned. Ranging TF should not count toward alignment."""
        state = StructureState(trend="ranging")
        df = pd.DataFrame({
            "open": [100.0]*100, "high": [100.5]*100,
            "low": [99.5]*100, "close": [100.0]*100,
            "volume": [500.0]*100,
        }, index=pd.date_range("2024-01-01", periods=100, freq="4h", tz="UTC"))

        mock_client = AsyncMock()
        mock_client.fetch_ohlcv = AsyncMock(return_value=df)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("market_structure.structure.analyze_structure", lambda *a, **k: state)
            result = await check_mtf_alignment(
                symbol="BTC/USDT",
                direction="bullish",
                primary_tf="1h",
                exchange_client=mock_client,
                required_alignment=1,
                timeframes=["4h"],
            )
        assert result.aligned is False
        assert result.alignment_state == "ranging"

    @pytest.mark.asyncio
    async def test_mixed_alignment(self):
        """Bullish + bearish TFs → mixed_alignment"""
        call_count = 0
        def mock_analyze(*a, **k):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return StructureState(trend="bullish")
            return StructureState(trend="bearish")

        df = _make_ohlcv_trending(n=100, trend="bullish", seed=10)
        mock_client = AsyncMock()
        mock_client.fetch_ohlcv = AsyncMock(return_value=df)

        with pytest.MonkeyPatch().context() as mp:
            mp.setattr("market_structure.structure.analyze_structure", mock_analyze)
            result = await check_mtf_alignment(
                symbol="BTC/USDT",
                direction="bullish",
                primary_tf="1h",
                exchange_client=mock_client,
                required_alignment=1,
                timeframes=["4h", "1d"],
            )
        assert result.alignment_state == "mixed"
        assert result.aligned is True
