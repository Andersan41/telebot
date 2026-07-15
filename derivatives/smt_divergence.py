"""
derivatives/smt_divergence.py — SMT Divergence Detection (ICT concept).

SMT (Smart Money Tool) divergence compares swing structure between BTC and
an altcoin to detect relative strength/weakness.

Core ICT principle: assets do NOT always correlate 100%. Divergences reveal
where smart money is rotating.

Bullish SMT:  BTC makes LL, altcoin makes HL → altcoin stronger → allows BUY
Bearish SMT:  BTC makes HL, altcoin makes LL → altcoin weaker → allows SELL
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
from loguru import logger

from config.settings import config


SMT_CACHE_TTL = 60 * 30  # 30 minutes
_smt_cache: dict[str, tuple] = {}


def reset_smt_cache():
    """Reset SMT cache (useful for testing)."""
    global _smt_cache
    _smt_cache.clear()


@dataclass
class SMTResult:
    """Result of SMT divergence analysis between BTC and an altcoin."""
    direction: str  # 'bullish', 'bearish', 'neutral'
    btc_swing_high: float
    btc_swing_low: float
    alt_swing_high: float
    alt_swing_low: float
    btc_trend: str   # 'bullish', 'bearish', 'ranging'
    alt_trend: str   # 'bullish', 'bearish', 'ranging'
    detail: str = ""

    def allows_long(self) -> bool:
        """Block BUY if bearish SMT (altcoin weaker than BTC)."""
        return self.direction != "bearish"

    def allows_short(self) -> bool:
        """Block SELL if bullish SMT (altcoin stronger than BTC)."""
        return self.direction != "bullish"


def _detect_swing_points(
    df: pd.DataFrame, lookback: int = 20
) -> tuple[float, float, str]:
    """Detect recent swing high, swing low, and micro-trend.

    Returns: (swing_high, swing_low, trend)
    """
    if df is None or len(df) < lookback + 2:
        return 0.0, 0.0, "ranging"

    recent = df.tail(lookback + 2)
    highs = recent["high"].values
    lows = recent["low"].values
    closes = recent["close"].values

    # Swing high: bar where high > neighbors
    swing_highs = []
    for i in range(1, len(highs) - 1):
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            swing_highs.append(highs[i])

    # Swing low: bar where low < neighbors
    swing_lows = []
    for i in range(1, len(lows) - 1):
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            swing_lows.append(lows[i])

    sh = max(swing_highs) if swing_highs else highs.max()
    sl = min(swing_lows) if swing_lows else lows.min()

    # Micro-trend from last 5 closes
    last_closes = closes[-5:]
    if len(last_closes) >= 3:
        ema_fast = pd.Series(last_closes).ewm(span=3).mean().iloc[-1]
        ema_slow = pd.Series(last_closes).ewm(span=5).mean().iloc[-1]
        if ema_fast > ema_slow * 1.002:
            trend = "bullish"
        elif ema_fast < ema_slow * 0.998:
            trend = "bearish"
        else:
            trend = "ranging"
    else:
        trend = "ranging"

    return sh, sl, trend


def _detect_bearish_smt(
    btc_sh: float, btc_sl: float, btc_trend: str,
    alt_sh: float, alt_sl: float, alt_trend: str,
    btc_price: float, alt_price: float,
) -> bool:
    """Bearish SMT: BTC strong (HL/HV), altcoin weak (LL/LV).

    BTC making higher structure while altcoin is making lower structure
    = altcoin is weaker than BTC = bearish for altcoin.
    """
    btc_bullish = btc_trend == "bullish" or btc_price > btc_sh * 0.98
    alt_bearish = alt_trend == "bearish" or alt_price < alt_sl * 1.05

    if btc_bullish and alt_bearish:
        return True

    if btc_trend == "bullish" and alt_trend == "bearish":
        return True

    return False


def _detect_bullish_smt(
    btc_sh: float, btc_sl: float, btc_trend: str,
    alt_sh: float, alt_sl: float, alt_trend: str,
    btc_price: float, alt_price: float,
) -> bool:
    """Bullish SMT: BTC weak (LL/LV), altcoin strong (HL/HV).

    BTC making lower structure while altcoin is holding higher structure
    = altcoin is stronger than BTC = bullish for altcoin.
    """
    btc_bearish = btc_trend == "bearish" or btc_price < btc_sl * 1.02
    alt_bullish = alt_trend == "bullish" or alt_price > alt_sh * 0.98

    if btc_bearish and alt_bullish:
        return True

    if btc_trend == "bearish" and alt_trend == "bullish":
        return True

    return False


async def fetch_smt_divergence(symbol: str) -> Optional[SMTResult]:
    """Compute SMT divergence between BTC and the given symbol.

    Uses 4H timeframe for swing structure comparison (ICT standard).
    Results are cached for SMT_CACHE_TTL.

    For BTC/USDT itself, returns neutral (SMT is meaningless for BTC vs BTC).
    """
    # SMT is meaningless for BTC itself
    base = symbol.split("/")[0].upper()
    if base == "BTC":
        return SMTResult(
            direction="neutral",
            btc_swing_high=0, btc_swing_low=0,
            alt_swing_high=0, alt_swing_low=0,
            btc_trend="ranging", alt_trend="ranging",
            detail="SMT skipped for BTC itself",
        )

    # Check cache
    cache_key = symbol
    if cache_key in _smt_cache:
        cached_result, cached_time = _smt_cache[cache_key]
        age = (datetime.now(timezone.utc) - cached_time).total_seconds()
        if age < SMT_CACHE_TTL:
            logger.debug(f"SMT cache hit for {symbol} (age={age:.0f}s)")
            return cached_result

    btc_symbol = config.derivatives.btc_symbol

    try:
        from data.exchange_client import exchange_client

        # Fetch 4H data for both BTC and altcoin
        btc_df = await exchange_client.fetch_ohlcv(btc_symbol, "4h", limit=60)
        alt_df = await exchange_client.fetch_ohlcv(symbol, "4h", limit=60)

        if btc_df is None or alt_df is None:
            logger.debug(f"SMT: missing data for {symbol}")
            return None
        if len(btc_df) < 25 or len(alt_df) < 25:
            logger.debug(f"SMT: insufficient data for {symbol}")
            return None

        btc_price = btc_df["close"].iloc[-1]
        alt_price = alt_df["close"].iloc[-1]

        # Detect swing structure (20-bar lookback on 4H = ~3.3 days)
        btc_sh, btc_sl, btc_trend = _detect_swing_points(btc_df)
        alt_sh, alt_sl, alt_trend = _detect_swing_points(alt_df)

        # Detect divergence
        bearish = _detect_bearish_smt(
            btc_sh, btc_sl, btc_trend,
            alt_sh, alt_sl, alt_trend,
            btc_price, alt_price,
        )
        bullish = _detect_bullish_smt(
            btc_sh, btc_sl, btc_trend,
            alt_sh, alt_sl, alt_trend,
            btc_price, alt_price,
        )

        if bullish and not bearish:
            direction = "bullish"
            detail = (f"Bullish SMT: BTC weak ({btc_trend}, "
                      f"sl={btc_sl:.0f}), alt strong ({alt_trend}, "
                      f"sh={alt_sh:.0f})")
        elif bearish and not bullish:
            direction = "bearish"
            detail = (f"Bearish SMT: BTC strong ({btc_trend}, "
                      f"sh={btc_sh:.0f}), alt weak ({alt_trend}, "
                      f"sl={alt_sl:.0f})")
        else:
            direction = "neutral"
            detail = (f"No SMT divergence: BTC={btc_trend}, "
                      f"alt={alt_trend}")

        result = SMTResult(
            direction=direction,
            btc_swing_high=btc_sh,
            btc_swing_low=btc_sl,
            alt_swing_high=alt_sh,
            alt_swing_low=alt_sl,
            btc_trend=btc_trend,
            alt_trend=alt_trend,
            detail=detail,
        )

        _smt_cache[cache_key] = (result, datetime.now(timezone.utc))
        logger.debug(f"SMT {symbol}: {direction} — {detail}")
        return result

    except Exception as e:
        logger.warning(f"SMT divergence failed for {symbol}: {e}")
        return None
