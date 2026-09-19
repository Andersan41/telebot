"""
market_structure/htf_bias_v2.py — HTF Bias V2 with Multi-Timeframe Alignment.

Direction from D1 + H4 majority vote (fast enough to react to trend changes).
W1 is informational only — too slow, stays bullish/bearish for months.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd


class BiasStrength(Enum):
    STRONG = 'strong'
    MODERATE = 'moderate'
    WEAK = 'weak'
    NEUTRAL = 'neutral'


@dataclass
class HTFBiasResult:
    direction: str  # 'bullish', 'bearish', 'neutral'
    strength: BiasStrength
    weekly_bias: str
    daily_bias: str
    h4_bias: str
    h1_bias: str
    override_reason: Optional[str] = None
    # A06: EMA-spread confidence (informational, NOT statistical confidence)
    # Derived from |EMA21-EMA55|/price*100*10, range [0, 100]
    confidence: float = 0.0


def detect_last_bos(df: pd.DataFrame) -> Optional[dict]:
    """Detect last BOS direction from DataFrame using structure analysis."""
    if df is None or len(df) < 20:
        return None
    try:
        from market_structure.structure import analyze_structure
        struct = analyze_structure(df, lookback=min(50, len(df)))
        if struct and struct.last_bos:
            return {
                'direction': struct.last_bos.type,
                'level': struct.last_bos.level,
                'candle_index': struct.last_bos.candle_index,
            }
    except Exception:
        pass
    return None


def get_tf_bias(df: pd.DataFrame, use_structure: bool = True) -> tuple[str, float]:
    """
    Определяет bias для одного таймфрейма.
    Returns: (direction, confidence)
    """
    if df is None or len(df) < 55:
        return 'neutral', 0.0

    ema21 = df['close'].ewm(span=21).mean().iloc[-1]
    ema55 = df['close'].ewm(span=55).mean().iloc[-1]
    price = df['close'].iloc[-1]

    # EMA alignment
    if price > ema21 > ema55:
        direction = 'bullish'
    elif price < ema21 < ema55:
        direction = 'bearish'
    else:
        direction = 'neutral'

    # Confidence based on EMA spread
    spread = abs(ema21 - ema55) / price * 100
    confidence = min(spread * 10, 100)

    # Structure boost (если доступен)
    if use_structure and direction != 'neutral':
        last_bos = detect_last_bos(df)
        if last_bos and last_bos['direction'] == direction:
            confidence = min(confidence * 1.2, 100)

    return direction, confidence


def get_htf_bias_v2(
    df_1w: Optional[pd.DataFrame],
    df_1d: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_1h: Optional[pd.DataFrame],
) -> HTFBiasResult:
    """
    Direction from D1 + H4 majority vote. W1 is informational only.

    Voting:
      - D1 + H4 both bullish → bullish (STRONG)
      - D1 + H4 both bearish → bearish (STRONG)
      - D1 or H4 has direction, other neutral → WEAK
      - Both neutral → neutral
    """
    w1_bias, w1_conf = get_tf_bias(df_1w, use_structure=True) if df_1w is not None else ('neutral', 0)
    d1_bias, d1_conf = get_tf_bias(df_1d, use_structure=True)
    h4_bias, h4_conf = get_tf_bias(df_4h, use_structure=True)
    h1_bias, h1_conf = get_tf_bias(df_1h, use_structure=False) if df_1h is not None else ('neutral', 0)

    # Majority voting on D1 + H4 only (W1 too slow — ignored for direction)
    if d1_bias == h4_bias and d1_bias != 'neutral':
        direction = d1_bias
        strength = BiasStrength.STRONG
    elif d1_bias != 'neutral' and h4_bias == 'neutral':
        direction = d1_bias
        strength = BiasStrength.WEAK
    elif h4_bias != 'neutral' and d1_bias == 'neutral':
        direction = h4_bias
        strength = BiasStrength.WEAK
    else:
        direction = 'neutral'
        strength = BiasStrength.NEUTRAL

    # Override: D1 and H4 disagree — use the one aligned with W1
    override_reason = None
    if d1_bias != h4_bias and d1_bias != 'neutral' and h4_bias != 'neutral':
        if w1_bias == d1_bias:
            direction = d1_bias
            strength = BiasStrength.MODERATE
            override_reason = f"d1_{d1_bias}_wins_over_h4_{h4_bias}_w1_aligned"
        elif w1_bias == h4_bias:
            direction = h4_bias
            strength = BiasStrength.MODERATE
            override_reason = f"h4_{h4_bias}_wins_over_d1_{d1_bias}_w1_aligned"
        else:
            # No W1 alignment — H4 is more recent, give it priority
            direction = h4_bias
            strength = BiasStrength.WEAK
            override_reason = f"h4_{h4_bias}_wins_over_d1_{d1_bias}_no_w1_alignment"

    # Confidence from D1 + H4 only
    avg_conf = (d1_conf + h4_conf) / 2.0

    return HTFBiasResult(
        direction=direction,
        strength=strength,
        weekly_bias=w1_bias,
        daily_bias=d1_bias,
        h4_bias=h4_bias,
        h1_bias=h1_bias,
        override_reason=override_reason,
        confidence=round(avg_conf, 1),
    )
