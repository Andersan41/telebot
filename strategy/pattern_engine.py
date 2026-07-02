"""
strategy/pattern_engine.py — ICT Pattern Engine (Layer 1)

The ONLY source of trading signals. Pure ICT — no indicators, no scoring.

Detects:
- BOS (Break of Structure) → direction
- Liquidity Sweep → direction + confirmation
- Order Block → confirmation zone
- Fair Value Gap → confirmation zone
- Displacement → candle quality signal

Minimum for valid setup: trigger (BOS or sweep) + confirmation (OB or FVG).
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

    # === Pattern components (boolean — present or not) ===
    has_bos: bool = False
    bos_type: Optional[str] = None  # "bullish" / "bearish"
    bos_level: float = 0.0

    has_sweep: bool = False
    sweep_type: Optional[str] = None
    sweep_strength: float = 0.0
    sweep_reclaim_candles: int = 0

    has_ob: bool = False
    ob_type: Optional[str] = None
    ob_distance_pct: float = 0.0  # how close price is to OB midpoint
    ob_midpoint: float = 0.0

    has_fvg: bool = False
    fvg_type: Optional[str] = None
    fvg_size_pct: float = 0.0

    has_displacement: bool = False
    displacement_body_pct: float = 0.0

    # === Structural info ===
    structure_trend: Optional[str] = None  # "bullish" / "bearish" / "ranging"

    # === Component count ===
    components_found: List[str] = field(default_factory=list)

    # === Rejection info ===
    rejection_reason: Optional[str] = None

    @property
    def components_count(self) -> int:
        return len(self.components_found)

    @property
    def has_trigger(self) -> bool:
        return self.has_bos or self.has_sweep

    @property
    def has_confirmation(self) -> bool:
        return self.has_ob or self.has_fvg


class PatternEngine:
    """Detects ICT setups from raw price action data.

    No indicators. No scoring. Pure pattern detection.
    """

    def __init__(
        self,
        require_bos_or_sweep: bool = True,
        require_ob_or_fvg: bool = True,
        ob_proximity_pct: float = 2.0,
    ):
        self.require_bos_or_sweep = require_bos_or_sweep
        self.require_ob_or_fvg = require_ob_or_fvg
        self.ob_proximity_pct = ob_proximity_pct

    def detect(
        self,
        sweeps: list,
        order_blocks: list,
        structure,
        fvgs: list,
        candle_quality,
        current_price: float,
    ) -> ICTSetup:
        """Detect whether a valid ICT setup exists.

        Args:
            sweeps: list of SweepEvent from liquidity.sweep.detect_sweeps()
            order_blocks: list of OrderBlock from liquidity.order_blocks.detect_order_blocks()
            structure: StructureState from market_structure.structure.analyze_structure()
            fvgs: list of FairValueGap from liquidity.fvg.detect_fvg()
            candle_quality: CandleQuality from liquidity.candle_quality.analyze_last_candle()
            current_price: current close price

        Returns:
            ICTSetup with detection result.
        """
        # 1. Resolve direction from structure/sweep
        direction = self._resolve_direction(structure, sweeps)
        if direction is None:
            return ICTSetup(
                detected=False,
                structure_trend=structure.trend if structure else None,
                rejection_reason="no clear direction (no BOS/sweep)",
            )

        # 2. Detect BOS
        has_bos = False
        bos_type = None
        bos_level = 0.0
        if structure and structure.last_bos:
            bos = structure.last_bos
            has_bos = True
            bos_type = bos.type
            bos_level = bos.level

        # 3. Detect sweep
        has_sweep = False
        sweep_type = None
        sweep_strength = 0.0
        sweep_reclaim = 0
        if sweeps:
            for s in sweeps:
                s_dir = "buy" if s.type == "bullish" else "sell" if s.type == "bearish" else s.type
                if s.is_valid and s_dir == direction:
                    has_sweep = True
                    sweep_type = s.type
                    sweep_strength = s.strength
                    sweep_reclaim = s.reclaim_candles
                    break

        # 4. Detect OB
        has_ob = False
        ob_type = None
        ob_distance = 0.0
        ob_mid = 0.0
        if order_blocks:
            for ob in order_blocks:
                ob_dir = "buy" if ob.type == "bullish" else "sell" if ob.type == "bearish" else ob.type
                if ob.is_valid and ob_dir == direction:
                    has_ob = True
                    ob_type = ob.type
                    ob_mid = ob.midpoint
                    if current_price > 0:
                        ob_distance = abs(current_price - ob.midpoint) / current_price * 100
                    break

        # 5. Detect FVG
        has_fvg = False
        fvg_type = None
        fvg_size = 0.0
        if fvgs:
            for f in fvgs:
                f_dir = "buy" if f.type == "bullish" else "sell" if f.type == "bearish" else f.type
                if f.is_active and f_dir == direction:
                    has_fvg = True
                    fvg_type = f.type
                    fvg_size = f.size_pct
                    break

        # 6. Detect displacement
        has_displacement = False
        disp_body = 0.0
        if candle_quality:
            has_displacement = candle_quality.is_displacement
            disp_body = candle_quality.body_pct

        # 7. Build component list
        components = []
        if has_bos:
            components.append("BOS")
        if has_sweep:
            components.append("Sweep")
        if has_ob:
            components.append("OB")
        if has_fvg:
            components.append("FVG")
        if has_displacement:
            components.append("Displacement")

        # 8. Check minimum requirements
        has_trigger = (not self.require_bos_or_sweep) or (has_bos or has_sweep)
        has_confirmation = (not self.require_ob_or_fvg) or (has_ob or has_fvg)

        if not has_trigger:
            return ICTSetup(
                detected=False,
                direction=direction,
                has_bos=has_bos, bos_type=bos_type, bos_level=bos_level,
                has_sweep=has_sweep, sweep_type=sweep_type,
                has_ob=has_ob, has_fvg=has_fvg,
                structure_trend=structure.trend if structure else None,
                components_found=components,
                rejection_reason="no trigger (need BOS or Sweep)",
            )

        if not has_confirmation:
            return ICTSetup(
                detected=False,
                direction=direction,
                has_bos=has_bos, bos_type=bos_type, bos_level=bos_level,
                has_sweep=has_sweep, sweep_type=sweep_type,
                structure_trend=structure.trend if structure else None,
                components_found=components,
                rejection_reason="no confirmation (need OB or FVG)",
            )

        # 9. Setup detected
        logger.info(
            f"ICT setup detected: {direction.upper()} | "
            f"components={components} | "
            f"BOS={has_bos} Sweep={has_sweep} OB={has_ob} FVG={has_fvg} Disp={has_displacement}"
        )

        return ICTSetup(
            detected=True,
            direction=direction,
            has_bos=has_bos, bos_type=bos_type, bos_level=bos_level,
            has_sweep=has_sweep, sweep_type=sweep_type,
            sweep_strength=sweep_strength, sweep_reclaim_candles=sweep_reclaim,
            has_ob=has_ob, ob_type=ob_type,
            ob_distance_pct=ob_distance, ob_midpoint=ob_mid,
            has_fvg=has_fvg, fvg_type=fvg_type, fvg_size_pct=fvg_size,
            has_displacement=has_displacement, displacement_body_pct=disp_body,
            structure_trend=structure.trend if structure else None,
            components_found=components,
        )

    def _resolve_direction(self, structure, sweeps) -> Optional[str]:
        """Determine trade direction from structure and sweeps.

        Priority:
        1. BOS direction (most reliable)
        2. Sweep direction (second most reliable)
        """
        # Primary: BOS
        if structure and structure.last_bos:
            bos = structure.last_bos
            if bos.type in ("bullish", "bearish"):
                return "buy" if bos.type == "bullish" else "sell"

        # Secondary: sweep
        valid_sweeps = [s for s in sweeps if s.is_valid]
        if valid_sweeps:
            last = valid_sweeps[-1]
            if last.type in ("bullish", "bearish"):
                return "buy" if last.type == "bullish" else "sell"

        return None


# Singleton
pattern_engine = PatternEngine()
