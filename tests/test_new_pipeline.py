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
from market_structure.structure import (
    CHoCH, BOS, StructureState, SwingPoint,
    classify_choch, calc_mss_score, calc_causality,
)


# === Mock objects ===

@dataclass
class MockBOS:
    type: str = "bullish"
    level: float = 50000.0
    timestamp: datetime = None
    candle_index: int = 10


@dataclass
class MockCHoCH:
    type: str = "bearish"
    level: float = 49000.0
    timestamp: datetime = None
    candle_index: int = 5
    strength: str = "mss"
    mss_score: float = 75.0
    causality_score: float = 0.8


@dataclass
class MockStructure:
    trend: str = "bullish"
    last_bos: object = None
    last_choch: object = None
    last_mss: object = None
    recent_highs: list = None
    recent_lows: list = None
    swing_points: list = None

    def __post_init__(self):
        if self.recent_highs is None:
            self.recent_highs = []
        if self.recent_lows is None:
            self.recent_lows = []
        if self.swing_points is None:
            self.swing_points = []


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
    candle_index: int = 0


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
    body_atr_ratio: float = 1.5


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
# MSS Classification Tests (structure.py)
# ============================================================

class TestMSSClassification:
    def test_calc_causality_zero_bars(self):
        assert calc_causality(0) == 1.0

    def test_calc_causality_3_bars(self):
        # exp(-0.693 * 3 / 3) = exp(-0.693) ≈ 0.5
        assert abs(calc_causality(3) - 0.5) < 0.05

    def test_calc_causality_5_bars(self):
        # exp(-0.693 * 5 / 3) ≈ 0.315
        assert calc_causality(5) < 0.5
        assert calc_causality(5) > 0.2

    def test_calc_causality_10_bars(self):
        assert calc_causality(10) < 0.15

    def test_calc_causality_negative(self):
        assert calc_causality(-1) == 0.0

    def test_calc_mss_score_all_max(self):
        score = calc_mss_score(
            sweep_strength=1.0, displacement_atr=3.0,
            reclaim_bars=1, volume_ratio=3.0, htf_aligned=True,
        )
        assert score == 100.0

    def test_calc_mss_score_all_zero(self):
        score = calc_mss_score(
            sweep_strength=0.0, displacement_atr=0.0,
            reclaim_bars=10, volume_ratio=0.5, htf_aligned=False,
        )
        assert score == 0.0

    def test_calc_mss_score_partial(self):
        score = calc_mss_score(
            sweep_strength=0.5, displacement_atr=1.5,
            reclaim_bars=2, volume_ratio=2.0, htf_aligned=False,
        )
        assert 30 < score < 70

    def test_classify_choch_as_mss(self):
        choch = CHoCH(type="bearish", level=49000, timestamp=datetime.now(timezone.utc), candle_index=5)
        sweep = MockSweep(type="bearish", candle_index=2, is_valid=True)
        result = classify_choch(
            choch, sweeps=[sweep],
            displacement_atr=1.5, reclaim_bars=1,
            volume_ratio=2.0, htf_aligned=True,
        )
        assert result.strength == "mss"
        assert result.mss_score > 50
        assert result.has_sweep_reference is True

    def test_classify_choch_weak_no_sweep(self):
        choch = CHoCH(type="bearish", level=49000, timestamp=datetime.now(timezone.utc), candle_index=5)
        result = classify_choch(
            choch, sweeps=[],
            displacement_atr=1.5, reclaim_bars=1,
        )
        assert result.strength == "weak"
        assert result.mss_score == 0.0

    def test_classify_choch_normal_with_sweep(self):
        choch = CHoCH(type="bearish", level=49000, timestamp=datetime.now(timezone.utc), candle_index=5)
        sweep = MockSweep(type="bearish", candle_index=2, is_valid=True)
        result = classify_choch(
            choch, sweeps=[sweep],
            displacement_atr=0.6, reclaim_bars=3,
        )
        assert result.strength == "normal"
        assert result.mss_score > 0

    def test_classify_choch_too_far_from_sweep(self):
        choch = CHoCH(type="bearish", level=49000, timestamp=datetime.now(timezone.utc), candle_index=20)
        sweep = MockSweep(type="bearish", candle_index=0, is_valid=True)
        result = classify_choch(
            choch, sweeps=[sweep],
            displacement_atr=1.5, reclaim_bars=1,
            max_causal_bars=5,
        )
        assert result.strength == "weak"
        assert result.has_sweep_reference is False


# ============================================================
# PatternEngine Tests
# ============================================================

class TestPatternEngine:
    def test_singleton_exists(self):
        assert pattern_engine is not None
        assert isinstance(pattern_engine, PatternEngine)

    def test_no_valid_setup_returns_rejection(self):
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=[], structure=None,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.detected is False
        assert setup.rejection_reason is not None

    # ── Reversal tests ──

    def test_reversal_full_setup(self):
        """Sweep + Displacement + MSS → reversal detected."""
        sweeps = [MockSweep(type="bearish", candle_index=2, is_valid=True)]
        structure = MockStructure(
            last_mss=MockCHoCH(type="bearish", candle_index=5),
            last_choch=MockCHoCH(type="bearish", candle_index=5),
        )
        candle_q = MockCandleQuality(is_displacement=True, body_pct=0.75, body_atr_ratio=1.5)

        setup = pattern_engine.detect(
            sweeps=sweeps, order_blocks=[], structure=structure,
            fvgs=[], candle_quality=candle_q, current_price=50000.0, atr=500.0,
        )
        assert setup.detected is True
        assert setup.direction == "sell"
        assert setup.setup_type == "reversal"
        assert setup.has_sweep is True
        assert setup.has_displacement is True
        assert setup.has_mss is True

    def test_reversal_no_sweep(self):
        """No sweep → reversal not detected."""
        structure = MockStructure(
            last_mss=MockCHoCH(type="bearish"),
            last_choch=MockCHoCH(type="bearish"),
        )
        candle_q = MockCandleQuality(is_displacement=True)

        setup = pattern_engine.detect(
            sweeps=[], order_blocks=[], structure=structure,
            fvgs=[], candle_quality=candle_q, current_price=50000.0, atr=500.0,
        )
        assert setup.detected is False
        assert setup.setup_type is None

    def test_reversal_no_displacement(self):
        """Sweep but no displacement → reversal not detected."""
        sweeps = [MockSweep(type="bearish", candle_index=2)]
        structure = MockStructure(
            last_mss=MockCHoCH(type="bearish"),
            last_choch=MockCHoCH(type="bearish"),
        )
        candle_q = MockCandleQuality(is_displacement=False)

        setup = pattern_engine.detect(
            sweeps=sweeps, order_blocks=[], structure=structure,
            fvgs=[], candle_quality=candle_q, current_price=50000.0, atr=500.0,
        )
        assert setup.detected is False
        assert "displacement" in setup.rejection_reason.lower()

    def test_reversal_no_mss(self):
        """Sweep + displacement but no MSS → reversal not detected."""
        sweeps = [MockSweep(type="bearish", candle_index=2)]
        structure = MockStructure(last_mss=None, last_choch=None)
        candle_q = MockCandleQuality(is_displacement=True, body_atr_ratio=1.5)

        setup = pattern_engine.detect(
            sweeps=sweeps, order_blocks=[], structure=structure,
            fvgs=[], candle_quality=candle_q, current_price=50000.0, atr=500.0,
        )
        assert setup.detected is False
        assert "MSS" in setup.rejection_reason

    # ── Continuation tests ──

    def test_continuation_full_setup(self):
        """Trend + BOS aligned → continuation detected."""
        structure = MockStructure(
            trend="bullish",
            last_bos=MockBOS(type="bullish", level=51000),
        )
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=[], structure=structure,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.detected is True
        assert setup.direction == "buy"
        assert setup.setup_type == "continuation"
        assert setup.has_bos is True

    def test_continuation_no_bos(self):
        """Trend but no BOS → continuation not detected."""
        structure = MockStructure(trend="bullish", last_bos=None)
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=[], structure=structure,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.detected is False
        assert "BOS" in setup.rejection_reason

    def test_continuation_ranging_rejected(self):
        """Ranging market → continuation not detected."""
        structure = MockStructure(trend="ranging", last_bos=MockBOS(type="bullish"))
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=[], structure=structure,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.detected is False
        assert "ranging" in setup.rejection_reason.lower()

    def test_continuation_bos_vs_trend_rejected(self):
        """BOS direction vs trend direction → continuation not detected."""
        structure = MockStructure(
            trend="bullish",
            last_bos=MockBOS(type="bearish"),  # bearish BOS in bullish trend
        )
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=[], structure=structure,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.detected is False
        assert "trend" in setup.rejection_reason.lower()

    # ── Entry zone tests ──

    def test_ob_detected_as_entry_zone(self):
        """OB is detected but is NOT a gate — it's an entry zone."""
        sweeps = [MockSweep(type="bearish", candle_index=2)]
        structure = MockStructure(
            last_mss=MockCHoCH(type="bearish", candle_index=5),
            last_choch=MockCHoCH(type="bearish", candle_index=5),
        )
        obs = [MockOB(type="bearish", midpoint=50500.0)]
        candle_q = MockCandleQuality(is_displacement=True, body_atr_ratio=1.5)

        setup = pattern_engine.detect(
            sweeps=sweeps, order_blocks=obs, structure=structure,
            fvgs=[], candle_quality=candle_q, current_price=50000.0, atr=500.0,
        )
        assert setup.detected is True
        assert setup.has_ob is True
        assert setup.ob_midpoint == 50500.0

    def test_ob_not_required_for_reversal(self):
        """Reversal can be detected without OB (OB is optional entry zone)."""
        sweeps = [MockSweep(type="bearish", candle_index=2)]
        structure = MockStructure(
            last_mss=MockCHoCH(type="bearish", candle_index=5),
            last_choch=MockCHoCH(type="bearish", candle_index=5),
        )
        candle_q = MockCandleQuality(is_displacement=True, body_atr_ratio=1.5)

        setup = pattern_engine.detect(
            sweeps=sweeps, order_blocks=[], structure=structure,
            fvgs=[], candle_quality=candle_q, current_price=50000.0, atr=500.0,
        )
        assert setup.detected is True
        assert setup.has_ob is False

    def test_fvg_not_required_for_reversal(self):
        """Reversal can be detected without FVG."""
        sweeps = [MockSweep(type="bearish", candle_index=2)]
        structure = MockStructure(
            last_mss=MockCHoCH(type="bearish", candle_index=5),
            last_choch=MockCHoCH(type="bearish", candle_index=5),
        )
        candle_q = MockCandleQuality(is_displacement=True, body_atr_ratio=1.5)

        setup = pattern_engine.detect(
            sweeps=sweeps, order_blocks=[], structure=structure,
            fvgs=[], candle_quality=candle_q, current_price=50000.0, atr=500.0,
        )
        assert setup.detected is True
        assert setup.has_fvg is False

    def test_entry_armed_when_ob_nearby(self):
        """Price near OB midpoint → entry_armed=True."""
        sweeps = [MockSweep(type="bearish", candle_index=2)]
        structure = MockStructure(
            last_mss=MockCHoCH(type="bearish", candle_index=5),
            last_choch=MockCHoCH(type="bearish", candle_index=5),
        )
        obs = [MockOB(type="bearish", midpoint=50050.0)]  # very close to 50000
        candle_q = MockCandleQuality(is_displacement=True, body_atr_ratio=1.5)

        setup = pattern_engine.detect(
            sweeps=sweeps, order_blocks=obs, structure=structure,
            fvgs=[], candle_quality=candle_q, current_price=50000.0, atr=500.0,
        )
        assert setup.entry_armed is True

    def test_entry_not_armed_when_ob_far(self):
        """Price far from OB midpoint → entry_armed=False."""
        sweeps = [MockSweep(type="bearish", candle_index=2)]
        structure = MockStructure(
            last_mss=MockCHoCH(type="bearish", candle_index=5),
            last_choch=MockCHoCH(type="bearish", candle_index=5),
        )
        obs = [MockOB(type="bearish", midpoint=55000.0)]  # far from 50000
        candle_q = MockCandleQuality(is_displacement=True, body_atr_ratio=1.5)

        setup = pattern_engine.detect(
            sweeps=sweeps, order_blocks=obs, structure=structure,
            fvgs=[], candle_quality=candle_q, current_price=50000.0, atr=500.0,
        )
        assert setup.entry_armed is False

    # ── ICTSetup properties ──

    def test_ict_setup_components_count(self):
        setup = ICTSetup(
            detected=True, setup_type="reversal",
            has_sweep=True, has_displacement=True, has_mss=True,
            components_found=["Sweep", "Displacement", "MSS"],
        )
        assert setup.components_count == 3
        assert setup.is_reversal is True
        assert setup.is_continuation is False

    def test_ict_setup_continuation_properties(self):
        setup = ICTSetup(
            detected=True, setup_type="continuation",
            has_bos=True, components_found=["BOS"],
        )
        assert setup.is_continuation is True
        assert setup.is_reversal is False

    def test_ict_setup_has_trigger_backward_compat(self):
        setup = ICTSetup(detected=True, has_sweep=True)
        assert setup.has_trigger is True

        setup2 = ICTSetup(detected=True, has_bos=True)
        assert setup2.has_trigger is True

        setup3 = ICTSetup(detected=False)
        assert setup3.has_trigger is False


# ============================================================
# FeatureBuilder Tests
# ============================================================

class TestFeatureBuilder:
    def test_singleton_exists(self):
        assert feature_builder is not None
        assert isinstance(feature_builder, FeatureBuilder)

    def test_build_returns_setup_features(self):
        setup = ICTSetup(
            detected=True, direction="buy", setup_type="continuation",
            has_bos=True, bos_type="bullish",
            components_found=["BOS"],
        )
        ind = MockIndicatorValues()
        structure = MockStructure(last_bos=MockBOS(type="bullish"))

        features = feature_builder.build(
            setup=setup, ind=ind, structure=structure,
            regime=MockRegime(), vol_regime=MockVolRegime(),
            mtf_aligned=True, mtf_count=2,
            context_score=0.3, fear_greed=40, funding_rate=-0.005,
            sl=49500.0, tp=51500.0, entry_price=50000.0,
            candle_quality=MockCandleQuality(),
        )
        assert isinstance(features, SetupFeatures)
        assert features.has_bos is True
        assert features.setup_type == "continuation"
        assert features.structure_bos_aligned is True

    def test_to_vector_returns_dict(self):
        features = SetupFeatures(
            setup_type="reversal",
            has_sweep=True, has_displacement=True, has_mss=True,
            mss_score=75.0, mss_causality=0.8,
            displacement_atr_ratio=1.5, sweep_to_mss_bars=3,
            components_count=3, volume_ratio=1.5,
            rr_ratio=3.0,
        )
        vec = features.to_vector()
        assert isinstance(vec, dict)
        assert vec["setup_type"] == 1  # reversal
        assert vec["has_sweep"] == 1
        assert vec["has_mss"] == 1
        assert vec["mss_score"] == 75.0
        assert vec["components_count"] == 3

    def test_to_vector_numeric_only(self):
        features = SetupFeatures()
        vec = features.to_vector()
        for k, v in vec.items():
            assert isinstance(v, (int, float)), f"{k} is not numeric: {type(v)}"

    def test_to_vector_structure_encoding(self):
        assert SetupFeatures(structure_trend="bullish").to_vector()["structure_trend"] == 1
        assert SetupFeatures(structure_trend="bearish").to_vector()["structure_trend"] == -1
        assert SetupFeatures(structure_trend="ranging").to_vector()["structure_trend"] == 0

    def test_to_vector_session_encoding(self):
        for session, expected in [("asian", 0), ("london", 1), ("overlap", 2), ("new_york", 3), ("off_hours", 4)]:
            assert SetupFeatures(session=session).to_vector()["session"] == expected

    def test_to_reasoning_reversal(self):
        features = SetupFeatures(
            setup_type="reversal",
            has_mss=True, mss_score=80.0,
            has_displacement=True, displacement_atr_ratio=1.5,
            has_sweep=True, sweep_strength=0.8,
            entry_armed=True,
        )
        reasons = features.to_reasoning()
        assert any("MSS" in r for r in reasons)
        assert any("Displacement" in r for r in reasons)
        assert any("Sweep" in r for r in reasons)
        assert any("Entry armed" in r for r in reasons)

    def test_to_reasoning_continuation(self):
        features = SetupFeatures(
            setup_type="continuation",
            has_bos=True, structure_bos_aligned=True,
        )
        reasons = features.to_reasoning()
        assert any("BOS" in r for r in reasons)
        assert any("aligned" in r.lower() for r in reasons)

    def test_to_reasoning_empty(self):
        features = SetupFeatures()
        reasons = features.to_reasoning()
        assert isinstance(reasons, list)

    def test_build_calculates_rr_ratio(self):
        setup = ICTSetup(detected=True, direction="buy", setup_type="continuation", has_bos=True)
        features = feature_builder.build(
            setup=setup, ind=MockIndicatorValues(),
            structure=MockStructure(last_bos=MockBOS(type="bullish")),
            regime=MockRegime(), vol_regime=MockVolRegime(),
            mtf_aligned=False, mtf_count=0,
            context_score=None, fear_greed=None, funding_rate=None,
            sl=49500.0, tp=51500.0, entry_price=50000.0,
            candle_quality=None,
        )
        assert features.rr_ratio == 3.0

    def test_build_calculates_volume_ratio(self):
        setup = ICTSetup(detected=True, direction="buy", setup_type="continuation", has_bos=True)
        features = feature_builder.build(
            setup=setup, ind=MockIndicatorValues(volume=1500.0, volume_sma=1000.0),
            structure=MockStructure(last_bos=MockBOS(type="bullish")),
            regime=MockRegime(), vol_regime=MockVolRegime(),
            mtf_aligned=False, mtf_count=0,
            context_score=None, fear_greed=None, funding_rate=None,
            sl=49500.0, tp=51500.0, entry_price=50000.0,
            candle_quality=None,
        )
        assert features.volume_ratio == 1.5

    def test_build_mss_fields_populated(self):
        setup = ICTSetup(
            detected=True, direction="sell", setup_type="reversal",
            has_sweep=True, has_displacement=True, has_mss=True,
            mss_score=80.0, mss_causality=0.7,
            displacement_atr_ratio=1.8, sweep_to_mss_bars=2,
            entry_armed=True,
        )
        features = feature_builder.build(
            setup=setup, ind=MockIndicatorValues(), structure=MockStructure(),
            regime=MockRegime(), vol_regime=MockVolRegime(),
            mtf_aligned=False, mtf_count=0,
            context_score=None, fear_greed=None, funding_rate=None,
            sl=51000.0, tp=48000.0, entry_price=50000.0,
            candle_quality=None,
        )
        assert features.has_mss is True
        assert features.mss_score == 80.0
        assert features.mss_causality == 0.7
        assert features.displacement_atr_ratio == 1.8
        assert features.sweep_to_mss_bars == 2
        assert features.entry_armed is True

    def test_build_with_none_ind(self):
        setup = ICTSetup(detected=True, direction="buy", setup_type="continuation", has_bos=True)
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


# ============================================================
# ProbabilityEngine Tests
# ============================================================

class TestProbabilityEngine:
    def test_singleton_exists(self):
        assert probability_engine is not None
        assert isinstance(probability_engine, ProbabilityEngine)

    def test_rules_based_fallback(self):
        features = SetupFeatures(
            setup_type="reversal",
            has_sweep=True, has_displacement=True, has_mss=True,
            mss_score=75.0,
            components_count=3, volume_ratio=1.5,
            rr_ratio=2.5, session="london", mtf_aligned=True,
        )
        prob = probability_engine.predict(features)
        assert isinstance(prob, TradeProbability)
        assert prob.model_type == "rules"
        assert 0.0 <= prob.p_tp <= 1.0

    def test_p_tp_in_range(self):
        features = SetupFeatures(setup_type="continuation", has_bos=True, rr_ratio=2.0)
        prob = probability_engine.predict(features)
        assert 0.2 <= prob.p_tp <= 0.85

    def test_quality_labels(self):
        assert TradeProbability(p_tp=0.70, expected_rr=2.0, profit_factor=2.5, confidence=0.8, model_type="rules").quality_label == "strong"
        assert TradeProbability(p_tp=0.55, expected_rr=2.0, profit_factor=2.0, confidence=0.6, model_type="rules").quality_label == "moderate"
        assert TradeProbability(p_tp=0.40, expected_rr=1.5, profit_factor=1.5, confidence=0.4, model_type="rules").quality_label == "weak"

    def test_reversal_mss_highest_edge(self):
        """MSS gives the highest component_edge in reversal."""
        features_no_mss = SetupFeatures(
            setup_type="reversal", has_sweep=True, has_displacement=True, has_mss=False,
        )
        features_with_mss = SetupFeatures(
            setup_type="reversal", has_sweep=True, has_displacement=True, has_mss=True,
            mss_score=75.0,
        )
        prob_no = probability_engine.predict(features_no_mss)
        prob_with = probability_engine.predict(features_with_mss)
        assert prob_with.p_tp > prob_no.p_tp

    def test_continuation_bos_edge(self):
        """BOS gives edge only for continuation, not reversal."""
        features_cont = SetupFeatures(
            setup_type="continuation", has_bos=True, structure_bos_aligned=True, rr_ratio=2.0,
        )
        features_rev = SetupFeatures(
            setup_type="reversal", has_bos=True, has_sweep=True,
            has_displacement=True, has_mss=True, mss_score=70.0, rr_ratio=2.0,
        )
        prob_cont = probability_engine.predict(features_cont)
        prob_rev = probability_engine.predict(features_rev)
        # Both should have positive edge, reversal with MSS should be higher
        assert prob_rev.p_tp > 0.5
        assert prob_cont.p_tp > 0.5

    def test_volume_boosts_p_tp(self):
        features_low = SetupFeatures(setup_type="continuation", has_bos=True, rr_ratio=2.0, volume_ratio=0.8)
        features_high = SetupFeatures(setup_type="continuation", has_bos=True, rr_ratio=2.0, volume_ratio=3.0)
        prob_low = probability_engine.predict(features_low)
        prob_high = probability_engine.predict(features_high)
        assert prob_high.p_tp > prob_low.p_tp

    def test_higher_rr_higher_p_tp(self):
        features_low = SetupFeatures(setup_type="continuation", has_bos=True, rr_ratio=1.5)
        features_high = SetupFeatures(setup_type="continuation", has_bos=True, rr_ratio=4.0)
        prob_low = probability_engine.predict(features_low)
        prob_high = probability_engine.predict(features_high)
        assert prob_high.p_tp >= prob_low.p_tp

    def test_mtf_aligned_boosts(self):
        features_no = SetupFeatures(setup_type="continuation", has_bos=True, rr_ratio=2.0, mtf_aligned=False)
        features_yes = SetupFeatures(setup_type="continuation", has_bos=True, rr_ratio=2.0, mtf_aligned=True)
        prob_no = probability_engine.predict(features_no)
        prob_yes = probability_engine.predict(features_yes)
        assert prob_yes.p_tp >= prob_no.p_tp

    def test_get_top_features_empty(self):
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
        assert decision.rr_ratio == 3.0

    def test_rr_too_low_rejects(self):
        features = SetupFeatures(atr_pct=2.0)
        prob = TradeProbability(p_tp=0.55, expected_rr=2.0, profit_factor=2.0, confidence=0.7, model_type="rules")
        portfolio = PortfolioState()

        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49000.0, tp=50500.0,
        )
        assert decision.should_trade is False
        assert "RR=" in decision.rejection_reason

    def test_sl_too_tight_rejects(self):
        features = SetupFeatures(atr_pct=2.0)
        prob = TradeProbability(p_tp=0.65, expected_rr=2.5, profit_factor=2.5, confidence=0.8, model_type="rules")
        portfolio = PortfolioState()

        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49980.0, tp=51000.0,
        )
        assert decision.should_trade is False
        assert "SL too tight" in decision.rejection_reason

    def test_sl_too_wide_rejects(self):
        features = SetupFeatures(atr_pct=2.0)
        prob = TradeProbability(p_tp=0.65, expected_rr=2.5, profit_factor=2.5, confidence=0.8, model_type="rules")
        portfolio = PortfolioState()

        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=47000.0, tp=56000.0,
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

    def test_high_volatility_reduces_risk(self):
        prob = TradeProbability(p_tp=0.65, expected_rr=2.5, profit_factor=2.5, confidence=0.8, model_type="rules")
        portfolio = PortfolioState()

        features_low = SetupFeatures(atr_pct=1.0)
        decision_low = risk_engine.evaluate(
            features=features_low, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49500.0, tp=51500.0,
        )

        features_high = SetupFeatures(atr_pct=5.0)
        decision_high = risk_engine.evaluate(
            features=features_high, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49500.0, tp=51500.0,
        )
        assert decision_high.risk_pct <= decision_low.risk_pct

    def test_mss_quality_soft_adjustment(self):
        """High MSS quality should increase risk_pct (soft adjustment)."""
        prob = TradeProbability(p_tp=0.65, expected_rr=2.5, profit_factor=2.5, confidence=0.8, model_type="rules")
        portfolio = PortfolioState()

        features = SetupFeatures(atr_pct=2.0)
        decision_no_mss = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49500.0, tp=51500.0,
            mss_quality=0.0,
        )
        decision_high_mss = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=49500.0, tp=51500.0,
            mss_quality=80.0,
        )
        assert decision_high_mss.risk_pct >= decision_no_mss.risk_pct

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
# ContextScore Tests
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
        assert -1.0 <= result.score <= 1.0

    def test_score_simple_never_blocks(self, scorer):
        from context.analyzer import ContextSnapshot
        snap = ContextSnapshot(
            symbol="BTC/USDT",
            timestamp=datetime.now(timezone.utc),
            fear_greed_value=95,
            funding_rate=0.05,
        )
        result = scorer.score_simple("BUY", snap)
        assert isinstance(result, ContextScore)
        assert -1.0 <= result.score <= 1.0

    def test_context_score_properties(self):
        cs = ContextScore(score=0.5, confidence=0.5)
        assert cs.score == 0.5
        assert cs.confidence == 0.5
        assert cs.supporting == []
        assert cs.opposing == []


# ============================================================
# Integration: Full Pipeline Tests
# ============================================================

class TestPipelineIntegration:
    def test_full_reversal_pipeline(self):
        """Sweep → Displacement → MSS → Features → Probability → Risk"""
        # 1. PatternEngine — reversal
        sweeps = [MockSweep(type="bearish", candle_index=2, is_valid=True)]
        structure = MockStructure(
            last_mss=MockCHoCH(type="bearish", candle_index=5, strength="mss", mss_score=75.0),
            last_choch=MockCHoCH(type="bearish", candle_index=5, strength="mss"),
        )
        candle_q = MockCandleQuality(is_displacement=True, body_pct=0.75, body_atr_ratio=1.5)

        setup = pattern_engine.detect(
            sweeps=sweeps, order_blocks=[], structure=structure,
            fvgs=[], candle_quality=candle_q, current_price=50000.0, atr=500.0,
        )
        assert setup.detected is True
        assert setup.direction == "sell"
        assert setup.setup_type == "reversal"

        # 2. FeatureBuilder
        features = feature_builder.build(
            setup=setup, ind=MockIndicatorValues(), structure=structure,
            regime=MockRegime(), vol_regime=MockVolRegime(),
            mtf_aligned=True, mtf_count=2,
            context_score=0.2, fear_greed=50, funding_rate=0.0,
            sl=51000.0, tp=48000.0, entry_price=50000.0,
            candle_quality=candle_q,
        )
        assert features.setup_type == "reversal"
        assert features.has_mss is True

        # 3. ProbabilityEngine
        prob = probability_engine.predict(features)
        assert prob.p_tp > 0

        # 4. RiskEngine
        portfolio = PortfolioState()
        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=portfolio,
            entry_price=50000.0, sl=51000.0, tp=48000.0,
            mss_quality=setup.mss_score,
        )
        assert decision.should_trade is True
        assert decision.rr_ratio == 2.0

    def test_full_continuation_pipeline(self):
        """Trend → BOS → Features → Probability → Risk"""
        # 1. PatternEngine — continuation
        structure = MockStructure(
            trend="bullish",
            last_bos=MockBOS(type="bullish", level=51000),
        )
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=[], structure=structure,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.detected is True
        assert setup.direction == "buy"
        assert setup.setup_type == "continuation"

        # 2. FeatureBuilder
        features = feature_builder.build(
            setup=setup, ind=MockIndicatorValues(), structure=structure,
            regime=MockRegime(), vol_regime=MockVolRegime(),
            mtf_aligned=False, mtf_count=0,
            context_score=None, fear_greed=None, funding_rate=None,
            sl=49500.0, tp=51500.0, entry_price=50000.0,
            candle_quality=None,
        )
        assert features.setup_type == "continuation"

        # 3. ProbabilityEngine
        prob = probability_engine.predict(features)
        assert prob.p_tp > 0

        # 4. RiskEngine
        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=PortfolioState(),
            entry_price=50000.0, sl=49500.0, tp=51500.0,
        )
        assert decision.should_trade is True
        assert decision.rr_ratio == 3.0

    def test_no_pattern_stops_early(self):
        """No pattern detected → pipeline stops."""
        setup = pattern_engine.detect(
            sweeps=[], order_blocks=[], structure=None,
            fvgs=[], candle_quality=None, current_price=50000.0,
        )
        assert setup.detected is False
        # In real pipeline, we'd stop here

    def test_risk_blocks_bad_rr(self):
        """RiskEngine blocks even when ProbabilityEngine gives high P(TP)."""
        features = SetupFeatures(atr_pct=2.0)
        prob = TradeProbability(p_tp=0.80, expected_rr=3.0, profit_factor=3.0, confidence=0.9, model_type="rules")

        decision = risk_engine.evaluate(
            features=features, probability=prob, portfolio=PortfolioState(),
            entry_price=50000.0, sl=49500.0, tp=50200.0,
        )
        assert decision.should_trade is False
        assert "RR=" in decision.rejection_reason
