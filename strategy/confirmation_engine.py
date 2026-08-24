"""
strategy/confirmation_engine.py — LTF Confirmation (multi_tf mode).

After a valid setup is found on the primary TF (e.g. 1h), this module
checks the confirmation TF (e.g. 5m) for micro-structure confirmation:
1. MICRO_BOS — micro-BOS/CHoCH on LTF after HTF setup
2._ZONE_RETEST — price retests the HTF OB/FVG zone on LTF
3. MOMENTUM — LTF candle closes beyond zone boundary
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

import pandas as pd
from loguru import logger


@dataclass
class ConfirmationResult:
    confirmed: bool = False
    trigger_type: Literal["MICRO_BOS", "ZONE_RETEST", "MOMENTUM", "NONE"] = "NONE"
    entry_price: float = 0.0
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)


def _find_micro_bos(
    df_5m: pd.DataFrame,
    direction: str,
    setup_timestamp: Optional[datetime] = None,
    lookback: int = 30,
) -> Optional[dict]:
    """Find micro-BOS/CHoCH on 5m in the direction of the HTF setup.

    Returns dict with (price, timestamp, type) or None.
    """
    from market_structure.structure import analyze_structure

    if len(df_5m) < 10:
        return None

    struct = analyze_structure(df_5m, lookback=lookback, swing_window=3)
    if struct is None:
        return None

    # Check for BOS in the setup direction
    bos = struct.last_bos
    if bos is None:
        return None

    # Must be after the HTF setup timestamp
    if setup_timestamp is not None:
        bos_ts = bos.timestamp
        if bos_ts.tzinfo is None:
            bos_ts = bos_ts.replace(tzinfo=timezone.utc)
        setup_ts = setup_timestamp
        if setup_ts.tzinfo is None:
            setup_ts = setup_ts.replace(tzinfo=timezone.utc)
        if bos_ts <= setup_ts:
            return None

    # Direction match
    if direction == "BUY" and bos.type != "bullish":
        return None
    if direction == "SELL" and bos.type != "bearish":
        return None

    return {
        "price": bos.level,
        "timestamp": bos.timestamp,
        "type": bos.type,
    }


def _find_zone_retest(
    df_5m: pd.DataFrame,
    entry_zone: tuple[float, float],
    direction: str,
    lookback_candles: int = 50,
) -> Optional[dict]:
    """Check if 5m price retested the HTF OB/FVG zone.

    entry_zone = (upper, lower) bounds of the OB/FVG from HTF.
    Returns dict with (price, timestamp) of the retest candle, or None.
    """
    if df_5m is None or len(df_5m) < 3:
        return None

    zone_upper, zone_lower = entry_zone
    data = df_5m.tail(lookback_candles)

    for i in range(len(data)):
        row = data.iloc[i]
        candle_high = float(row["high"])
        candle_low = float(row["low"])
        candle_close = float(row["close"])
        candle_open = float(row["open"])

        # Get timestamp
        if hasattr(data.index[i], "to_pydatetime"):
            ts = data.index[i].to_pydatetime()
        elif isinstance(data.index[i], (int, float)):
            from datetime import timezone as _tz
            ts = datetime.fromtimestamp(data.index[i], tz=_tz.utc)
        else:
            ts = data.index[i]
        if isinstance(ts, datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        if direction == "BUY":
            # Price dipped into zone and closed above zone lower bound
            if candle_low <= zone_upper and candle_close > zone_lower:
                # Prefer close above zone upper (stronger)
                if candle_close >= zone_upper:
                    return {"price": candle_close, "timestamp": ts, "strength": "strong"}
                return {"price": candle_close, "timestamp": ts, "strength": "weak"}
        else:  # SELL
            # Price spiked into zone and closed below zone upper bound
            if candle_high >= zone_lower and candle_close < zone_upper:
                if candle_close <= zone_lower:
                    return {"price": candle_close, "timestamp": ts, "strength": "strong"}
                return {"price": candle_close, "timestamp": ts, "strength": "weak"}

    return None


def _find_momentum(
    df_5m: pd.DataFrame,
    entry_zone: tuple[float, float],
    direction: str,
    lookback_candles: int = 20,
) -> Optional[dict]:
    """Check for momentum close beyond zone boundary.

    Returns dict with (price, timestamp) or None.
    """
    if df_5m is None or len(df_5m) < 2:
        return None

    zone_upper, zone_lower = entry_zone
    data = df_5m.tail(lookback_candles)

    for i in range(len(data)):
        row = data.iloc[i]
        candle_close = float(row["close"])

        if hasattr(data.index[i], "to_pydatetime"):
            ts = data.index[i].to_pydatetime()
        elif isinstance(data.index[i], (int, float)):
            from datetime import timezone as _tz
            ts = datetime.fromtimestamp(data.index[i], tz=_tz.utc)
        else:
            ts = data.index[i]
        if isinstance(ts, datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        if direction == "BUY" and candle_close > zone_upper:
            return {"price": candle_close, "timestamp": ts}
        if direction == "SELL" and candle_close < zone_lower:
            return {"price": candle_close, "timestamp": ts}

    return None


def find_confirmation(
    df_5m: pd.DataFrame,
    direction: str,
    entry_zone: Optional[tuple[float, float]] = None,
    sl_price: float = 0.0,
    setup_timestamp: Optional[datetime] = None,
    atr_5m: float = 0.0,
) -> ConfirmationResult:
    """Find LTF confirmation for an HTF setup.

    Args:
        df_5m: 5m OHLCV DataFrame.
        direction: "BUY" or "SELL".
        entry_zone: (upper, lower) bounds of HTF OB/FVG zone.
        sl_price: SL from HTF setup (for zone validation).
        setup_timestamp: when the HTF setup was detected.
        atr_5m: ATR on 5m (for filtering).

    Returns:
        ConfirmationResult with the best confirmation found.
    """
    result = ConfirmationResult()

    if df_5m is None or len(df_5m) < 5:
        result.reasons.append("insufficient 5m data")
        return result

    # Type A: Micro-BOS (highest priority)
    micro_bos = _find_micro_bos(df_5m, direction, setup_timestamp)
    if micro_bos:
        result.confirmed = True
        result.trigger_type = "MICRO_BOS"
        result.entry_price = micro_bos["price"]
        result.confidence = 0.9
        result.reasons.append(f"micro-BOS {micro_bos['type']} at {micro_bos['price']:.4f}")
        return result

    # Type B: Zone retest (medium priority)
    if entry_zone is not None:
        zone_retest = _find_zone_retest(df_5m, entry_zone, direction)
        if zone_retest:
            result.confirmed = True
            result.trigger_type = "ZONE_RETEST"
            result.entry_price = zone_retest["price"]
            result.confidence = 0.7 if zone_retest["strength"] == "strong" else 0.55
            result.reasons.append(
                f"zone retest ({zone_retest['strength']}) at {zone_retest['price']:.4f}"
            )
            return result

    # Type C: Momentum (lowest priority, fallback)
    if entry_zone is not None:
        momentum = _find_momentum(df_5m, entry_zone, direction)
        if momentum:
            result.confirmed = True
            result.trigger_type = "MOMENTUM"
            result.entry_price = momentum["price"]
            result.confidence = 0.5
            result.reasons.append(f"momentum close at {momentum['price']:.4f}")
            return result

    result.reasons.append("no 5m confirmation found")
    return result
