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
from datetime import datetime
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
    sweep_failed_reversal: bool = False  # sweep detected but reversal path failed (no MSS)

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
    fvg_midpoint: float = 0.0

    # ── Entry readiness (soft — log but don't block) ──
    entry_armed: bool = False

    # ── Structural info ──
    structure_trend: Optional[str] = None

    # ── Component list ──
    components_found: List[str] = field(default_factory=list)

    # ── Rejection info ──
    rejection_reason: Optional[str] = None

    # ── Visual data (for chart overlay in sandbox) ──
    sweep_price: float = 0.0
    sweep_candle_timestamp: Optional[datetime] = None
    displacement_candle_timestamp: Optional[datetime] = None
    mss_level_price: float = 0.0
    mss_candle_timestamp: Optional[datetime] = None
    ob_high_price: float = 0.0
    ob_low_price: float = 0.0
    ob_candle_timestamp: Optional[datetime] = None
    fvg_top_price: float = 0.0
    fvg_bottom_price: float = 0.0
    fvg_candle_timestamp: Optional[datetime] = None
    bos_level_price: float = 0.0
    bos_candle_timestamp: Optional[datetime] = None

    @property
    def components_count(self) -> int:
        return len(self.components_found)

    @property
    def confirmation_score(self) -> int:
        """Weighted confirmation score (TZ §6.4, H-013):
        Continuation: BOS=2, FVG=1, OB=1
        Reversal: Sweep=2, MSS=1, FVG=1, OB=1
        Minimum score for entry: 2."""
        score = 0
        if self.setup_type == "reversal":
            # Reversal: sweep is the trigger (analogous to BOS for continuation)
            if self.has_sweep:
                score += 2
            if self.has_mss:
                score += 1
        else:
            # Continuation: BOS is the trigger
            if self.has_bos:
                score += 2
        if self.has_fvg:
            score += 1
        if self.has_ob:
            score += 1
        return score

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
        sweep_timestamp: Optional[datetime] = None,
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
            continuation = self._try_continuation(structure, sweeps)
            if continuation.detected:
                direction = continuation.direction
                setup_type = "continuation"
                # TZ fix: if sweep was detected but reversal failed (no MSS),
                # mark it so probability engine doesn't count sweep as +3.0 edge
                if reversal.has_sweep:
                    continuation.has_sweep = reversal.has_sweep
                    continuation.sweep_type = reversal.sweep_type
                    continuation.sweep_strength = reversal.sweep_strength
                    continuation.sweep_failed_reversal = True
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

        # Extract sweep timestamp for temporal binding (TZ §6.0)
        # Prefer timestamp from the sweep actually selected by classifier (via setup)
        _sweep_ts = sweep_timestamp or getattr(setup, 'sweep_candle_timestamp', None)
        if _sweep_ts is None:
            for s in sweeps:
                if s.is_valid:
                    _sweep_ts = s.timestamp
                    break

        self._detect_entry_zones(setup, order_blocks, fvgs, direction, current_price, _sweep_ts)

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
        _sweep_price = 0.0
        _sweep_ts = None

        valid_sweeps = [s for s in sweeps if s.is_valid]
        candidate_mss = structure.last_mss if structure is not None else None
        if candidate_mss is not None:
            matched_index = getattr(candidate_mss, "sweep_candle_index", None)
            matched_level = getattr(candidate_mss, "sweep_level", None)
            if matched_index is not None and matched_level is not None:
                valid_sweeps = [
                    s for s in valid_sweeps
                    if s.candle_index == matched_index
                    and s.swept_level == matched_level
                ]
        sweep_reject_reasons = []
        for s in valid_sweeps:
            # Apply false sweep filters (TZ §5.3)
            passes, filter_reason = s.passes_false_sweep_filters(
                atr=s.atr, pool_age_bars=s.pool_age_bars
            )
            if not passes:
                wick_pct = 0.0
                if s.swept_level > 0:
                    if s.type == "bearish":
                        wick_pct = max(0, s.sweep_high - s.swept_level) / s.swept_level * 100
                    else:
                        wick_pct = max(0, s.swept_level - s.sweep_low) / s.swept_level * 100
                body_pct = abs(s.sweep_high - s.sweep_low) / max(s.swept_level, 1e-10) * 100
                logger.info(
                    f"Sweep REJECTED: {s.type} swept={s.swept_level:.4f} "
                    f"wick={wick_pct:.4f}% body={body_pct:.4f}% "
                    f"reclaim={s.reclaim_candles} reason={filter_reason}"
                )
                sweep_reject_reasons.append(filter_reason)
                continue
            # Pick strongest sweep (highest strength, most recent if tied)
            if not has_sweep or s.strength > sweep_strength or (
                s.strength == sweep_strength and s.candle_index > sweep_candle_index
            ):
                has_sweep = True
                sweep_type = s.type
                sweep_strength = s.strength
                sweep_reclaim = s.reclaim_candles
                sweep_candle_index = s.candle_index
                _sweep_price = s.swept_level
                _sweep_ts = s.timestamp

        if not has_sweep:
            total_valid = len(valid_sweeps)
            rejected_count = len(sweep_reject_reasons)
            if total_valid > 0:
                reason_counts = {}
                for r in sweep_reject_reasons:
                    key = r.split(" ")[0:3]
                    reason_counts[" ".join(key)] = reason_counts.get(" ".join(key), 0) + 1
                logger.info(
                    f"Sweep summary: {total_valid} valid, {rejected_count} rejected "
                    f"by false filters, 0 accepted. Top rejections: {reason_counts}"
                )
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
        _mss_level = 0.0
        _mss_ts = None

        if structure and structure.last_mss is not None:
            mss = structure.last_mss
            has_mss = True
            mss_score = mss.mss_score
            mss_causality = mss.causality_score
            _mss_level = mss.level
            _mss_ts = mss.timestamp
            # Direction from MSS + sweep alignment
            if mss.type == "bullish":
                direction = "buy"
            elif mss.type == "bearish":
                direction = "sell"
            # Bars between sweep and MSS
            if sweep_candle_index >= 0 and mss.candle_index >= 0:
                sweep_to_mss = max(0, mss.candle_index - sweep_candle_index)

        if not has_mss:
            # Sweep without MSS: not a valid reversal, but don't suppress continuation.
            # Return detected=False so detect() can try the continuation path.
            return ICTSetup(
                detected=False,
                direction=None,
                setup_type="reversal",
                has_sweep=has_sweep, sweep_type=sweep_type,
                sweep_strength=sweep_strength,
                sweep_reclaim_candles=sweep_reclaim,
                has_displacement=has_displacement,
                displacement_body_pct=disp_body,
                displacement_atr_ratio=disp_atr,
                has_mss=False,
                sweep_price=_sweep_price, sweep_candle_timestamp=_sweep_ts,
                rejection_reason="reversal: sweep only (no MSS)",
            )

        if direction is None:
            return ICTSetup(
                detected=False,
                has_sweep=has_sweep, sweep_type=sweep_type,
                has_displacement=has_displacement,
                has_mss=has_mss,
                sweep_price=_sweep_price, sweep_candle_timestamp=_sweep_ts,
                mss_level_price=_mss_level, mss_candle_timestamp=_mss_ts,
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
            sweep_price=_sweep_price,
            sweep_candle_timestamp=_sweep_ts,
            mss_level_price=_mss_level,
            mss_candle_timestamp=_mss_ts,
        )

    def _try_continuation(self, structure, sweeps: list = None) -> ICTSetup:
        """Try to detect a CONTINUATION setup: trend + BOS.

        TZ §6.3: BOS must break the last swing before the pullback.
        We validate this by checking BOS level against recent swing points.
        """
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
        _bos_price = 0.0
        _bos_ts = None

        if structure.last_bos is not None:
            bos = structure.last_bos
            has_bos = True
            bos_type = bos.type
            bos_level = bos.level
            _bos_price = bos.level
            _bos_ts = bos.timestamp
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

        # TZ §6.3: BOS must break the last swing before the pullback.
        # Validate BOS level against the most recent swing in the opposite direction.
        if structure.swing_points:
            _swings = structure.swing_points
            if direction == "buy":
                # Bullish BOS should break the most recent swing high
                _recent_highs = [s for s in _swings if s.type == "high" and s.candle_index < structure.last_bos.candle_index]
                if _recent_highs:
                    _last_swing_before = max(_recent_highs, key=lambda s: s.candle_index)
                    if structure.last_bos.level <= _last_swing_before.price:
                        return ICTSetup(
                            detected=False,
                            has_bos=has_bos, bos_type=bos_type,
                            structure_trend=trend,
                            bos_level_price=_bos_price, bos_candle_timestamp=_bos_ts,
                            rejection_reason=f"continuation: BOS level {structure.last_bos.level:.2f} <= last swing high {_last_swing_before.price:.2f}",
                        )
            elif direction == "sell":
                # Bearish BOS should break the most recent swing low
                _recent_lows = [s for s in _swings if s.type == "low" and s.candle_index < structure.last_bos.candle_index]
                if _recent_lows:
                    _last_swing_before = max(_recent_lows, key=lambda s: s.candle_index)
                    if structure.last_bos.level >= _last_swing_before.price:
                        return ICTSetup(
                            detected=False,
                            has_bos=has_bos, bos_type=bos_type,
                            structure_trend=trend,
                            bos_level_price=_bos_price, bos_candle_timestamp=_bos_ts,
                            rejection_reason=f"continuation: BOS level {structure.last_bos.level:.2f} >= last swing low {_last_swing_before.price:.2f}",
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
                bos_level_price=_bos_price, bos_candle_timestamp=_bos_ts,
                rejection_reason=f"continuation: BOS {bos_type} vs trend {trend}",
            )

        return ICTSetup(
            detected=True,
            direction=direction,
            setup_type="continuation",
            has_bos=has_bos,
            bos_type=bos_type,
            bos_level=bos_level,
            bos_level_price=_bos_price,
            bos_candle_timestamp=_bos_ts,
        )

    def _detect_entry_zones(
        self,
        setup: ICTSetup,
        order_blocks: list,
        fvgs: list,
        direction: str,
        current_price: float,
        sweep_timestamp: Optional[datetime] = None,
    ):
        """Detect OB and FVG as entry zones (not gates).

        Temporal binding (TZ §6.0): only consider OBs/FVGs formed AFTER sweep.
        """
        # OB — temporal binding: ob.timestamp >= sweep_timestamp
        for ob in order_blocks:
            ob_dir = "buy" if ob.type == "bullish" else "sell" if ob.type == "bearish" else ob.type
            if ob.is_valid and ob_dir == direction:
                if sweep_timestamp is not None and hasattr(ob, 'timestamp') and ob.timestamp is not None:
                    if ob.timestamp < sweep_timestamp:
                        continue
                setup.has_ob = True
                setup.ob_type = ob.type
                setup.ob_midpoint = ob.midpoint
                setup.ob_high_price = ob.high
                setup.ob_low_price = ob.low
                setup.ob_candle_timestamp = ob.timestamp
                if current_price > 0:
                    setup.ob_distance_pct = abs(current_price - ob.midpoint) / current_price * 100
                break

        # FVG — temporal binding: fvg.timestamp >= sweep_timestamp
        for f in fvgs:
            f_dir = "buy" if f.type == "bullish" else "sell" if f.type == "bearish" else f.type
            if f.is_active and f_dir == direction:
                if sweep_timestamp is not None and hasattr(f, 'timestamp') and f.timestamp is not None:
                    if f.timestamp < sweep_timestamp:
                        continue
                setup.has_fvg = True
                setup.fvg_type = f.type
                setup.fvg_size_pct = f.size_pct
                setup.fvg_midpoint = (f.top + f.bottom) / 2
                setup.fvg_top_price = f.top
                setup.fvg_bottom_price = f.bottom
                setup.fvg_candle_timestamp = f.timestamp
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
        if setup.has_fvg and setup.fvg_midpoint > 0:
            dist_pct = abs(current_price - setup.fvg_midpoint) / current_price * 100
            if dist_pct <= self.ob_proximity_pct:
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
            if setup.structure_trend and setup.structure_trend in ("bullish", "bearish"):
                components.append("Trend")
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
