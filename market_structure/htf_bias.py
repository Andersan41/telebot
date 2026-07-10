"""
market_structure/htf_bias.py — HTF Bias Hard Gate

Determines higher-timeframe directional bias using:
1. Market structure (BOS/CHoCH) — highest priority
2. EMA alignment (EMA21/55 with slope check) — fallback
3. Neutral fallback

Used by scanner to hard-reject continuation trades against HTF trend.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger


class HTFBias(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


def get_htf_bias(
    df_1d: Optional[pd.DataFrame] = None,
    df_4h: Optional[pd.DataFrame] = None,
    structure_1d: Optional[dict] = None,
    structure_4h: Optional[dict] = None,
) -> HTFBias:
    """Determine HTF bias by priority: structure > EMA > neutral.

    Args:
        df_1d: Daily OHLCV data
        df_4h: 4H OHLCV data
        structure_1d: dict with 'last_bos_direction' and 'bos_age_candles'
        structure_4h: dict with 'last_bos_direction' and 'bos_age_candles'

    Returns:
        HTFBias enum: BULLISH, BEARISH, or NEUTRAL
    """
    # Priority 1: 1D structure (BOS/CHoCH)
    if structure_1d:
        last_bos = structure_1d.get("last_bos_direction")
        bos_age = structure_1d.get("bos_age_candles", 999)
        if last_bos and bos_age < 20:
            return HTFBias.BULLISH if last_bos == "bullish" else HTFBias.BEARISH

    # Priority 2: 1D EMA
    bias_1d = _ema_bias(df_1d)
    if bias_1d != HTFBias.NEUTRAL:
        return bias_1d

    # Priority 3: 4H structure
    if structure_4h:
        last_bos = structure_4h.get("last_bos_direction")
        bos_age = structure_4h.get("bos_age_candles", 999)
        if last_bos and bos_age < 12:
            return HTFBias.BULLISH if last_bos == "bullish" else HTFBias.BEARISH

    # Priority 4: 4H EMA
    bias_4h = _ema_bias(df_4h)
    if bias_4h != HTFBias.NEUTRAL:
        return bias_4h

    return HTFBias.NEUTRAL


def _ema_bias(
    df: Optional[pd.DataFrame],
    ema_fast: int = 21,
    ema_slow: int = 55,
) -> HTFBias:
    """EMA-based bias with slope verification.

    Bullish: price > EMA21 > EMA55 AND EMA21 rising
    Bearish: price < EMA21 < EMA55 AND EMA21 falling
    Neutral: everything else
    """
    if df is None or len(df) < ema_slow + 10:
        return HTFBias.NEUTRAL

    ema_f = df["close"].ewm(span=ema_fast).mean()
    ema_s = df["close"].ewm(span=ema_slow).mean()

    price = float(df["close"].iloc[-1])
    ema_f_now = float(ema_f.iloc[-1])
    ema_s_now = float(ema_s.iloc[-1])
    ema_f_prev = float(ema_f.iloc[-5])

    # Slope: % change over 5 periods
    slope = (ema_f_now - ema_f_prev) / ema_f_prev * 100 if ema_f_prev > 0 else 0
    slope_threshold = 0.05  # 0.05% minimum slope

    if price > ema_f_now > ema_s_now and slope > slope_threshold:
        return HTFBias.BULLISH
    elif price < ema_f_now < ema_s_now and slope < -slope_threshold:
        return HTFBias.BEARISH

    return HTFBias.NEUTRAL


def extract_structure_dict(structure) -> Optional[dict]:
    """Extract structure dict from StructureState for HTF bias lookup."""
    if structure is None:
        return None

    result = {}

    if hasattr(structure, "last_bos") and structure.last_bos is not None:
        bos = structure.last_bos
        result["last_bos_direction"] = bos.type if hasattr(bos, "type") else None
        result["bos_age_candles"] = getattr(bos, "candle_index", 999)

    if hasattr(structure, "last_choch") and structure.last_choch is not None:
        choch = structure.last_choch
        if "last_bos_direction" not in result:
            result["last_bos_direction"] = choch.type if hasattr(choch, "type") else None
            result["bos_age_candles"] = getattr(choch, "candle_index", 999)

    return result if result else None
