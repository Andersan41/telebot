import sys
from pathlib import Path
from dataclasses import dataclass

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategy.market_phase_engine import (
    MarketPhaseEngine, MarketPhase, PhaseAssessment,
    get_phase_modifier, PHASE_SCENARIO_MODIFIERS,
)


class TestMarketPhaseEngine:
    """Tests for Market Phase Engine."""

    def setup_method(self):
        self.engine = MarketPhaseEngine()

    def test_trend_up_detection(self):
        phase = self.engine.assess(
            adx=30,
            ema_fast=100,
            ema_slow=95,
            ema_trend=90,
        )
        assert phase.phase == MarketPhase.TREND_UP
        assert phase.confidence > 0.5

    def test_trend_down_detection(self):
        phase = self.engine.assess(
            adx=30,
            ema_fast=80,
            ema_slow=85,
            ema_trend=90,
        )
        assert phase.phase == MarketPhase.TREND_DOWN
        assert phase.confidence > 0.5

    def test_compression_detection(self):
        phase = self.engine.assess(
            adx=15,
            atr_current=100,
            atr_avg=150,
            range_pct=1.5,
        )
        assert phase.phase == MarketPhase.COMPRESSION

    def test_expansion_detection(self):
        phase = self.engine.assess(
            adx=20,
            atr_current=200,
            atr_avg=100,
            displacement_count=3,
        )
        assert phase.phase == MarketPhase.EXPANSION

    def test_reversal_detection(self):
        phase = self.engine.assess(
            adx=22,
            has_bos=True,
            bos_direction="up",
        )
        assert phase.phase == MarketPhase.REVERSAL

    def test_accumulation_detection(self):
        phase = self.engine.assess(
            adx=20,
            ema_fast=100,
            ema_slow=99,
            ema_trend=98,
            range_pct=1.5,
        )
        assert phase.phase == MarketPhase.ACCUMULATION

    def test_distribution_detection(self):
        phase = self.engine.assess(
            adx=20,
            ema_fast=95,
            ema_slow=96,
            ema_trend=97,
            range_pct=1.5,
        )
        assert phase.phase == MarketPhase.DISTRIBUTION

    def test_phase_modifier_returns_1_for_unknown(self):
        assert get_phase_modifier(None, "unknown") == 1.0

    def test_phase_modifier_for_expansion(self):
        mod = get_phase_modifier(MarketPhase.EXPANSION, "Sweep+BOS+OB+FVG")
        assert mod > 1.0

    def test_phase_modifier_for_mitigation_ob_retest(self):
        mod = get_phase_modifier(MarketPhase.MITIGATION, "OB Retest")
        assert mod > 1.0

    def test_phase_confidence_range(self):
        phase = self.engine.assess(adx=30, ema_fast=100, ema_slow=95, ema_trend=90)
        assert 0.0 <= phase.confidence <= 1.0

    def test_assess_from_indicators(self):
        @dataclass
        class MockIndicators:
            adx: float = 30.0
            atr: float = 100.0
            close: float = 50000.0
            high: float = 51000.0
            low: float = 49000.0
            ema_fast: float = 50500.0
            ema_slow: float = 50000.0
            ema_trend: float = 49500.0
            ema_fast_prev: float = 50400.0
            ema_slow_prev: float = 49900.0

        phase = self.engine.assess_from_indicators(MockIndicators())
        assert isinstance(phase, PhaseAssessment)
        assert isinstance(phase.phase, MarketPhase)
