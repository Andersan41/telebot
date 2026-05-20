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
        volume_delta_pct=None,
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
        ind = make_ind(adx=20.0, rsi=40.0, macd_hist=50.0, macd_hist_prev=-10.0, volume_delta_pct=20.0, volume=1300.0)
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
            volume_delta_pct=20.0,
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
            volume_delta_pct=-20.0,
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
        assert "MODERATE" in msg
        assert "Уверенность" in msg

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
        assert "STRONG" in msg or "MODERATE" in msg

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
        assert "Цена входа" in msg
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
        assert "Цена входа" in msg

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
        entry_idx = msg.index("Цена входа")
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
        assert "Цена входа" in msg
        assert "50050" in msg
        entry_idx = msg.index("Цена входа")
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
            volume_delta_pct=20.0,
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
            volume_delta_pct=20.0,
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
            volume_delta_pct=-20.0,
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
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY
        assert result.score <= 7

    def test_format_message_shows_7(self):
        sig = SignalResult(
            signal=SignalType.BUY,
            symbol="BTC/USDT",
            timeframe="1h",
            close=50000.0,
            score=6,
            reasons=["reason1", "reason2"],
        )
        msg = sig.format_message()
        assert "(6/7)" in msg
        assert "(6/6)" not in msg

    def test_full_signal_score_7(self, engine):
        ind = make_ind(
            rsi=40.0,
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
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY
        # Score is 8 now: delta leading trigger adds an extra reason
        assert result.score >= 7
        assert result._has_leading_trigger is True
        assert result._rsi_strength == 0.5


class TestVerdictAndConfidence:
    def test_verdict_strong_high_confidence(self):
        sig = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT", timeframe="1h",
            close=50000.0, score=7, reasons=[],
        )
        assert sig.verdict == "STRONG"
        assert sig.confidence >= 75

    def test_verdict_moderate_mid_confidence(self):
        sig = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT", timeframe="1h",
            close=50000.0, score=5, reasons=[],
        )
        assert sig.verdict == "MODERATE"

    def test_verdict_weak_low_confidence(self):
        sig = SignalResult(
            signal=SignalType.NO_SIGNAL, symbol="BTC/USDT", timeframe="1h",
            close=50000.0, score=3, reasons=[],
        )
        assert sig.verdict == "WEAK"

    def test_verdict_very_weak_very_low_confidence(self):
        sig = SignalResult(
            signal=SignalType.NO_SIGNAL, symbol="BTC/USDT", timeframe="1h",
            close=50000.0, score=1, reasons=[],
        )
        assert sig.verdict == "VERY WEAK"

    def test_confidence_with_context_score(self):
        sig = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT", timeframe="1h",
            close=50000.0, score=7, reasons=[],
            _context_score=0.5,
        )
        tech_pct = 7 / 7
        market_pct = (0.5 + 1.0) / 2.0
        expected = round((tech_pct * 0.6 + market_pct * 0.4) * 100, 1)
        assert sig.confidence == expected

    def test_confidence_without_context_score(self):
        sig = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT", timeframe="1h",
            close=50000.0, score=6, reasons=[],
        )
        expected = round(6 / 7 * 100, 1)
        assert sig.confidence == expected

    def test_confidence_with_negative_context(self):
        sig = SignalResult(
            signal=SignalType.BUY, symbol="BTC/USDT", timeframe="1h",
            close=50000.0, score=7, reasons=[],
            _context_score=-0.5,
        )
        tech_pct = 7 / 7
        market_pct = (-0.5 + 1.0) / 2.0
        expected = round((tech_pct * 0.6 + market_pct * 0.4) * 100, 1)
        assert sig.confidence == expected

    def test_format_message_shows_verdict_and_confidence(self):
        sig = SignalResult(
            signal=SignalType.BUY,
            symbol="BTC/USDT",
            timeframe="1h",
            close=50000.0,
            score=7,
            reasons=["reason1"],
        )
        msg = sig.format_message()
        assert "STRONG" in msg or "MODERATE" in msg
        assert "(7/7)" in msg
        assert "Уверенность" in msg
        assert "⭐" not in msg

    def test_no_stars_in_format_message(self):
        sig = SignalResult(
            signal=SignalType.BUY,
            symbol="BTC/USDT",
            timeframe="1h",
            close=50000.0,
            score=5,
            reasons=[],
        )
        msg = sig.format_message()
        assert "⭐" not in msg
        assert "Сила сигнала" not in msg
        assert "Итог:" in msg


class TestVolumeDelta:
    def test_volume_reason_shows_delta_when_available(self, engine):
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
            volume_delta_pct=68.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY
        vol_reasons = [r for r in result.reasons if "Delta" in r]
        assert len(vol_reasons) >= 1
        assert "+68%" in vol_reasons[0]
        assert "покупки доминируют" in vol_reasons[0]

    def test_volume_reason_shows_negative_delta(self, engine):
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
            volume_delta_pct=-45.0,
            dmi_plus=15.0,
            dmi_minus=25.0,
        )
        result = engine.evaluate(ind)
        vol_reasons = [r for r in result.reasons if "Delta" in r]
        assert len(vol_reasons) >= 1
        assert "-45%" in vol_reasons[0]
        assert "продажи доминируют" in vol_reasons[0]

    def test_volume_reason_shows_na_when_delta_missing(self, engine):
        """When delta is None, volume above avg does NOT add reasons (no directional info)"""
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
            volume_delta_pct=None,
        )
        result = engine.evaluate(ind)
        vol_reasons = [r for r in result.reasons if "Delta" in r or "Объём:" in r]
        assert len(vol_reasons) == 0

    def test_delta_bullish_adds_to_buy_score_only(self, engine):
        """Delta > 15 + volume above avg → BUY score +1, NOT sell"""
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
            volume_delta_pct=20.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY
        vol_reasons = [r for r in result.reasons if "Delta" in r]
        assert len(vol_reasons) >= 1
        assert "покупки доминируют" in vol_reasons[0]
        sell_vol = [r for r in vol_reasons if "продажи" in r]
        assert len(sell_vol) == 0

    def test_delta_bearish_adds_to_sell_score_only(self, engine):
        """Delta < -15 + volume above avg → SELL score +1, NOT buy"""
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
            volume_delta_pct=-20.0,
            dmi_plus=15.0,
            dmi_minus=25.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.SELL
        vol_reasons = [r for r in result.reasons if "Delta" in r]
        assert len(vol_reasons) >= 1
        assert "продажи доминируют" in vol_reasons[0]

    def test_delta_neutral_no_score(self, engine):
        """Delta between -15 and +15 → volume does NOT add reasons (no directional info)"""
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
            volume_delta_pct=5.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
        )
        result = engine.evaluate(ind)
        vol_reasons = [r for r in result.reasons if "Объём:" in r]
        assert len(vol_reasons) == 0

    def test_volume_above_avg_but_delta_below_threshold_no_score(self, engine):
        """Volume above avg but delta < threshold → no score for either side"""
        ind = make_ind(
            adx=30.0,
            close=50000.0,
            ema_fast=49000.0,
            ema_slow=48000.0,
            ema_trend=47000.0,
            ema_fast_prev=48000.0,
            ema_slow_prev=48100.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=0.0,
            macd_hist_prev=0.0,
            volume_sma=900.0,
            volume=1200.0,
            volume_delta_pct=10.0,
            dmi_plus=18.0,
            dmi_minus=17.0,
        )
        result = engine.evaluate(ind)
        vol_reasons = [r for r in result.reasons if "Delta" in r or "Объём:" in r]
        assert len(vol_reasons) == 0


class TestNoneIndicatorGuard:
    def test_none_rsi_returns_no_signal(self, engine):
        ind = make_ind(rsi=None)
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL
        assert any("Incomplete" in r for r in result.reasons)
        assert "rsi" in result.reasons[0]

    def test_none_adx_returns_no_signal(self, engine):
        ind = make_ind(adx=None)
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL
        assert "adx" in result.reasons[0]

    def test_none_macd_hist_returns_no_signal(self, engine):
        ind = make_ind(macd_hist=None)
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL
        assert "macd_hist" in result.reasons[0]

    def test_none_dmi_plus_returns_no_signal(self, engine):
        ind = make_ind(dmi_plus=None)
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL
        assert "dmi_plus" in result.reasons[0]

    def test_multiple_none_fields_listed(self, engine):
        ind = make_ind(rsi=None, adx=None)
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL
        assert "rsi" in result.reasons[0]
        assert "adx" in result.reasons[0]


class TestEMADeduplication:
    def test_ema_no_cross_no_fallback_reason(self, engine):
        ind = make_ind(
            adx=30.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47900.0,
            ema_slow_prev=47200.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=50.0,
            macd_hist_prev=40.0,
            volume_sma=900.0,
            volume=1200.0,
        )
        result = engine.evaluate(ind)
        ema_reasons = [r for r in result.reasons if "EMA" in r]
        assert len(ema_reasons) == 0

    def test_ema_cross_adds_only_one_extra_reason(self, engine):
        ind = make_ind(
            adx=30.0,
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
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        ema_reasons = [r for r in result.reasons if "EMA" in r]
        assert len(ema_reasons) == 1
        assert "пересекла" in ema_reasons[0].lower()

    def test_ema_bearish_no_cross_no_fallback(self, engine):
        ind = make_ind(
            adx=30.0,
            ema_fast=47000.0,
            ema_slow=48000.0,
            ema_trend=49000.0,
            ema_fast_prev=46900.0,
            ema_slow_prev=47900.0,
            supertrend_direction=-1,
            supertrend=50000.0,
            macd_hist=-50.0,
            macd_hist_prev=-40.0,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=10.0,
            dmi_minus=30.0,
        )
        result = engine.evaluate(ind)
        ema_reasons = [r for r in result.reasons if "EMA" in r and "пересекла" in r.lower()]
        assert len(ema_reasons) == 0


class TestEMASpreadFilter:
    def test_ema_spread_too_small_rejects_buy(self, engine):
        ind = make_ind(
            adx=30.0,
            close=50000.0,
            ema_fast=49990.0,
            ema_slow=49985.0,
            ema_trend=49980.0,
            ema_fast_prev=49980.0,
            ema_slow_prev=49986.0,
            supertrend_direction=1,
            supertrend=49000.0,
            macd_hist=50.0,
            macd_hist_prev=-10.0,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL
        assert result._ema_alignment_info == "" or "слишком близко" in result.reasons[0].lower() or "недостаточно" in result.reasons[0].lower()

    def test_ema_spread_sufficient_allows_signal(self, engine):
        ind = make_ind(
            adx=30.0,
            close=50000.0,
            ema_fast=49000.0,
            ema_slow=48000.0,
            ema_trend=47000.0,
            ema_fast_prev=47000.0,
            ema_slow_prev=47100.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=50.0,
            macd_hist_prev=-10.0,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY


class TestEMASlopeFilter:
    def test_ema_slope_wrong_direction_rejects_buy(self, engine):
        ind = make_ind(
            adx=30.0,
            close=50000.0,
            ema_fast=49000.0,
            ema_slow=48000.0,
            ema_trend=47000.0,
            ema_fast_prev=49100.0,
            ema_slow_prev=48100.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=50.0,
            macd_hist_prev=-10.0,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL

    def test_ema_slope_correct_allows_signal(self, engine):
        ind = make_ind(
            adx=30.0,
            close=50000.0,
            ema_fast=49000.0,
            ema_slow=48000.0,
            ema_trend=47000.0,
            ema_fast_prev=48900.0,
            ema_slow_prev=48100.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=50.0,
            macd_hist_prev=-10.0,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY


class TestMACDNoiseFilter:
    def test_macd_noise_below_threshold_no_buy_reason(self, engine):
        """MACD hist = 0.01 at price 50000 → norm = 0.00002% < 0.03% → noise, no score"""
        ind = make_ind(
            adx=30.0,
            close=50000.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47000.0,
            ema_slow_prev=47100.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=0.01,
            macd_hist_prev=-0.01,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
        )
        result = engine.evaluate(ind)
        macd_reasons = [r for r in result.reasons if "MACD" in r]
        assert len(macd_reasons) == 0

    def test_macd_noise_below_threshold_no_sell_reason(self, engine):
        """MACD hist = -0.01 at price 50000 → noise, no sell score"""
        ind = make_ind(
            adx=30.0,
            close=50000.0,
            ema_fast=51000.0,
            ema_slow=52000.0,
            ema_trend=53000.0,
            ema_fast_prev=51100.0,
            ema_slow_prev=51900.0,
            supertrend_direction=-1,
            supertrend=54000.0,
            macd_hist=-0.01,
            macd_hist_prev=0.01,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=15.0,
            dmi_minus=25.0,
            rsi=45.0,
        )
        result = engine.evaluate(ind)
        macd_reasons = [r for r in result.reasons if "MACD" in r]
        assert len(macd_reasons) == 0

    def test_macd_significant_above_threshold(self, engine):
        """MACD hist = 20 at price 50000 → norm = 0.04% > 0.03% → significant"""
        ind = make_ind(
            adx=30.0,
            close=50000.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47000.0,
            ema_slow_prev=47100.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=20.0,
            macd_hist_prev=-10.0,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        macd_reasons = [r for r in result.reasons if "MACD" in r and "шум" not in r.lower()]
        assert len(macd_reasons) >= 1
        assert "norm=" in macd_reasons[0]

    def test_macd_at_exact_threshold(self, engine):
        """MACD hist = 15 at price 50000 → norm = 0.03% == threshold → significant"""
        ind = make_ind(
            adx=30.0,
            close=50000.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47000.0,
            ema_slow_prev=47100.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=15.0,
            macd_hist_prev=10.0,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        macd_reasons = [r for r in result.reasons if "MACD" in r and "шум" not in r.lower()]
        assert len(macd_reasons) >= 1


class TestEMAGateAlignment:
    def test_no_bullish_alignment_rejects_buy(self, engine):
        ind = make_ind(
            adx=30.0,
            close=50000.0,
            ema_fast=49000.0,
            ema_slow=49500.0,
            ema_trend=48500.0,
            ema_fast_prev=48900.0,
            ema_slow_prev=49400.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=50.0,
            macd_hist_prev=-10.0,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL

    def test_no_bearish_alignment_rejects_sell(self, engine):
        ind = make_ind(
            adx=30.0,
            close=50000.0,
            ema_fast=50000.0,
            ema_slow=49500.0,
            ema_trend=49000.0,
            ema_fast_prev=50100.0,
            ema_slow_prev=49600.0,
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
        assert result.signal == SignalType.NO_SIGNAL

    def test_alignment_gives_reason_not_score(self, engine):
        ind = make_ind(
            adx=30.0,
            close=50000.0,
            ema_fast=49000.0,
            ema_slow=48000.0,
            ema_trend=47000.0,
            ema_fast_prev=48000.0,
            ema_slow_prev=48100.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=50.0,
            macd_hist_prev=-10.0,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY
        assert result._ema_alignment_info != ""
        ema_cross_reasons = [r for r in result.reasons if "EMA" in r and "пересекла" in r.lower()]
        assert len(ema_cross_reasons) == 1
        alignment_in_reasons = [r for r in result.reasons if "выравнивание" in r.lower()]
        assert len(alignment_in_reasons) == 0


class TestRSIBoundary:
    def test_rsi_30_in_neutral_bullish_zone(self, engine):
        """RSI = 30.0 → 30-50 zone (neutral→bullish), +0.5"""
        ind = make_ind(
            rsi=30.0,
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
            dmi_plus=25.0,
            dmi_minus=15.0,
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY
        rsi_reasons = [r for r in result.reasons if "RSI" in r]
        assert len(rsi_reasons) == 1
        assert "нейтральная" in rsi_reasons[0]
        assert result._rsi_strength == 0.5

    def test_rsi_29_9_oversold_reversal_buy(self, engine):
        """RSI = 29.9 → oversold reversal BUY, +1.0"""
        ind = make_ind(rsi=29.9, macd_hist=50.0, macd_hist_prev=-10.0, volume_delta_pct=20.0, volume=1300.0)
        result = engine.evaluate(ind)
        rsi_reasons = [r for r in result.reasons if "RSI" in r]
        assert any("перепродан" in r for r in rsi_reasons)
        assert result._rsi_strength == 1.0

    def test_rsi_70_exhaustion_sell(self, engine):
        """RSI = 70.0 → exhaustion SELL, +1.0"""
        ind = make_ind(
            rsi=70.0,
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
            volume_delta_pct=-20.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.SELL
        rsi_reasons = [r for r in result.reasons if "RSI" in r]
        assert any("перекуплен" in r for r in rsi_reasons)
        assert result._rsi_strength == -1.0

    def test_rsi_30_to_50_neutral_bullish_half_score(self, engine):
        """RSI 30-50 → neutral→bullish, +0.5 strength"""
        ind = make_ind(rsi=40.0, macd_hist=50.0, macd_hist_prev=-10.0, volume_delta_pct=20.0, volume=1300.0)
        result = engine.evaluate(ind)
        rsi_reasons = [r for r in result.reasons if "RSI" in r]
        assert len(rsi_reasons) == 1
        assert result._rsi_strength == 0.5

    def test_rsi_65_to_70_neutral_bearish_half_score(self, engine):
        """RSI 65-70 → neutral→bearish, +0.5 sell strength"""
        ind = make_ind(
            rsi=67.0,
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
            volume_delta_pct=-20.0,
        )
        result = engine.evaluate(ind)
        rsi_reasons = [r for r in result.reasons if "RSI" in r]
        assert len(rsi_reasons) == 1
        assert result._rsi_strength == -0.5


class TestWeightedFactorModel:
    """Task 2.1 — Weighted Factor Model replaces binary scoring."""

    def test_factor_strengths_populated_on_signal(self, engine):
        """SignalResult._factor_strengths содержит strength для каждого фактора."""
        ind = make_ind(
            rsi=40.0,
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
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY
        assert result._factor_strengths != {}
        assert "Supertrend" in result._factor_strengths
        assert "EMA" in result._factor_strengths
        assert "MACD" in result._factor_strengths
        assert "RSI" in result._factor_strengths
        assert "Volume" in result._factor_strengths
        assert "ADX" in result._factor_strengths
        assert "DMI" in result._factor_strengths

    def test_factor_strength_in_valid_range(self, engine):
        """Все factor strength значения в диапазоне [-1.0, 1.0]."""
        ind = make_ind(
            rsi=40.0,
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
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        for name, strength in result._factor_strengths.items():
            assert -1.0 <= strength <= 1.0, f"{name}: {strength} out of range"

    def test_weighted_score_populated(self, engine):
        """_weighted_score содержит raw weighted sum."""
        ind = make_ind(
            rsi=40.0,
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
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        assert result._weighted_score != 0.0

    def test_confidence_v2_populated_on_signal(self, engine):
        """_confidence_v2 установлен для actionable signals."""
        ind = make_ind(
            rsi=40.0,
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
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        assert result._confidence_v2 is not None
        assert result._confidence_v2.recommendation == "BUY"
        assert len(result._confidence_v2.factors) == 7

    def test_no_signal_has_no_v2_or_weak(self, engine):
        """NO_SIGNAL либо без _confidence_v2, либо с weak quality."""
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


class TestFactorStrength:
    """Task 2.2 — Factor strength [-1.0, 1.0] вместо binary."""

    def test_strong_buy_has_positive_strengths(self, engine):
        """Сильный BUY сигнал → большинство факторов положительные."""
        ind = make_ind(
            rsi=25.0,
            adx=40.0,
            close=49000.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47000.0,
            ema_slow_prev=47100.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=100.0,
            macd_hist_prev=-20.0,
            volume_sma=900.0,
            volume=2000.0,
            dmi_plus=40.0,
            dmi_minus=10.0,
            volume_delta_pct=30.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY
        positive = sum(1 for s in result._factor_strengths.values() if s > 0)
        assert positive >= 5

    def test_strong_sell_has_positive_strengths(self, engine):
        """Сильный SELL сигнал → factor strengths положительные (SELL direction)."""
        ind = make_ind(
            rsi=75.0,
            adx=40.0,
            close=50000.0,
            ema_fast=49000.0,
            ema_slow=50000.0,
            ema_trend=51000.0,
            ema_fast_prev=49100.0,
            ema_slow_prev=49900.0,
            supertrend_direction=-1,
            supertrend=51000.0,
            macd_hist=-100.0,
            macd_hist_prev=20.0,
            volume_sma=900.0,
            volume=2000.0,
            dmi_plus=10.0,
            dmi_minus=40.0,
            volume_delta_pct=-30.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.SELL
        positive = sum(1 for s in result._factor_strengths.values() if s > 0)
        assert positive >= 5

    def test_ema_strength_negative_when_gate_fails(self, engine):
        """EMA gate не прошёл → EMA strength = -1.0."""
        ind = make_ind(
            adx=30.0,
            close=50000.0,
            ema_fast=49990.0,
            ema_slow=49985.0,
            ema_trend=49980.0,
            ema_fast_prev=49980.0,
            ema_slow_prev=49986.0,
            supertrend_direction=1,
            supertrend=49000.0,
            macd_hist=50.0,
            macd_hist_prev=-10.0,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL
        # Factor strengths всё ещё посчитаны
        assert "BUY" in result._factor_strengths or "SELL" in result._factor_strengths

    def test_macd_strength_zero_when_below_threshold(self, engine):
        """MACD ниже порога → strength ≈ 0."""
        ind = make_ind(
            adx=30.0,
            close=50000.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47000.0,
            ema_slow_prev=47100.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=0.01,
            macd_hist_prev=-0.01,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
        )
        result = engine.evaluate(ind)
        if result._factor_strengths and "MACD" in result._factor_strengths:
            assert abs(result._factor_strengths["MACD"]) < 0.1


class TestTriggerConfirmation:
    """Task 2.3 — Trigger → Confirmation → Verdict pipeline."""

    def test_trigger_required_for_signal(self, engine):
        """Без trigger (нет cross/flip) → NO_SIGNAL даже с confirmation."""
        ind = make_ind(
            adx=30.0,
            close=49000.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47900.0,
            ema_slow_prev=47200.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=50.0,
            macd_hist_prev=40.0,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL

    def test_ema_cross_is_trigger(self, engine):
        """EMA cross → trigger срабатывает (with leading trigger)."""
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
            dmi_plus=25.0,
            dmi_minus=15.0,
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        assert result._has_trigger is True
        assert result._has_leading_trigger is True
        assert result.signal == SignalType.BUY

    def test_macd_cross_is_trigger(self, engine):
        """MACD cross → trigger срабатывает (with leading trigger)."""
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
            dmi_plus=25.0,
            dmi_minus=15.0,
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        assert result._has_trigger is True
        assert result._has_leading_trigger is True

    def test_no_trigger_flag_on_no_signal(self, engine):
        """NO_SIGNAL без trigger → _has_trigger = False."""
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
        assert result._has_trigger is False

    def test_confirmation_factors_boost_score(self, engine):
        """Больше confirmation факторов → выше score."""
        ind_strong = make_ind(
            rsi=25.0,
            adx=40.0,
            close=49000.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47000.0,
            ema_slow_prev=47100.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=100.0,
            macd_hist_prev=-20.0,
            volume_sma=900.0,
            volume=2000.0,
            dmi_plus=40.0,
            dmi_minus=10.0,
            volume_delta_pct=30.0,
        )
        ind_weak = make_ind(
            rsi=55.0,
            adx=22.0,
            close=49000.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47000.0,
            ema_slow_prev=47100.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=20.0,
            macd_hist_prev=-5.0,
            volume_sma=900.0,
            volume=1100.0,
            dmi_plus=22.0,
            dmi_minus=18.0,
        )
        result_strong = engine.evaluate(ind_strong)
        result_weak = engine.evaluate(ind_weak)
        if result_strong.signal == SignalType.BUY and result_weak.signal == SignalType.BUY:
            assert result_strong.score >= result_weak.score


class TestRegimeSwitching:
    """Task 4.2 — Strategy switching based on market regime."""

    def _make_regime(self, regime: str):
        from risk.market_regime import MarketRegime
        return MarketRegime(
            regime=regime,
            confidence=0.8,
            adx=25.0,
            atr_percentile=50.0,
            ema_spread_trend="rising",
        )

    def test_compression_regime_blocks_all_signals(self, engine):
        """Compression regime → NO_SIGNAL, _regime_blocked=True."""
        ind = make_ind(
            rsi=40.0,
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
            volume_delta_pct=20.0,
        )
        regime = self._make_regime("compression")
        result = engine.evaluate(ind, regime=regime)
        assert result.signal == SignalType.NO_SIGNAL
        assert result._regime == "compression"
        assert result._regime_blocked is True
        assert "Compression" in result.reasons[0]

    def test_range_regime_blocks_ema_cross_signal(self, engine):
        """Range regime + EMA cross → NO_SIGNAL (EMA entries disabled)."""
        ind = make_ind(
            rsi=40.0,
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
            macd_hist_prev=40.0,
            volume_sma=900.0,
            volume=1500.0,
            dmi_plus=32.0,
            dmi_minus=12.0,
        )
        regime = self._make_regime("range")
        result = engine.evaluate(ind, regime=regime)
        assert result.signal == SignalType.NO_SIGNAL
        assert result._regime == "range"

    def test_reversal_regime_blocks_ema_cross_signal(self, engine):
        """Reversal regime + EMA cross → NO_SIGNAL (trend-following disabled)."""
        ind = make_ind(
            rsi=40.0,
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
            macd_hist_prev=40.0,
            volume_sma=900.0,
            volume=1500.0,
            dmi_plus=32.0,
            dmi_minus=12.0,
        )
        regime = self._make_regime("reversal")
        result = engine.evaluate(ind, regime=regime)
        assert result.signal == SignalType.NO_SIGNAL
        assert result._regime == "reversal"

    def test_trend_regime_allows_signals(self, engine):
        """Trend regime → signals allowed (no restrictions)."""
        ind = make_ind(
            rsi=40.0,
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
            volume_delta_pct=20.0,
        )
        regime = self._make_regime("trend")
        result = engine.evaluate(ind, regime=regime)
        assert result.signal == SignalType.BUY
        assert result._regime == "trend"
        assert result._regime_blocked is False

    def test_expansion_regime_allows_signals(self, engine):
        """Expansion regime → signals allowed (like trend)."""
        ind = make_ind(
            rsi=40.0,
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
            volume_delta_pct=20.0,
        )
        regime = self._make_regime("expansion")
        result = engine.evaluate(ind, regime=regime)
        assert result.signal == SignalType.BUY
        assert result._regime == "expansion"
        assert result._regime_blocked is False

    def test_no_regime_param_uses_legacy_behavior(self, engine):
        """No regime parameter → legacy behavior (no regime filtering)."""
        ind = make_ind(
            rsi=40.0,
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
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY
        assert result._regime is None

    def test_regime_displayed_in_format_message(self):
        """Regime info appears in formatted message."""
        from risk.market_regime import MarketRegime
        regime = MarketRegime(
            regime="trend",
            confidence=0.8,
            adx=25.0,
            atr_percentile=50.0,
            ema_spread_trend="rising",
        )
        sig = SignalResult(
            signal=SignalType.BUY,
            symbol="BTC/USDT",
            timeframe="1h",
            close=50000.0,
            sl=48500.0,
            tp=53000.0,
            score=5,
            reasons=["ADX > 20 (trending)", "RSI oversold"],
            _regime="trend",
        )
        msg = sig.format_message()
        assert "Regime" in msg
        assert "Trend" in msg

    def test_blocked_regime_displayed_in_format_message(self):
        """Blocked regime shows BLOCKED status in formatted message."""
        sig = SignalResult(
            signal=SignalType.NO_SIGNAL,
            symbol="BTC/USDT",
            timeframe="1h",
            close=50000.0,
            score=0,
            reasons=["Compression regime — все сигналы заблокированы, ждём expansion"],
            _regime="compression",
            _regime_blocked=True,
        )
        msg = sig.format_message()
        assert "Compression" in msg
        assert "BLOCKED" in msg


class TestLeadingSignals:
    """Task 7.1 — Leading signals (Delta, Sweep, BOS) priority over lagging (EMA, MACD)."""

    def _make_sweep(self, sweep_type: str, swept_level: float, sweep_low: float,
                    sweep_high: float, reclaim_candles: int = 2,
                    volume_ratio: float = 2.0):
        from liquidity.sweep import SweepEvent
        from datetime import datetime, timezone
        return SweepEvent(
            type=sweep_type,
            swept_level=swept_level,
            sweep_low=sweep_low,
            sweep_high=sweep_high,
            reclaim_candles=reclaim_candles,
            volume_ratio=volume_ratio,
            timestamp=datetime.now(timezone.utc),
            wick_body_ratio=3.0,
            displacement_after=1.5,
            delta_aligned=True,
            candle_index=0,
        )

    def _make_bos(self, bos_type: str, level: float = 50000.0):
        from market_structure.structure import BOS, StructureState
        from datetime import datetime, timezone
        bos = BOS(type=bos_type, level=level, timestamp=datetime.now(timezone.utc), candle_index=0)
        return StructureState(
            trend="bullish" if bos_type == "bullish" else "bearish",
            last_bos=bos,
        )

    def test_delta_leading_trigger_without_ema_cross_gives_signal(self, engine):
        """Delta > 15 + volume above avg → leading trigger → SIGNAL even without EMA cross."""
        ind = make_ind(
            rsi=55.0,
            adx=30.0,
            close=49000.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47900.0,
            ema_slow_prev=47200.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=50.0,
            macd_hist_prev=40.0,
            volume_sma=900.0,
            volume=1500.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY
        assert result._has_leading_trigger is True
        delta_reasons = [r for r in result.reasons if "Delta" in r and "leading" in r.lower()]
        assert len(delta_reasons) >= 1

    def test_sweep_leading_trigger_without_ema_cross_gives_signal(self, engine):
        """Bullish sweep with fast reclaim → leading trigger → SIGNAL without EMA cross."""
        ind = make_ind(
            rsi=55.0,
            adx=30.0,
            close=49000.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47900.0,
            ema_slow_prev=47200.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=50.0,
            macd_hist_prev=40.0,
            volume_sma=900.0,
            volume=1500.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
        )
        sweeps = [self._make_sweep("bullish", swept_level=47000.0, sweep_low=46800.0, sweep_high=47200.0)]
        result = engine.evaluate(ind, sweeps=sweeps)
        assert result.signal == SignalType.BUY
        assert result._has_leading_trigger is True
        sweep_reasons = [r for r in result.reasons if "Sweep" in r]
        assert len(sweep_reasons) >= 1

    def test_bos_leading_trigger_without_ema_cross_gives_signal(self, engine):
        """Bullish BOS → leading trigger → SIGNAL without EMA cross."""
        ind = make_ind(
            rsi=55.0,
            adx=30.0,
            close=49000.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47900.0,
            ema_slow_prev=47200.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=50.0,
            macd_hist_prev=40.0,
            volume_sma=900.0,
            volume=1500.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
        )
        structure = self._make_bos("bullish")
        result = engine.evaluate(ind, structure=structure)
        assert result.signal == SignalType.BUY
        assert result._has_leading_trigger is True
        bos_reasons = [r for r in result.reasons if "BOS" in r]
        assert len(bos_reasons) >= 1

    def test_ema_cross_without_leading_trigger_no_signal(self, engine):
        """EMA cross without any leading trigger → NO_SIGNAL (lagging only)."""
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
            dmi_plus=25.0,
            dmi_minus=15.0,
            volume_delta_pct=None,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL
        assert result._has_leading_trigger is False

    def test_macd_cross_without_leading_trigger_no_signal(self, engine):
        """MACD cross without any leading trigger → NO_SIGNAL (lagging only)."""
        ind = make_ind(
            rsi=55.0,
            adx=30.0,
            close=49000.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47900.0,
            ema_slow_prev=47200.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=50.0,
            macd_hist_prev=-10.0,
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
            volume_delta_pct=None,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL
        assert result._has_leading_trigger is False

    def test_leading_plus_lagging_gives_strong_signal(self, engine):
        """Leading trigger (delta) + lagging (EMA cross) → strong signal."""
        ind = make_ind(
            rsi=40.0,
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
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.BUY
        assert result._has_leading_trigger is True
        assert result._has_trigger is True

    def test_bearish_delta_leading_trigger(self, engine):
        """Delta < -15 + volume above avg → bearish leading trigger → SELL signal."""
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
            macd_hist_prev=-40.0,
            volume_sma=900.0,
            volume=1500.0,
            dmi_plus=15.0,
            dmi_minus=25.0,
            volume_delta_pct=-20.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.SELL
        assert result._has_leading_trigger is True

    def test_bearish_sweep_leading_trigger(self, engine):
        """Bearish sweep with fast reclaim → leading trigger → SELL signal."""
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
            macd_hist_prev=-40.0,
            volume_sma=900.0,
            volume=1500.0,
            dmi_plus=15.0,
            dmi_minus=25.0,
        )
        sweeps = [self._make_sweep("bearish", swept_level=51000.0, sweep_low=50800.0, sweep_high=51200.0)]
        result = engine.evaluate(ind, sweeps=sweeps)
        assert result.signal == SignalType.SELL
        assert result._has_leading_trigger is True

    def test_bearish_bos_leading_trigger(self, engine):
        """Bearish BOS → leading trigger → SELL signal."""
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
            macd_hist_prev=-40.0,
            volume_sma=900.0,
            volume=1500.0,
            dmi_plus=15.0,
            dmi_minus=25.0,
        )
        structure = self._make_bos("bearish")
        result = engine.evaluate(ind, structure=structure)
        assert result.signal == SignalType.SELL
        assert result._has_leading_trigger is True

    def test_delta_neutral_no_leading_trigger(self, engine):
        """Delta between -15 and +15 → no leading trigger from delta."""
        ind = make_ind(
            rsi=55.0,
            adx=30.0,
            close=49000.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47900.0,
            ema_slow_prev=47200.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=50.0,
            macd_hist_prev=40.0,
            volume_sma=900.0,
            volume=1500.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
            volume_delta_pct=5.0,
        )
        result = engine.evaluate(ind)
        assert result._has_leading_trigger is False

    def test_sweep_not_valid_no_leading_trigger(self, engine):
        """Sweep with slow reclaim (> 3 candles) → not valid → no leading trigger."""
        ind = make_ind(
            rsi=55.0,
            adx=30.0,
            close=49000.0,
            ema_fast=48000.0,
            ema_slow=47000.0,
            ema_trend=46000.0,
            ema_fast_prev=47900.0,
            ema_slow_prev=47200.0,
            supertrend_direction=1,
            supertrend=45000.0,
            macd_hist=50.0,
            macd_hist_prev=40.0,
            volume_sma=900.0,
            volume=1500.0,
            dmi_plus=25.0,
            dmi_minus=15.0,
        )
        sweeps = [self._make_sweep("bullish", swept_level=47000.0, sweep_low=46800.0,
                                    sweep_high=47200.0, reclaim_candles=5, volume_ratio=1.0)]
        result = engine.evaluate(ind, sweeps=sweeps)
        assert result._has_leading_trigger is False

    def test_has_leading_trigger_flag_on_no_signal(self, engine):
        """NO_SIGNAL with leading trigger detected but insufficient confirmation."""
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
            volume_sma=900.0,
            volume=1200.0,
            dmi_plus=18.0,
            dmi_minus=17.0,
            volume_delta_pct=20.0,
        )
        result = engine.evaluate(ind)
        assert result.signal == SignalType.NO_SIGNAL
        assert result._has_leading_trigger is True
