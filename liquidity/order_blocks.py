"""
liquidity/order_blocks.py — Order Block Detection.

Bullish OB: last bearish candle before impulsive move up, validated by BOS.
Bearish OB: last bullish candle before strong selloff, validated by BOS.

Validation requirements:
1. BOS after OB candle (break of previous swing high/low)
2. ATR-normalized displacement (move_size / atr >= MIN_OB_DISPLACEMENT_ATR)
3. Volume confirmation (candle_volume / avg_volume > MIN_OB_VOLUME_RATIO)
4. Retest validation (price revisits zone with bounce/rejection)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

import pandas as pd

from config.settings import config
from market_structure.swing_detector import detect_swings, SwingType


@dataclass
class OrderBlock:
    type: Literal["bullish", "bearish"]
    high: float
    low: float
    timestamp: datetime
    mitigated: bool = False
    mitigation_price: Optional[float] = None
    candle_index: int = 0
    displacement_atr: float = 0.0
    volume_ratio: float = 1.0
    has_bos: bool = False
    retested: bool = False
    retest_reaction: Optional[float] = None

    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2

    @property
    def is_valid(self) -> bool:
        min_disp = getattr(config, "liquidity_ob_min_displacement_atr", 1.5)
        min_vol = getattr(config, "liquidity_ob_min_volume_ratio", 1.5)
        retest_req = getattr(config, "liquidity_ob_retest_required", False)
        if not self.has_bos:
            return False
        if self.displacement_atr < min_disp:
            return False
        if self.volume_ratio < min_vol:
            return False
        if retest_req and not self.retested:
            return False
        return True


def detect_order_blocks(
    df: pd.DataFrame,
    lookback: int = 100,
    displacement_pct: Optional[float] = None,
    max_age_candles: Optional[int] = None,
    min_displacement_atr: Optional[float] = None,
    min_volume_ratio: Optional[float] = None,
    require_bos: bool = True,
    retest_required: Optional[bool] = None,
    check_retest_lookback: Optional[int] = None,
) -> list[OrderBlock]:
    """
    Detect order blocks in OHLCV data with full validation.

    Args:
        df: DataFrame with OHLCV data.
        lookback: number of recent candles to analyze.
        displacement_pct: minimum % move after OB to confirm (from config if None).
        max_age_candles: max age of OB in candles (from config if None).
        min_displacement_atr: min displacement in ATR units (from config if None).
        min_volume_ratio: min volume ratio vs average (from config if None).
        require_bos: require BOS validation (default True).
        retest_required: require price retest of zone (from config if None).

    Returns:
        List of OrderBlock objects.
    """
    if displacement_pct is None:
        displacement_pct = getattr(config, "liquidity_ob_min_displacement_pct", 2.0)
    if max_age_candles is None:
        max_age_candles = getattr(config, "liquidity_ob_max_age_candles", 50)
    if min_displacement_atr is None:
        min_displacement_atr = getattr(config, "liquidity_ob_min_displacement_atr", 1.5)
    if min_volume_ratio is None:
        min_volume_ratio = getattr(config, "liquidity_ob_min_volume_ratio", 1.5)
    if retest_required is None:
        retest_required = getattr(config, "liquidity_ob_retest_required", False)
    if check_retest_lookback is None:
        check_retest_lookback = getattr(config, "ob_retest_history", 30)

    data = df.tail(lookback).reset_index(drop=True)
    if len(data) < 5:
        return []

    atr = _calc_atr(data)
    avg_vol = data["volume"].mean()
    swing_highs = [{"index": s.index, "price": s.price}
                    for s in detect_swings(data, left_bars=5, right_bars=5, strict=False)
                    if s.swing_type == SwingType.HIGH]
    swing_lows = [{"index": s.index, "price": s.price}
                   for s in detect_swings(data, left_bars=5, right_bars=5, strict=False)
                   if s.swing_type == SwingType.LOW]

    blocks: list[OrderBlock] = []

    for i in range(1, len(data) - 2):
        candle = data.iloc[i]
        next_candle = data.iloc[i + 1]

        body = abs(float(candle["close"]) - float(candle["open"]))
        range_val = float(candle["high"]) - float(candle["low"])
        if range_val == 0:
            continue

        is_bearish_candle = float(candle["close"]) < float(candle["open"])
        is_bullish_candle = float(candle["close"]) > float(candle["open"])

        if is_bearish_candle:
            next_move_pct = (float(next_candle["close"]) - float(candle["low"])) / float(candle["low"]) * 100
            if next_move_pct >= displacement_pct:
                move_size = float(next_candle["close"]) - float(candle["low"])
                disp_atr = move_size / atr if atr > 0 else 0.0
                vol_ratio = float(data["volume"].iloc[i + 1]) / avg_vol if avg_vol > 0 else 1.0
                has_bos = _check_bos_bullish(data, i + 1, swing_highs)

                if require_bos and not has_bos:
                    continue

                ts = _to_datetime(data.index[i])
                retested, reaction = _check_retest_bullish(
                    data, i, float(candle["high"]), float(candle["low"]),
                    lookback=check_retest_lookback,
                )

                blocks.append(OrderBlock(
                    type="bullish",
                    high=float(candle["high"]),
                    low=float(candle["low"]),
                    timestamp=ts,
                    candle_index=i,
                    displacement_atr=round(disp_atr, 3),
                    volume_ratio=round(vol_ratio, 3),
                    has_bos=has_bos,
                    retested=retested,
                    retest_reaction=reaction,
                ))

        if is_bullish_candle:
            next_move_pct = (float(candle["high"]) - float(next_candle["close"])) / float(candle["high"]) * 100
            if next_move_pct >= displacement_pct:
                move_size = float(candle["high"]) - float(next_candle["close"])
                disp_atr = move_size / atr if atr > 0 else 0.0
                vol_ratio = float(data["volume"].iloc[i + 1]) / avg_vol if avg_vol > 0 else 1.0
                has_bos = _check_bos_bearish(data, i + 1, swing_lows)

                if require_bos and not has_bos:
                    continue

                ts = _to_datetime(data.index[i])
                retested, reaction = _check_retest_bearish(
                    data, i, float(candle["high"]), float(candle["low"]),
                    lookback=check_retest_lookback,
                )

                blocks.append(OrderBlock(
                    type="bearish",
                    high=float(candle["high"]),
                    low=float(candle["low"]),
                    timestamp=ts,
                    candle_index=i,
                    displacement_atr=round(disp_atr, 3),
                    volume_ratio=round(vol_ratio, 3),
                    has_bos=has_bos,
                    retested=retested,
                    retest_reaction=reaction,
                ))

    blocks = _filter_by_age(blocks, len(data), max_age_candles)
    return blocks


def find_ob_for_sweep(
    df: pd.DataFrame,
    sweep_index: int,
    sweep_direction: str,
    sweep_timestamp: datetime,
    lookback: int = 20,
) -> Optional[OrderBlock]:
    """TZ §6.2: Find OB by backward scan from sweep.

    Bullish OB (for LONG after sweep low): last bearish candle before impulse,
    where bars[i+1].low < bars[i].low * 0.998.

    Bearish OB (for SHORT after sweep high): last bullish candle before impulse,
    where bars[i+1].high > bars[i].high * 1.002.

    Temporal binding: OB.timestamp >= sweep_timestamp.
    """
    # Ensure sweep_timestamp is a datetime
    if isinstance(sweep_timestamp, (int, float)):
        from datetime import timezone as _tz
        sweep_timestamp = datetime.fromtimestamp(sweep_timestamp, tz=_tz.utc)
    elif sweep_timestamp.tzinfo is None:
        sweep_timestamp = sweep_timestamp.replace(tzinfo=datetime.timezone.utc)

    data = df.tail(max(sweep_index + 10, 100)).reset_index(drop=True)
    if sweep_index >= len(data):
        return None

    for i in range(sweep_index - 1, max(0, sweep_index - lookback), -1):
        candle = data.iloc[i]
        ts = _to_datetime(data.index[i])

        # Temporal binding: OB cannot be before sweep
        if ts < sweep_timestamp:
            break

        if sweep_direction == "bullish":
            # TZ §6.2.2: bullish OB = last bearish candle before impulse
            if float(candle["close"]) < float(candle["open"]):  # bearish
                if i + 1 < len(data):
                    next_candle = data.iloc[i + 1]
                    if float(next_candle["low"]) < float(candle["low"]) * 0.998:
                        return OrderBlock(
                            type="bullish",
                            high=float(candle["open"]),  # TZ: top = open
                            low=float(candle["close"]),  # bottom = close
                            timestamp=ts,
                            candle_index=i,
                            displacement_atr=0.0,  # not required for sweep OB
                            volume_ratio=1.0,
                            has_bos=False,  # BOS checked separately
                        )
        elif sweep_direction == "bearish":
            # TZ §6.2.3: bearish OB = last bullish candle before impulse
            if float(candle["close"]) > float(candle["open"]):  # bullish
                if i + 1 < len(data):
                    next_candle = data.iloc[i + 1]
                    if float(next_candle["high"]) > float(candle["high"]) * 1.002:
                        return OrderBlock(
                            type="bearish",
                            high=float(candle["close"]),  # TZ: top = close
                            low=float(candle["open"]),    # bottom = open
                            timestamp=ts,
                            candle_index=i,
                            displacement_atr=0.0,
                            volume_ratio=1.0,
                            has_bos=False,
                        )

    return None


def _calc_atr(df: pd.DataFrame, period: int = 14) -> float:
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


def _check_bos_bullish(df: pd.DataFrame, start_idx: int, swing_highs: list[dict], lookback: int = 20) -> bool:
    """Check if price breaks above a previous swing high after OB formation.

    Scans candles from start_idx forward (all closed — no look-ahead).
    """
    relevant_highs = [s for s in swing_highs if s["index"] < start_idx]
    if not relevant_highs:
        return False
    prev_swing_high = max(relevant_highs, key=lambda s: s["index"])["price"]
    end = min(start_idx + lookback, len(df))
    for j in range(start_idx, end):
        if float(df["high"].iloc[j]) > prev_swing_high:
            return True
    return False


def _check_bos_bearish(df: pd.DataFrame, start_idx: int, swing_lows: list[dict], lookback: int = 20) -> bool:
    """Check if price breaks below a previous swing low after OB formation.

    Scans candles from start_idx forward (all closed — no look-ahead).
    """
    relevant_lows = [s for s in swing_lows if s["index"] < start_idx]
    if not relevant_lows:
        return False
    prev_swing_low = min(relevant_lows, key=lambda s: s["index"])["price"]
    end = min(start_idx + lookback, len(df))
    for j in range(start_idx, end):
        if float(df["low"].iloc[j]) < prev_swing_low:
            return True
    return False


def _check_retest_bullish(df: pd.DataFrame, ob_idx: int, ob_high: float, ob_low: float, lookback: int = 30) -> tuple[bool, Optional[float]]:
    """Check if price already retested bullish OB zone using LOOKBACK (no look-ahead).

    Scans candles AFTER the OB formation up to the end of available data.
    All candles are closed — no future data is used.
    """
    end = min(ob_idx + lookback + 1, len(df))
    for j in range(ob_idx + 1, end):
        low = float(df["low"].iloc[j])
        close = float(df["close"].iloc[j])
        if low <= ob_high and low >= ob_low:
            reaction = close - low
            return True, reaction
    return False, None


def _check_retest_bearish(df: pd.DataFrame, ob_idx: int, ob_high: float, ob_low: float, lookback: int = 30) -> tuple[bool, Optional[float]]:
    """Check if price already retested bearish OB zone using LOOKBACK (no look-ahead).

    Scans candles AFTER the OB formation up to the end of available data.
    All candles are closed — no future data is used.
    """
    end = min(ob_idx + lookback + 1, len(df))
    for j in range(ob_idx + 1, end):
        high = float(df["high"].iloc[j])
        close = float(df["close"].iloc[j])
        if high >= ob_low and high <= ob_high:
            reaction = high - close
            return True, reaction
    return False, None


def _filter_by_age(blocks: list[OrderBlock], total_candles: int, max_age: int) -> list[OrderBlock]:
    """Remove order blocks older than max_age candles."""
    if max_age is None:
        return blocks
    current_idx = total_candles - 1
    return [
        b for b in blocks
        if (current_idx - b.candle_index) <= max_age
    ]


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
