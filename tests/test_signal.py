"""
tests/test_signal.py — Tests for signal_engine data types and SL/TP calculation.

The old SignalEngine.evaluate() with indicator gates has been removed.
ICT Core: Pattern Engine is the sole source of signals.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.signal_engine import SignalType, SignalResult, _calculate_sl_tp
from indicators.engine import IndicatorValues


def make_ind(**kwargs):
    base = dict(
        symbol="BTC/USDT",
        timeframe="1h",
        close=50800.0,
        high=51000.0,
        low=49000.0,
        volume=1200.0,
        ema_fast=49000.0,
        ema_slow=48000.0,
        ema_trend=47000.0,
        ema_fast_prev=48900.0,
        ema_slow_prev=48100.0,
        rsi=60.0,
        macd=100.0,
        macd_signal=50.0,
        macd_hist=30.0,
        macd_hist_prev=20.0,
        adx=30.0,
        dmi_plus=25.0,
        dmi_minus=15.0,
        atr=100.0,
        supertrend=48000.0,
        supertrend_direction=1,
        volume_sma=1000.0,
        volume_delta_pct=None,
    )
    base.update(kwargs)
    return IndicatorValues(**base)


class TestSignalTypes:
    def test_signal_type_values(self):
        assert SignalType.BUY == "BUY"
        assert SignalType.SELL == "SELL"
        assert SignalType.NO_SIGNAL == "NO_SIGNAL"

    def test_signal_result_actionable(self):
        sig = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT", timeframe="1h",
            close=50000.0, sl=48500.0, tp=53000.0, score=5, reasons=[],
        )
        assert sig.is_actionable is True

    def test_signal_result_not_actionable(self):
        sig = SignalResult(
            signal=SignalType.NO_SIGNAL, symbol="BTC/USDT", timeframe="1h",
            close=50000.0, score=3, reasons=[],
        )
        assert sig.is_actionable is False


class TestCalculateSLTP:
    def test_buy_with_bos(self):
        ind = make_ind(atr=100.0, close=50000.0)

        class MockBOS:
            type = "bullish"
            level = 49500.0

        class MockStructure:
            last_bos = MockBOS()

        sl, tp, source = _calculate_sl_tp(ind, SignalType.BUY, MockStructure(), entry=50000.0)
        assert source == "bos"
        assert sl < 50000.0
        assert tp > 50000.0

    def test_sell_with_bos(self):
        ind = make_ind(atr=100.0, close=50000.0)

        class MockBOS:
            type = "bearish"
            level = 50500.0

        class MockStructure:
            last_bos = MockBOS()

        sl, tp, source = _calculate_sl_tp(ind, SignalType.SELL, MockStructure(), entry=50000.0)
        assert source == "bos"
        assert sl > 50000.0
        assert tp < 50000.0

    def test_buy_without_bos_uses_atr(self):
        ind = make_ind(atr=100.0, close=50000.0)
        sl, tp, source = _calculate_sl_tp(ind, SignalType.BUY, entry=50000.0)
        assert source == "atr"
        assert sl < 50000.0
        assert tp > 50000.0
        assert abs(sl - (50000.0 - 100.0 * 1.5)) < 0.01
        assert abs(tp - (50000.0 + 100.0 * 3.0)) < 0.01

    def test_sell_without_bos_uses_atr(self):
        ind = make_ind(atr=100.0, close=50000.0)
        sl, tp, source = _calculate_sl_tp(ind, SignalType.SELL, entry=50000.0)
        assert source == "atr"
        assert sl > 50000.0
        assert tp < 50000.0

    def test_bos_sl_above_entry_fallback_to_atr(self):
        """BOS SL above entry for BUY is invalid — falls back to ATR."""
        ind = make_ind(atr=100.0, close=50000.0)

        class MockBOS:
            type = "bullish"
            level = 51000.0  # above entry

        class MockStructure:
            last_bos = MockBOS()

        sl, tp, source = _calculate_sl_tp(ind, SignalType.BUY, MockStructure(), entry=50000.0)
        assert source == "atr"


class TestFormatMessage:
    def test_buy_format(self):
        sig = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT", timeframe="1h",
            close=50000.0, sl=48500.0, tp=53000.0, score=5, reasons=["test"],
        )
        msg = sig.format_message()
        assert "BUY" in msg or "ПОКУПКА" in msg
        assert "BTC/USDT" in msg
        assert "48500" in msg
        assert "53000" in msg

    def test_sell_format(self):
        sig = SignalResult(
            signal=SignalType.SELL, symbol="ETH/USDT", timeframe="4h",
            close=3000.0, sl=3150.0, tp=2700.0, score=6, reasons=[],
        )
        msg = sig.format_message()
        assert "SELL" in msg or "ПРОДАЖА" in msg
        assert "3150" in msg
        assert "2700" in msg

    def test_entry_price_shown(self):
        sig = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT", timeframe="1h",
            close=50000.0, entry_price=49950.0, sl=48500.0, tp=53000.0,
            score=5, reasons=[],
        )
        msg = sig.format_message()
        assert "Entry:" in msg or "entry" in msg
        assert "49950" in msg


class TestScoreVerdict:
    def test_strong(self):
        sig = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT", timeframe="1h",
            close=50000.0, score=6, reasons=[],
        )
        assert sig.score_verdict == "strong"

    def test_moderate(self):
        sig = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT", timeframe="1h",
            close=50000.0, score=4, reasons=[],
        )
        assert sig.score_verdict == "moderate"

    def test_weak(self):
        sig = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT", timeframe="1h",
            close=50000.0, score=2, reasons=[],
        )
        assert sig.score_verdict == "weak"
