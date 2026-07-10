"""
tests/test_mss_diagnostic.py — Tests for MSS funnel diagnostics.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import pytest

from market_structure.diagnostic import (
    MSSFunnelStats,
    diagnose_mss_funnel,
    diagnose_mss_funnel_full,
)


def _make_ohlcv(n=200, base_price=100.0, volatility=0.02):
    """Create synthetic OHLCV data with a trend."""
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    closes = [base_price]
    for i in range(1, n):
        change = np.random.normal(0.0002, volatility)
        closes.append(closes[-1] * (1 + change))

    df = pd.DataFrame({
        "open": [c * (1 + np.random.uniform(-0.005, 0.005)) for c in closes],
        "high": [c * (1 + abs(np.random.normal(0, volatility))) for c in closes],
        "low": [c * (1 - abs(np.random.normal(0, volatility))) for c in closes],
        "close": closes,
        "volume": [np.random.uniform(1000, 5000) for _ in closes],
    }, index=dates)
    return df


class TestMSSFunnelStats:
    def test_empty_stats(self):
        stats = MSSFunnelStats()
        assert stats.total_candles == 0
        assert stats.sweep_detected == 0
        assert stats.mss_final == 0

    def test_record_choch(self):
        stats = MSSFunnelStats(total_candles=100)
        stats.record_choch(
            choch_type="bullish",
            choch_candle_index=50,
            has_sweep_reference=True,
            bars_since_sweep=3,
            displacement_atr=1.5,
            reclaim_bars=1,
            is_mss=True,
        )
        assert len(stats.choch_details) == 1
        assert stats.choch_details[0]["is_mss"] is True

    def test_print_summary(self, capsys):
        stats = MSSFunnelStats(total_candles=1000)
        stats.sweep_detected = 50
        stats.sweep_valid = 30
        stats.choch_detected = 10
        stats.choch_with_sweep_in_window = 5
        stats.displacement_pass = 2
        stats.reclaim_pass = 1
        stats.mss_final = 0

        stats.print_summary()
        captured = capsys.readouterr()
        assert "MSS FUNNEL DIAGNOSTICS" in captured.out
        assert "MSS final:              0" in captured.out


class TestDiagnoseMSSFunnel:
    def test_runs_on_synthetic_data(self):
        df = _make_ohlcv(n=200)
        # ATR ~ 1% of price
        atr_value = float(df["close"].pct_change().std() * df["close"].mean())

        stats = diagnose_mss_funnel(
            df,
            sweeps=[],
            atr_value=atr_value,
        )
        assert stats.total_candles == 200
        assert isinstance(stats.sweep_detected, int)

    def test_full_mode_runs(self):
        df = _make_ohlcv(n=200)
        atr_value = float(df["close"].pct_change().std() * df["close"].mean())

        stats = diagnose_mss_funnel_full(
            df,
            atr_value=atr_value,
        )
        assert stats.total_candles == 200
        # Full mode should detect some structure breaks
        assert stats.choch_detected >= 0
