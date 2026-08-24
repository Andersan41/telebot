"""
liquidity/sweep.py — Liquidity Sweep Engine.

Detects stop hunts, liquidity grabs, and wick-based sweeps.

Bullish sweep:
1. Low swept below previous swing low
2. Fast reclaim (within N candles)
3. High volume rejection candle

Bearish sweep:
1. High swept above previous swing high
2. Fast rejection
3. Close back below range

Strength scoring:
- Fast reclaim (< 3 candles): +0.3
- High volume (ratio > 1.5): +0.3
- Delta aligned: +0.2
- Displacement after sweep: +0.2
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

import pandas as pd

from config.settings import config


@dataclass
class SweepEvent:
    type: Literal["bullish", "bearish"]
    swept_level: float
    sweep_low: float
    sweep_high: float
    reclaim_candles: int
    volume_ratio: float
    timestamp: datetime
    wick_body_ratio: float = 0.0
    displacement_after: float = 0.0
    delta_aligned: bool = False
    candle_index: int = 0
    pool_age_bars: int = 0  # age of the pool at sweep time (for false filter)
    atr: float = 0.0  # ATR at sweep time (for false filter)

    @property
    def is_valid(self) -> bool:
        """Sweep validity: TZ §5.2 volume is OPTIONAL (enhancement, not required)."""
        max_reclaim = getattr(config, "liquidity_sweep_max_reclaim_candles", 3)
        return self.reclaim_candles <= max_reclaim

    def passes_false_sweep_filters(
        self,
        atr: float = 0.0,
        pool_age_bars: int = 0,
    ) -> tuple[bool, str]:
        """Check false sweep filters per TZ §5.3.

        Args:
            atr: current ATR value for body-beyond-level check
            pool_age_bars: age of the pool in bars

        Returns:
            (passes, reason) — True if sweep is NOT a false positive
        """
        from config.settings import config as _cfg
        liq = _cfg.liquidity

        # max_body_beyond_level: % of ATR
        if atr > 0:
            max_body = atr * liq.sweep_max_body_beyond_level
            body_size = abs(self.sweep_high - self.sweep_low)
            wick_beyond = max(0, self.sweep_high - self.swept_level) if self.type == "bearish" else max(0, self.swept_level - self.sweep_low)
            if wick_beyond > max_body:
                return False, f"body beyond level {wick_beyond:.4f} > {max_body:.4f}"

        # min_wick_beyond_level: % of price
        if self.swept_level > 0:
            wick_pct = 0.0
            if self.type == "bearish":
                wick_pct = max(0, self.sweep_high - self.swept_level) / self.swept_level * 100
            else:
                wick_pct = max(0, self.swept_level - self.sweep_low) / self.swept_level * 100
            if wick_pct < liq.sweep_min_wick_beyond_level:
                return False, f"wick beyond too small {wick_pct:.3f}% < {liq.sweep_min_wick_beyond_level}%"

        # min_body_size: % of price
        if self.swept_level > 0:
            body_pct = abs(
                float(self.sweep_high) - float(self.sweep_low)
            ) / self.swept_level * 100
            if body_pct < liq.sweep_min_body_size:
                return False, f"body too small {body_pct:.3f}% < {liq.sweep_min_body_size}%"

        # max_pool_age_bars
        if pool_age_bars > liq.sweep_max_pool_age_bars:
            return False, f"pool too old {pool_age_bars} > {liq.sweep_max_pool_age_bars}"

        return True, ""

    @property
    def strength(self) -> float:
        """Calculate sweep strength score [0.0, 1.0]."""
        score = 0.0
        fast_reclaim = getattr(config, "liquidity_sweep_fast_reclaim_candles", 3)
        high_vol = getattr(config, "liquidity_sweep_min_volume_ratio", 1.5)
        min_wick_body = getattr(config, "liquidity_sweep_min_wick_body_ratio", 2.0)

        if self.reclaim_candles <= fast_reclaim:
            score += 0.3
        if self.volume_ratio > high_vol:
            score += 0.3
        if self.delta_aligned:
            score += 0.2
        if self.displacement_after > 0:
            score += 0.2

        return min(score, 1.0)


def detect_sweeps(
    df: pd.DataFrame,
    lookback: int = 50,
    swing_window: int = 2,
) -> list[SweepEvent]:
    """
    Detect liquidity sweeps in OHLCV data.

    Args:
        df: DataFrame with OHLCV data.
        lookback: number of recent candles to analyze.
        swing_window: window size for swing point detection.

    Returns:
        List of SweepEvent objects.
    """
    data = df.tail(lookback).reset_index(drop=True)
    if len(data) < swing_window * 2 + 2:
        return []

    # Compute offset so candle_index is absolute in the original df
    offset = len(df) - len(data)

    sweeps: list[SweepEvent] = []

    swing_highs = _find_swing_highs(data, swing_window)
    swing_lows = _find_swing_lows(data, swing_window)

    # TZ §5.2: 1-candle sweep detection
    # Bearish: High[current] > Pool_Level AND Close[current] < Pool_Level
    # Bullish: Low[current] < Pool_Level AND Close[current] > Pool_Level
    for i in range(len(data)):
        current = data.iloc[i]

        ts = _to_datetime(data.index[i])

        for swing_high in swing_highs:
            if swing_high["index"] >= i:
                continue
            if current["high"] > swing_high["price"] and current["close"] < swing_high["price"]:
                volume_ratio = _calc_volume_ratio(data, i)
                reclaim = _count_candles_to_reclaim_bearish(data, i, swing_high["price"])
                wick_body = _calc_wick_body_ratio(data, i)
                displacement = _calc_displacement_after_sweep(data, i, "bearish")
                delta_aligned = _check_delta_aligned(data, i, "bearish")

                sweeps.append(SweepEvent(
                    type="bearish",
                    swept_level=swing_high["price"],
                    sweep_low=float(current["low"]),
                    sweep_high=float(current["high"]),
                    reclaim_candles=reclaim,
                    volume_ratio=volume_ratio,
                    timestamp=ts,
                    wick_body_ratio=wick_body,
                    displacement_after=displacement,
                    delta_aligned=delta_aligned,
                    candle_index=offset + i,
                ))

        for swing_low in swing_lows:
            if swing_low["index"] >= i:
                continue
            if current["low"] < swing_low["price"] and current["close"] > swing_low["price"]:
                volume_ratio = _calc_volume_ratio(data, i)
                reclaim = _count_candles_to_reclaim_bullish(data, i, swing_low["price"])
                wick_body = _calc_wick_body_ratio(data, i)
                displacement = _calc_displacement_after_sweep(data, i, "bullish")
                delta_aligned = _check_delta_aligned(data, i, "bullish")

                sweeps.append(SweepEvent(
                    type="bullish",
                    swept_level=swing_low["price"],
                    sweep_low=float(current["low"]),
                    sweep_high=float(current["high"]),
                    reclaim_candles=reclaim,
                    volume_ratio=volume_ratio,
                    timestamp=ts,
                    wick_body_ratio=wick_body,
                    displacement_after=displacement,
                    delta_aligned=delta_aligned,
                    candle_index=offset + i,
                ))

    return sweeps


def _find_swing_highs(df: pd.DataFrame, window: int) -> list[dict]:
    """Find swing highs using TZ §4.1 strict 2-neighbor formula.

    High[i] is swing high iff:
      High[i-2] < High[i] AND High[i-1] < High[i] AND
      High[i+1] < High[i] AND High[i+2] < High[i]
    """
    highs = []
    for i in range(window, len(df) - window):
        h = df["high"].iloc[i]
        if (df["high"].iloc[i - 2] < h and
            df["high"].iloc[i - 1] < h and
            df["high"].iloc[i + 1] < h and
            df["high"].iloc[i + 2] < h):
            highs.append({"index": i, "price": float(h)})
    return highs


def _find_swing_lows(df: pd.DataFrame, window: int) -> list[dict]:
    """Find swing lows using TZ §4.1 strict 2-neighbor formula.

    Low[i] is swing low iff:
      Low[i-2] > Low[i] AND Low[i-1] > Low[i] AND
      Low[i+1] > Low[i] AND Low[i+2] > Low[i]
    """
    lows = []
    for i in range(window, len(df) - window):
        l = df["low"].iloc[i]
        if (df["low"].iloc[i - 2] > l and
            df["low"].iloc[i - 1] > l and
            df["low"].iloc[i + 1] > l and
            df["low"].iloc[i + 2] > l):
            lows.append({"index": i, "price": float(l)})
    return lows


def _calc_volume_ratio(df: pd.DataFrame, index: int) -> float:
    """Calculate volume ratio vs recent average."""
    vol_window = config.trading.volume_sma_period
    start = max(0, index - vol_window + 1)
    recent_vol = df["volume"].iloc[start:index + 1]
    avg_vol = recent_vol.mean()
    if avg_vol == 0:
        return 1.0
    return float(df["volume"].iloc[index] / avg_vol)


def _count_candles_to_reclaim_bullish(df: pd.DataFrame, sweep_index: int, level: float, max_check: int = 10) -> int:
    """Count candles until price reclaims above level after a bullish sweep."""
    for j in range(sweep_index + 1, min(sweep_index + max_check + 1, len(df))):
        if df["close"].iloc[j] > level:
            return j - sweep_index
    return max_check


def _count_candles_to_reclaim_bearish(df: pd.DataFrame, sweep_index: int, level: float, max_check: int = 10) -> int:
    """Count candles until price reclaims below level after a bearish sweep."""
    for j in range(sweep_index + 1, min(sweep_index + max_check + 1, len(df))):
        if df["close"].iloc[j] < level:
            return j - sweep_index
    return max_check


def _calc_wick_body_ratio(df: pd.DataFrame, index: int) -> float:
    """Calculate wick-to-body ratio for a candle."""
    candle = df.iloc[index]
    body = abs(float(candle["close"]) - float(candle["open"]))
    range_val = float(candle["high"]) - float(candle["low"])
    if body == 0:
        return float("inf") if range_val > 0 else 0.0
    wick = range_val - body
    return wick / body


def _calc_displacement_after_sweep(df: pd.DataFrame, sweep_index: int, sweep_type: str, max_check: int = 5) -> float:
    """Calculate displacement % after sweep."""
    start_close = float(df["close"].iloc[sweep_index])
    max_move = 0.0
    for j in range(sweep_index + 1, min(sweep_index + max_check + 1, len(df))):
        close = float(df["close"].iloc[j])
        if sweep_type == "bullish":
            move = (close - start_close) / start_close * 100
        else:
            move = (start_close - close) / start_close * 100
        if move > max_move:
            max_move = move
    return round(max_move, 3)


def _check_delta_aligned(df: pd.DataFrame, sweep_index: int, sweep_type: str) -> bool:
    """Check if volume delta confirms sweep direction (heuristic: close position)."""
    if sweep_index + 1 >= len(df):
        return False
    next_candle = df.iloc[sweep_index + 1]
    body = float(next_candle["close"]) - float(next_candle["open"])
    range_val = float(next_candle["high"]) - float(next_candle["low"])
    if range_val == 0:
        return False
    close_position = body / range_val
    if sweep_type == "bullish":
        return close_position > 0.5
    else:
        return close_position < -0.5


def _to_datetime(idx) -> datetime:
    """Convert index value to datetime."""
    if isinstance(idx, (int, float)):
        from datetime import timezone as _tz
        return datetime.fromtimestamp(idx, tz=_tz.utc)
    if hasattr(idx, "to_pydatetime"):
        ts = idx.to_pydatetime()
    else:
        ts = idx
    if isinstance(ts, datetime) and ts.tzinfo is None:
        ts = ts.replace(tzinfo=__import__("datetime", fromlist=["timezone"]).timezone.utc)
    return ts
