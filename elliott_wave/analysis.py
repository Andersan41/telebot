"""
elliott_wave/analysis.py — Core Elliott Wave analysis engine.

Implements the wave detection algorithm from wave.md:
1. ATR-filtered zigzag pivot detection
2. Impulse validation (1-2-3-4-5 rules)
3. Correction validation (A-B-C zigzag rules)
4. Confidence scoring
5. Alternative count generation

Soft feature only — never blocks signals.
"""
from __future__ import annotations

from typing import List, Optional, Tuple
from loguru import logger
import pandas as pd
import numpy as np

from elliott_wave.wave_types import (
    WavePoint, WaveSegment, WaveCount, WaveAnalysis,
    WaveDirection, WaveDegree,
)
from market_structure.swing_detector import detect_swings, SwingType, filter_significant_swings
from config.settings import config


def analyze_waves(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    degree: WaveDegree = WaveDegree.MINOR,
    max_lookback: Optional[int] = None,
) -> WaveAnalysis:
    """
    Run Elliott Wave analysis on OHLCV data.

    Args:
        df: OHLCV DataFrame (already filtered by caller).
        symbol: Trading pair (e.g. "BTC/USDT").
        timeframe: Timeframe (e.g. "1h", "4h").
        degree: Wave degree to analyze.
        max_lookback: Max candles to analyze (from config if None).

    Returns:
        WaveAnalysis with primary count, alternatives, confidence, direction.
    """
    if not config.wave.enabled:
        return WaveAnalysis(symbol=symbol, timeframe=timeframe)

    if max_lookback is None:
        max_lookback = config.wave.max_lookback

    # Trim to lookback
    data = df.tail(max_lookback).copy()
    if len(data) < 20:
        return WaveAnalysis(symbol=symbol, timeframe=timeframe)

    # Step 1: Detect ATR-filtered pivots
    pivots = _detect_wave_pivots(data)
    if len(pivots) < 5:
        return WaveAnalysis(symbol=symbol, timeframe=timeframe)

    # Step 2: Try impulse count (1-2-3-4-5)
    impulse_count = _try_impulse(data, pivots, degree)

    # Step 3: Try correction count (A-B-C)
    correction_count = _try_correction(data, pivots, degree)

    # Step 4: Pick primary count (higher confidence)
    primary: Optional[WaveCount] = None
    alternatives: List[WaveCount] = []

    if impulse_count and correction_count:
        if impulse_count.confidence >= correction_count.confidence:
            primary = impulse_count
            alternatives.append(correction_count)
        else:
            primary = correction_count
            alternatives.append(impulse_count)
    elif impulse_count:
        primary = impulse_count
    elif correction_count:
        primary = correction_count

    # Generate additional alternatives from sub-variations
    if primary:
        extras = _generate_alternatives(data, pivots, primary, degree)
        alternatives.extend(extras)
        alternatives = sorted(alternatives, key=lambda c: c.confidence, reverse=True)
        alternatives = alternatives[:config.wave.max_alternatives]

    # Determine direction and conflict
    direction = primary.direction if primary else None
    conflict = False
    if alternatives:
        alt_dirs = {a.direction for a in alternatives}
        if direction and len(alt_dirs) > 1:
            conflict = True

    confidence = primary.confidence if primary else 0.0

    return WaveAnalysis(
        symbol=symbol,
        timeframe=timeframe,
        primary=primary,
        alternatives=alternatives,
        direction=direction,
        confidence=confidence,
        conflict=conflict,
    )


# ── Pivot Detection ──────────────────────────────────────────────────────

def _detect_wave_pivots(df: pd.DataFrame) -> List[WavePoint]:
    """
    Detect wave pivots using ATR-filtered swing points.

    Uses the unified swing_detector with rolling window mode (left=2, right=2)
    then filters by ATR multiple.
    """
    swings = detect_swings(df, left_bars=2, right_bars=2, strict=False)
    if not swings:
        return []

    # Filter by ATR
    has_atr = "atr" in df.columns
    pivots: List[WavePoint] = []

    for sw in swings:
        if sw.index >= len(df):
            continue

        # Skip tiny moves
        if has_atr:
            atr_val = df["atr"].iloc[sw.index]
            if pd.notna(atr_val) and atr_val > 0:
                # Need minimum amplitude from previous pivot
                if pivots:
                    amp = abs(sw.price - pivots[-1].price)
                    if amp < atr_val * config.wave.min_swing_atr:
                        continue

        label = "H" if sw.swing_type == SwingType.HIGH else "L"
        pivots.append(WavePoint(
            index=sw.index,
            price=sw.price,
            wave_label=label,
            timestamp=sw.timestamp,
        ))

    return pivots


# ── Impulse Validation ───────────────────────────────────────────────────

def _try_impulse(
    df: pd.DataFrame,
    pivots: List[WavePoint],
    degree: WaveDegree,
) -> Optional[WaveCount]:
    """
    Try to label pivots as a 5-wave impulse (1-2-3-4-5).

    Rules:
    - Wave 3 can't be the shortest (rules 2 & 3)
    - Wave 4 can't overlap wave 1 territory (rule 4)
    - Alternation: waves 2 and 4 should differ in structure
    """
    if len(pivots) < 6:
        return None

    best_count: Optional[WaveCount] = None
    best_score = 0.0

    # Try different starting points and window sizes
    for start_idx in range(0, min(3, len(pivots) - 5)):
        for end_idx in range(start_idx + 5, min(start_idx + 11, len(pivots) + 1)):
            window = pivots[start_idx:end_idx]
            if len(window) < 6:
                continue

            # Take every other pivot as wave point (alternating H/L)
            # For impulse: 0(H)→1(L)→2(H)→3(L)→4(H)→5(L) for bullish
            # or 0(L)→1(H)→2(L)→3(H)→4(L)→5(H) for bearish
            wave_points = window[:6]
            score = _score_impulse(wave_points)

            if score > best_score:
                best_score = score
                # Label the points
                labels = ["0", "1", "2", "3", "4", "5"]
                labeled_points = [
                    WavePoint(
                        index=wp.index,
                        price=wp.price,
                        wave_label=labels[i],
                        timestamp=wp.timestamp,
                    )
                    for i, wp in enumerate(wave_points)
                ]

                # Determine direction
                is_bullish = wave_points[-1].price > wave_points[0].price
                direction = WaveDirection.IMPULSE
                segments = [
                    WaveSegment(
                        start=labeled_points[i],
                        end=labeled_points[i + 1],
                        label=str(i + 1),
                        degree=degree,
                        direction=direction,
                    )
                    for i in range(5)
                ]

                best_count = WaveCount(
                    points=labeled_points,
                    segments=segments,
                    direction=direction,
                    degree=degree,
                    confidence=score,
                    is_primary=True,
                    label="impulse (1-2-3-4-5)",
                )

    return best_count


def _score_impulse(points: List[WavePoint]) -> float:
    """Score an impulse count [0.0, 1.0]."""
    if len(points) < 6:
        return 0.0

    scores = []

    # Rule 2+3: Wave 3 can't be the shortest
    w1_len = abs(points[1].price - points[0].price)
    w3_len = abs(points[3].price - points[2].price)
    w5_len = abs(points[5].price - points[4].price)

    if w3_len > 0 and w3_len >= max(w1_len, w5_len):
        scores.append(0.3)  # valid
    else:
        scores.append(0.0)  # violated

    # Rule 4: Wave 4 can't overlap wave 1
    is_bullish = points[5].price > points[0].price
    if is_bullish:
        w4_valid = points[4].price > points[1].price  # w4 low > w1 high
    else:
        w4_valid = points[4].price < points[1].price  # w4 high < w1 low

    scores.append(0.25 if w4_valid else 0.0)

    # Alternation: waves 2 and 4 should be different types
    # (Approximated by checking if both are "sharp" or both "flat")
    w2_depth = abs(points[2].price - points[1].price) / max(w1_len, 1e-10)
    w4_depth = abs(points[4].price - points[3].price) / max(w3_len, 1e-10)

    # Good alternation: one shallow, one deep
    alt_diff = abs(w2_depth - w4_depth)
    scores.append(min(0.2, alt_diff * 0.5))

    # Fibonacci: wave 3 should be 1.618× of wave 1 (common but not required)
    if w1_len > 0:
        ratio = w3_len / w1_len
        fib_score = max(0, 0.25 - abs(ratio - 1.618) * 0.1)
        scores.append(fib_score)
    else:
        scores.append(0.0)

    return min(1.0, sum(scores))


# ── Correction Validation ────────────────────────────────────────────────

def _try_correction(
    df: pd.DataFrame,
    pivots: List[WavePoint],
    degree: WaveDegree,
) -> Optional[WaveCount]:
    """
    Try to label pivots as an A-B-C correction (zigzag).

    Rules:
    - Wave B can't retrace more than 100% of wave A
    - Wave C must go beyond wave A end
    - Typical B retracement: 50-78.6% of A
    """
    if len(pivots) < 4:
        return None

    best_count: Optional[WaveCount] = None
    best_score = 0.0

    for start_idx in range(0, min(3, len(pivots) - 3)):
        for end_idx in range(start_idx + 3, min(start_idx + 7, len(pivots) + 1)):
            window = pivots[start_idx:end_idx]
            if len(window) < 4:
                continue

            # For A-B-C: take first 4 pivots as 0→A→B→C
            wave_points = window[:4]
            score = _score_correction(wave_points)

            if score > best_score:
                best_score = score
                labels = ["0", "A", "B", "C"]
                labeled_points = [
                    WavePoint(
                        index=wp.index,
                        price=wp.price,
                        wave_label=labels[i],
                        timestamp=wp.timestamp,
                    )
                    for i, wp in enumerate(wave_points)
                ]

                is_bullish = wave_points[-1].price > wave_points[0].price
                direction = WaveDirection.CORRECTION
                segments = [
                    WaveSegment(
                        start=labeled_points[i],
                        end=labeled_points[i + 1],
                        label=labels[i + 1],
                        degree=degree,
                        direction=direction,
                    )
                    for i in range(3)
                ]

                best_count = WaveCount(
                    points=labeled_points,
                    segments=segments,
                    direction=direction,
                    degree=degree,
                    confidence=score,
                    is_primary=True,
                    label="correction (A-B-C)",
                )

    return best_count


def _score_correction(points: List[WavePoint]) -> float:
    """Score an A-B-C correction count [0.0, 1.0]."""
    if len(points) < 4:
        return 0.0

    scores = []
    a_move = abs(points[1].price - points[0].price)
    b_move = abs(points[2].price - points[1].price)
    c_move = abs(points[3].price - points[2].price)

    # Rule: B can't retrace more than 100% of A
    if a_move > 0:
        b_retrace = b_move / a_move
        if b_retrace <= 1.0:
            scores.append(0.3)
            # Typical 50-78.6% retracement
            if 0.382 <= b_retrace <= 0.786:
                scores.append(0.15)
            else:
                scores.append(0.05)
        else:
            scores.append(0.0)
    else:
        scores.append(0.0)

    # Rule: C must go beyond A end
    is_bullish = points[3].price > points[0].price
    if is_bullish:
        c_beyond = points[3].price > points[1].price
    else:
        c_beyond = points[3].price < points[1].price

    scores.append(0.25 if c_beyond else 0.0)

    # C should be roughly equal to A (common guideline)
    if a_move > 0:
        c_ratio = c_move / a_move
        fib_score = max(0, 0.2 - abs(c_ratio - 1.0) * 0.15)
        scores.append(fib_score)
    else:
        scores.append(0.0)

    return min(1.0, sum(scores))


# ── Alternatives ─────────────────────────────────────────────────────────

def _generate_alternatives(
    df: pd.DataFrame,
    pivots: List[WavePoint],
    primary: WaveCount,
    degree: WaveDegree,
) -> List[WaveCount]:
    """Generate alternative wave counts by trying different pivot selections."""
    alternatives: List[WaveCount] = []

    # Try using different pivot windows
    for offset in [-1, 1]:
        shifted = pivots[max(0, offset):] if offset > 0 else pivots[:offset]
        if len(shifted) < 4:
            continue

        imp = _try_impulse(df, shifted, degree)
        corr = _try_correction(df, shifted, degree)

        if imp and imp.confidence > 0.3:
            imp = WaveCount(
                points=imp.points,
                segments=imp.segments,
                direction=imp.direction,
                degree=imp.degree,
                confidence=imp.confidence * 0.85,  # discount alternatives
                is_primary=False,
                label=imp.label,
            )
            alternatives.append(imp)

        if corr and corr.confidence > 0.3:
            corr = WaveCount(
                points=corr.points,
                segments=corr.segments,
                direction=corr.direction,
                degree=corr.degree,
                confidence=corr.confidence * 0.85,
                is_primary=False,
                label=corr.label,
            )
            alternatives.append(corr)

    return alternatives
