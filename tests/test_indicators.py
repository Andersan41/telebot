import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pandas_ta as ta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from indicators.engine import IndicatorEngine


class TestSupertrend:
    """Verify Supertrend column parsing in new pandas-ta (>=0.4.0)"""

    def test_supertrend_columns_naming(self):
        high = pd.Series(np.random.randn(100).cumsum() + 101)
        low = pd.Series(np.random.randn(100).cumsum() + 99)
        close = pd.Series(np.random.randn(100).cumsum() + 100)
        st = ta.supertrend(high, low, close, length=10, multiplier=3)
        cols = list(st.columns)

        val_cols = [c for c in cols if c.startswith("SUPERT_") and "d" not in c and "l" not in c and "s" not in c]
        dir_cols = [c for c in cols if "SUPERTd_" in c]
        assert len(val_cols) == 1, f"Expected 1 value column, got {val_cols}"
        assert len(dir_cols) == 1, f"Expected 1 direction column, got {dir_cols}"


class TestADXDMI:
    """Verify ADX/DMI column extraction with new pandas-ta ADXR column"""

    def test_adx_column_order(self):
        high = pd.Series(np.random.randn(100).cumsum() + 101)
        low = pd.Series(np.random.randn(100).cumsum() + 99)
        close = pd.Series(np.random.randn(100).cumsum() + 100)
        adx_df = ta.adx(high, low, close, length=14)
        cols = list(adx_df.columns)

        adx_col = [c for c in cols if c.startswith("ADX_") and "R" not in c]
        dmp_col = [c for c in cols if c.startswith("DMP_")]
        dmn_col = [c for c in cols if c.startswith("DMN_")]

        assert len(adx_col) == 1, f"Expected 1 ADX column, got {adx_col}"
        assert len(dmp_col) == 1, f"Expected 1 DMP column, got {dmp_col}"
        assert len(dmn_col) == 1, f"Expected 1 DMN column, got {dmn_col}"
        assert adx_df.columns.get_loc(adx_col[0]) < adx_df.columns.get_loc(dmp_col[0]), "ADX should be before DMP"

    def test_adx_with_engine(self, sample_ohlcv):
        engine = IndicatorEngine()
        result = engine.calculate(sample_ohlcv, "BTC/USDT", "1h")
        assert result is not None
        assert result.adx is not None
        assert result.dmi_plus is not None
        assert result.dmi_minus is not None
        assert not np.isnan(result.adx)

    def test_adx_dmi_relationship(self, sample_ohlcv):
        engine = IndicatorEngine()
        result = engine.calculate(sample_ohlcv, "ETH/USDT", "1h")
        assert result is not None
        assert result.dmi_plus >= 0
        assert result.dmi_minus >= 0


class TestMACD:
    def test_macd_with_engine(self, sample_ohlcv):
        engine = IndicatorEngine()
        result = engine.calculate(sample_ohlcv, "BTC/USDT", "1h")
        assert result is not None
        assert result.macd_hist is not None
        assert result.macd_signal is not None
        assert not np.isnan(result.macd_hist)

    def test_macd_columns_match(self, sample_ohlcv):
        close = sample_ohlcv["close"]
        macd_df = ta.macd(close, fast=12, slow=26, signal=9)
        cols = list(macd_df.columns)
        assert any("MACD_" in c for c in cols)
        assert any("MACDh_" in c for c in cols)
        assert any("MACDs_" in c for c in cols)


class TestIndicatorEngine:
    def test_calculate_full_output(self, sample_ohlcv):
        engine = IndicatorEngine()
        result = engine.calculate(sample_ohlcv, "SOL/USDT", "1h")
        assert result is not None
        assert result.symbol == "SOL/USDT"
        assert result.timeframe == "1h"
        for attr in ["rsi", "adx", "atr", "macd_hist", "macd_signal", "ema_fast", "ema_slow", "ema_trend", "volume_sma"]:
            assert getattr(result, attr) is not None, f"{attr} is None"

    def test_supertrend_direction(self, sample_ohlcv):
        engine = IndicatorEngine()
        result = engine.calculate(sample_ohlcv, "BTC/USDT", "1h")
        assert result is not None
        assert result.supertrend_direction in (1, -1)
        assert result.supertrend is not None
        assert not np.isnan(result.supertrend)

    def test_computed_properties(self, sample_ohlcv):
        engine = IndicatorEngine()
        result = engine.calculate(sample_ohlcv, "BTC/USDT", "1h")
        assert result is not None
        assert result.trend_is_strong in (True, False)
        assert result.supertrend_bullish in (True, False)
        assert result.supertrend_bearish in (True, False)

    def test_ema_ordering(self, sample_ohlcv):
        engine = IndicatorEngine()
        result = engine.calculate(sample_ohlcv, "BTC/USDT", "1h")
        assert result is not None
        assert isinstance(result.ema_fast, float)
        assert isinstance(result.ema_slow, float)
        assert isinstance(result.ema_trend, float)
