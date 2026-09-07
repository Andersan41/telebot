"""
strategy/htf_poi.py — Multi-Timeframe Points of Interest.

Detects OB/FVG on higher timeframes (D1, H4) and checks if current price
is approaching them. Professional traders use HTF POI as primary zones,
then look for entry triggers on LTF.

Flow:
1. Detect OB/FVG on D1, H4
2. Check proximity to current price
3. If price near HTF POI → pass to trade engine for SL placement
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd
from loguru import logger

from liquidity.order_blocks import OrderBlock, detect_order_blocks
from liquidity.fvg import FairValueGap, detect_fvg


@dataclass
class HTFPOI:
    """A Point of Interest from a higher timeframe."""
    poi_type: Literal["ob", "fvg"]
    direction: Literal["bullish", "bearish"]
    high: float
    low: float
    source_tf: str  # "1d", "4h", "1w"
    confidence: float = 0.5  # 0-1, based on OB quality or FVG size

    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2

    @property
    def range_pct(self) -> float:
        """Zone width as % of midpoint."""
        if self.midpoint == 0:
            return 0.0
        return abs(self.high - self.low) / self.midpoint * 100

    def distance_pct(self, price: float) -> float:
        """Distance from price to midpoint as %."""
        if price == 0:
            return 999.0
        return abs(price - self.midpoint) / price * 100

    def contains_price(self, price: float) -> bool:
        """Check if price is inside the zone."""
        return self.low <= price <= self.high


@dataclass
class HTFPOIResult:
    """Result of HTF POI analysis."""
    pois: list[HTFPOI]
    nearest: Optional[HTFPOI] = None
    is_near: bool = False  # True if price is within proximity threshold

    @property
    def has_htf_poi(self) -> bool:
        return len(self.pois) > 0


def detect_htf_pois(
    df_1d: Optional[pd.DataFrame] = None,
    df_4h: Optional[pd.DataFrame] = None,
    df_1w: Optional[pd.DataFrame] = None,
    current_price: float = 0.0,
    direction: Optional[str] = None,  # "buy" / "sell" — filter POIs by direction
    proximity_pct: float = 2.0,  # max distance to consider "near"
) -> HTFPOIResult:
    """Detect POIs on higher timeframes and check proximity.

    Args:
        df_1d: Daily OHLCV DataFrame.
        df_4h: 4-hour OHLCV DataFrame.
        df_1w: Weekly OHLCV DataFrame.
        current_price: Current market price.
        direction: Signal direction ("buy"/"sell") to filter relevant POIs.
                   If None, returns all POIs.
        proximity_pct: Max distance from price to POI midpoint to consider "near".

    Returns:
        HTFPOIResult with detected POIs and proximity info.
    """
    pois: list[HTFPOI] = []

    # Detect on each available TF
    for tf_name, df in [("1w", df_1w), ("1d", df_1d), ("4h", df_4h)]:
        if df is None or len(df) < 20:
            continue

        # OBs on HTF — use relaxed thresholds (HTF OBs are more significant)
        try:
            htf_obs = detect_order_blocks(
                df,
                lookback=50,
                require_bos=False,  # HTF OBs don't always need BOS validation
                retest_required=False,
            )
            for ob in htf_obs:
                # Filter by direction if specified
                if direction:
                    ob_dir = "buy" if ob.type == "bullish" else "sell"
                    if ob_dir != direction:
                        continue

                confidence = min(1.0, ob.displacement_atr / 2.0)  # normalize
                pois.append(HTFPOI(
                    poi_type="ob",
                    direction=ob.type,
                    high=ob.high,
                    low=ob.low,
                    source_tf=tf_name,
                    confidence=confidence,
                ))
        except Exception as e:
            logger.debug(f"HTF OB detection failed on {tf_name}: {e}")

        # FVGs on HTF
        try:
            htf_fvgs = detect_fvg(df, lookback=50)
            for fvg in htf_fvgs:
                if direction:
                    fvg_dir = "buy" if fvg.type == "bullish" else "sell"
                    if fvg_dir != direction:
                        continue

                confidence = min(1.0, fvg.size_pct / 1.0)  # normalize by size
                pois.append(HTFPOI(
                    poi_type="fvg",
                    direction=fvg.type,
                    high=fvg.top,
                    low=fvg.bottom,
                    source_tf=tf_name,
                    confidence=confidence,
                ))
        except Exception as e:
            logger.debug(f"HTF FVG detection failed on {tf_name}: {e}")

    if not pois:
        return HTFPOIResult(pois=[])

    # Sort by confidence (best first)
    pois.sort(key=lambda p: p.confidence, reverse=True)

    # Find nearest to current price
    nearest = min(pois, key=lambda p: p.distance_pct(current_price)) if current_price > 0 else None
    is_near = nearest is not None and nearest.distance_pct(current_price) <= proximity_pct

    if is_near and nearest:
        logger.info(
            f"HTF POI near: {nearest.source_tf} {nearest.poi_type} {nearest.direction} "
            f"mid={nearest.midpoint:.4f} dist={nearest.distance_pct(current_price):.2f}%"
        )

    return HTFPOIResult(
        pois=pois,
        nearest=nearest,
        is_near=is_near,
    )


def get_htf_sl_level(
    result: HTFPOIResult,
    direction: str,
    current_price: float,
    fallback_level: Optional[float] = None,
) -> Optional[float]:
    """Get SL level from HTF POI.

    For BUY: SL below the nearest bullish HTF OB/FVG low.
    For SELL: SL above the nearest bearish HTF OB/FVG high.

    Only returns HTF level if it's actually better (wider) than the fallback.
    """
    if not result.is_near or result.nearest is None:
        return None

    poi = result.nearest

    # Direction must match: bullish POI for BUY, bearish POI for SELL
    if direction == "buy" and poi.direction != "bullish":
        return None
    if direction == "sell" and poi.direction != "bearish":
        return None

    # HTF POI low/high as SL anchor
    if direction == "buy":
        htf_sl = poi.low
        # Only use if it's below entry and wider than fallback
        if htf_sl >= current_price:
            return None
        if fallback_level is not None and htf_sl >= fallback_level:
            return None  # fallback is tighter, keep it
        return htf_sl
    else:
        htf_sl = poi.high
        if htf_sl <= current_price:
            return None
        if fallback_level is not None and htf_sl <= fallback_level:
            return None
        return htf_sl
