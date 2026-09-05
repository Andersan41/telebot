"""
liquidity/candle_quality.py — Candle Quality Engine.

Analyzes individual candles for:
- Displacement (body > ATR * multiplier)
- Body/wick ratio
- Momentum score
- Weak candle rejection (small bodies, long wicks against position)
- Event-specific quality (sweep, ob, bos)

Event-based analysis:
- Sweep candle: expects long wick, quick reclaim, high volume
- OB candle: expects large body, displacement, volume confirmation
- BOS candle: expects strong close, displacement, follow-through
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd

from config.settings import config


@dataclass
class CandleQuality:
    body_pct: float
    upper_wick_pct: float
    lower_wick_pct: float
    is_displacement: bool
    is_weak: bool
    momentum_score: float
    event_type: Optional[str] = None
    wick_body_ratio: float = 0.0
    close_position: float = 0.0
    volume_ratio: float = 1.0
    body_atr_ratio: float = 0.0
    quality_score: float = 0.0

    @property
    def is_bullish(self) -> bool:
        return self.momentum_score > 0

    @property
    def is_bearish(self) -> bool:
        return self.momentum_score < 0


def analyze_candle(
    open_price: float,
    high: float,
    low: float,
    close: float,
    atr_value: Optional[float] = None,
    atr_mult: Optional[float] = None,
    min_body_pct: Optional[float] = None,
    max_wick_ratio: Optional[float] = None,
) -> CandleQuality:
    """
    Analyze a single candle's quality.

    Args:
        open_price: Candle open.
        high: Candle high.
        low: Candle low.
        close: Candle close.
        atr_value: Current ATR value (for displacement detection).
        atr_mult: ATR multiplier for displacement (from config if None).
        min_body_pct: Minimum body % to not be weak (from config if None).
        max_wick_ratio: Max wick ratio before weak (from config if None).

    Returns:
        CandleQuality dataclass.
    """
    if atr_mult is None:
        atr_mult = getattr(config, "liquidity_candle_displacement_atr_mult", 1.2)
    if min_body_pct is None:
        min_body_pct = getattr(config, "liquidity_candle_min_body_pct", 0.5)
    if max_wick_ratio is None:
        max_wick_ratio = getattr(config, "liquidity_candle_max_wick_ratio", 0.3)

    range_val = high - low
    if range_val == 0:
        return CandleQuality(
            body_pct=0.0,
            upper_wick_pct=0.0,
            lower_wick_pct=0.0,
            is_displacement=False,
            is_weak=True,
            momentum_score=0.0,
        )

    body = abs(close - open_price)
    body_pct = body / range_val

    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low
    upper_wick_pct = upper_wick / range_val
    lower_wick_pct = lower_wick / range_val

    is_displacement = False
    if atr_value is not None and atr_value > 0:
        # Use full range (high-low), not body — matches structure.py fix
        # for same-candle displacement detection
        is_displacement = range_val > atr_value * atr_mult

    is_weak = body_pct < min_body_pct
    if not is_weak:
        wick_against = lower_wick_pct if close > open_price else upper_wick_pct
        if wick_against > max_wick_ratio:
            is_weak = True

    if close > open_price:
        momentum_score = body_pct * (1 - lower_wick_pct)
    elif close < open_price:
        momentum_score = -body_pct * (1 - upper_wick_pct)
    else:
        momentum_score = 0.0

    momentum_score = max(-1.0, min(1.0, momentum_score))

    return CandleQuality(
        body_pct=round(body_pct, 4),
        upper_wick_pct=round(upper_wick_pct, 4),
        lower_wick_pct=round(lower_wick_pct, 4),
        is_displacement=is_displacement,
        is_weak=is_weak,
        momentum_score=round(momentum_score, 4),
    )


def analyze_candle_quality(
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float,
    atr: float,
    avg_volume: float,
    event_type: Literal["sweep", "ob", "bos"],
) -> CandleQuality:
    """
    Analyze a specific event candle with quality scoring.

    Args:
        open_price: Candle open.
        high: Candle high.
        low: Candle low.
        close: Candle close.
        volume: Candle volume.
        atr: Current ATR value.
        avg_volume: Average volume for ratio calculation.
        event_type: Type of event ("sweep", "ob", "bos").

    Returns:
        CandleQuality with event-specific quality_score.
    """
    range_val = high - low
    if range_val == 0:
        return CandleQuality(
            body_pct=0.0,
            upper_wick_pct=0.0,
            lower_wick_pct=0.0,
            is_displacement=False,
            is_weak=True,
            momentum_score=0.0,
            event_type=event_type,
            quality_score=0.0,
        )

    body = abs(close - open_price)
    body_pct = body / range_val

    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low
    upper_wick_pct = upper_wick / range_val
    lower_wick_pct = lower_wick / range_val

    atr_mult = getattr(config, "liquidity_candle_displacement_atr_mult", 1.2)
    # Use full range (high-low), not body — matches structure.py fix
    is_displacement = range_val > atr * atr_mult if atr > 0 else False

    min_body_pct = getattr(config, "liquidity_candle_min_body_pct", 0.5)
    max_wick_ratio = getattr(config, "liquidity_candle_max_wick_ratio", 0.3)
    is_weak = body_pct < min_body_pct
    if not is_weak:
        wick_against = lower_wick_pct if close > open_price else upper_wick_pct
        if wick_against > max_wick_ratio:
            is_weak = True

    if close > open_price:
        momentum_score = body_pct * (1 - lower_wick_pct)
    elif close < open_price:
        momentum_score = -body_pct * (1 - upper_wick_pct)
    else:
        momentum_score = 0.0
    momentum_score = max(-1.0, min(1.0, momentum_score))

    wick_body_ratio = (range_val - body) / body if body > 0 else float("inf")
    close_position = (close - low) / range_val if range_val > 0 else 0.5
    volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0
    body_atr_ratio = body / atr if atr > 0 else 0.0

    quality_score = _calc_event_quality(event_type, body_pct, wick_body_ratio,
                                         close_position, volume_ratio,
                                         body_atr_ratio, is_displacement,
                                         close > open_price)

    return CandleQuality(
        body_pct=round(body_pct, 4),
        upper_wick_pct=round(upper_wick_pct, 4),
        lower_wick_pct=round(lower_wick_pct, 4),
        is_displacement=is_displacement,
        is_weak=is_weak,
        momentum_score=round(momentum_score, 4),
        event_type=event_type,
        wick_body_ratio=round(wick_body_ratio, 4) if wick_body_ratio != float("inf") else float("inf"),
        close_position=round(close_position, 4),
        volume_ratio=round(volume_ratio, 4),
        body_atr_ratio=round(body_atr_ratio, 4),
        quality_score=round(quality_score, 4),
    )


def _calc_event_quality(
    event_type: str,
    body_pct: float,
    wick_body_ratio: float,
    close_position: float,
    volume_ratio: float,
    body_atr_ratio: float,
    is_displacement: bool,
    is_bullish: bool,
) -> float:
    """
    Calculate quality score [0.0, 1.0] based on event type.

    Sweep: long wick (rejection), volume spike
    OB: large body, displacement, volume
    BOS: strong close, displacement, follow-through
    """
    score = 0.0

    if event_type == "sweep":
        if wick_body_ratio >= 2.0:
            score += 0.4
        elif wick_body_ratio >= 1.0:
            score += 0.2
        if volume_ratio > 1.5:
            score += 0.3
        elif volume_ratio > 1.0:
            score += 0.15
        if body_pct < 0.3:
            score += 0.3
        elif body_pct < 0.5:
            score += 0.15

    elif event_type == "ob":
        if body_pct >= 0.6:
            score += 0.3
        elif body_pct >= 0.4:
            score += 0.15
        if is_displacement:
            score += 0.3
        if volume_ratio > 1.5:
            score += 0.2
        elif volume_ratio > 1.0:
            score += 0.1
        if body_atr_ratio >= 1.5:
            score += 0.2
        elif body_atr_ratio >= 1.0:
            score += 0.1

    elif event_type == "bos":
        if is_displacement:
            score += 0.3
        close_strength = close_position if is_bullish else (1 - close_position)
        if close_strength >= 0.7:
            score += 0.3
        elif close_strength >= 0.5:
            score += 0.15
        if volume_ratio > 1.5:
            score += 0.2
        elif volume_ratio > 1.0:
            score += 0.1
        if body_atr_ratio >= 1.5:
            score += 0.2
        elif body_atr_ratio >= 1.0:
            score += 0.1

    return min(score, 1.0)


def analyze_last_candle(
    df: pd.DataFrame,
    atr_value: Optional[float] = None,
    **kwargs,
) -> Optional[CandleQuality]:
    """
    Analyze the last candle in a DataFrame.

    Args:
        df: DataFrame with OHLCV data.
        atr_value: ATR value for displacement detection.
        **kwargs: Passed to analyze_candle.

    Returns:
        CandleQuality or None if DataFrame is empty.
    """
    if df is None or len(df) == 0:
        return None

    last = df.iloc[-1]
    result = analyze_candle(
        open_price=float(last["open"]),
        high=float(last["high"]),
        low=float(last["low"]),
        close=float(last["close"]),
        atr_value=atr_value,
        **kwargs,
    )
    # Compute body_atr_ratio (analyze_candle doesn't — it only sets basic fields)
    if result and atr_value and atr_value > 0:
        body = abs(float(last["close"]) - float(last["open"]))
        result.body_atr_ratio = round(body / atr_value, 4)
    return result


def analyze_candle_at_index(
    df: pd.DataFrame,
    index: int,
    atr: Optional[float] = None,
    avg_volume: Optional[float] = None,
    event_type: Optional[Literal["sweep", "ob", "bos"]] = None,
) -> Optional[CandleQuality]:
    """
    Analyze a specific candle at a given index in a DataFrame.

    Args:
        df: DataFrame with OHLCV data.
        index: Candle index to analyze.
        atr: ATR value (from config or pre-calculated).
        avg_volume: Average volume (from config or pre-calculated).
        event_type: Event type for quality scoring.

    Returns:
        CandleQuality or None if index out of bounds.
    """
    if df is None or len(df) == 0 or index < 0 or index >= len(df):
        return None

    candle = df.iloc[index]
    open_price = float(candle["open"])
    high = float(candle["high"])
    low = float(candle["low"])
    close = float(candle["close"])
    volume = float(candle["volume"])

    if event_type is not None:
        if atr is None:
            atr = _calc_atr_from_df(df)
        if avg_volume is None:
            avg_volume = float(df["volume"].mean())
        return analyze_candle_quality(
            open_price=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
            atr=atr,
            avg_volume=avg_volume,
            event_type=event_type,
        )

    return analyze_candle(
        open_price=open_price,
        high=high,
        low=low,
        close=close,
        atr_value=atr,
    )


def _calc_atr_from_df(df: pd.DataFrame, period: int = 14) -> float:
    """Calculate average ATR over the DataFrame."""
    if len(df) < period + 1:
        return 0.0
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return float(tr.iloc[-period:].mean())
