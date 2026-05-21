import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import config

from risk.volatility_regime import (
    VolatilityRegime,
    classify_volatility,
    get_volatility_config,
)
from risk.dynamic_risk import (
    RiskParams,
    calculate_risk,
    _base_risk_for_quality,
    _volatility_multiplier,
    _correlation_multiplier,
)
from risk.no_trade_zones import (
    NoTradeCheck,
    check_no_trade_zones,
)
from risk.market_regime import (
    MarketRegime,
    RegimeDetector,
)
from risk.dynamic_risk import (
    TPTarget,
    calculate_structural_sl,
    calculate_structural_tp,
)
from liquidity.sweep import SweepEvent
from liquidity.order_blocks import OrderBlock
from liquidity.fvg import FairValueGap
from market_structure.structure import StructureState
from datetime import datetime, timezone


# === Volatility Regime Tests ===

class TestVolatilityRegime:
    def test_low_volatility(self):
        regime = classify_volatility(atr_value=0.5, close_price=100.0)
        assert regime.regime == "low"
        assert regime.atr_pct == 0.5
        assert regime.allow_breakout is False
        assert regime.position_size_multiplier == 1.0

    def test_medium_volatility(self):
        regime = classify_volatility(atr_value=2.0, close_price=100.0)
        assert regime.regime == "medium"
        assert regime.atr_pct == 2.0
        assert regime.allow_breakout is True
        assert regime.position_size_multiplier == 1.0

    def test_high_volatility(self):
        regime = classify_volatility(atr_value=5.0, close_price=100.0)
        assert regime.regime == "high"
        assert regime.atr_pct == 5.0
        assert regime.allow_breakout is True
        assert regime.position_size_multiplier == 0.5

    def test_zero_close_price(self):
        regime = classify_volatility(atr_value=1.0, close_price=0.0)
        assert regime.regime == "medium"
        assert regime.atr_pct == 0.0

    def test_negative_close_price(self):
        regime = classify_volatility(atr_value=1.0, close_price=-10.0)
        assert regime.regime == "medium"
        assert regime.atr_pct == 0.0

    def test_boundary_low_threshold(self):
        regime = classify_volatility(atr_value=1.0, close_price=100.0)
        assert regime.regime == "medium"

    def test_boundary_high_threshold(self):
        regime = classify_volatility(atr_value=4.0, close_price=100.0)
        assert regime.regime == "medium"

    def test_just_below_low_threshold(self):
        regime = classify_volatility(atr_value=0.99, close_price=100.0)
        assert regime.regime == "low"

    def test_just_above_high_threshold(self):
        regime = classify_volatility(atr_value=4.01, close_price=100.0)
        assert regime.regime == "high"

    def test_get_volatility_config(self):
        cfg = get_volatility_config()
        assert "low_threshold" in cfg
        assert "high_threshold" in cfg
        assert "atr_period" in cfg
        assert cfg["low_threshold"] == 1.0
        assert cfg["high_threshold"] == 4.0
        assert cfg["atr_period"] == 14

    def test_custom_thresholds_via_env(self):
        with patch.dict("os.environ", {
            "VOLATILITY_LOW_THRESHOLD": "2.0",
            "VOLATILITY_HIGH_THRESHOLD": "5.0",
        }):
            regime = classify_volatility(atr_value=1.5, close_price=100.0)
            assert regime.regime == "low"
            assert regime.atr_pct == 1.5

            regime = classify_volatility(atr_value=3.0, close_price=100.0)
            assert regime.regime == "medium"

            regime = classify_volatility(atr_value=6.0, close_price=100.0)
            assert regime.regime == "high"


# === Dynamic Risk Tests ===

class TestDynamicRisk:
    def test_strong_setup_base_risk(self):
        assert _base_risk_for_quality("strong") == 1.0

    def test_moderate_setup_base_risk(self):
        assert _base_risk_for_quality("moderate") == 0.5

    def test_weak_setup_base_risk(self):
        assert _base_risk_for_quality("weak") == 0.0

    def test_volatility_multiplier_high(self):
        assert _volatility_multiplier("high") == 0.5

    def test_volatility_multiplier_medium(self):
        assert _volatility_multiplier("medium") == 1.0

    def test_volatility_multiplier_low(self):
        assert _volatility_multiplier("low") == 1.0

    def test_correlation_multiplier_all_aligned(self):
        assert _correlation_multiplier(True, True) == 1.0

    def test_correlation_multiplier_btc_not_aligned(self):
        assert _correlation_multiplier(False, True) == 0.5

    def test_correlation_multiplier_eth_not_aligned(self):
        assert _correlation_multiplier(True, False) == 0.5

    def test_correlation_multiplier_both_not_aligned(self):
        assert _correlation_multiplier(False, False) == 0.5

    def test_calculate_risk_strong_normal(self):
        params = calculate_risk("strong", "medium", True, True)
        assert params.setup_quality == "strong"
        assert params.base_risk_pct == 1.0
        assert params.volatility_multiplier == 1.0
        assert params.correlation_multiplier == 1.0
        assert params.effective_risk_pct == 1.0
        assert params.should_trade is True

    def test_calculate_risk_strong_high_vol(self):
        params = calculate_risk("strong", "high", True, True)
        assert params.effective_risk_pct == 0.5

    def test_calculate_risk_moderate_normal(self):
        params = calculate_risk("moderate", "medium", True, True)
        assert params.base_risk_pct == 0.5
        assert params.effective_risk_pct == 0.5

    def test_calculate_risk_weak_no_trade(self):
        params = calculate_risk("weak", "medium", True, True)
        assert params.base_risk_pct == 0.0
        assert params.should_trade is False

    def test_calculate_risk_weak_with_correlation_penalty(self):
        params = calculate_risk("strong", "high", False, True)
        assert params.effective_risk_pct == 0.25

    def test_risk_params_effective_calculation(self):
        params = RiskParams(
            setup_quality="strong",
            base_risk_pct=1.0,
            volatility_multiplier=0.5,
            correlation_multiplier=0.5,
        )
        assert params.effective_risk_pct == 0.25

    def test_weak_should_trade_reads_config(self, monkeypatch):
        monkeypatch.setenv("RISK_WEAK_TRADE", "true")
        import importlib
        import config.settings as settings_mod
        import risk.dynamic_risk as risk_mod
        importlib.reload(settings_mod)
        importlib.reload(risk_mod)

        from risk.dynamic_risk import RiskParams
        params = RiskParams(
            setup_quality="weak",
            base_risk_pct=0.0,
            volatility_multiplier=1.0,
            correlation_multiplier=1.0,
        )
        assert params.should_trade is True


# === No Trade Zones Tests ===

class TestNoTradeZones:
    def test_no_trade_check_add_condition(self):
        check = NoTradeCheck()
        check.add(True, "test reason")
        assert check.blocked is True
        assert len(check.reasons) == 1
        assert check.reasons[0] == "test reason"

    def test_no_trade_check_add_false_condition(self):
        check = NoTradeCheck()
        check.add(False, "test reason")
        assert check.blocked is False
        assert len(check.reasons) == 0

    def test_no_trade_check_multiple_reasons(self):
        check = NoTradeCheck()
        check.add(True, "reason 1")
        check.add(True, "reason 2")
        check.add(False, "reason 3")
        assert check.blocked is True
        assert len(check.reasons) == 2

    def test_funding_neutral_does_not_block(self):
        """FIX M5: neutral funding no longer blocks trades."""
        result = check_no_trade_zones(
            funding_state="neutral",
            funding_strength="weak",
            atr_pct=2.0,
        )
        assert result.blocked is False

    def test_funding_non_neutral_passes(self):
        result = check_no_trade_zones(
            funding_state="bullish",
            funding_strength="strong",
        )
        assert "Funding neutral" not in " ".join(result.reasons)

    def test_low_atr_blocks(self):
        result = check_no_trade_zones(atr_pct=0.3)
        assert result.blocked is True
        assert any("ATR too low" in r for r in result.reasons)

    def test_normal_atr_passes(self):
        result = check_no_trade_zones(atr_pct=2.0)
        assert not any("ATR too low" in r for r in result.reasons)

    def test_ranging_market_blocks(self):
        result = check_no_trade_zones(market_structure="ranging")
        assert result.blocked is True
        assert any("range-bound" in r for r in result.reasons)

    def test_trending_market_passes(self):
        result = check_no_trade_zones(market_structure="bullish")
        assert not any("range-bound" in r for r in result.reasons)

    def test_btc_not_aligned_blocks(self):
        result = check_no_trade_zones(btc_aligned=False)
        assert result.blocked is True
        assert any("BTC unclear" in r for r in result.reasons)

    def test_tp_blocked_blocks(self):
        result = check_no_trade_zones(tp_blocked=True)
        assert result.blocked is True
        assert any("TP blocked" in r for r in result.reasons)

    def test_oi_ignore_does_not_block(self):
        """FIX P3: OI ignore/None не блокирует — нет данных != опасность."""
        result = check_no_trade_zones(oi_significance="ignore", atr_pct=2.0)
        assert result.blocked is False

    def test_oi_none_does_not_block(self):
        """FIX P3: OI=None не блокирует."""
        result = check_no_trade_zones(oi_significance=None, atr_pct=2.0)
        assert result.blocked is False

    def test_oi_extreme_long_blocks(self):
        """FIX P3: extreme_long OI pattern блокирует."""
        result = check_no_trade_zones(oi_significance="strong", oi_pattern="extreme_long", atr_pct=2.0)
        assert result.blocked is True
        assert any("extreme_long" in r for r in result.reasons)

    def test_oi_extreme_short_blocks(self):
        """FIX P3: extreme_short OI pattern блокирует."""
        result = check_no_trade_zones(oi_significance="strong", oi_pattern="extreme_short", atr_pct=2.0)
        assert result.blocked is True
        assert any("extreme_short" in r for r in result.reasons)

    def test_oi_moderate_passes(self):
        result = check_no_trade_zones(oi_significance="moderate", atr_pct=2.0)
        assert result.blocked is False

    def test_all_clear_passes(self):
        result = check_no_trade_zones(
            funding_state="bullish",
            funding_strength="strong",
            atr_pct=2.0,
            market_structure="bullish",
            btc_aligned=True,
            tp_blocked=False,
            oi_significance="strong",
        )
        assert result.blocked is False
        assert len(result.reasons) == 0

    def test_multiple_blocks_accumulate(self):
        """Multiple no-trade conditions accumulate reasons."""
        result = check_no_trade_zones(
            funding_state="neutral",
            funding_strength="weak",
            atr_pct=0.1,
            market_structure="ranging",
        )
        assert result.blocked is True
        # FIX M5: funding neutral no longer blocks, so only 2 reasons (ATR + ranging)
        assert len(result.reasons) >= 2


# === Config Tests ===

class TestRiskConfig:
    def test_default_values(self, monkeypatch):
        monkeypatch.delenv("RISK_WEAK_TRADE", raising=False)
        monkeypatch.delenv("RISK_STRONG_PCT", raising=False)
        monkeypatch.delenv("RISK_MODERATE_PCT", raising=False)
        import importlib
        import config.settings as settings_mod
        importlib.reload(settings_mod)
        cfg = settings_mod.config.risk
        assert cfg.volatility_low_threshold == 1.0
        assert cfg.volatility_high_threshold == 4.0
        assert cfg.volatility_atr_period == 14
        assert cfg.risk_strong_pct == 1.0
        assert cfg.risk_moderate_pct == 0.5
        assert cfg.risk_weak_trade is False
        assert cfg.no_trade_min_atr_pct == 0.5

    def test_risk_weak_trade_from_env(self, monkeypatch):
        monkeypatch.setenv("RISK_WEAK_TRADE", "true")
        import importlib
        import config.settings as settings
        importlib.reload(settings)
        assert settings.config.risk.risk_weak_trade is True

    def test_risk_strong_pct_from_env(self, monkeypatch):
        monkeypatch.setenv("RISK_STRONG_PCT", "2.0")
        import importlib
        import config.settings as settings
        importlib.reload(settings)
        assert settings.config.risk.risk_strong_pct == 2.0

    def test_risk_moderate_pct_from_env(self, monkeypatch):
        monkeypatch.setenv("RISK_MODERATE_PCT", "0.75")
        import importlib
        import config.settings as settings
        importlib.reload(settings)
        assert settings.config.risk.risk_moderate_pct == 0.75


# === Market Regime Tests ===

class TestMarketRegime:
    def _make_detector(self, adx=20.0, atr_history=None, ema_spread_history=None,
                       volume_history=None, current_atr=None, current_volume=None):
        if atr_history is None:
            atr_history = [1.0] * 50
        if ema_spread_history is None:
            ema_spread_history = [0.5] * 10
        if volume_history is None:
            volume_history = [1000.0] * 10
        return RegimeDetector(
            adx=adx,
            atr_history=atr_history,
            ema_spread_history=ema_spread_history,
            volume_history=volume_history,
            current_atr=current_atr,
            current_volume=current_volume,
        )

    def test_regime_trend_high_adx_rising_spread(self):
        atr_hist = [1.0] * 50
        ema_spread = [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75]
        detector = self._make_detector(adx=30.0, atr_history=atr_hist,
                                       ema_spread_history=ema_spread, current_atr=1.2)
        regime = detector.detect()
        assert regime.regime == "trend"
        assert regime.adx == 30.0
        assert regime.ema_spread_trend == "rising"
        assert 0.0 <= regime.confidence <= 1.0

    def test_regime_range_low_adx(self):
        detector = self._make_detector(adx=15.0, current_atr=1.0)
        regime = detector.detect()
        assert regime.regime == "range"
        assert regime.adx == 15.0
        assert 0.0 <= regime.confidence <= 1.0

    def test_regime_compression_low_atr_percentile(self):
        atr_hist = [2.0, 2.5, 3.0, 3.5, 4.0] * 10
        detector = self._make_detector(adx=20.0, atr_history=atr_hist, current_atr=0.5)
        regime = detector.detect()
        assert regime.regime == "compression"
        assert regime.atr_percentile < 20.0
        assert 0.0 <= regime.confidence <= 1.0

    def test_regime_expansion_atr_rising_volume_rising(self):
        atr_hist = [1.0] * 50
        vol_hist = [1000.0] * 10
        detector = self._make_detector(
            adx=22.0,
            atr_history=atr_hist,
            ema_spread_history=[0.5] * 10,
            volume_history=vol_hist,
            current_atr=2.0,
            current_volume=2000.0,
        )
        regime = detector.detect()
        assert regime.regime == "expansion"
        assert 0.0 <= regime.confidence <= 1.0

    def test_atr_percentile_calculation(self):
        atr_hist = [1.0, 2.0, 3.0, 4.0, 5.0]
        detector = self._make_detector(atr_history=atr_hist, current_atr=3.0)
        pct = detector._atr_percentile()
        assert pct == 60.0

    def test_atr_percentile_empty_history(self):
        detector = self._make_detector(atr_history=[], current_atr=1.0)
        pct = detector._atr_percentile()
        assert pct == 50.0

    def test_atr_percentile_no_current_atr(self):
        detector = self._make_detector(atr_history=[1.0, 2.0, 3.0], current_atr=None)
        pct = detector._atr_percentile()
        assert pct == 50.0

    def test_ema_spread_trend_rising(self):
        spreads = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        detector = self._make_detector(ema_spread_history=spreads)
        trend = detector._ema_spread_trend()
        assert trend == "rising"

    def test_ema_spread_trend_falling(self):
        spreads = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]
        detector = self._make_detector(ema_spread_history=spreads)
        trend = detector._ema_spread_trend()
        assert trend == "falling"

    def test_ema_spread_trend_stable(self):
        spreads = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
        detector = self._make_detector(ema_spread_history=spreads)
        trend = detector._ema_spread_trend()
        assert trend == "stable"

    def test_ema_spread_trend_short_history(self):
        detector = self._make_detector(ema_spread_history=[0.5])
        trend = detector._ema_spread_trend()
        assert trend == "stable"

    def test_expansion_atr_rising(self):
        atr_hist = [1.0] * 50
        detector = self._make_detector(atr_history=atr_hist, current_atr=2.0)
        assert detector._atr_rising() is True

    def test_expansion_atr_not_rising(self):
        atr_hist = [2.0] * 50
        detector = self._make_detector(atr_history=atr_hist, current_atr=1.0)
        assert detector._atr_rising() is False

    def test_expansion_volume_rising(self):
        vol_hist = [1000.0] * 10
        detector = self._make_detector(volume_history=vol_hist, current_volume=2000.0)
        assert detector._volume_rising() is True

    def test_expansion_volume_not_rising(self):
        vol_hist = [2000.0] * 10
        detector = self._make_detector(volume_history=vol_hist, current_volume=1000.0)
        assert detector._volume_rising() is False

    def test_fallback_range_when_no_match(self):
        atr_hist = [1.0] * 50
        ema_spread = [0.5] * 10
        detector = self._make_detector(adx=20.0, atr_history=atr_hist,
                                       ema_spread_history=ema_spread, current_atr=1.0)
        regime = detector.detect()
        assert regime.regime == "range"

    def test_market_regime_dataclass_fields(self):
        regime = MarketRegime(
            regime="trend",
            confidence=0.8,
            adx=30.0,
            atr_percentile=65.0,
            ema_spread_trend="rising",
        )
        assert regime.regime == "trend"
        assert regime.confidence == 0.8
        assert regime.adx == 30.0
        assert regime.atr_percentile == 65.0
        assert regime.ema_spread_trend == "rising"

    def test_regime_config_defaults(self):
        cfg = config.risk
        assert cfg.regime_trend_adx == 25.0
        assert cfg.regime_range_adx == 18.0
        assert cfg.regime_compression_atr_pct == 20.0
        assert cfg.regime_atr_lookback == 100


# === Structural SL/TP Tests (Task 5.1) ===

def _make_sweep(sweep_type: str, sweep_low: float, sweep_high: float, volume_ratio: float = 2.0, reclaim_candles: int = 2) -> SweepEvent:
    return SweepEvent(
        type=sweep_type,
        swept_level=sweep_low if sweep_type == "bullish" else sweep_high,
        sweep_low=sweep_low,
        sweep_high=sweep_high,
        reclaim_candles=reclaim_candles,
        volume_ratio=volume_ratio,
        timestamp=datetime.now(timezone.utc),
    )


def _make_ob(ob_type: str, low: float, high: float, has_bos: bool = True, displacement_atr: float = 2.0, volume_ratio: float = 2.0) -> OrderBlock:
    return OrderBlock(
        type=ob_type,
        high=high,
        low=low,
        timestamp=datetime.now(timezone.utc),
        has_bos=has_bos,
        displacement_atr=displacement_atr,
        volume_ratio=volume_ratio,
    )


def _make_structure(recent_highs: list[float], recent_lows: list[float], trend: str = "bullish") -> StructureState:
    return StructureState(
        trend=trend,
        recent_highs=recent_highs,
        recent_lows=recent_lows,
    )


class TestStructuralSL:
    def test_buy_sl_uses_sweep_low(self):
        sweeps = [_make_sweep("bullish", sweep_low=98.0, sweep_high=100.0)]
        sl = calculate_structural_sl("BUY", entry=100.0, sweeps=sweeps, order_blocks=[], atr=2.0, close=100.0)
        assert sl == 98.0

    def test_buy_sl_uses_ob_low(self):
        obs = [_make_ob("bullish", low=97.5, high=99.0)]
        sl = calculate_structural_sl("BUY", entry=100.0, sweeps=[], order_blocks=obs, atr=2.0, close=100.0)
        assert sl == 97.5

    def test_buy_sl_uses_structure_low(self):
        structure = _make_structure(recent_highs=[105.0, 103.0], recent_lows=[96.0, 97.0])
        sl = calculate_structural_sl("BUY", entry=100.0, sweeps=[], order_blocks=[], structure=structure, atr=2.0, close=100.0)
        assert sl == 97.0

    def test_buy_sl_nearest_below_entry(self):
        sweeps = [
            _make_sweep("bullish", sweep_low=95.0, sweep_high=97.0),
            _make_sweep("bullish", sweep_low=98.0, sweep_high=99.0),
        ]
        sl = calculate_structural_sl("BUY", entry=100.0, sweeps=sweeps, order_blocks=[], atr=2.0, close=100.0)
        assert sl == 98.0

    def test_buy_sl_fallback_to_atr(self):
        sl = calculate_structural_sl("BUY", entry=100.0, sweeps=[], order_blocks=[], atr=2.0, close=100.0)
        cfg = config.trading
        assert sl == round(100.0 - 2.0 * cfg.atr_multiplier_sl, 8)

    def test_sell_sl_uses_sweep_high(self):
        sweeps = [_make_sweep("bearish", sweep_low=100.0, sweep_high=102.0)]
        sl = calculate_structural_sl("SELL", entry=100.0, sweeps=sweeps, order_blocks=[], atr=2.0, close=100.0)
        assert sl == 102.0

    def test_sell_sl_uses_ob_high(self):
        obs = [_make_ob("bearish", low=101.0, high=103.0)]
        sl = calculate_structural_sl("SELL", entry=100.0, sweeps=[], order_blocks=obs, atr=2.0, close=100.0)
        assert sl == 103.0

    def test_sell_sl_uses_structure_high(self):
        structure = _make_structure(recent_highs=[104.0, 106.0], recent_lows=[98.0, 97.0])
        sl = calculate_structural_sl("SELL", entry=100.0, sweeps=[], order_blocks=[], structure=structure, atr=2.0, close=100.0)
        assert sl == 104.0

    def test_sell_sl_nearest_above_entry(self):
        sweeps = [
            _make_sweep("bearish", sweep_low=100.0, sweep_high=105.0),
            _make_sweep("bearish", sweep_low=100.0, sweep_high=102.0),
        ]
        sl = calculate_structural_sl("SELL", entry=100.0, sweeps=sweeps, order_blocks=[], atr=2.0, close=100.0)
        assert sl == 102.0

    def test_sell_sl_fallback_to_atr(self):
        sl = calculate_structural_sl("SELL", entry=100.0, sweeps=[], order_blocks=[], atr=2.0, close=100.0)
        cfg = config.trading
        assert sl == round(100.0 + 2.0 * cfg.atr_multiplier_sl, 8)

    def test_buy_sl_ignores_bearish_sweep(self):
        sweeps = [_make_sweep("bearish", sweep_low=95.0, sweep_high=102.0)]
        sl = calculate_structural_sl("BUY", entry=100.0, sweeps=sweeps, order_blocks=[], atr=2.0, close=100.0)
        cfg = config.trading
        assert sl == round(100.0 - 2.0 * cfg.atr_multiplier_sl, 8)

    def test_sell_sl_ignores_bullish_sweep(self):
        sweeps = [_make_sweep("bullish", sweep_low=95.0, sweep_high=100.0)]
        sl = calculate_structural_sl("SELL", entry=100.0, sweeps=sweeps, order_blocks=[], atr=2.0, close=100.0)
        cfg = config.trading
        assert sl == round(100.0 + 2.0 * cfg.atr_multiplier_sl, 8)

    def test_buy_sl_ignores_levels_above_entry(self):
        sweeps = [_make_sweep("bullish", sweep_low=101.0, sweep_high=103.0)]
        sl = calculate_structural_sl("BUY", entry=100.0, sweeps=sweeps, order_blocks=[], atr=2.0, close=100.0)
        cfg = config.trading
        assert sl == round(100.0 - 2.0 * cfg.atr_multiplier_sl, 8)

    def test_sell_sl_ignores_levels_below_entry(self):
        sweeps = [_make_sweep("bearish", sweep_low=95.0, sweep_high=99.0)]
        sl = calculate_structural_sl("SELL", entry=100.0, sweeps=sweeps, order_blocks=[], atr=2.0, close=100.0)
        cfg = config.trading
        assert sl == round(100.0 + 2.0 * cfg.atr_multiplier_sl, 8)

    def test_sl_atr_fallback_uses_close_when_atr_zero(self):
        sl = calculate_structural_sl("BUY", entry=100.0, sweeps=[], order_blocks=[], atr=0.0, close=100.0)
        cfg = config.trading
        expected = round(100.0 - (100.0 * 0.02) * cfg.atr_multiplier_sl, 8)
        assert sl == expected

    def test_sl_combines_multiple_sources(self):
        sweeps = [_make_sweep("bullish", sweep_low=97.0, sweep_high=99.0)]
        obs = [_make_ob("bullish", low=96.0, high=98.0)]
        structure = _make_structure(recent_highs=[105.0], recent_lows=[95.0])
        sl = calculate_structural_sl("BUY", entry=100.0, sweeps=sweeps, order_blocks=obs, structure=structure, atr=2.0, close=100.0)
        assert sl == 97.0


class TestStructuralTP:
    def test_buy_tp_uses_sweep_high(self):
        sweeps = [_make_sweep("bullish", sweep_low=98.0, sweep_high=110.0)]
        sl = 98.0
        targets = calculate_structural_tp("BUY", entry=100.0, sl=sl, sweeps=sweeps, order_blocks=[], atr=2.0, close=100.0)
        assert len(targets) >= 1
        assert targets[0].price == 110.0
        assert targets[0].rr >= 2.0

    def test_buy_tp_uses_ob_high(self):
        obs = [_make_ob("bullish", low=97.0, high=108.0)]
        sl = 97.0
        targets = calculate_structural_tp("BUY", entry=100.0, sl=sl, sweeps=[], order_blocks=obs, atr=2.0, close=100.0)
        assert len(targets) >= 1
        assert targets[0].price == 108.0

    def test_buy_tp_uses_structure_high(self):
        structure = _make_structure(recent_highs=[112.0, 108.0], recent_lows=[97.0])
        sl = 97.0
        targets = calculate_structural_tp("BUY", entry=100.0, sl=sl, sweeps=[], order_blocks=[], structure=structure, atr=2.0, close=100.0)
        assert len(targets) >= 1
        assert targets[0].price == 108.0

    def test_buy_tp_sorted_by_proximity(self):
        sweeps = [
            _make_sweep("bullish", sweep_low=98.0, sweep_high=105.0),
            _make_sweep("bullish", sweep_low=98.0, sweep_high=110.0),
        ]
        sl = 98.0
        targets = calculate_structural_tp("BUY", entry=100.0, sl=sl, sweeps=sweeps, order_blocks=[], atr=2.0, close=100.0)
        valid_targets = [t for t in targets if t.rr >= 2.0]
        if len(valid_targets) >= 2:
            assert valid_targets[0].price <= valid_targets[1].price

    def test_buy_tp_fallback_to_atr(self):
        sl = 98.0
        targets = calculate_structural_tp("BUY", entry=100.0, sl=sl, sweeps=[], order_blocks=[], atr=2.0, close=100.0)
        assert len(targets) == 1
        assert "ATR fallback" in targets[0].label

    def test_sell_tp_uses_sweep_low(self):
        sweeps = [_make_sweep("bearish", sweep_low=90.0, sweep_high=102.0)]
        sl = 102.0
        targets = calculate_structural_tp("SELL", entry=100.0, sl=sl, sweeps=sweeps, order_blocks=[], atr=2.0, close=100.0)
        assert len(targets) >= 1
        assert targets[0].price == 90.0

    def test_sell_tp_uses_ob_low(self):
        obs = [_make_ob("bearish", low=92.0, high=103.0)]
        sl = 103.0
        targets = calculate_structural_tp("SELL", entry=100.0, sl=sl, sweeps=[], order_blocks=obs, atr=2.0, close=100.0)
        assert len(targets) >= 1
        assert targets[0].price == 92.0

    def test_sell_tp_uses_structure_low(self):
        structure = _make_structure(recent_highs=[104.0], recent_lows=[88.0, 92.0])
        sl = 104.0
        targets = calculate_structural_tp("SELL", entry=100.0, sl=sl, sweeps=[], order_blocks=[], structure=structure, atr=2.0, close=100.0)
        assert len(targets) >= 1
        assert targets[0].price == 92.0

    def test_sell_tp_sorted_by_proximity(self):
        sweeps = [
            _make_sweep("bearish", sweep_low=95.0, sweep_high=102.0),
            _make_sweep("bearish", sweep_low=90.0, sweep_high=102.0),
        ]
        sl = 102.0
        targets = calculate_structural_tp("SELL", entry=100.0, sl=sl, sweeps=sweeps, order_blocks=[], atr=2.0, close=100.0)
        valid_targets = [t for t in targets if t.rr >= 2.0]
        if len(valid_targets) >= 2:
            assert valid_targets[0].price >= valid_targets[1].price

    def test_sell_tp_fallback_to_atr(self):
        sl = 102.0
        targets = calculate_structural_tp("SELL", entry=100.0, sl=sl, sweeps=[], order_blocks=[], atr=2.0, close=100.0)
        assert len(targets) == 1
        assert "ATR fallback" in targets[0].label

    def test_tp_empty_if_min_rr_not_met(self):
        sweeps = [_make_sweep("bullish", sweep_low=99.0, sweep_high=101.0)]
        sl = 99.0
        targets = calculate_structural_tp("BUY", entry=100.0, sl=sl, sweeps=sweeps, order_blocks=[], atr=2.0, close=100.0)
        structural_targets = [t for t in targets if "ATR" not in t.label]
        assert len(structural_targets) == 0

    def test_tp_rr_calculation(self):
        sweeps = [_make_sweep("bullish", sweep_low=98.0, sweep_high=106.0)]
        sl = 98.0
        targets = calculate_structural_tp("BUY", entry=100.0, sl=sl, sweeps=sweeps, order_blocks=[], atr=2.0, close=100.0)
        valid_targets = [t for t in targets if t.rr >= 2.0]
        if valid_targets:
            expected_rr = abs(106.0 - 100.0) / abs(100.0 - 98.0)
            assert valid_targets[0].rr == round(expected_rr, 2)

    def test_tp_atr_fallback_uses_close_when_atr_zero(self):
        sl = 98.0
        targets = calculate_structural_tp("BUY", entry=100.0, sl=sl, sweeps=[], order_blocks=[], atr=0.0, close=100.0)
        assert len(targets) == 1
        assert "ATR fallback" in targets[0].label

    def test_tp_target_dataclass(self):
        target = TPTarget(price=110.0, label="test", rr=3.0)
        assert target.price == 110.0
        assert target.label == "test"
        assert target.rr == 3.0


# === FVG TP Tests (Task 5.2 — Dynamic TP) ===

def _make_fvg(fvg_type: str, top: float, bottom: float, filled: bool = False) -> FairValueGap:
    return FairValueGap(
        type=fvg_type,
        top=top,
        bottom=bottom,
        timestamp=datetime.now(timezone.utc),
        filled=filled,
    )


class TestFVGTP:
    def test_buy_tp_uses_bearish_fvg_fill(self):
        """LONG: bearish FVG above entry → TP at FVG midpoint."""
        fvg = _make_fvg("bearish", top=108.0, bottom=106.0)
        sl = 98.0
        targets = calculate_structural_tp(
            "BUY", entry=100.0, sl=sl, sweeps=[], order_blocks=[],
            fvgs=[fvg], atr=2.0, close=100.0,
        )
        fvg_targets = [t for t in targets if "FVG" in t.label]
        assert len(fvg_targets) >= 1
        assert fvg_targets[0].price == 107.0

    def test_sell_tp_uses_bullish_fvg_fill(self):
        """SHORT: bullish FVG below entry → TP at FVG midpoint."""
        fvg = _make_fvg("bullish", top=94.0, bottom=92.0)
        sl = 102.0
        targets = calculate_structural_tp(
            "SELL", entry=100.0, sl=sl, sweeps=[], order_blocks=[],
            fvgs=[fvg], atr=2.0, close=100.0,
        )
        fvg_targets = [t for t in targets if "FVG" in t.label]
        assert len(fvg_targets) >= 1
        assert fvg_targets[0].price == 93.0

    def test_buy_tp_ignores_bullish_fvg(self):
        """LONG: bullish FVG is not a TP target (it's below, not above)."""
        fvg = _make_fvg("bullish", top=94.0, bottom=92.0)
        sl = 98.0
        targets = calculate_structural_tp(
            "BUY", entry=100.0, sl=sl, sweeps=[], order_blocks=[],
            fvgs=[fvg], atr=2.0, close=100.0,
        )
        fvg_targets = [t for t in targets if "FVG" in t.label]
        assert len(fvg_targets) == 0

    def test_sell_tp_ignores_bearish_fvg(self):
        """SHORT: bearish FVG is not a TP target (it's above, not below)."""
        fvg = _make_fvg("bearish", top=108.0, bottom=106.0)
        sl = 102.0
        targets = calculate_structural_tp(
            "SELL", entry=100.0, sl=sl, sweeps=[], order_blocks=[],
            fvgs=[fvg], atr=2.0, close=100.0,
        )
        fvg_targets = [t for t in targets if "FVG" in t.label]
        assert len(fvg_targets) == 0

    def test_buy_tp_ignores_filled_fvg(self):
        """LONG: filled FVG is not used as TP target."""
        fvg = _make_fvg("bearish", top=108.0, bottom=106.0, filled=True)
        sl = 98.0
        targets = calculate_structural_tp(
            "BUY", entry=100.0, sl=sl, sweeps=[], order_blocks=[],
            fvgs=[fvg], atr=2.0, close=100.0,
        )
        fvg_targets = [t for t in targets if "FVG" in t.label]
        assert len(fvg_targets) == 0

    def test_sell_tp_ignores_filled_fvg(self):
        """SHORT: filled FVG is not used as TP target."""
        fvg = _make_fvg("bullish", top=94.0, bottom=92.0, filled=True)
        sl = 102.0
        targets = calculate_structural_tp(
            "SELL", entry=100.0, sl=sl, sweeps=[], order_blocks=[],
            fvgs=[fvg], atr=2.0, close=100.0,
        )
        fvg_targets = [t for t in targets if "FVG" in t.label]
        assert len(fvg_targets) == 0

    def test_buy_tp_fvg_below_entry_ignored(self):
        """LONG: bearish FVG below entry is ignored."""
        fvg = _make_fvg("bearish", top=98.0, bottom=96.0)
        sl = 98.0
        targets = calculate_structural_tp(
            "BUY", entry=100.0, sl=sl, sweeps=[], order_blocks=[],
            fvgs=[fvg], atr=2.0, close=100.0,
        )
        fvg_targets = [t for t in targets if "FVG" in t.label]
        assert len(fvg_targets) == 0

    def test_sell_tp_fvg_above_entry_ignored(self):
        """SHORT: bullish FVG above entry is ignored."""
        fvg = _make_fvg("bullish", top=104.0, bottom=102.0)
        sl = 102.0
        targets = calculate_structural_tp(
            "SELL", entry=100.0, sl=sl, sweeps=[], order_blocks=[],
            fvgs=[fvg], atr=2.0, close=100.0,
        )
        fvg_targets = [t for t in targets if "FVG" in t.label]
        assert len(fvg_targets) == 0

    def test_buy_tp_fvg_with_sweep_and_ob(self):
        """LONG: FVG combined with sweep and OB targets."""
        sweeps = [_make_sweep("bullish", sweep_low=98.0, sweep_high=105.0)]
        obs = [_make_ob("bullish", low=97.0, high=108.0)]
        fvg = _make_fvg("bearish", top=112.0, bottom=110.0)
        sl = 98.0
        targets = calculate_structural_tp(
            "BUY", entry=100.0, sl=sl, sweeps=sweeps, order_blocks=obs,
            fvgs=[fvg], atr=2.0, close=100.0,
        )
        labels = [t.label for t in targets]
        has_sweep = any("sweep" in l for l in labels)
        has_ob = any("OB" in l for l in labels)
        has_fvg = any("FVG" in l for l in labels)
        assert has_sweep
        assert has_ob
        assert has_fvg

    def test_buy_tp_empty_fvg_fallback_atr(self):
        """LONG: no valid FVG targets → ATR fallback."""
        fvg = _make_fvg("bearish", top=101.0, bottom=100.5)
        sl = 99.5
        targets = calculate_structural_tp(
            "BUY", entry=100.0, sl=sl, sweeps=[], order_blocks=[],
            fvgs=[fvg], atr=2.0, close=100.0,
        )
        assert len(targets) == 1
        assert "ATR fallback" in targets[0].label

    def test_sell_tp_empty_fvg_fallback_atr(self):
        """SHORT: no valid FVG targets → ATR fallback."""
        fvg = _make_fvg("bullish", top=99.5, bottom=99.0)
        sl = 100.5
        targets = calculate_structural_tp(
            "SELL", entry=100.0, sl=sl, sweeps=[], order_blocks=[],
            fvgs=[fvg], atr=2.0, close=100.0,
        )
        assert len(targets) == 1
        assert "ATR fallback" in targets[0].label

    def test_buy_tp_fvg_rr_calculation(self):
        """LONG: FVG TP RR is calculated correctly."""
        fvg = _make_fvg("bearish", top=110.0, bottom=106.0)
        sl = 98.0
        targets = calculate_structural_tp(
            "BUY", entry=100.0, sl=sl, sweeps=[], order_blocks=[],
            fvgs=[fvg], atr=2.0, close=100.0,
        )
        fvg_targets = [t for t in targets if "FVG" in t.label]
        if fvg_targets:
            expected_rr = abs(108.0 - 100.0) / abs(100.0 - 98.0)
            assert fvg_targets[0].rr == round(expected_rr, 2)

    def test_buy_tp_fvg_below_min_rr_excluded(self):
        """LONG: FVG target with RR < 2.0 is excluded."""
        fvg = _make_fvg("bearish", top=100.8, bottom=100.4)
        sl = 99.5
        targets = calculate_structural_tp(
            "BUY", entry=100.0, sl=sl, sweeps=[], order_blocks=[],
            fvgs=[fvg], atr=2.0, close=100.0,
        )
        fvg_targets = [t for t in targets if "FVG" in t.label]
        assert len(fvg_targets) == 0
