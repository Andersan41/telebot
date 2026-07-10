"""
liquidity/ob_state.py — OB/FVG Mitigation State Tracker

Incrementally tracks the state of Order Blocks and FVGs:
- fresh: no touches
- tested: wick touch, no close inside
- partial: close inside, penetration < 50%
- mitigated: close inside, penetration >= 50%
- broken: close beyond zone (against OB type)

State is tracked in memory (singleton registry) and updated per candle.
Multipliers: fresh=1.25, tested=1.0, partial=0.75, mitigated=0.5, broken=0.0
"""
from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Optional

import pandas as pd
from loguru import logger


class OBState(Enum):
    FRESH = "fresh"
    TESTED = "tested"
    PARTIAL = "partial"
    MITIGATED = "mitigated"
    BROKEN = "broken"


class FVGState(Enum):
    FRESH = "fresh"
    PARTIALLY_FILLED = "partially_filled"
    BALANCED = "balanced"
    INVALIDATED = "invalidated"


# Multipliers for probability engine
OB_MULTIPLIERS = {
    OBState.FRESH: 1.25,
    OBState.TESTED: 1.0,
    OBState.PARTIAL: 0.75,
    OBState.MITIGATED: 0.5,
    OBState.BROKEN: 0.0,
}

FVG_MULTIPLIERS = {
    FVGState.FRESH: 1.1,
    FVGState.PARTIALLY_FILLED: 0.9,
    FVGState.BALANCED: 0.7,
    FVGState.INVALIDATED: 0.0,
}


class OBStateTracker:
    """Incrementally tracks OB state based on incoming candles."""

    def __init__(
        self,
        symbol: str,
        ob_type: str,
        high: float,
        low: float,
        created_at: Optional[datetime] = None,
    ):
        self.ob_id = f"{symbol}_{ob_type}_{high:.4f}_{low:.4f}"
        self.symbol = symbol
        self.ob_type = ob_type  # 'bullish' or 'bearish'
        self.high = high
        self.low = low
        self.created_at = created_at or datetime.now()
        self.state = OBState.FRESH
        self.touch_count = 0
        self.close_inside_count = 0
        self.max_penetration = 0.0
        self.last_candle_time: Optional[datetime] = None

    def update(self, candle: pd.Series) -> OBState:
        """Update state based on ONE new candle."""
        if self.state == OBState.BROKEN:
            return self.state

        # Wick touch
        wick_touch = candle["low"] <= self.high and candle["high"] >= self.low

        if wick_touch:
            self.touch_count += 1
            if self.state == OBState.FRESH:
                self.state = OBState.TESTED

        # Close inside zone
        close_inside = self.low <= candle["close"] <= self.high

        if close_inside:
            self.close_inside_count += 1
            zone_center = (self.high + self.low) / 2
            zone_height = self.high - self.low
            if zone_height > 0:
                penetration = abs(candle["close"] - zone_center) / (zone_height / 2)
                self.max_penetration = max(self.max_penetration, penetration)

            if self.max_penetration >= 0.5:
                self.state = OBState.MITIGATED
            else:
                self.state = OBState.PARTIAL

        # Broken: close beyond zone (against OB type)
        if self.ob_type == "bullish" and candle["close"] < self.low:
            self.state = OBState.BROKEN
        elif self.ob_type == "bearish" and candle["close"] > self.high:
            self.state = OBState.BROKEN

        self.last_candle_time = (
            candle.name
            if isinstance(candle.name, datetime)
            else datetime.now()
        )
        return self.state


class FVGStateTracker:
    """Incrementally tracks FVG state."""

    def __init__(
        self,
        symbol: str,
        fvg_type: str,
        high: float,
        low: float,
        created_at: Optional[datetime] = None,
    ):
        self.fvg_id = f"{symbol}_{fvg_type}_{high:.4f}_{low:.4f}"
        self.symbol = symbol
        self.fvg_type = fvg_type  # 'bullish' or 'bearish'
        self.high = high
        self.low = low
        self.created_at = created_at or datetime.now()
        self.state = FVGState.FRESH
        self.max_penetration = 0.0

    def update(self, candle: pd.Series) -> FVGState:
        """Update state based on ONE new candle."""
        if self.state == FVGState.INVALIDATED:
            return self.state

        close = candle["close"]
        zone_height = self.high - self.low

        if zone_height <= 0:
            return self.state

        # Price enters FVG
        if self.low <= close <= self.high:
            penetration = abs(close - (self.high + self.low) / 2) / (zone_height / 2)
            self.max_penetration = max(self.max_penetration, penetration)

            if self.max_penetration >= 0.8:
                self.state = FVGState.BALANCED
            elif self.state == FVGState.FRESH:
                self.state = FVGState.PARTIALLY_FILLED

        # Price passes through FVG completely
        if self.fvg_type == "bullish" and close > self.high:
            if self.state in (FVGState.PARTIALLY_FILLED, FVGState.BALANCED):
                self.state = FVGState.INVALIDATED
        elif self.fvg_type == "bearish" and close < self.low:
            if self.state in (FVGState.PARTIALLY_FILLED, FVGState.BALANCED):
                self.state = FVGState.INVALIDATED

        return self.state


# ── Global Registry (singleton) ────────────────────────────────────────────

_ob_registry: Dict[str, OBStateTracker] = {}
_fvg_registry: Dict[str, FVGStateTracker] = {}


def get_ob_tracker(
    symbol: str,
    ob_type: str,
    ob_high: float,
    ob_low: float,
    ob_time: Optional[datetime] = None,
) -> OBStateTracker:
    """Get or create tracker for an Order Block."""
    ob_id = f"{symbol}_{ob_type}_{ob_high:.4f}_{ob_low:.4f}"

    if ob_id not in _ob_registry:
        _ob_registry[ob_id] = OBStateTracker(
            symbol=symbol,
            ob_type=ob_type,
            high=ob_high,
            low=ob_low,
            created_at=ob_time,
        )

    return _ob_registry[ob_id]


def get_fvg_tracker(
    symbol: str,
    fvg_type: str,
    fvg_high: float,
    fvg_low: float,
    fvg_time: Optional[datetime] = None,
) -> FVGStateTracker:
    """Get or create tracker for an FVG."""
    fvg_id = f"{symbol}_{fvg_type}_{fvg_high:.4f}_{fvg_low:.4f}"

    if fvg_id not in _fvg_registry:
        _fvg_registry[fvg_id] = FVGStateTracker(
            symbol=symbol,
            fvg_type=fvg_type,
            high=fvg_high,
            low=fvg_low,
            created_at=fvg_time,
        )

    return _fvg_registry[fvg_id]


def get_ob_multiplier(state: OBState) -> float:
    """Get probability multiplier for OB state."""
    return OB_MULTIPLIERS.get(state, 1.0)


def get_fvg_multiplier(state: FVGState) -> float:
    """Get probability multiplier for FVG state."""
    return FVG_MULTIPLIERS.get(state, 1.0)


def cleanup_old_trackers(max_age_hours: int = 168) -> int:
    """Remove trackers older than N hours (default 7 days). Returns count removed."""
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    removed = 0

    to_remove = [k for k, v in _ob_registry.items() if v.created_at < cutoff]
    for k in to_remove:
        del _ob_registry[k]
        removed += 1

    to_remove = [k for k, v in _fvg_registry.items() if v.created_at < cutoff]
    for k in to_remove:
        del _fvg_registry[k]
        removed += 1

    return removed
