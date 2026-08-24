"""
liquidity/fvg.py — Fair Value Gap (Imbalance) Detection.

Bullish FVG: Low of candle 3 > High of candle 1 (gap between candles 1 and 3).
Bearish FVG: High of candle 3 < Low of candle 1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

import pandas as pd

from config.settings import config


@dataclass
class FairValueGap:
    type: Literal["bullish", "bearish"]
    top: float
    bottom: float
    timestamp: datetime
    filled: bool = False
    index: int = 0  # позиция свечи в DataFrame (для проверки закрытия)

    @property
    def size_pct(self) -> float:
        if self.bottom == 0:
            return 0.0
        return abs(self.top - self.bottom) / self.bottom * 100

    @property
    def is_active(self) -> bool:
        return not self.filled


def detect_fvg(
    df: pd.DataFrame,
    lookback: int = 100,
    min_size_pct: Optional[float] = None,
) -> list[FairValueGap]:
    """
    Detect Fair Value Gaps in OHLCV data.

    TZ §6.1: FVG requires candle color checks:
    - Bullish: candle1 bullish (C>O), candle3 bullish (C>O), Low[candle3] > High[candle1]
    - Bearish: candle1 bearish (C<O), candle3 bearish (C<O), High[candle3] < Low[candle1]

    Args:
        df: DataFrame with OHLCV data.
        lookback: number of recent candles to analyze.
        min_size_pct: minimum gap size % to include (default 0.05% per TZ §6.1.4).

    Returns:
        List of FairValueGap objects.
    """
    if min_size_pct is None:
        min_size_pct = getattr(config, "liquidity_fvg_min_size_pct", 0.05)

    data = df.tail(lookback).reset_index(drop=True)
    if len(data) < 3:
        return []

    fvgs: list[FairValueGap] = []

    for i in range(1, len(data) - 1):
        candle1 = data.iloc[i - 1]
        candle2 = data.iloc[i]
        candle3 = data.iloc[i + 1]

        high1 = float(candle1["high"])
        low1 = float(candle1["low"])
        close1 = float(candle1["close"])
        open1 = float(candle1["open"])
        high3 = float(candle3["high"])
        low3 = float(candle3["low"])
        close3 = float(candle3["close"])
        open3 = float(candle3["open"])

        # TZ §6.1.2: Bullish FVG — candle1 bullish, candle3 bullish, gap up
        if close1 > open1 and close3 > open3 and low3 > high1:
            gap_size_pct = (low3 - high1) / high1 * 100
            if gap_size_pct >= min_size_pct:
                ts = _to_datetime(data.index[i])
                fvgs.append(FairValueGap(
                    type="bullish",
                    top=low3,
                    bottom=high1,
                    timestamp=ts,
                    index=i + 1,
                ))

        # TZ §6.1.3: Bearish FVG — candle1 bearish, candle3 bearish, gap down
        if close1 < open1 and close3 < open3 and high3 < low1:
            gap_size_pct = (low1 - high3) / high3 * 100
            if gap_size_pct >= min_size_pct:
                ts = _to_datetime(data.index[i])
                fvgs.append(FairValueGap(
                    type="bearish",
                    top=low1,
                    bottom=high3,
                    timestamp=ts,
                    index=i + 1,
                ))

    # TZ §6.1.4: fill_threshold = 0.7 (70% filled = inactive)
    for fvg in fvgs:
        candles_after = data.iloc[fvg.index + 1:]
        fvg.filled = _is_fvg_filled(fvg, candles_after)

    return fvgs


def _is_fvg_filled(fvg: FairValueGap, candles_after: pd.DataFrame) -> bool:
    """TZ §6.1.4: FVG filled when price penetrates 70% of the gap."""
    fill_threshold = 0.70
    gap_height = fvg.top - fvg.bottom
    if gap_height <= 0:
        return False

    for _, candle in candles_after.iterrows():
        if fvg.type == "bullish":
            # Bullish FVG: filled when price drops into 70% of gap from top
            penetration = fvg.top - float(candle["low"])
            if penetration >= gap_height * fill_threshold:
                return True
        elif fvg.type == "bearish":
            # Bearish FVG: filled when price rises into 70% of gap from bottom
            penetration = float(candle["high"]) - fvg.bottom
            if penetration >= gap_height * fill_threshold:
                return True
    return False


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
