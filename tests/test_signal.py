import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.signal_engine import SignalEngine, SignalType, SignalResult
from indicators.engine import IndicatorValues


@pytest.fixture
def engine():
    return SignalEngine()


def make_ind(**kwargs):
    base = dict(
        symbol="BTC/USDT",
        timeframe="1h",
        close=50000.0,
        high=50100.0,
        low=49900.0,
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
    )
    base.update(kwargs)
    return IndicatorValues(**base)


class TestSignalCriteria:
    def test_adx_filter_no_signal_when_flat(self, engine):
        ind = make_ind(adx=15.0)
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL
        assert result.score == 0

    def test_adx_filter_passes_at_min_threshold(self, engine):
        ind = make_ind(adx=20.0)
        result = engine.evaluate(ind)
        assert result.signal != SignalType.NO_SIGNAL

    def test_adx_filter_blocks_below_min(self, engine):
        ind = make_ind(adx=19.99)
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL

    def test_buy_signal_all_criteria(self, engine):
        ind = make_ind(
            rsi=55.0,
            adx=30.0,
            close=49000.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47000.0,
            ema_slow_prev=47100.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=50.0,
            macd_hist_prev=-10.0,
            volume_sma=900.0,
            volume=1200.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY, f"Got {result.signal}, reasons: {result.reasons}"
        assert result.score >= 4

    def test_sell_signal_all_criteria(self, engine):
        ind = make_ind(
            rsi=45.0,
            adx=30.0,
            close=50000.0,
            ema_fast=49000.0,
            ema_slow=50000.0,
            ema_trend=51000.0,
            ema_fast_prev=49100.0,
            ema_slow_prev=49900.0,
            supertrend_direction=-1,
            supertrend=51000.0,
            macd_hist=-50.0,
            macd_hist_prev=10.0,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=15.0,
            dmi_minus=25.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.SELL, f"Got {result.signal}, reasons: {result.reasons}"
        assert result.score >= 4

    def test_weak_signal_below_threshold(self, engine):
        ind = make_ind(
            rsi=45.0,
            adx=25.0,
            close=49500.0,
            ema_fast=49300.0,
            ema_slow=49200.0,
            ema_trend=49100.0,
            supertrend_direction=-1,
            supertrend=49000.0,
            macd_hist=-10.0,
            volume_sma=1000.0,
            volume=900.0,
            dmi_plus=10.0,
            dmi_minus=20.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL
        assert result.score < 4


class TestSignalResult:
    def test_format_message(self):
        sig = SignalResult(
            signal=SignalType.BUY,
            symbol="BTC/USDT",
            timeframe="1h",
            close=50000.0,
            sl=48500.0,
            tp=53000.0,
            score=5,
            reasons=["ADX > 20 (trending)", "RSI oversold"],
        )
        msg = sig.format_message()
        assert "BUY" in msg or "ПОКУПКА" in msg
        assert "BTC/USDT" in msg
        assert "48500" in msg
        assert "53000" in msg
        assert "5" in msg

    def test_sl_tp_consistency(self):
        sig = SignalResult(
            signal=SignalType.SELL,
            symbol="ETH/USDT",
            timeframe="4h",
            close=3000.0,
            sl=3150.0,
            tp=2700.0,
            score=6,
            reasons=[],
        )
        msg = sig.format_message()
        assert "SELL" in msg or "ПРОДАЖА" in msg
        assert "3150" in msg
        assert "2700" in msg

    def test_is_actionable_buy(self):
        sig = SignalResult(
            signal=SignalType.BUY, symbol="XRP/USDT", timeframe="1h",
            close=1.0, sl=0.95, tp=1.1, score=5, reasons=[],
        )
        assert sig.is_actionable is True

    def test_is_actionable_no_signal(self):
        sig = SignalResult(
            signal=SignalType.NO_SIGNAL, symbol="XRP/USDT", timeframe="1h",
            close=1.0, score=3, reasons=[],
        )
        assert sig.is_actionable is False
