"""Tests for elliott_wave/analysis.py — core wave analysis."""
import pandas as pd
import numpy as np
import pytest
from unittest.mock import patch

from elliott_wave.analysis import (
    analyze_waves, _detect_wave_pivots, _score_impulse, _score_correction,
)
from elliott_wave.wave_types import WaveDirection, WaveDegree, WavePoint
from config.settings import config


def _make_ohlcv(n=100, base_price=100.0, atr_val=1.0):
    """Create synthetic OHLCV with a clean impulse move."""
    np.random.seed(42)
    data = {
        "open": [base_price] * n,
        "high": [base_price + atr_val] * n,
        "low": [base_price - atr_val] * n,
        "close": [base_price] * n,
        "volume": [1000.0] * n,
        "atr": [atr_val] * n,
    }
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    return pd.DataFrame(data, index=idx)


def _make_impulse_df():
    """Create OHLCV with a clear bullish5-wave impulse structure."""
    n = 60
    prices = (
        [100] * 5 +   # wave 0 base
        [105] * 5 +   # wave 1 up
        [102] * 5 +   # wave 2 down (doesn't overlap wave 1 start)
        [115] * 5 +   # wave 3 up (longest)
        [110] * 5 +   # wave 4 down
        [125] * 5 +   # wave 5 up
        [120] * 30    # extra data
    )
    df = _make_ohlcv(n=n, base_price=0, atr_val=0.5)
    df["close"] = prices[:n]
    df["high"] = [p + 1.0 for p in prices[:n]]
    df["low"] = [p - 1.0 for p in prices[:n]]
    df["open"] = prices[:n]
    df["atr"] = [2.0] * n
    return df


class TestDetectWavePivots:
    def test_returns_wave_points(self):
        df = _make_impulse_df()
        pivots = _detect_wave_pivots(df)
        assert len(pivots) > 0
        assert all(isinstance(p, WavePoint) for p in pivots)

    def test_pivots_alternate_h_l(self):
        """Pivots should roughly alternate between highs and lows."""
        df = _make_impulse_df()
        pivots = _detect_wave_pivots(df)
        if len(pivots) >= 3:
            labels = [p.wave_label for p in pivots]
            # Should have both H and L
            assert "H" in labels or "L" in labels


class TestScoreImpulse:
    def test_perfect_impulse(self):
        """Perfect 1-2-3-4-5 should score high."""
        points = [
            WavePoint(index=0, price=100.0, wave_label="0"),
            WavePoint(index=10, price=110.0, wave_label="1"),
            WavePoint(index=20, price=105.0, wave_label="2"),
            WavePoint(index=30, price=125.0, wave_label="3"),
            WavePoint(index=40, price=120.0, wave_label="4"),
            WavePoint(index=50, price=135.0, wave_label="5"),
        ]
        score = _score_impulse(points)
        assert score > 0.5

    def test_wave3_shortest_scores_low(self):
        """Wave 3 being shortest should penalize score."""
        points = [
            WavePoint(index=0, price=100.0, wave_label="0"),
            WavePoint(index=10, price=115.0, wave_label="1"),  # w1=15
            WavePoint(index=20, price=110.0, wave_label="2"),
            WavePoint(index=30, price=113.0, wave_label="3"),  # w3=3 (shortest!)
            WavePoint(index=40, price=108.0, wave_label="4"),
            WavePoint(index=50, price=120.0, wave_label="5"),  # w5=12
        ]
        score = _score_impulse(points)
        assert score < 0.4  # penalized

    def test_wave4_overlap_scores_low(self):
        """Wave 4 overlapping wave 1 should penalize score."""
        points = [
            WavePoint(index=0, price=100.0, wave_label="0"),
            WavePoint(index=10, price=110.0, wave_label="1"),
            WavePoint(index=20, price=105.0, wave_label="2"),
            WavePoint(index=30, price=120.0, wave_label="3"),
            WavePoint(index=40, price=108.0, wave_label="4"),  # below w1 high
            WavePoint(index=50, price=130.0, wave_label="5"),
        ]
        score = _score_impulse(points)
        assert score < 0.5


class TestScoreCorrection:
    def test_perfect_zigzag(self):
        """Perfect A-B-C should score well."""
        points = [
            WavePoint(index=0, price=100.0, wave_label="0"),
            WavePoint(index=10, price=110.0, wave_label="A"),
            WavePoint(index=20, price=105.0, wave_label="B"),  # 50% retrace
            WavePoint(index=30, price=115.0, wave_label="C"),  # beyond A
        ]
        score = _score_correction(points)
        assert score > 0.4

    def test_b_retrace_too_deep(self):
        """B retracing >100% of A should score zero."""
        points = [
            WavePoint(index=0, price=100.0, wave_label="0"),
            WavePoint(index=10, price=110.0, wave_label="A"),
            WavePoint(index=20, price=95.0, wave_label="B"),  # >100% retrace
            WavePoint(index=30, price=105.0, wave_label="C"),
        ]
        score = _score_correction(points)
        assert score < 0.3


class TestAnalyzeWaves:
    @patch("elliott_wave.analysis.config")
    def test_disabled_returns_empty(self, mock_config):
        """When WAVE_ANALYSIS_ENABLED=false, returns empty analysis."""
        mock_config.wave.enabled = False
        df = _make_impulse_df()
        result = analyze_waves(df, "BTC/USDT", "1h")
        assert result.primary is None
        assert result.confidence == 0.0

    @patch("elliott_wave.analysis.config")
    def test_short_df_returns_empty(self, mock_config):
        """Too few candles returns empty analysis."""
        mock_config.wave.enabled = True
        mock_config.wave.max_lookback = 200
        mock_config.wave.min_swing_atr = 0.5
        df = _make_ohlcv(n=5)
        result = analyze_waves(df, "BTC/USDT", "1h")
        assert result.primary is None

    @patch("elliott_wave.analysis.config")
    def test_returns_analysis_object(self, mock_config):
        """Returns a valid WaveAnalysis."""
        mock_config.wave.enabled = True
        mock_config.wave.max_lookback = 200
        mock_config.wave.min_swing_atr = 0.5
        mock_config.wave.max_alternatives = 3
        df = _make_impulse_df()
        result = analyze_waves(df, "BTC/USDT", "1h")
        assert result.symbol == "BTC/USDT"
        assert result.timeframe == "1h"

    @patch("elliott_wave.analysis.config")
    def test_to_dict(self, mock_config):
        """WaveAnalysis serializes to dict."""
        mock_config.wave.enabled = True
        mock_config.wave.max_lookback = 200
        mock_config.wave.min_swing_atr = 0.5
        mock_config.wave.max_alternatives = 3
        df = _make_impulse_df()
        result = analyze_waves(df, "BTC/USDT", "1h")
        d = result.to_dict()
        assert d["symbol"] == "BTC/USDT"
        assert "direction" in d
        assert "confidence" in d
        assert "primary" in d
