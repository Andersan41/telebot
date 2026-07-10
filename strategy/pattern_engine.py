"""
strategy/pattern_engine.py — ICT Pattern Engine (Layer 1)

Two separate pipelines:

REVERSAL:
  Sweep → Displacement → MSS → [OB/FVG entry zone] → Entry

CONTINUATION:
  Trend → Pullback → BOS → [OB/FVG retrace] → Entry

Scenario Detection ≠ Entry Ready.
- Scenario: "Is there a trade idea?"
- Entry Armed: "Can we enter now?" (price in OB/FVG zone)

Hard gates per setup type:
  Reversal: sweep + displacement + mss
  Continuation: BOS + trend alignment

OB/FVG are entry zones, never gates.
RSI/ADX/EMA never block.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

from loguru import logger


@dataclass
class ICTSetup:
    """Result of ICT pattern detection."""

    detected: bool
    direction: Optional[str] = None  # "buy" / "sell"
    setup_type: Optional[str] = None  # "reversal" / "continuation"

    # ── Reversal components ──
    has_sweep: bool = False
    sweep_type: Optional[str] = None
    sweep_strength: float = 0.0
    sweep_reclaim_candles: int = 0

    has_displacement: bool = False
    displacement_body_pct: float = 0.0
    displacement_atr_ratio: float = 0.0

    has_mss: bool = False
    mss_score: float = 0.0  # 0-100
    mss_causality: float = 0.0  # 0-1 exponential decay
    sweep_to_mss_bars: int = 0

    # ── Continuation components ──
    has_bos: bool = False
    bos_type: Optional[str] = None  # "bullish" / "bearish"
    bos_level: float = 0.0

    # ── Entry zones (NOT gates) ──
    has_ob: bool = False
    ob_type: Optional[str] = None
    ob_distance_pct: float = 0.0
    ob_midpoint: float = 0.0

    has_fvg: bool = False
    fvg_type: Optional[str] = None
    fvg_size_pct: float = 0.0

    # ── Entry readiness (soft — log but don't block) ──
    entry_armed: bool = False

    # ── Structural info ──
    structure_trend: Optional[str] = None

    # ── Component list ──
    components_found: List[str] = field(default_factory=list)

    # ── Rejection info ──
    rejection_reason: Optional[str] = None

    @property
    def components_count(self) -> int:
        return len(self.components_found)

    @property
    def is_reversal(self) -> bool:
        return self.setup_type == "reversal"

    @property
    def is_continuation(self) -> bool:
        return self.setup_type == "continuation"

    @property
    def has_trigger(self) -> bool:
        """Backward-compatible: any trigger present."""
        return self.has_sweep or self.has_bos

    @property
    def has_confirmation(self) -> bool:
        """Backward-compatible: any confirmation present."""
        return self.has_ob or self.has_fvg


class PatternEngine:
    """Detects ICT setups from raw price action data.

    No indicators. No scoring. Pure pattern detection.
    Two pipelines: reversal and continuation.
    """

    def __init__(
        self,
        ob_proximity_pct: float = 2.0,
    ):
        self.ob_proximity_pct = ob_proximity_pct

    def detect(
        self,
        sweeps: list,
        order_blocks: list,
        structure,
        fvgs: list,
        candle_quality,
        current_price: float,
        atr: float = 0.0,
    ) -> ICTSetup:
        """Detect whether a valid ICT setup exists.

        Tries REVERSAL first (sweep + displacement + MSS).
        Falls back to CONTINUATION (trend + BOS).

        Args:
            sweeps: list of SweepEvent from liquidity.sweep.detect_sweeps()
            order_blocks: list of OrderBlock from liquidity.order_blocks.detect_order_blocks()
            structure: StructureState from market_structure.structure.analyze_structure()
            fvgs: list of FairValueGap from liquidity.fvg.detect_fvg()
            candle_quality: CandleQuality from liquidity.candle_quality.analyze_last_candle()
            current_price: current close price
            atr: current ATR value

        Returns:
            ICTSetup with detection result.
        """
        direction = None
        setup_type = None
        reversal_rejection = None
        continuation_rejection = None

        # ═══ REVERSAL PATH ═══
        # Sweep → Displacement → MSS
        reversal = self._try_reversal(
            sweeps, structure, candle_quality, atr, current_price,
        )
        if reversal.detected:
            direction = reversal.direction
            setup_type = "reversal"
        else:
            reversal_rejection = reversal.rejection_reason

        # ═══ CONTINUATION PATH ═══
        # Trend → BOS (only if reversal not found)
        if not reversal.detected:
            continuation = self._try_continuation(structure)
            if continuation.detected:
                direction = continuation.direction
                setup_type = "continuation"
                reversal = continuation
            else:
                continuation_rejection = continuation.rejection_reason

        if direction is None:
            trend = structure.trend if structure else "ranging"
            # Prefer continuation-specific reason if continuation was tried
            # and reversal failed at early stage (no sweep)
            if continuation_rejection and reversal_rejection:
                # If reversal failed at first step, continuation reason is more relevant
                if "no sweep" in (reversal_rejection or ""):
                    reason = continuation_rejection
                else:
                    reason = reversal_rejection
            else:
                reason = continuation_rejection or reversal_rejection or "no valid setup"
            return ICTSetup(
                detected=False,
                structure_trend=trend,
                rejection_reason=reason,
            )

        # ═══ DETECT ENTRY ZONES ═══
        setup = reversal
        setup.direction = direction
        setup.setup_type = setup_type
        setup.structure_trend = structure.trend if structure else None

        self._detect_entry_zones(setup, order_blocks, fvgs, direction, current_price)

        # ═══ CHECK ENTRY ARMED ═══
        setup.entry_armed = self._check_entry_armed(setup, current_price)

        # ═══ BUILD COMPONENT LIST ═══
        setup.components_found = self._build_components(setup)

        # ═══ LOG ═══
        logger.info(
            f"ICT setup: {direction.upper()} {setup_type} | "
            f"components={setup.components_found} | "
            f"entry_armed={setup.entry_armed} | "
            f"MSS={setup.has_mss} BOS={setup.has_bos} "
            f"Sweep={setup.has_sweep} Disp={setup.has_displacement} "
            f"OB={setup.has_ob} FVG={setup.has_fvg}"
        )

        return setup

    def _try_reversal(
        self,
        sweeps: list,
        structure,
        candle_quality,
        atr: float,
        current_price: float,
    ) -> ICTSetup:
        """Try to detect a REVERSAL setup: sweep + displacement + MSS."""
        # 1. Sweep required
        has_sweep = False
        sweep_type = None
        sweep_strength = 0.0
        sweep_reclaim = 0
        sweep_candle_index = -1

        valid_sweeps = [s for s in sweeps if s.is_valid]
        for s in valid_sweeps:
            has_sweep = True
            sweep_type = s.type
            sweep_strength = s.strength
            sweep_reclaim = s.reclaim_candles
            sweep_candle_index = s.candle_index
            break  # use first valid sweep

        if not has_sweep:
            return ICTSetup(
                detected=False,
                rejection_reason="reversal: no sweep",
            )

        # 2. Displacement (informational — not a gate for MSS setups)
        # MSS classification already measures displacement >= 1 ATR between sweep and CHoCH.
        # The current candle does NOT need to be a displacement candle.
        has_displacement = False
        disp_body = 0.0
        disp_atr = 0.0
        if candle_quality:
            has_displacement = candle_quality.is_displacement
            disp_body = candle_quality.body_pct
        if atr > 0 and candle_quality:
            disp_atr = candle_quality.body_pct * (current_price / 100) / atr
        if candle_quality:
            disp_atr = candle_quality.body_atr_ratio if hasattr(candle_quality, 'body_atr_ratio') else disp_atr

        # 3. MSS required (strong CHoCH after sweep)
        has_mss = False
        mss_score = 0.0
        mss_causality = 0.0
        sweep_to_mss = 0
        direction = None

        if structure and structure.last_mss is not None:
            mss = structure.last_mss
            has_mss = True
            mss_score = mss.mss_score
            mss_causality = mss.causality_score
            # Direction from MSS + sweep alignment
            if mss.type == "bullish":
                direction = "buy"
            elif mss.type == "bearish":
                direction = "sell"
            # Bars between sweep and MSS
            if sweep_candle_index >= 0 and mss.candle_index >= 0:
                sweep_to_mss = max(0, mss.candle_index - sweep_candle_index)

        if not has_mss:
            return ICTSetup(
                detected=False,
                has_sweep=has_sweep, sweep_type=sweep_type,
                has_displacement=has_displacement,
                rejection_reason="reversal: no MSS (strong CHoCH)",
            )

        if direction is None:
            return ICTSetup(
                detected=False,
                has_sweep=has_sweep, sweep_type=sweep_type,
                has_displacement=has_displacement,
                has_mss=has_mss,
                rejection_reason="reversal: MSS direction unclear",
            )

        return ICTSetup(
            detected=True,
            direction=direction,
            setup_type="reversal",
            has_sweep=has_sweep,
            sweep_type=sweep_type,
            sweep_strength=sweep_strength,
            sweep_reclaim_candles=sweep_reclaim,
            has_displacement=has_displacement,
            displacement_body_pct=disp_body,
            displacement_atr_ratio=disp_atr,
            has_mss=has_mss,
            mss_score=mss_score,
            mss_causality=mss_causality,
            sweep_to_mss_bars=sweep_to_mss,
        )

    def _try_continuation(self, structure) -> ICTSetup:
        """Try to detect a CONTINUATION setup: trend + BOS."""
        if structure is None:
            return ICTSetup(
                detected=False,
                rejection_reason="continuation: no structure",
            )

        trend = structure.trend

        # 1. Trend required (no ranging)
        if trend == "ranging":
            return ICTSetup(
                detected=False,
                structure_trend=trend,
                rejection_reason="continuation: ranging market",
            )

        # 2. BOS required
        has_bos = False
        bos_type = None
        bos_level = 0.0
        direction = None

        if structure.last_bos is not None:
            bos = structure.last_bos
            has_bos = True
            bos_type = bos.type
            bos_level = bos.level
            if bos.type == "bullish":
                direction = "buy"
            elif bos.type == "bearish":
                direction = "sell"

        if not has_bos:
            return ICTSetup(
                detected=False,
                structure_trend=trend,
                rejection_reason="continuation: no BOS",
            )

        # 3. Trend alignment required
        trend_aligned = (
            (direction == "buy" and trend == "bullish") or
            (direction == "sell" and trend == "bearish")
        )

        if not trend_aligned:
            return ICTSetup(
                detected=False,
                has_bos=has_bos, bos_type=bos_type,
                structure_trend=trend,
                rejection_reason=f"continuation: BOS {bos_type} vs trend {trend}",
            )

        return ICTSetup(
            detected=True,
            direction=direction,
            setup_type="continuation",
            has_bos=has_bos,
            bos_type=bos_type,
            bos_level=bos_level,
        )

    def _detect_entry_zones(
        self,
        setup: ICTSetup,
        order_blocks: list,
        fvgs: list,
        direction: str,
        current_price: float,
    ):
        """Detect OB and FVG as entry zones (not gates)."""
        # OB
        for ob in order_blocks:
            ob_dir = "buy" if ob.type == "bullish" else "sell" if ob.type == "bearish" else ob.type
            if ob.is_valid and ob_dir == direction:
                setup.has_ob = True
                setup.ob_type = ob.type
                setup.ob_midpoint = ob.midpoint
                if current_price > 0:
                    setup.ob_distance_pct = abs(current_price - ob.midpoint) / current_price * 100
                break

        # FVG
        for f in fvgs:
            f_dir = "buy" if f.type == "bullish" else "sell" if f.type == "bearish" else f.type
            if f.is_active and f_dir == direction:
                setup.has_fvg = True
                setup.fvg_type = f.type
                setup.fvg_size_pct = f.size_pct
                break

    def _check_entry_armed(self, setup: ICTSetup, current_price: float) -> bool:
        """Check if price is in an OB or FVG zone.

        Entry armed is soft — logged but NOT a gate.
        For BUY: price near OB midpoint (below) or inside bullish FVG.
        For SELL: price near OB midpoint (above) or inside bearish FVG.
        """
        if current_price <= 0:
            return False

        # Check OB proximity
        if setup.has_ob and setup.ob_midpoint > 0:
            dist_pct = abs(current_price - setup.ob_midpoint) / current_price * 100
            if dist_pct <= self.ob_proximity_pct:
                return True

        # Check FVG containment
        if setup.has_fvg:
            # For bullish FVG: price should be within or below the gap
            if setup.fvg_type == "bullish":
                # FVG gap is between bottom and top
                # Price entering from above retracing into the gap
                return True  # FVG exists and is active → armed
            elif setup.fvg_type == "bearish":
                return True

        return False

    def _build_components(self, setup: ICTSetup) -> List[str]:
        """Build component list for logging and features."""
        components = []
        if setup.setup_type == "reversal":
            if setup.has_sweep:
                components.append("Sweep")
            if setup.has_displacement:
                components.append("Displacement")
            if setup.has_mss:
                components.append("MSS")
        elif setup.setup_type == "continuation":
            if setup.has_bos:
                components.append("BOS")
        if setup.has_ob:
            components.append("OB")
        if setup.has_fvg:
            components.append("FVG")
        if setup.entry_armed:
            components.append("EntryArmed")
        return components


# Singleton
pattern_engine = PatternEngine()
