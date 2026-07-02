import sys
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.pattern_engine import PatternEngine, ICTSetup, pattern_engine
from strategy.feature_builder import FeatureBuilder, SetupFeatures, feature_builder
from strategy.probability_engine import ProbabilityEngine, TradeProbability, probability_engine
from risk.engine import RiskEngine, RiskDecision, PortfolioState, risk_engine
from context.scorer import ContextScorer, ContextScore


# === Mock objects ===

@dataclass
class MockBOS:
    type: str = "bullish"
    level: float = 50000.0
    timestamp: datetime = None
    candle_index: int = 10


@dataclass
class MockStructure:
    trend: str = "bullish"
    last_bos: object = None
    last_choch: object = None
    recent_highs: list = None
    recent_lows: list = None

    def __post_init__(self):
        if self.recent_highs is None:
            self.recent_highs = []
        if self.recent_lows is None:
            self.recent_lows = []


@dataclass
class MockSweep:
    type: str = "bullish"
    is_valid: bool = True
    strength: float = 0.75
    reclaim_candles: int = 2
    swept_level: float = 50000.0
    sweep_low: float = 49500.0
    sweep_high: float = 50200.0
    volume_ratio: float = 2.0
    timestamp: datetime = None


@dataclass
class MockOB:
    type: str = "bullish"
    high: float = 50200.0
    low: float = 49800.0
    midpoint: float = 50000.0
    is_valid: bool = True
    has_bos: bool = True
    displacement_atr: float = 2.0
    volume_ratio: float = 2.0
    timestamp: datetime = None


@dataclass
class MockFVG:
    type: str = "bearish"
    top: float = 51000.0
    bottom: float = 50500.0
    is_active: bool = True
    filled: bool = False
    size_pct: float = 1.0
    timestamp: datetime = None


@dataclass
class MockCandleQuality:
    is_displacement: bool = True
    body_pct: float = 0.75
    close_position: float = 0.8


@dataclass
class MockIndicatorValues:
    close: float = 50000.0
    high: float = 50500.0
    low: float = 49500.0
    atr: float = 500.0
    rsi: float = 55.0
    adx: float = 25.0
    ema_fast: float = 50100.0
    ema_slow: float = 49900.0
    ema_trend: float = 49800.0
    ema_fast_prev: float = 50050.0
    ema_slow_prev: float = 49850.0
    dmi_plus: float = 20.0
    dmi_minus: float = 15.0
    supertrend_direction: int = 1
    macd_hist: float = 100.0
    volume: float = 1500.0
    volume_sma: float = 1000.0
    volume_delta_pct: float = 5.0
    volume_above_avg: bool = True


@dataclass
class MockRegime:
    regime: str = "trend"


@dataclass
class MockVolRegime:
    regime: str = "medium"


# ============================================================
# PatternEngine Tests
# ============================================================

class TestPatternEngine:
    def test_singleton_exists(self):
        assert pattern_engine is not None
        assert isinstance(pattern_engine, PatternEngine)

    def test_no_direction_returns_not_detected(self):
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=[], structure=None,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.detected is False
        assert setup.rejection_reason == "no clear direction (no BOS/sweep)"

    def test_bos_provides_direction(self):
        structure = MockStructure(last_bos=MockBOS(type="bullish"))
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=[], structure=structure,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.direction == "buy"

    def test_sweep_provides_direction(self):
        sweeps = [MockSweep(type="bearish")]
        setup = pattern_engine.detect(
            sweeps=sweeps, order_blocks=[], structure=MockStructure(),
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.direction == "sell"

    def test_bos_primary_direction(self):
        structure = MockStructure(last_bos=MockBOS(type="bullish"))
        sweeps = [MockSweep(type="bearish")]
        setup = pattern_engine.detect(
            sweeps=sweeps, order_blocks=[], structure=structure,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.direction == "buy"  # BOS wins

    def test_no_trigger_no_ob_returns_rejection(self):
        structure = MockStructure(last_bos=MockBOS(type="bullish"))
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=[], structure=structure,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.detected is False
        assert setup.has_bos is True
        assert setup.has_ob is False
        assert "confirmation" in setup.rejection_reason

    def test_full_setup_bos_ob_detected(self):
        structure = MockStructure(last_bos=MockBOS(type="bullish"))
        obs = [MockOB(type="bullish")]
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=obs, structure=structure,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.detected is True
        assert setup.direction == "buy"
        assert setup.has_bos is True
        assert setup.has_ob is True
        assert "BOS" in setup.components_found
        assert "OB" in setup.components_found

    def test_full_setup_sweep_fvg_detected(self):
        sweeps = [MockSweep(type="bearish")]
        fvgs = [MockFVG(type="bearish")]
        setup = pattern_engine.detect(
            sweeps=sweeps, order_blocks=[], structure=MockStructure(),
            fvgs=fvgs, candle_quality=None, current_price=50000.0,
        )
        assert setup.detected is True
        assert setup.direction == "sell"
        assert setup.has_sweep is True
        assert setup.has_fvg is True

    def test_displacement_included(self):
        structure = MockStructure(last_bos=MockBOS(type="bullish"))
        obs = [MockOB(type="bullish")]
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=obs, structure=structure,
            fvgs=[], candle_quality=MockCandleQuality(), current_price=50000.0,
        )
        assert setup.has_displacement is True
        assert setup.displacement_body_pct == 0.75

    def test_components_count(self):
        structure = MockStructure(last_bos=MockBOS(type="bullish"))
        obs = [MockOB(type="bullish")]
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=obs, structure=structure,
            fvgs=[], candle_quality=MockCandleQuality(), current_price=50000.0,
        )
        assert setup.components_count == 3  # BOS + OB + Displacement

    def test_bos_level_captured(self):
        structure = MockStructure(last_bos=MockBOS(type="bullish", level=48000.0))
        obs = [MockOB(type="bullish")]
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=obs, structure=structure,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.bos_level == 48000.0

    def test_ob_distance_calculated(self):
        structure = MockStructure(last_bos=MockBOS(type="bullish"))
        obs = [MockOB(type="bullish", midpoint=49000.0)]
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=obs, structure=structure,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        expected_dist = abs(50000.0 - 49000.0) / 50000.0 * 100
        assert abs(setup.ob_distance_pct - expected_dist) < 0.01

    def test_custom_config(self):
        engine = PatternEngine(
            require_bos_or_sweep=False,
            require_ob_or_fvg=False,
        )
        setup = engine.detect(
            sweeps=[], order_blocks=[], structure=MockStructure(trend="bullish"),
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        # Even with relaxed requirements, need direction first
        assert setup.detected is False

    def test_ict_setup_properties(self):
        setup = ICTSetup(
            detected=True,
            has_bos=True,
            has_ob=True,
            components_found=["BOS", "OB"],
        )
        assert setup.has_trigger is True
        assert setup.has_confirmation is True
        assert setup.components_count == 2

    def test_ict_setup_no_trigger(self):
        setup = ICTSetup(
            detected=False,
            has_bos=False,
            has_sweep=False,
        )
        assert setup.has_trigger is False

    def test_invalid_ob_not_detected(self):
        structure = MockStructure(last_bos=MockBOS(type="bullish"))
        obs = [MockOB(type="bullish", is_valid=False)]
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=obs, structure=structure,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.has_ob is False
        assert setup.detected is False

    def test_wrong_direction_ob_not_detected(self):
        structure = MockStructure(last_bos=MockBOS(type="bullish"))
        obs = [MockOB(type="bearish")]
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=obs, structure=structure,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.has_ob is False


# ============================================================
# FeatureBuilder Tests
# ============================================================

class TestFeatureBuilder:
    def test_singleton_exists(self):
        assert feature_builder is not None
        assert isinstance(feature_builder, FeatureBuilder)

    def test_build_returns_setup_features(self):
        setup = ICTSetup(
            detected=True, direction="buy",
            has_bos=True, bos_type="bullish",
            components_found=["BOS"],
        )
        ind = MockIndicatorValues()
        structure = MockStructure(last_bos=MockBOS(type="bullish"))
        regime = MockRegime()
        vol_regime = MockVolRegime()

        features = feature_builder.build(
            setup=setup, ind=ind, structure=structure,
            regime=regime, vol_regime=vol_regime,
            mtf_aligned=True, mtf_count=2,
            context_score=0.3, fear_greed=40, funding_rate=-0.005,
            sl=49500.0, tp=51500.0, entry_price=50000.0,
            candle_quality=MockCandleQuality(),
        )
        assert isinstance(features, SetupFeatures)
        assert features.has_bos is True
        assert features.structure_bos_aligned is True

    def test_to_vector_returns_dict(self):
        features = SetupFeatures(
            has_bos=True, has_sweep=False, has_ob=True,
            components_count=2, volume_ratio=1.5,
            rr_ratio=3.0, rsi=55.0, adx=25.0,
        )
        vec = features.to_vector()
        assert isinstance(vec, dict)
        assert vec["has_bos"] == 1
        assert vec["has_sweep"] == 0
        assert vec["has_ob"] == 1
        assert vec["components_count"] == 2
        assert vec["volume_ratio"] == 1.5
        assert vec["rr_ratio"] == 3.0
        assert vec["rsi"] == 55.0

    def test_to_vector_numeric_only(self):
        features = SetupFeatures()
        vec = features.to_vector()
        for k, v in vec.items():
            assert isinstance(v, (int, float)), f"{k} is not numeric: {type(v)}"

    def test_to_vector_structure_encoding(self):
        features = SetupFeatures(structure_trend="bullish")
        vec = features.to_vector()
        assert vec["structure_trend"] == 1

        features = SetupFeatures(structure_trend="bearish")
        vec = features.to_vector()
        assert vec["structure_trend"] == -1

        features = SetupFeatures(structure_trend="ranging")
        vec = features.to_vector()
        assert vec["structure_trend"] == 0

    def test_to_vector_regime_encoding(self):
        for regime, expected in [("trend", 1), ("expansion", 0.5), ("range", -0.5), ("compression", -1)]:
            features = SetupFeatures(regime=regime)
            vec = features.to_vector()
            assert vec["regime"] == expected, f"regime={regime}"

    def test_to_vector_session_encoding(self):
        for session, expected in [("asian", 0), ("london", 1), ("overlap", 2), ("new_york", 3), ("off_hours", 4)]:
            features = SetupFeatures(session=session)
            vec = features.to_vector()
            assert vec["session"] == expected

    def test_to_reasoning_basic(self):
        features = SetupFeatures(
            has_bos=True, structure_trend="bullish",
            has_ob=True, ob_distance_pct=0.5,
            volume_ratio=2.0, rr_ratio=3.0,
            session="london",
        )
        reasons = features.to_reasoning()
        assert len(reasons) >= 3
        assert any("BOS" in r for r in reasons)
        assert any("Volume" in r for r in reasons)

    def test_to_reasoning_empty(self):
        features = SetupFeatures()
        reasons = features.to_reasoning()
        assert isinstance(reasons, list)

    def test_build_calculates_rr_ratio(self):
        setup = ICTSetup(
            detected=True, direction="buy",
            has_bos=True, components_found=["BOS"],
        )
        ind = MockIndicatorValues()
        structure = MockStructure(last_bos=MockBOS(type="bullish"))

        features = feature_builder.build(
            setup=setup, ind=ind, structure=structure,
            regime=MockRegime(), vol_regime=MockVolRegime(),
            mtf_aligned=False, mtf_count=0,
            context_score=None, fear_greed=None, funding_rate=None,
            sl=49500.0, tp=51500.0, entry_price=50000.0,
            candle_quality=None,
        )
        # risk = 500, reward = 1500, rr = 3.0
        assert features.rr_ratio == 3.0

    def test_build_calculates_sl_distance(self):
        setup = ICTSetup(
            detected=True, direction="buy",
            has_bos=True, components_found=["BOS"],
        )
        ind = MockIndicatorValues()
        structure = MockStructure(last_bos=MockBOS(type="bullish"))

        features = feature_builder.build(
            setup=setup, ind=ind, structure=structure,
            regime=MockRegime(), vol_regime=MockVolRegime(),
            mtf_aligned=False, mtf_count=0,
            context_score=None, fear_greed=None, funding_rate=None,
            sl=49500.0, tp=51500.0, entry_price=50000.0,
            candle_quality=None,
        )
        # (50000 - 49500) / 50000 * 100 = 1.0%
        assert features.sl_distance_pct == 1.0

    def test_build_calculates_volume_ratio(self):
        setup = ICTSetup(
            detected=True, direction="buy",
            has_bos=True, components_found=["BOS"],
        )
        ind = MockIndicatorValues(volume=1500.0, volume_sma=1000.0)
        structure = MockStructure(last_bos=MockBOS(type="bullish"))

        features = feature_builder.build(
            setup=setup, ind=ind, structure=structure,
            regime=MockRegime(), vol_regime=MockVolRegime(),
            mtf_aligned=False, mtf_count=0,
            context_score=None, fear_greed=None, funding_rate=None,
            sl=49500.0, tp=51500.0, entry_price=50000.0,
            candle_quality=None,
        )
        assert features.volume_ratio == 1.5

    def test_build_calculates_ema_spread(self):
        setup = ICTSetup(
            detected=True, direction="buy",
            has_bos=True, components_found=["BOS"],
        )
        ind = MockIndicatorValues(ema_fast=50100.0, ema_slow=49900.0)
        structure = MockStructure(last_bos=MockBOS(type="bullish"))

        features = feature_builder.build(
            setup=setup, ind=ind, structure=structure,
            regime=MockRegime(), vol_regime=MockVolRegime(),
            mtf_aligned=False, mtf_count=0,
            context_score=None, fear_greed=None, funding_rate=None,
            sl=49500.0, tp=51500.0, entry_price=50000.0,
            candle_quality=None,
        )
        # (50100 - 49900) / 49900 * 100 ≈ 0.40%
        expected = (50100.0 - 49900.0) / 49900.0 * 100
        assert abs(features.ema_spread_pct - expected) < 0.01

    def test_build_supertrend_aligned(self):
        setup = ICTSetup(
            detected=True, direction="buy",
            has_bos=True, components_found=["BOS"],
        )
        ind = MockIndicatorValues(supertrend_direction=1)
        structure = MockStructure(last_bos=MockBOS(type="bullish"))

        features = feature_builder.build(
            setup=setup, ind=ind, structure=structure,
            regime=MockRegime(), vol_regime=MockVolRegime(),
            mtf_aligned=False, mtf_count=0,
            context_score=None, fear_greed=None, funding_rate=None,
            sl=49500.0, tp=51500.0, entry_price=50000.0,
            candle_quality=None,
        )
        assert features.supertrend_aligned is True

    def test_build_supertrend_not_aligned(self):
        setup = ICTSetup(
            detected=True, direction="buy",
            has_bos=True, components_found=["BOS"],
        )
        ind = MockIndicatorValues(supertrend_direction=-1)
        structure = MockStructure(last_bos=MockBOS(type="bullish"))

        features = feature_builder.build(
            setup=setup, ind=ind, structure=structure,
            regime=MockRegime(), vol_regime=MockVolRegime(),
            mtf_aligned=False, mtf_count=0,
            context_score=None, fear_greed=None, funding_rate=None,
            sl=49500.0, tp=51500.0, entry_price=50000.0,
            candle_quality=None,
        )
        assert features.supertrend_aligned is False

    def test_build_with_none_ind(self):
        setup = ICTSetup(
            detected=True, direction="buy",
            has_bos=True, components_found=["BOS"],
        )
        features = feature_builder.build(
            setup=setup, ind=None, structure=None,
            regime=None, vol_regime=None,
            mtf_aligned=False, mtf_count=0,
            context_score=None, fear_greed=None, funding_rate=None,
            sl=49500.0, tp=51500.0, entry_price=50000.0,
            candle_quality=None,
        )
        assert features.rsi == 50.0
        assert features.adx == 20.0
        assert features.structure_trend == "ranging"

    def test_build_context_values(self):
        setup = ICTSetup(
            detected=True, direction="buy",
            has_bos=True, components_found=["BOS"],
        )
        features = feature_builder.build(
            setup=setup, ind=MockIndicatorValues(), structure=MockStructure(),
            regime=MockRegime(), vol_regime=MockVolRegime(),
            mtf_aligned=False, mtf_count=0,
            context_score=0.5, fear_greed=30, funding_rate=-0.01,
            sl=49500.0, tp=51500.0, entry_price=50000.0,
            candle_quality=None,
        )
        assert features.fear_greed == 30
        assert features.funding_rate == -0.01
        assert features.context_score == 0.5


# ============================================================
# ProbabilityEngine Tests
# ============================================================

class TestProbabilityEngine:
    def test_singleton_exists(self):
        assert probability_engine is not None
        assert isinstance(probability_engine, ProbabilityEngine)

    def test_rules_based_fallback(self):
        features = SetupFeatures(
            has_bos=True, has_ob=True, components_count=2,
            structure_bos_aligned=True, volume_ratio=1.5,
            rr_ratio=2.5, rsi=55.0, adx=25.0,
            session="london", mtf_aligned=True,
        )
        prob = probability_engine.predict(features)
        assert isinstance(prob, TradeProbability)
        assert prob.model_type == "rules"
        assert 0.0 <= prob.p_tp <= 1.0
        assert prob.expected_rr > 0
        assert prob.profit_factor > 0

    def test_p_tp_in_range(self):
        features = SetupFeatures(
            has_bos=True, components_count=2, rr_ratio=2.0,
        )
        prob = probability_engine.predict(features)
        assert 0.2 <= prob.p_tp <= 0.85  # clamped

    def test_quality_label_strong(self):
        prob = TradeProbability(p_tp=0.70, expected_rr=2.0, profit_factor=2.5, confidence=0.8, model_type="rules")
        assert prob.quality_label == "strong"

    def test_quality_label_moderate(self):
        prob = TradeProbability(p_tp=0.55, expected_rr=2.0, profit_factor=2.0, confidence=0.6, model_type="rules")
        assert prob.quality_label == "moderate"

    def test_quality_label_weak(self):
        prob = TradeProbability(p_tp=0.40, expected_rr=1.5, profit_factor=1.5, confidence=0.4, model_type="rules")
        assert prob.quality_label == "weak"

    def test_profit_factor_label_excellent(self):
        prob = TradeProbability(p_tp=0.60, expected_rr=3.0, profit_factor=3.0, confidence=0.8, model_type="rules")
        assert prob.profit_factor_label == "excellent"

    def test_profit_factor_label_good(self):
        prob = TradeProbability(p_tp=0.55, expected_rr=2.5, profit_factor=1.8, confidence=0.7, model_type="rules")
        assert prob.profit_factor_label == "good"

    def test_profit_factor_label_marginal(self):
        prob = TradeProbability(p_tp=0.50, expected_rr=2.0, profit_factor=1.1, confidence=0.5, model_type="rules")
        assert prob.profit_factor_label == "marginal"

    def test_profit_factor_label_poor(self):
        prob = TradeProbability(p_tp=0.40, expected_rr=1.5, profit_factor=0.8, confidence=0.4, model_type="rules")
        assert prob.profit_factor_label == "poor"

    def test_p_tp_pct(self):
        prob = TradeProbability(p_tp=0.625, expected_rr=2.0, profit_factor=2.5, confidence=0.8, model_type="rules")
        assert prob.p_tp_pct == 62.5

    def test_more_components_higher_p_tp(self):
        features_few = SetupFeatures(
            has_bos=True, components_count=1, rr_ratio=2.0,
        )
        features_many = SetupFeatures(
            has_bos=True, has_sweep=True, has_ob=True, has_fvg=True,
            components_count=4, rr_ratio=2.0,
        )
        prob_few = probability_engine.predict(features_few)
        prob_many = probability_engine.predict(features_many)
        assert prob_many.p_tp > prob_few.p_tp

    def test_higher_rr_higher_p_tp(self):
        features_low_rr = SetupFeatures(
            has_bos=True, components_count=2, rr_ratio=1.5,
        )
        features_high_rr = SetupFeatures(
            has_bos=True, components_count=2, rr_ratio=4.0,
        )
        prob_low = probability_engine.predict(features_low_rr)
        prob_high = probability_engine.predict(features_high_rr)
        assert prob_high.p_tp >= prob_low.p_tp

    def test_volume_boosts_p_tp(self):
        features_low_vol = SetupFeatures(
            has_bos=True, components_count=2, rr_ratio=2.0,
            volume_ratio=0.8,
        )
        features_high_vol = SetupFeatures(
            has_bos=True, components_count=2, rr_ratio=2.0,
            volume_ratio=3.0,
        )
        prob_low = probability_engine.predict(features_low_vol)
        prob_high = probability_engine.predict(features_high_vol)
        assert prob_high.p_tp > prob_low.p_tp

    def test_mtf_aligned_boosts(self):
        features_no_mtf = SetupFeatures(
            has_bos=True, components_count=2, rr_ratio=2.0,
            mtf_aligned=False,
        )
        features_mtf = SetupFeatures(
            has_bos=True, components_count=2, rr_ratio=2.0,
            mtf_aligned=True,
        )
        prob_no = probability_engine.predict(features_no_mtf)
        prob_mtf = probability_engine.predict(features_mtf)
        assert prob_mtf.p_tp >= prob_no.p_tp

    def test_get_top_features_empty(self):
        # No ML model loaded
        result = probability_engine.get_top_features(5)
        assert isinstance(result, list)


# ============================================================
# RiskEngine Tests
# ============================================================

class TestRiskEngine:
    def test_singleton_exists(self):
        assert risk_engine is not None
        assert isinstance(risk_engine, RiskEngine)

    def test_valid_trade_passes(self):
        features = SetupFeatures(atr_pct=2.0)
        prob = TradeProbability(p_tp=0.65, expected_rr=2.5, profit_factor=2.5, confidence=0.8, model_type="rules")
        portfolio = PortfolioState(active_count=0, total_risk_pct=0.0)

        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49000.0, tp=53000.0,
        )
        assert decision.should_trade is True
        assert decision.risk_pct > 0
        # (53000-50000)/(50000-49000) = 3000/1000 = 3.0
        assert decision.rr_ratio == 3.0
        assert decision.sl_price == 49000.0
        assert decision.tp_price == 53000.0

    def test_rr_too_low_rejects(self):
        features = SetupFeatures(atr_pct=2.0)
        prob = TradeProbability(p_tp=0.55, expected_rr=2.0, profit_factor=2.0, confidence=0.7, model_type="rules")
        portfolio = PortfolioState()

        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49000.0, tp=50500.0,  # rr = 500/1000 = 0.5
        )
        assert decision.should_trade is False
        assert "RR=" in decision.rejection_reason

    def test_sl_too_tight_rejects(self):
        features = SetupFeatures(atr_pct=2.0)
        prob = TradeProbability(p_tp=0.65, expected_rr=2.5, profit_factor=2.5, confidence=0.8, model_type="rules")
        portfolio = PortfolioState()

        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49980.0, tp=51000.0,  # sl_distance = 0.04%
        )
        assert decision.should_trade is False
        assert "SL too tight" in decision.rejection_reason

    def test_sl_too_wide_rejects(self):
        features = SetupFeatures(atr_pct=2.0)
        prob = TradeProbability(p_tp=0.65, expected_rr=2.5, profit_factor=2.5, confidence=0.8, model_type="rules")
        portfolio = PortfolioState()

        # SL=6% from entry, but also RR=1.0 < 1.5 → RR rejects first
        # Use a TP that gives good RR so SL width is the failing gate
        # SL=47000 (6% below 50000), TP=56000 (12% above) → RR=2.0 > 1.5
        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=47000.0, tp=56000.0,  # sl_distance = 6%
        )
        assert decision.should_trade is False
        assert "SL too wide" in decision.rejection_reason

    def test_portfolio_risk_full_rejects(self):
        features = SetupFeatures(atr_pct=2.0)
        prob = TradeProbability(p_tp=0.65, expected_rr=2.5, profit_factor=2.5, confidence=0.8, model_type="rules")
        portfolio = PortfolioState(active_count=1, total_risk_pct=3.0)

        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49500.0, tp=51500.0,
        )
        assert decision.should_trade is False
        assert "portfolio risk" in decision.rejection_reason

    def test_max_active_signals_rejects(self):
        features = SetupFeatures(atr_pct=2.0)
        prob = TradeProbability(p_tp=0.65, expected_rr=2.5, profit_factor=2.5, confidence=0.8, model_type="rules")
        portfolio = PortfolioState(active_count=3, total_risk_pct=1.0)

        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49500.0, tp=51500.0,
        )
        assert decision.should_trade is False
        assert "max active signals" in decision.rejection_reason

    def test_invalid_price_rejects(self):
        features = SetupFeatures()
        prob = TradeProbability(p_tp=0.6, expected_rr=2.0, profit_factor=2.0, confidence=0.7, model_type="rules")
        portfolio = PortfolioState()

        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=0.0, sl=49500.0, tp=51500.0,
        )
        assert decision.should_trade is False
        assert "invalid price" in decision.rejection_reason

    def test_zero_risk_distance_rejects(self):
        features = SetupFeatures()
        prob = TradeProbability(p_tp=0.6, expected_rr=2.0, profit_factor=2.0, confidence=0.7, model_type="rules")
        portfolio = PortfolioState()

        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=50000.0, tp=51500.0,
        )
        assert decision.should_trade is False
        assert "zero risk" in decision.rejection_reason

    def test_high_volatility_reduces_risk(self):
        prob = TradeProbability(p_tp=0.65, expected_rr=2.5, profit_factor=2.5, confidence=0.8, model_type="rules")
        portfolio = PortfolioState()

        features_low_vol = SetupFeatures(atr_pct=1.0)
        decision_low = risk_engine.evaluate(
            features=features_low_vol, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49500.0, tp=51500.0,
        )

        features_high_vol = SetupFeatures(atr_pct=5.0)
        decision_high = risk_engine.evaluate(
            features=features_high_vol, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49500.0, tp=51500.0,
        )
        assert decision_high.risk_pct <= decision_low.risk_pct

    def test_tight_sl_bonus(self):
        prob = TradeProbability(p_tp=0.65, expected_rr=2.5, profit_factor=2.5, confidence=0.8, model_type="rules")
        portfolio = PortfolioState()

        features = SetupFeatures(atr_pct=2.0)
        # SL=49850 (0.30% from 50000) passes min 0.25% and gets tight SL bonus
        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49850.0, tp=53000.0,  # sl_distance = 0.30%, rr = 20.0
        )
        assert decision.should_trade is True

    def test_custom_config(self):
        engine = RiskEngine(min_rr_ratio=2.0, sl_absolute_max_pct=3.0)
        prob = TradeProbability(p_tp=0.65, expected_rr=2.5, profit_factor=2.5, confidence=0.8, model_type="rules")
        portfolio = PortfolioState()

        decision = engine.evaluate(
            features=SetupFeatures(atr_pct=2.0),
            probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49500.0, tp=51500.0,  # sl_distance = 1.0%
        )
        assert decision.should_trade is True

    def test_custom_config_stricter_rr(self):
        engine = RiskEngine(min_rr_ratio=3.0)
        prob = TradeProbability(p_tp=0.65, expected_rr=2.5, profit_factor=2.5, confidence=0.8, model_type="rules")
        portfolio = PortfolioState()

        decision = engine.evaluate(
            features=SetupFeatures(atr_pct=2.0),
            probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49500.0, tp=51500.0,  # rr = 3.0
        )
        assert decision.should_trade is True

        decision2 = engine.evaluate(
            features=SetupFeatures(atr_pct=2.0),
            probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49500.0, tp=51000.0,  # rr = 1.0
        )
        assert decision2.should_trade is False

    def test_kelly_fraction_used(self):
        features = SetupFeatures(atr_pct=2.0)
        prob = TradeProbability(p_tp=0.75, expected_rr=3.0, profit_factor=3.0, confidence=0.9, model_type="rules")
        portfolio = PortfolioState()

        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49500.0, tp=52500.0,
        )
        assert decision.should_trade is True
        assert decision.kelly_fraction > 0
        assert decision.probability_confidence == 0.9


# ============================================================
# ContextScore Tests (new simplified scorer)
# ============================================================

class TestContextScore:
    @pytest.fixture
    def scorer(self):
        return ContextScorer()

    def test_score_simple_returns_context_score(self, scorer):
        from context.analyzer import ContextSnapshot
        snap = ContextSnapshot(
            symbol="BTC/USDT",
            timestamp=datetime.now(timezone.utc),
            fear_greed_value=25,
        )
        result = scorer.score_simple("BUY", snap)
        assert isinstance(result, ContextScore)
        assert not hasattr(result, "verdict")  # no verdict field
        assert -1.0 <= result.score <= 1.0

    def test_score_simple_never_blocks(self, scorer):
        from context.analyzer import ContextSnapshot
        # Very unfavorable context
        snap = ContextSnapshot(
            symbol="BTC/USDT",
            timestamp=datetime.now(timezone.utc),
            fear_greed_value=95,
            funding_rate=0.05,
        )
        result = scorer.score_simple("BUY", snap)
        # Should still return a score, never BLOCKED
        assert isinstance(result, ContextScore)
        assert -1.0 <= result.score <= 1.0

    def test_score_simple_has_supporting_opposing(self, scorer):
        from context.analyzer import ContextSnapshot
        snap = ContextSnapshot(
            symbol="BTC/USDT",
            timestamp=datetime.now(timezone.utc),
            fear_greed_value=20,
            funding_rate=-0.005,
        )
        result = scorer.score_simple("BUY", snap)
        assert isinstance(result.supporting, list)
        assert isinstance(result.opposing, list)

    def test_context_score_properties(self):
        cs = ContextScore(score=0.5, confidence=0.5)
        assert cs.score == 0.5
        assert cs.confidence == 0.5
        assert cs.supporting == []
        assert cs.opposing == []


# ============================================================
# Integration: Full Pipeline Test
# ============================================================

class TestPipelineIntegration:
    def test_end_to_end_buy(self):
        """Test full pipeline: PatternEngine → FeatureBuilder → ProbabilityEngine → RiskEngine"""
        # 1. PatternEngine
        structure = MockStructure(last_bos=MockBOS(type="bullish"))
        obs = [MockOB(type="bullish")]
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=obs, structure=structure,
            fvgs=[], candle_quality=MockCandleQuality(), current_price=50000.0,
        )
        assert setup.detected is True
        assert setup.direction == "buy"

        # 2. FeatureBuilder
        ind = MockIndicatorValues()
        features = feature_builder.build(
            setup=setup, ind=ind, structure=structure,
            regime=MockRegime(), vol_regime=MockVolRegime(),
            mtf_aligned=True, mtf_count=2,
            context_score=0.3, fear_greed=40, funding_rate=-0.005,
            sl=49500.0, tp=51500.0, entry_price=50000.0,
            candle_quality=MockCandleQuality(),
        )
        assert isinstance(features, SetupFeatures)

        # 3. ProbabilityEngine
        prob = probability_engine.predict(features)
        assert prob.p_tp > 0
        assert prob.model_type == "rules"

        # 4. RiskEngine
        portfolio = PortfolioState()
        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49500.0, tp=51500.0,
        )
        assert decision.should_trade is True
        assert decision.risk_pct > 0
        assert decision.rr_ratio == 3.0

    def test_end_to_end_sell(self):
        """Test full pipeline for sell signal."""
        sweeps = [MockSweep(type="bearish")]
        fvgs = [MockFVG(type="bearish")]
        setup = pattern_engine.detect(
            sweeps=sweeps, order_blocks=[], structure=MockStructure(),
            fvgs=fvgs, candle_quality=None, current_price=50000.0,
        )
        assert setup.detected is True
        assert setup.direction == "sell"

        features = feature_builder.build(
            setup=setup, ind=MockIndicatorValues(), structure=MockStructure(),
            regime=MockRegime(), vol_regime=MockVolRegime(),
            mtf_aligned=False, mtf_count=0,
            context_score=None, fear_greed=None, funding_rate=None,
            sl=51000.0, tp=48000.0, entry_price=50000.0,
            candle_quality=None,
        )
        prob = probability_engine.predict(features)
        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=PortfolioState(),
            entry_price=50000.0, sl=51000.0, tp=48000.0,
        )
        assert decision.should_trade is True
        assert decision.rr_ratio == 2.0

    def test_no_pattern_no_features(self):
        """No pattern detected → no feature building needed."""
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=[], structure=None,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.detected is False
        # In real pipeline, we'd stop here and not build features

    def test_risk_engine_blocks_bad_rr(self):
        """RiskEngine blocks even if ProbabilityEngine gives high P(TP)."""
        features = SetupFeatures(atr_pct=2.0)
        prob = TradeProbability(p_tp=0.80, expected_rr=3.0, profit_factor=3.0, confidence=0.9, model_type="rules")
        portfolio = PortfolioState()

        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49500.0, tp=50200.0,  # rr = 0.4
        )
        assert decision.should_trade is False
        assert "RR=" in decision.rejection_reason
