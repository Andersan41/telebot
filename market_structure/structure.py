"""
market_structure/structure.py — Market Structure Engine V2.

Detects BOS (Break of Structure), CHoCH (Change of Character),
swing points (HH/HL/LH/LL), and multi-timeframe alignment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

import pandas as pd

from config.settings import config


@dataclass
class SwingPoint:
    price: float
    timestamp: datetime
    type: Literal["high", "low"]


@dataclass
class BOS:
    """Break of Structure."""
    type: Literal["bullish", "bearish"]
    level: float
    timestamp: datetime
    candle_index: int


@dataclass
class CHoCH:
    """Change of Character — first break of opposite structure."""
    type: Literal["bullish", "bearish"]
    level: float
    timestamp: datetime
    candle_index: int


@dataclass
class StructureState:
    trend: Literal["bullish", "bearish", "ranging"]
    last_bos: Optional[BOS] = None
    last_choch: Optional[CHoCH] = None
    swing_points: list[SwingPoint] = field(default_factory=list)
    structure_breaks: int = 0
    recent_highs: list[float] = field(default_factory=list)
    recent_lows: list[float] = field(default_factory=list)


def _find_swing_points(
    df: pd.DataFrame,
    lookback: int = 50,
    swing_window: int = 5,
) -> list[SwingPoint]:
    """Find swing highs and lows in OHLCV data."""
    swings: list[SwingPoint] = []
    data = df.tail(lookback)

    for i in range(swing_window, len(data) - swing_window):
        high_window = data["high"].iloc[i - swing_window : i + swing_window + 1]
        low_window = data["low"].iloc[i - swing_window : i + swing_window + 1]

        ts = data.index[i]
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=__import__("datetime", fromlist=["timezone"]).timezone.utc)

        if data["high"].iloc[i] == high_window.max():
            swings.append(
                SwingPoint(
                    price=float(data["high"].iloc[i]),
                    timestamp=ts,
                    type="high",
                )
            )
        if data["low"].iloc[i] == low_window.min():
            swings.append(
                SwingPoint(
                    price=float(data["low"].iloc[i]),
                    timestamp=ts,
                    type="low",
                )
            )

    return swings


def _detect_bos_choch(
    swings: list[SwingPoint],
) -> tuple[Optional[BOS], Optional[CHoCH], int]:
    """
    Detect BOS and CHoCH from swing points.

    Bullish BOS: close above previous swing high (we use swing high break)
    Bearish BOS: close below previous swing low
    Bullish CHoCH: first higher high after bearish structure
    Bearish CHoCH: first lower low after bullish structure
    """
    if len(swings) < 4:
        return None, None, 0

    highs = [s for s in swings if s.type == "high"]
    lows = [s for s in swings if s.type == "low"]

    last_bos: Optional[BOS] = None
    last_choch: Optional[CHoCH] = None
    structure_breaks = 0

    if len(highs) >= 2 and len(lows) >= 2:
        last_high = highs[-1]
        prev_high = highs[-2]
        last_low = lows[-1]
        prev_low = lows[-2]

        bullish_structure = prev_high.price > prev_low.price

        if last_high.price > prev_high.price:
            if not bullish_structure:
                last_choch = CHoCH(
                    type="bullish",
                    level=last_high.price,
                    timestamp=last_high.timestamp,
                    candle_index=-1,
                )
                structure_breaks += 1
            else:
                last_bos = BOS(
                    type="bullish",
                    level=last_high.price,
                    timestamp=last_high.timestamp,
                    candle_index=-1,
                )
                structure_breaks += 1

        if last_low.price < prev_low.price:
            if bullish_structure:
                last_choch = CHoCH(
                    type="bearish",
                    level=last_low.price,
                    timestamp=last_low.timestamp,
                    candle_index=-1,
                )
                structure_breaks += 1
            else:
                last_bos = BOS(
                    type="bearish",
                    level=last_low.price,
                    timestamp=last_low.timestamp,
                    candle_index=-1,
                )
                structure_breaks += 1

    return last_bos, last_choch, structure_breaks


def _classify_trend(
    swings: list[SwingPoint],
    last_bos: Optional[BOS],
    last_choch: Optional[CHoCH],
) -> Literal["bullish", "bearish", "ranging"]:
    """Classify overall trend based on structure."""
    if last_choch is not None:
        return "bullish" if last_choch.type == "bullish" else "bearish"
    if last_bos is not None:
        return "bullish" if last_bos.type == "bullish" else "bearish"

    highs = [s.price for s in swings if s.type == "high"]
    lows = [s.price for s in swings if s.type == "low"]

    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
            return "bullish"
        if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
            return "bearish"

    return "ranging"


def analyze_structure(
    df: pd.DataFrame,
    lookback: int = 50,
    swing_window: int = 5,
) -> StructureState:
    """
    Analyze market structure from OHLCV data.

    Args:
        df: DataFrame with OHLCV data (index should be datetime-like).
        lookback: number of recent candles to analyze.
        swing_window: window size for swing point detection.

    Returns:
        StructureState with trend, BOS, CHoCH, swing points.
    """
    swings = _find_swing_points(df, lookback=lookback, swing_window=swing_window)
    last_bos, last_choch, breaks = _detect_bos_choch(swings)
    trend = _classify_trend(swings, last_bos, last_choch)

    highs = [s.price for s in swings if s.type == "high"]
    lows = [s.price for s in swings if s.type == "low"]

    return StructureState(
        trend=trend,
        last_bos=last_bos,
        last_choch=last_choch,
        swing_points=swings,
        structure_breaks=breaks,
        recent_highs=highs[-5:] if len(highs) >= 5 else highs,
        recent_lows=lows[-5:] if len(lows) >= 5 else lows,
    )


def _parse_timeframe_to_seconds(tf: str) -> int:
    """Convert timeframe string to seconds."""
    tf = tf.lower().strip()
    if tf.endswith("m"):
        return int(tf[:-1]) * 60
    if tf.endswith("h"):
        return int(tf[:-1]) * 3600
    if tf.endswith("d"):
        return int(tf[:-1]) * 86400
    if tf.endswith("w"):
        return int(tf[:-1]) * 604800
    return 3600


@dataclass
class MTFAlignmentResult:
    alignment_state: Literal["bullish_aligned", "bearish_aligned", "mixed", "ranging"]
    aligned: bool
    states: dict[str, StructureState]


async def check_mtf_alignment(
    symbol: str,
    direction: Literal["bullish", "bearish"],
    primary_tf: str,
    exchange_client,
    required_alignment: int | None = None,
    timeframes: list[str] | None = None,
) -> MTFAlignmentResult:
    """
    Check multi-timeframe structure alignment.

    Signal direction must align with at least `required_alignment` higher timeframes.
    Range is NOT counted as aligned — it produces "mixed" or "ranging" state.

    Args:
        symbol: Trading pair symbol.
        direction: Signal direction ("bullish" for LONG, "bearish" for SHORT).
        primary_tf: Primary signal timeframe.
        exchange_client: Exchange client for fetching OHLCV data.
        required_alignment: Minimum number of aligned HTFs (from config if None).
        timeframes: List of HTFs to check (from config if None).

    Returns:
        MTFAlignmentResult with alignment_state, aligned flag, and states dict.
    """
    if required_alignment is None:
        required_alignment = getattr(config, "mtf_required_alignment", 2)
    if timeframes is None:
        raw = getattr(config, "mtf_timeframes", "1d,4h,1h")
        timeframes = [tf.strip() for tf in raw.split(",")]

    primary_seconds = _parse_timeframe_to_seconds(primary_tf)
    higher_tfs = [
        tf for tf in timeframes
        if _parse_timeframe_to_seconds(tf) > primary_seconds
    ]

    if not higher_tfs:
        return MTFAlignmentResult(alignment_state="bullish_aligned", aligned=True, states={})

    states: dict[str, StructureState] = {}
    aligned_count = 0
    bullish_count = 0
    bearish_count = 0
    ranging_count = 0

    for tf in higher_tfs:
        try:
            df = await exchange_client.fetch_ohlcv(symbol, tf, limit=100)
            if df is None or len(df) < 20:
                continue
            state = analyze_structure(df, lookback=50)
            states[tf] = state

            if state.trend == "bullish":
                bullish_count += 1
                if direction == "bullish":
                    aligned_count += 1
            elif state.trend == "bearish":
                bearish_count += 1
                if direction == "bearish":
                    aligned_count += 1
            else:
                ranging_count += 1
        except Exception:
            continue

    total = bullish_count + bearish_count + ranging_count
    if total == 0:
        alignment_state = "bullish_aligned"
    elif ranging_count == total:
        alignment_state = "ranging"
    elif bullish_count == total:
        alignment_state = "bullish_aligned"
    elif bearish_count == total:
        alignment_state = "bearish_aligned"
    else:
        alignment_state = "mixed"

    return MTFAlignmentResult(
        alignment_state=alignment_state,
        aligned=aligned_count >= required_alignment,
        states=states,
    )
