"""
strategy/feature_builder.py — Feature Builder

Collects all raw features for a detected ICT setup into a flat vector.
No scoring. No blocking. Just data.

Features are organized into:
- ICT Pattern (from PatternEngine)
- Market Structure
- Volume & Volatility
- Indicators (raw values, not gates)
- Multi-Timeframe
- Context (secondary)
- Risk metrics
- Execution context
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from strategy.pattern_engine import ICTSetup


# Session detection based on UTC hour
_SESSION_MAP = {
    "asian": (0, 7),      # 00:00–07:00 UTC
    "london": (7, 12),    # 07:00–12:00 UTC
    "overlap": (12, 16),  # 12:00–16:00 UTC (London + NY)
    "new_york": (16, 21), # 16:00–21:00 UTC
}


def _detect_session() -> str:
    """Detect current trading session from UTC time."""
    hour = datetime.now(timezone.utc).hour
    for session, (start, end) in _SESSION_MAP.items():
        if start <= hour < end:
            return session
    return "off_hours"


@dataclass
class SetupFeatures:
    """Raw feature vector for one ICT setup.

    All values are raw — no normalization, no scoring, no blocking.
    Used as input for ProbabilityEngine.
    """

    # === Setup classification ===
    setup_type: str = "unknown"  # "reversal" / "continuation"

    # === ICT Pattern (from PatternEngine) ===
    has_bos: bool = False
    has_sweep: bool = False
    has_ob: bool = False
    has_fvg: bool = False
    has_displacement: bool = False
    components_count: int = 0

    # === Reversal-specific ===
    has_mss: bool = False
    mss_score: float = 0.0  # 0-100
    mss_causality: float = 0.0  # 0-1
    displacement_atr_ratio: float = 0.0
    sweep_to_mss_bars: int = 0

    # Pattern-specific metrics
    ob_distance_pct: float = 0.0   # 0 = at OB midpoint, higher = farther
    fvg_size_pct: float = 0.0      # size of FVG as % of price
    sweep_reclaim_speed: int = 0   # candles to reclaim (lower = faster = better)
    sweep_strength: float = 0.0    # 0.0–1.0

    # === Market Structure ===
    structure_trend: str = "ranging"  # "bullish" / "bearish" / "ranging"
    structure_bos_aligned: bool = False  # BOS direction matches setup direction

    # === Volume ===
    volume_ratio: float = 1.0   # volume / volume_sma
    volume_delta_pct: float = 0.0  # taker buy delta

    # === Volatility ===
    atr_pct: float = 0.0     # ATR / close * 100
    regime: str = "unknown"   # "trend" / "range" / "compression" / "expansion"

    # === Indicators (raw values — ML features, not gates) ===
    rsi: float = 50.0
    adx: float = 20.0
    ema_spread_pct: float = 0.0   # (fast - slow) / slow * 100
    dmi_diff: float = 0.0         # dmi_plus - dmi_minus (signed)
    macd_hist_pct: float = 0.0    # macd_hist / close * 100

    # === Multi-Timeframe ===
    mtf_aligned: bool = False
    mtf_htf_count: int = 0

    # === Context (secondary — low weight in ML) ===
    fear_greed: int = 50
    funding_rate: float = 0.0
    context_score: float = 0.0  # from ContextScorer [-1, 1]

    # === Risk metrics ===
    rr_ratio: float = 0.0
    sl_distance_pct: float = 0.0
    tp_distance_pct: float = 0.0

    # === Execution context ===
    session: str = "unknown"
    candle_close_pct: float = 0.5   # position in candle range (0=low, 1=high)
    is_reversal: bool = False       # CHoCH detected

    # === Entry readiness (soft — not a gate) ===
    entry_armed: bool = False

    # === Soft multipliers (computed externally, passed in) ===
    htf_alignment_score: Optional[float] = None   # W1/D1/H4 agreement [0.0–1.0]
    premium_discount_score: Optional[float] = None  # price location vs equilibrium [0.0–1.0]
    htf_bias_penalty: float = 1.0  # 0.8 if reversal mismatches HTF bias, 1.0 otherwise
    ob_state_multiplier: float = 1.0  # OB mitigation factor (0.0 = broken, 0.6-1.2)

    # === Additional ===
    nearest_support_pct: float = 0.0
    nearest_resistance_pct: float = 0.0
    is_4h_aligned: bool = False     # HTF (4h) trend aligns with direction
    volume_above_avg: bool = False

    def to_vector(self) -> Dict[str, Any]:
        """Convert to flat dictionary for ML model input.

        Numeric values only — ready for XGBoost/RandomForest.
        Indicators are included as raw ML features, NOT as gates.
        """
        return {
            # Setup classification
            "setup_type": {"reversal": 1, "continuation": -1}.get(self.setup_type, 0),
            # ICT Pattern
            "has_bos": int(self.has_bos),
            "has_sweep": int(self.has_sweep),
            "has_ob": int(self.has_ob),
            "has_fvg": int(self.has_fvg),
            "has_displacement": int(self.has_displacement),
            "has_mss": int(self.has_mss),
            "components_count": self.components_count,
            # Reversal metrics
            "mss_score": self.mss_score,
            "mss_causality": self.mss_causality,
            "displacement_atr_ratio": self.displacement_atr_ratio,
            "sweep_to_mss_bars": self.sweep_to_mss_bars,
            # Pattern metrics
            "ob_distance_pct": self.ob_distance_pct,
            "fvg_size_pct": self.fvg_size_pct,
            "sweep_reclaim_speed": self.sweep_reclaim_speed,
            "sweep_strength": self.sweep_strength,
            # Market Structure
            "structure_trend": {"bullish": 1, "bearish": -1, "ranging": 0}.get(self.structure_trend, 0),
            "structure_bos_aligned": int(self.structure_bos_aligned),
            # Volume
            "volume_ratio": self.volume_ratio,
            "volume_delta_pct": self.volume_delta_pct,
            "volume_above_avg": int(self.volume_above_avg),
            # Volatility
            "atr_pct": self.atr_pct,
            "regime": {"trend": 1, "expansion": 0.5, "range": -0.5, "compression": -1}.get(self.regime, 0),
            # Indicators (raw ML features, not gates)
            "rsi": self.rsi,
            "adx": self.adx,
            "ema_spread_pct": self.ema_spread_pct,
            "dmi_diff": self.dmi_diff,
            "macd_hist_pct": self.macd_hist_pct,
            # MTF
            "mtf_aligned": int(self.mtf_aligned),
            "mtf_htf_count": self.mtf_htf_count,
            "is_4h_aligned": int(self.is_4h_aligned),
            # Context
            "fear_greed": self.fear_greed,
            "funding_rate": self.funding_rate,
            "context_score": self.context_score,
            # Risk
            "rr_ratio": self.rr_ratio,
            "sl_distance_pct": self.sl_distance_pct,
            "tp_distance_pct": self.tp_distance_pct,
            # Execution
            "session": {"asian": 0, "london": 1, "overlap": 2, "new_york": 3, "off_hours": 4}.get(self.session, 4),
            "candle_close_pct": self.candle_close_pct,
            "is_reversal": int(self.is_reversal),
            "entry_armed": int(self.entry_armed),
            # S/R proximity
            "nearest_support_pct": self.nearest_support_pct,
            "nearest_resistance_pct": self.nearest_resistance_pct,
            # Soft multipliers
            "htf_alignment_score": self.htf_alignment_score if self.htf_alignment_score is not None else 0.5,
            "premium_discount_score": self.premium_discount_score if self.premium_discount_score is not None else 0.5,
        }

    def to_reasoning(self) -> List[str]:
        """Human-readable list of supporting/opposing factors.

        Priority: MSS > Displacement > Sweep > OB > FVG > HTF > Session
        Indicators (RSI, ADX, EMA) are NOT included — they are ML features only.
        """
        reasons = []
        # Reversal components (highest priority)
        if self.setup_type == "reversal":
            if self.has_mss:
                reasons.append(f"MSS (score={self.mss_score:.0f})")
            if self.has_displacement:
                reasons.append(f"Displacement ({self.displacement_atr_ratio:.1f} ATR)")
            if self.has_sweep:
                reasons.append(f"Sweep (strength={self.sweep_strength:.2f})")
        # Continuation components
        elif self.setup_type == "continuation":
            if self.has_bos:
                reasons.append(f"BOS ({self.structure_trend})")
            if self.structure_bos_aligned:
                reasons.append("Structure aligned")
        # Entry zones (confirmation, not trigger)
        if self.has_ob:
            reasons.append(f"OB (distance={self.ob_distance_pct:.1f}%)")
        if self.has_fvg:
            reasons.append(f"FVG (size={self.fvg_size_pct:.2f}%)")
        if self.entry_armed:
            reasons.append("Entry armed")
        # Context
        if self.volume_ratio > 1.5:
            reasons.append(f"Volume {self.volume_ratio:.1f}x avg")
        if self.mtf_aligned:
            reasons.append(f"MTF aligned ({self.mtf_htf_count} HTFs)")
        if self.rr_ratio >= 2.0:
            reasons.append(f"R:R {self.rr_ratio:.1f}")
        if self.session in ("london", "overlap", "new_york"):
            reasons.append(f"Session: {self.session}")
        if self.context_score > 0.2:
            reasons.append("Context supportive")
        elif self.context_score < -0.2:
            reasons.append("Context opposing")
        # Soft multipliers
        if self.htf_alignment_score is not None:
            if self.htf_alignment_score >= 0.8:
                reasons.append(f"HTF aligned ({self.htf_alignment_score:.1f})")
            elif self.htf_alignment_score <= 0.3:
                reasons.append(f"HTF opposing ({self.htf_alignment_score:.1f})")
        if self.premium_discount_score is not None:
            if self.premium_discount_score >= 0.8:
                reasons.append(f"Good location ({self.premium_discount_score:.1f})")
            elif self.premium_discount_score <= 0.3:
                reasons.append(f"Bad location ({self.premium_discount_score:.1f})")
        return reasons


class FeatureBuilder:
    """Builds SetupFeatures from raw market data and pattern detection results."""

    def build(
        self,
        setup: ICTSetup,
        ind: Any,  # IndicatorValues
        structure: Any,  # StructureState
        regime: Any,  # MarketRegime
        vol_regime: Any,  # VolatilityRegime
        mtf_aligned: bool,
        mtf_count: int,
        context_score: Optional[float],
        fear_greed: Optional[int],
        funding_rate: Optional[float],
        sl: float,
        tp: float,
        entry_price: float,
        candle_quality: Any,  # CandleQuality
        sr_levels: Optional[Dict] = None,
        is_reversal: bool = False,
        htf_alignment_score: Optional[float] = None,
        premium_discount_score: Optional[float] = None,
        htf_bias_penalty: float = 1.0,
        ob_state_multiplier: float = 1.0,
    ) -> SetupFeatures:
        """Build feature vector from all available data.

        Args:
            setup: ICTSetup from PatternEngine
            ind: IndicatorValues from indicator_engine
            structure: StructureState from analyze_structure()
            regime: MarketRegime from RegimeDetector
            vol_regime: VolatilityRegime from classify_volatility()
            mtf_aligned: bool from check_mtf_alignment()
            mtf_count: int number of HTFs checked
            context_score: float from ContextScorer (optional)
            fear_greed: int from Fear & Greed index (optional)
            funding_rate: float from funding rate (optional)
            sl: float stop loss price
            tp: float take profit price
            entry_price: float entry price
            candle_quality: CandleQuality from analyze_last_candle()
            sr_levels: dict of support/resistance levels (optional)
            is_reversal: bool whether this is a CHoCH reversal
            htf_alignment_score: float W1/D1/H4 agreement score 0.0–1.0 (optional)
            premium_discount_score: float price location vs equilibrium 0.0–1.0 (optional)

        Returns:
            SetupFeatures with all raw values populated.
        """
        # --- ICT Pattern ---
        has_bos = setup.has_bos
        has_sweep = setup.has_sweep
        has_ob = setup.has_ob
        has_fvg = setup.has_fvg
        has_displacement = setup.has_displacement
        components_count = setup.components_count

        # --- Market Structure ---
        structure_trend = structure.trend if structure else "ranging"
        structure_bos_aligned = False
        if structure and structure.last_bos and setup.direction:
            bos = structure.last_bos
            structure_bos_aligned = (
                (setup.direction == "buy" and bos.type == "bullish") or
                (setup.direction == "sell" and bos.type == "bearish")
            )

        # --- Volume ---
        volume_ratio = 1.0
        volume_delta = 0.0
        volume_above_avg = False
        if ind:
            volume_ratio = ind.volume / ind.volume_sma if ind.volume_sma > 0 else 1.0
            volume_delta = ind.volume_delta_pct or 0.0
            volume_above_avg = ind.volume_above_avg

        # --- Volatility ---
        atr_pct = 0.0
        if ind and ind.close and ind.close > 0 and ind.atr:
            atr_pct = ind.atr / ind.close * 100
        regime_name = regime.regime if regime else "unknown"

        # --- Indicators (raw ML features) ---
        rsi = ind.rsi if ind else 50.0
        adx = ind.adx if ind else 20.0
        ema_spread_pct = 0.0
        dmi_diff = 0.0
        macd_hist_pct = 0.0
        if ind:
            if ind.ema_slow and ind.ema_slow > 0:
                ema_spread_pct = (ind.ema_fast - ind.ema_slow) / ind.ema_slow * 100
            dmi_diff = ind.dmi_plus - ind.dmi_minus
            if ind.close and ind.close > 0:
                macd_hist_pct = ind.macd_hist / ind.close * 100

        # --- MTF ---
        is_4h_aligned = False
        if mtf_aligned and setup.direction:
            # Simple heuristic: if aligned and direction matches
            is_4h_aligned = True

        # --- Context ---
        fg = fear_greed if fear_greed is not None else 50
        fr = funding_rate if funding_rate is not None else 0.0
        ctx = context_score if context_score is not None else 0.0

        # --- Risk ---
        rr_ratio = 0.0
        sl_distance = 0.0
        tp_distance = 0.0
        if entry_price and entry_price > 0:
            if sl:
                sl_distance = abs(entry_price - sl) / entry_price * 100
            if tp:
                tp_distance = abs(tp - entry_price) / entry_price * 100
            if sl and tp and sl != tp:
                risk = abs(entry_price - sl)
                reward = abs(tp - entry_price)
                rr_ratio = reward / risk if risk > 0 else 0.0

        # --- Candle ---
        candle_close_pct = 0.5
        if candle_quality:
            candle_close_pct = candle_quality.close_position

        # --- S/R proximity ---
        nearest_sup = 0.0
        nearest_res = 0.0
        if sr_levels and entry_price and entry_price > 0:
            all_supports = []
            all_resistances = []
            for tf_lvls in sr_levels.values():
                all_supports.extend(tf_lvls.get("support", []))
                all_resistances.extend(tf_lvls.get("resistance", []))
            below = [s for s in all_supports if s < entry_price]
            if below:
                nearest_sup = (entry_price - max(below)) / entry_price * 100
            above = [r for r in all_resistances if r > entry_price]
            if above:
                nearest_res = (min(above) - entry_price) / entry_price * 100

        return SetupFeatures(
            # Setup classification
            setup_type=setup.setup_type or "unknown",
            # ICT Pattern
            has_bos=has_bos,
            has_sweep=has_sweep,
            has_ob=has_ob,
            has_fvg=has_fvg,
            has_displacement=has_displacement,
            components_count=components_count,
            # Reversal-specific
            has_mss=setup.has_mss,
            mss_score=setup.mss_score,
            mss_causality=setup.mss_causality,
            displacement_atr_ratio=setup.displacement_atr_ratio,
            sweep_to_mss_bars=setup.sweep_to_mss_bars,
            # Pattern metrics
            ob_distance_pct=setup.ob_distance_pct,
            fvg_size_pct=setup.fvg_size_pct,
            sweep_reclaim_speed=setup.sweep_reclaim_candles,
            sweep_strength=setup.sweep_strength,
            # Market Structure
            structure_trend=structure_trend,
            structure_bos_aligned=structure_bos_aligned,
            # Volume
            volume_ratio=volume_ratio,
            volume_delta_pct=volume_delta,
            volume_above_avg=volume_above_avg,
            # Volatility
            atr_pct=atr_pct,
            regime=regime_name,
            # Indicators (raw ML features)
            rsi=rsi,
            adx=adx,
            ema_spread_pct=ema_spread_pct,
            dmi_diff=dmi_diff,
            macd_hist_pct=macd_hist_pct,
            # MTF
            mtf_aligned=mtf_aligned,
            mtf_htf_count=mtf_count,
            is_4h_aligned=is_4h_aligned,
            # Context
            fear_greed=fg,
            funding_rate=fr,
            context_score=ctx,
            # Risk
            rr_ratio=rr_ratio,
            sl_distance_pct=sl_distance,
            tp_distance_pct=tp_distance,
            # Execution
            session=_detect_session(),
            candle_close_pct=candle_close_pct,
            is_reversal=is_reversal,
            # Entry readiness
            entry_armed=setup.entry_armed,
            # Soft multipliers
            htf_alignment_score=htf_alignment_score if htf_alignment_score is not None else 0.5,
            premium_discount_score=premium_discount_score if premium_discount_score is not None else 0.5,
            htf_bias_penalty=htf_bias_penalty,
            ob_state_multiplier=ob_state_multiplier,
            # S/R
            nearest_support_pct=nearest_sup,
            nearest_resistance_pct=nearest_res,
        )


# Singleton
feature_builder = FeatureBuilder()
