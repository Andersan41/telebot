"""
risk/dynamic_risk.py — Dynamic risk allocation based on setup quality.

Risk by setup quality:
- Strong:     RISK_STRONG_PCT     (default 1.0%)
- Moderate:   RISK_MODERATE_PCT   (default 0.5%)
- Weak:       No trade (RISK_WEAK_TRADE=false)

Effective risk is adjusted by:
- Volatility regime multiplier (high vol → 0.5x)
- Correlation multiplier (BTC/ETH misaligned → 0.5x)

Structural SL/TP (Task 5.1):
- LONG SL: below nearest sweep low / OB low / structure low
- SHORT SL: above nearest sweep high / OB high / structure high
- Fallback: ATR-based if no structures nearby
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional

import config.settings as settings

if TYPE_CHECKING:
    from liquidity.sweep import SweepEvent
    from liquidity.order_blocks import OrderBlock
    from liquidity.fvg import FairValueGap
    from market_structure.structure import StructureState


@dataclass
class TPTarget:
    price: float
    label: str
    rr: float = 0.0


@dataclass
class RiskParams:
    setup_quality: Literal["strong", "moderate", "weak"]
    base_risk_pct: float
    volatility_multiplier: float
    correlation_multiplier: float

    @property
    def effective_risk_pct(self) -> float:
        return round(
            self.base_risk_pct * self.volatility_multiplier * self.correlation_multiplier,
            4,
        )

    @property
    def should_trade(self) -> bool:
        if self.setup_quality == "weak":
            return settings.config.risk.risk_weak_trade
        return True


def _base_risk_for_quality(quality: str) -> float:
    if quality == "strong":
        return settings.config.risk.risk_strong_pct
    elif quality == "moderate":
        return settings.config.risk.risk_moderate_pct
    return 0.0


def _volatility_multiplier(volatility_regime: str) -> float:
    if volatility_regime == "high":
        return settings.config.risk.volatility_high_multiplier
    return 1.0


def _correlation_multiplier(
    btc_aligned: bool = True,
    eth_aligned: bool = True,
) -> float:
    if not btc_aligned or not eth_aligned:
        return settings.config.risk.correlation_misaligned_multiplier
    return 1.0


def calculate_risk(
    setup_quality: str,
    volatility_regime: str = "medium",
    btc_aligned: bool = True,
    eth_aligned: bool = True,
) -> RiskParams:
    """Calculate dynamic risk parameters for a signal.

    Args:
        setup_quality: "strong", "moderate", or "weak"
        volatility_regime: "low", "medium", or "high"
        btc_aligned: True if BTC correlation allows the trade direction
        eth_aligned: True if ETH correlation allows the trade direction
    """
    base = _base_risk_for_quality(setup_quality)
    vol_mult = _volatility_multiplier(volatility_regime)
    corr_mult = _correlation_multiplier(btc_aligned, eth_aligned)

    return RiskParams(
        setup_quality=setup_quality,
        base_risk_pct=base,
        volatility_multiplier=vol_mult,
        correlation_multiplier=corr_mult,
    )


# ─── Structural SL/TP (Task 5.1) ─────────────────────────────────────────

def _find_nearest_below(levels: list[float], reference: float) -> Optional[float]:
    """Find the nearest level below reference price."""
    below = [lvl for lvl in levels if lvl < reference]
    if not below:
        return None
    return max(below)


def _find_nearest_above(levels: list[float], reference: float) -> Optional[float]:
    """Find the nearest level above reference price."""
    above = [lvl for lvl in levels if lvl > reference]
    if not above:
        return None
    return min(above)


def calculate_structural_sl(
    direction: Literal["BUY", "SELL"],
    entry: float,
    sweeps: list["SweepEvent"],
    order_blocks: list["OrderBlock"],
    structure: Optional["StructureState"] = None,
    atr: float = 0.0,
    close: float = 0.0,
) -> float:
    """Calculate stop loss based on market structure.

    LONG SL: below nearest sweep low / OB low / structure low
    SHORT SL: above nearest sweep high / OB high / structure high
    Fallback: ATR * atr_multiplier_sl if no structures nearby.

    Args:
        direction: "BUY" or "SELL"
        entry: entry price
        sweeps: detected liquidity sweeps
        order_blocks: detected order blocks
        structure: market structure state
        atr: current ATR value (for fallback)
        close: current close price (for fallback)

    Returns:
        Stop loss price
    """
    candidate_levels: list[float] = []

    if direction == "BUY":
        # Collect levels below entry
        for s in sweeps:
            if s.type == "bullish" and s.sweep_low < entry:
                candidate_levels.append(s.sweep_low)
        for ob in order_blocks:
            if ob.low < entry:
                candidate_levels.append(ob.low)
        if structure:
            for low in structure.recent_lows:
                if low < entry:
                    candidate_levels.append(low)

        sl_level = _find_nearest_below(candidate_levels, entry)
        if sl_level is not None:
            return round(sl_level, 8)
    else:
        # SELL: collect levels above entry
        for s in sweeps:
            if s.type == "bearish" and s.sweep_high > entry:
                candidate_levels.append(s.sweep_high)
        for ob in order_blocks:
            if ob.high > entry:
                candidate_levels.append(ob.high)
        if structure:
            for high in structure.recent_highs:
                if high > entry:
                    candidate_levels.append(high)

        sl_level = _find_nearest_above(candidate_levels, entry)
        if sl_level is not None:
            return round(sl_level, 8)

    # Fallback: ATR-based
    cfg = settings.config.trading
    if atr <= 0:
        atr = close * (cfg.atr_fallback_pct / 100.0)
    if direction == "BUY":
        return round(entry - atr * cfg.atr_multiplier_sl, 8)
    return round(entry + atr * cfg.atr_multiplier_sl, 8)


def calculate_structural_tp(
    direction: Literal["BUY", "SELL"],
    entry: float,
    sl: float,
    sweeps: list["SweepEvent"],
    order_blocks: list["OrderBlock"],
    structure: Optional["StructureState"] = None,
    fvgs: Optional[list["FairValueGap"]] = None,
    atr: float = 0.0,
    close: float = 0.0,
) -> list[TPTarget]:
    """Calculate take profit targets based on market structure.

    LONG TP: above entry — nearest sweep high / OB high / structure high / FVG fill
    SHORT TP: below entry — nearest sweep low / OB low / structure low / FVG fill
    Fallback: ATR * atr_multiplier_tp if no structures nearby.

    Returns list of TPTarget sorted by proximity.
    Minimum RR = 1:2, otherwise returns empty list.

    Args:
        direction: "BUY" or "SELL"
        entry: entry price
        sl: stop loss price (used to compute RR)
        sweeps: detected liquidity sweeps
        order_blocks: detected order blocks
        structure: market structure state
        fvgs: detected fair value gaps (active, used as TP targets)
        atr: current ATR value (for fallback)
        close: current close price (for fallback)

    Returns:
        List of TPTarget, may be empty if min RR not met
    """
    risk = abs(entry - sl)
    if risk <= 0:
        risk = entry * (settings.config.trading.atr_fallback_pct / 100.0)

    candidate_levels: list[tuple[float, str]] = []

    if direction == "BUY":
        for s in sweeps:
            if s.sweep_high > entry:
                candidate_levels.append((s.sweep_high, f"sweep high {s.sweep_high:.4f}"))
        for ob in order_blocks:
            if ob.high > entry:
                candidate_levels.append((ob.high, f"OB high {ob.high:.4f}"))
        if structure:
            for high in structure.recent_highs:
                if high > entry:
                    candidate_levels.append((high, f"structure high {high:.4f}"))
        if fvgs:
            for fvg in fvgs:
                if fvg.is_active and fvg.type == "bearish":
                    fvg_fill = (fvg.top + fvg.bottom) / 2
                    if fvg_fill > entry:
                        candidate_levels.append((fvg_fill, f"FVG fill {fvg_fill:.4f}"))

        candidate_levels.sort(key=lambda x: x[0])
    else:
        for s in sweeps:
            if s.sweep_low < entry:
                candidate_levels.append((s.sweep_low, f"sweep low {s.sweep_low:.4f}"))
        for ob in order_blocks:
            if ob.low < entry:
                candidate_levels.append((ob.low, f"OB low {ob.low:.4f}"))
        if structure:
            for low in structure.recent_lows:
                if low < entry:
                    candidate_levels.append((low, f"structure low {low:.4f}"))
        if fvgs:
            for fvg in fvgs:
                if fvg.is_active and fvg.type == "bullish":
                    fvg_fill = (fvg.top + fvg.bottom) / 2
                    if fvg_fill < entry:
                        candidate_levels.append((fvg_fill, f"FVG fill {fvg_fill:.4f}"))

        candidate_levels.sort(key=lambda x: x[0], reverse=True)

    targets: list[TPTarget] = []
    for price, label in candidate_levels:
        reward = abs(price - entry)
        rr = reward / risk if risk > 0 else 0
        if rr >= 2.0:
            targets.append(TPTarget(price=round(price, 8), label=label, rr=round(rr, 2)))

    if not targets:
        cfg = settings.config.trading
        if atr <= 0:
            atr = close * 0.02
        if direction == "BUY":
            tp_price = round(entry + atr * cfg.atr_multiplier_tp, 8)
        else:
            tp_price = round(entry - atr * cfg.atr_multiplier_tp, 8)
        reward = abs(tp_price - entry)
        rr = reward / risk if risk > 0 else 0
        targets.append(TPTarget(price=tp_price, label=f"ATR fallback ({cfg.atr_multiplier_tp}x)", rr=round(rr, 2)))

    return targets
