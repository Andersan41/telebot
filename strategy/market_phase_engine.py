"""
strategy/market_phase_engine.py — Market Phase Detection

Determines the current market phase BEFORE hypothesis construction.
The same Bullish OB works differently in Expansion vs Distribution.

Phases:
    ACCUMULATION    — sideways, position building
    DISTRIBUTION    — sideways, position unwinding
    EXPANSION       — strong directional move
    TREND_UP        — ascending trend
    TREND_DOWN      — descending trend
    MITIGATION      — pullback to a level
    COMPRESSION     — narrowing range (precedes expansion)
    REVERSAL        — trend reversal

Phase provides narrative weights (not binary allowed/blocked).
weight > 1.0 = phase favors this narrative
weight < 1.0 = phase disfavors this narrative
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from loguru import logger


class MarketPhase(Enum):
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"
    EXPANSION = "expansion"
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    MITIGATION = "mitigation"
    COMPRESSION = "compression"
    REVERSAL = "reversal"


@dataclass
class PhaseAssessment:
    """Result of market phase detection."""
    phase: MarketPhase
    confidence: float           # 0..1
    duration_bars: int          # how many bars in this phase

    # Metrics used for detection
    adx: float = 0.0
    atr_ratio: float = 1.0     # current ATR / average ATR
    range_pct: float = 0.0     # range width over N bars (% of price)
    ema_slope: float = 0.0     # EMA trend slope
    displacement_count: int = 0 # recent displacement candles
    volume_trend: float = 0.0  # volume change vs average

    # Sub-phase (e.g., compression before expansion)
    sub_phase: Optional[MarketPhase] = None

    def __repr__(self) -> str:
        sub = f" (sub: {self.sub_phase.value})" if self.sub_phase else ""
        return (
            f"Phase({self.phase.value}, conf={self.confidence:.2f}, "
            f"dur={self.duration_bars}bars, adx={self.adx:.1f}, "
            f"atr_ratio={self.atr_ratio:.2f}{sub})"
        )


# ── Narrative Weights ──────────────────────────────────────────────
# > 1.0 = phase favors this narrative
# < 1.0 = phase disfavors
# = 0.0 = fully blocked

ALL_NARRATIVE_TYPES: list[str] = [
    "sweep_bos_ob_fvg", "sweep_bos_ob", "bos_ob_fvg",
    "ob_retest", "choch_ob", "liquidity_grab",
    "trend_continuation", "reversal", "range_bound",
    "bos_mitigation", "fvg_fill", "pullback_ob",
]

NARRATIVE_WEIGHT_MAP: dict[MarketPhase, dict[str, float]] = {
    MarketPhase.EXPANSION: {
        "sweep_bos_ob_fvg": 1.2,
        "sweep_bos_ob": 1.15,
        "bos_ob_fvg": 1.1,
        "trend_continuation": 1.3,
        "ob_retest": 0.7,
        "liquidity_grab": 0.8,
        "range_bound": 0.3,
        "reversal": 0.4,
        "choch_ob": 0.6,
        "bos_mitigation": 0.7,
        "fvg_fill": 0.6,
        "pullback_ob": 1.1,
    },
    MarketPhase.COMPRESSION: {
        "ob_retest": 1.3,
        "liquidity_grab": 1.2,
        "range_bound": 1.4,
        "sweep_bos_ob_fvg": 0.5,
        "sweep_bos_ob": 0.5,
        "bos_ob_fvg": 0.5,
        "trend_continuation": 0.3,
        "reversal": 0.4,
        "choch_ob": 0.6,
        "bos_mitigation": 0.8,
        "fvg_fill": 0.9,
        "pullback_ob": 0.4,
    },
    MarketPhase.MITIGATION: {
        "ob_retest": 1.4,
        "bos_mitigation": 1.3,
        "fvg_fill": 1.2,
        "sweep_bos_ob_fvg": 0.6,
        "sweep_bos_ob": 0.6,
        "bos_ob_fvg": 0.7,
        "trend_continuation": 0.5,
        "reversal": 0.6,
        "choch_ob": 0.8,
        "liquidity_grab": 0.7,
        "range_bound": 0.8,
        "pullback_ob": 0.9,
    },
    MarketPhase.TREND_UP: {
        "pullback_ob": 1.3,
        "trend_continuation": 1.4,
        "bos_ob_fvg": 1.1,
        "sweep_bos_ob_fvg": 1.0,
        "sweep_bos_ob": 1.0,
        "ob_retest": 0.9,
        "reversal": 0.3,
        "range_bound": 0.2,
        "choch_ob": 0.4,
        "liquidity_grab": 0.7,
        "bos_mitigation": 0.6,
        "fvg_fill": 0.6,
    },
    MarketPhase.TREND_DOWN: {
        "pullback_ob": 1.3,
        "trend_continuation": 1.4,
        "bos_ob_fvg": 1.1,
        "sweep_bos_ob_fvg": 1.0,
        "sweep_bos_ob": 1.0,
        "ob_retest": 0.9,
        "reversal": 0.3,
        "range_bound": 0.2,
        "choch_ob": 0.4,
        "liquidity_grab": 0.7,
        "bos_mitigation": 0.6,
        "fvg_fill": 0.6,
    },
    MarketPhase.REVERSAL: {
        "choch_ob": 1.4,
        "reversal": 1.5,
        "liquidity_grab": 1.2,
        "trend_continuation": 0.2,
        "sweep_bos_ob_fvg": 0.8,
        "sweep_bos_ob": 0.8,
        "bos_ob_fvg": 0.7,
        "ob_retest": 0.6,
        "range_bound": 0.5,
        "bos_mitigation": 0.7,
        "fvg_fill": 0.7,
        "pullback_ob": 0.3,
    },
    MarketPhase.ACCUMULATION: {
        "ob_retest": 1.2,
        "liquidity_grab": 1.3,
        "range_bound": 1.1,
        "trend_continuation": 0.4,
        "sweep_bos_ob_fvg": 0.7,
        "sweep_bos_ob": 0.7,
        "bos_ob_fvg": 0.7,
        "reversal": 0.8,
        "choch_ob": 0.7,
        "bos_mitigation": 0.8,
        "fvg_fill": 0.8,
        "pullback_ob": 0.6,
    },
    MarketPhase.DISTRIBUTION: {
        "ob_retest": 1.2,
        "liquidity_grab": 1.3,
        "range_bound": 1.1,
        "trend_continuation": 0.4,
        "sweep_bos_ob_fvg": 0.7,
        "sweep_bos_ob": 0.7,
        "bos_ob_fvg": 0.7,
        "reversal": 0.8,
        "choch_ob": 0.7,
        "bos_mitigation": 0.8,
        "fvg_fill": 0.8,
        "pullback_ob": 0.6,
    },
}

DEFAULT_NARRATIVE_WEIGHTS: dict[str, float] = {nt: 1.0 for nt in ALL_NARRATIVE_TYPES}


def get_narrative_weights(phase: Optional[MarketPhase]) -> dict[str, float]:
    """Get narrative weight map for the given phase."""
    if phase is None:
        return dict(DEFAULT_NARRATIVE_WEIGHTS)
    return dict(NARRATIVE_WEIGHT_MAP.get(phase, DEFAULT_NARRATIVE_WEIGHTS))


def get_narrative_weight(phase: Optional[MarketPhase], narrative_type: str) -> float:
    """Get weight for a specific narrative type in the given phase."""
    weights = get_narrative_weights(phase)
    return weights.get(narrative_type, 1.0)


# ──────────────────────────────────────────────────────────
# Legacy phase modifiers (for backward compatibility)
# ──────────────────────────────────────────────────────────

PHASE_SCENARIO_MODIFIERS: dict[MarketPhase, dict[str, float]] = {
    MarketPhase.EXPANSION: {
        "Sweep+BOS+OB+FVG": 1.20,
        "Sweep+BOS+OB": 1.15,
        "CHoCH+OB": 0.85,
        "OB Retest": 0.90,
    },
    MarketPhase.COMPRESSION: {
        "Sweep+BOS+OB+FVG": 1.00,
        "Sweep+BOS+OB": 1.00,
        "CHoCH+OB": 1.10,
        "OB Retest": 1.05,
    },
    MarketPhase.MITIGATION: {
        "Sweep+BOS+OB+FVG": 0.95,
        "Sweep+BOS+OB": 0.95,
        "CHoCH+OB": 1.00,
        "OB Retest": 1.30,
    },
    MarketPhase.TREND_UP: {
        "Sweep+BOS+OB+FVG": 1.15,
        "Sweep+BOS+OB": 1.10,
        "CHoCH+OB": 0.80,
        "OB Retest": 0.90,
    },
    MarketPhase.TREND_DOWN: {
        "Sweep+BOS+OB+FVG": 1.15,
        "Sweep+BOS+OB": 1.10,
        "CHoCH+OB": 0.80,
        "OB Retest": 0.90,
    },
    MarketPhase.ACCUMULATION: {
        "Sweep+BOS+OB+FVG": 1.05,
        "Sweep+BOS+OB": 1.05,
        "CHoCH+OB": 1.00,
        "OB Retest": 1.10,
    },
    MarketPhase.DISTRIBUTION: {
        "Sweep+BOS+OB+FVG": 0.90,
        "Sweep+BOS+OB": 0.90,
        "CHoCH+OB": 1.15,
        "OB Retest": 1.05,
    },
    MarketPhase.REVERSAL: {
        "Sweep+BOS+OB+FVG": 1.10,
        "Sweep+BOS+OB": 1.10,
        "CHoCH+OB": 1.20,
        "OB Retest": 1.00,
    },
}


def get_phase_modifier(phase: Optional[MarketPhase], scenario_name: str) -> float:
    """Get the probability modifier for a scenario given the current phase."""
    if phase is None:
        return 1.0
    modifiers = PHASE_SCENARIO_MODIFIERS.get(phase, {})
    return modifiers.get(scenario_name, 1.0)


# ──────────────────────────────────────────────────────────
# Market Phase Engine
# ──────────────────────────────────────────────────────────

class MarketPhaseEngine:
    """Determines the current market phase from indicators and structure.

    Detection algorithm (priority order):
        1. ADX > 25 + directional EMA → TREND_UP / TREND_DOWN
        2. ADX < 18 + narrow range + low ATR → COMPRESSION
        3. ATR ratio > 1.3 + displacement candles → EXPANSION
        4. ADX 18-25 + BOS/CHoCH after trend → REVERSAL
        5. Price at OB/FVG after expansion → MITIGATION
        6. ADX 18-25 + sideways → ACCUMULATION / DISTRIBUTION
    """

    def assess(
        self,
        adx: float = 0.0,
        atr_current: float = 0.0,
        atr_avg: float = 0.0,
        ema_fast: float = 0.0,
        ema_slow: float = 0.0,
        ema_trend: float = 0.0,
        ema_fast_prev: float = 0.0,
        ema_slow_prev: float = 0.0,
        close: float = 0.0,
        high: float = 0.0,
        low: float = 0.0,
        has_bos: bool = False,
        bos_direction: Optional[str] = None,
        has_choch: bool = False,
        has_displacement: bool = False,
        displacement_count: int = 0,
        volume_ratio: float = 1.0,
        range_pct: float = 0.0,
        bars_in_range: int = 20,
    ) -> PhaseAssessment:
        """Detect the current market phase.

        All parameters are raw values from indicators — the engine
        does not fetch data itself.
        """
        atr_ratio = atr_current / atr_avg if atr_avg > 0 else 1.0

        # EMA slope (positive = up)
        ema_slope = 0.0
        if ema_slow > 0:
            ema_slope = (ema_fast - ema_slow) / ema_slow * 100

        # ── 1. Strong trend ──
        if adx > 25:
            if ema_fast > ema_slow > ema_trend:
                return PhaseAssessment(
                    phase=MarketPhase.TREND_UP,
                    confidence=min(1.0, 0.5 + adx / 100),
                    duration_bars=bars_in_range,
                    adx=adx, atr_ratio=atr_ratio, ema_slope=ema_slope,
                    displacement_count=displacement_count,
                    volume_trend=volume_ratio - 1.0,
                )
            elif ema_fast < ema_slow < ema_trend:
                return PhaseAssessment(
                    phase=MarketPhase.TREND_DOWN,
                    confidence=min(1.0, 0.5 + adx / 100),
                    duration_bars=bars_in_range,
                    adx=adx, atr_ratio=atr_ratio, ema_slope=ema_slope,
                    displacement_count=displacement_count,
                    volume_trend=volume_ratio - 1.0,
                )

        # ── 2. Compression ──
        if adx < 18 and atr_ratio < 0.8 and range_pct < 2.0:
            return PhaseAssessment(
                phase=MarketPhase.COMPRESSION,
                confidence=min(1.0, 0.5 + (18 - adx) / 30),
                duration_bars=bars_in_range,
                adx=adx, atr_ratio=atr_ratio, range_pct=range_pct,
                ema_slope=ema_slope,
                volume_trend=volume_ratio - 1.0,
            )

        # ── 3. Expansion ──
        if atr_ratio > 1.3 and displacement_count >= 2:
            return PhaseAssessment(
                phase=MarketPhase.EXPANSION,
                confidence=min(1.0, 0.5 + (atr_ratio - 1) * 0.3),
                duration_bars=bars_in_range,
                adx=adx, atr_ratio=atr_ratio, range_pct=range_pct,
                ema_slope=ema_slope,
                displacement_count=displacement_count,
                volume_trend=volume_ratio - 1.0,
            )

        # ── 4. Reversal (BOS/CHoCH after trend) ──
        if (has_bos or has_choch) and adx > 18:
            return PhaseAssessment(
                phase=MarketPhase.REVERSAL,
                confidence=0.65,
                duration_bars=bars_in_range,
                adx=adx, atr_ratio=atr_ratio,
                ema_slope=ema_slope,
                displacement_count=displacement_count,
                volume_trend=volume_ratio - 1.0,
            )

        # ── 5. Mitigation (pullback to level) ──
        if atr_ratio > 0.8 and adx < 25 and range_pct < 3.0:
            # Heuristic: if we had displacement recently, now we're pulling back
            if displacement_count >= 1 and atr_ratio < 1.2:
                return PhaseAssessment(
                    phase=MarketPhase.MITIGATION,
                    confidence=0.55,
                    duration_bars=bars_in_range,
                    adx=adx, atr_ratio=atr_ratio, range_pct=range_pct,
                    ema_slope=ema_slope,
                    volume_trend=volume_ratio - 1.0,
                )

        # ── 6. Accumulation / Distribution (default sideways) ──
        if ema_slope > 0:
            return PhaseAssessment(
                phase=MarketPhase.ACCUMULATION,
                confidence=0.50,
                duration_bars=bars_in_range,
                adx=adx, atr_ratio=atr_ratio, range_pct=range_pct,
                ema_slope=ema_slope,
                volume_trend=volume_ratio - 1.0,
            )
        else:
            return PhaseAssessment(
                phase=MarketPhase.DISTRIBUTION,
                confidence=0.50,
                duration_bars=bars_in_range,
                adx=adx, atr_ratio=atr_ratio, range_pct=range_pct,
                ema_slope=ema_slope,
                volume_trend=volume_ratio - 1.0,
            )

    def assess_from_indicators(self, indicators, structure=None) -> PhaseAssessment:
        """Convenience: assess from IndicatorValues + optional structure."""
        from indicators.engine import IndicatorValues

        adx = indicators.adx if hasattr(indicators, "adx") else 0.0
        atr = indicators.atr if hasattr(indicators, "atr") else 0.0
        close = indicators.close if hasattr(indicators, "close") else 0.0
        high = indicators.high if hasattr(indicators, "high") else 0.0
        low = indicators.low if hasattr(indicators, "low") else 0.0

        has_bos = False
        bos_direction = None
        has_choch = False
        has_displacement = False

        if structure is not None:
            if hasattr(structure, "last_bos") and structure.last_bos:
                has_bos = True
                bos_direction = getattr(structure.last_bos, "direction", None)
            if hasattr(structure, "last_choch") and structure.last_choch:
                has_choch = True

        return self.assess(
            adx=adx,
            atr_current=atr,
            atr_avg=atr,  # will be overridden by scanner if available
            ema_fast=indicators.ema_fast if hasattr(indicators, "ema_fast") else 0.0,
            ema_slow=indicators.ema_slow if hasattr(indicators, "ema_slow") else 0.0,
            ema_trend=indicators.ema_trend if hasattr(indicators, "ema_trend") else 0.0,
            ema_fast_prev=indicators.ema_fast_prev if hasattr(indicators, "ema_fast_prev") else 0.0,
            ema_slow_prev=indicators.ema_slow_prev if hasattr(indicators, "ema_slow_prev") else 0.0,
            close=close,
            high=high,
            low=low,
            has_bos=has_bos,
            bos_direction=bos_direction,
            has_choch=has_choch,
            has_displacement=has_displacement,
            volume_ratio=1.0,
        )


# Module-level singleton
market_phase_engine = MarketPhaseEngine()
