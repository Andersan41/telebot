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
            rsi=50.0,
            adx=22.0,
            close=49500.0,
            ema_fast=49300.0,
            ema_slow=49350.0,
            ema_trend=49400.0,
            ema_fast_prev=49320.0,
            ema_slow_prev=49370.0,
            supertrend_direction=-1,
            supertrend=49000.0,
            macd_hist=0.0,
            macd_hist_prev=0.0,
            volume_sma=1000.0,
            volume=900.0,
            dmi_plus=18.0,
            dmi_minus=17.0,
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

    def test_format_message_with_entry_price(self):
        sig = SignalResult(
            signal=SignalType.BUY,
            symbol="BTC/USDT",
            timeframe="1h",
            close=50000.0,
            entry_price=49950.0,
            sl=48500.0,
            tp=53000.0,
            score=5,
            reasons=[],
        )
        msg = sig.format_message()
        assert "Вход" in msg
        assert "49950" in msg

    def test_format_message_without_entry_price(self):
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
        assert "Вход" not in msg

    def test_entry_price_before_sl(self):
        sig = SignalResult(
            signal=SignalType.BUY,
            symbol="BTC/USDT",
            timeframe="1h",
            close=50000.0,
            entry_price=49950.0,
            sl=48500.0,
            tp=53000.0,
            score=5,
            reasons=[],
        )
        msg = sig.format_message()
        entry_idx = msg.index("Вход")
        sl_idx = msg.index("Stop Loss")
        assert entry_idx < sl_idx

    def test_entry_price_in_sell(self):
        sig = SignalResult(
            signal=SignalType.SELL,
            symbol="BTC/USDT",
            timeframe="1h",
            close=50000.0,
            entry_price=50050.0,
            sl=51500.0,
            tp=47000.0,
            score=5,
            reasons=[],
        )
        msg = sig.format_message()
        assert "Вход" in msg
        assert "50050" in msg
        entry_idx = msg.index("Вход")
        sl_idx = msg.index("Stop Loss")
        assert entry_idx < sl_idx


class TestScoreFormulaA6:
    def test_adx_strong_adds_to_both_sides(self, engine):
        ind = make_ind(
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
        assert result.signal == SignalType.BUY
        adx_reasons = [r for r in result.reasons if "strong trend" in r.lower() or "ADX=" in r]
        assert len(adx_reasons) >= 1

    def test_dmi_bonus_buy_side(self, engine):
        ind = make_ind(
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
            dmi_plus=30.0,
            dmi_minus=10.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY
        dmi_reasons = [r for r in result.reasons if "DMI+" in r]
        assert len(dmi_reasons) >= 1

    def test_dmi_bonus_sell_side(self, engine):
        ind = make_ind(
            adx=30.0,
            close=51000.0,
            ema_fast=50000.0,
            ema_slow=51000.0,
            ema_trend=52000.0,
            ema_fast_prev=50100.0,
            ema_slow_prev=50900.0,
            supertrend_direction=-1,
            supertrend=52000.0,
            macd_hist=-50.0,
            macd_hist_prev=10.0,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=10.0,
            dmi_minus=30.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.SELL
        dmi_reasons = [r for r in result.reasons if "DMI-" in r]
        assert len(dmi_reasons) >= 1

    def test_adx_between_min_and_25_no_adx_bonus(self, engine):
        ind = make_ind(
            adx=22.0,
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
        assert result.signal == SignalType.BUY
        assert result.score <= 7

    def test_format_message_shows_8(self):
        sig = SignalResult(
            signal=SignalType.BUY,
            symbol="BTC/USDT",
            timeframe="1h",
            close=50000.0,
            score=6,
            reasons=["reason1", "reason2"],
        )
        msg = sig.format_message()
        assert "(6/8)" in msg
        assert "(6/6)" not in msg

    def test_full_signal_score_8(self, engine):
        ind = make_ind(
            rsi=55.0,
            adx=35.0,
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
            volume=1500.0,
            dmi_plus=32.0,
            dmi_minus=12.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY
        assert result.score == 8
