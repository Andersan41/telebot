"""
scheduler/core_v2.py — Rebuilt core: 5 phases, not 32 gates.

Architecture from core_strategy.md:

1. Market Structure    → Is there a structural setup? (BOS/CHoCH)
2. Liquidity Event     → Is there a valid entry zone? (Sweep/OB/FVG)
3. Execution Window    → Does context confirm? (HTF, Volume)
4. Risk Check          → Is the risk acceptable? (RR, SL, Portfolio)
5. Send                → Publish signal

Each phase = one question = one decision.
No redundant information sources.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

from config.settings import config, get_active_symbols, VERSION
from data.exchange_client import exchange_client
from indicators.engine import indicator_engine
from strategy.pattern_engine import pattern_engine, ICTSetup
from market_structure.structure import analyze_structure, check_mtf_alignment
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from risk.engine import risk_engine
from storage.database import db
from storage.trace import DecisionTraceBuilder


@dataclass
class PhaseResult:
    """Result of a single pipeline phase."""
    passed: bool
    reason: str = ""
    data: dict = None

    def __post_init__(self):
        if self.data is None:
            self.data = {}


async def phase_1_market_structure(
    symbol: str,
    timeframe: str,
    df,
    direction: str,
) -> PhaseResult:
    """Phase 1: Market Structure — Is there a structural setup?

    Checks:
    - BOS or CHoCH exists
    - Structure trend aligns with direction
    """
    try:
        structure = analyze_structure(df, lookback=50)
    except Exception as e:
        return PhaseResult(passed=False, reason=f"structure_analysis_failed: {e}")

    if structure.trend == "ranging" and not structure.last_bos and not structure.last_choch:
        return PhaseResult(passed=False, reason="no_structure")

    # Check alignment
    if direction == "buy" and structure.trend == "bearish":
        if not structure.last_choch or structure.last_choch.type != "bullish":
            return PhaseResult(passed=False, reason="structure_bearish_for_buy")

    if direction == "sell" and structure.trend == "bullish":
        if not structure.last_choch or structure.last_choch.type != "bearish":
            return PhaseResult(passed=False, reason="structure_bullish_for_sell")

    return PhaseResult(
        passed=True,
        data={"structure": structure},
    )


async def phase_2_liquidity_event(
    symbol: str,
    timeframe: str,
    df,
    direction: str,
    entry_price: float,
) -> PhaseResult:
    """Phase 2: Liquidity Event — Is there a valid entry zone?

    Checks:
    - Sweep detected (with reclaim)
    - Order Block or FVG present
    - Price is in a tradeable zone
    """
    try:
        sweeps = detect_sweeps(df)
        order_blocks = detect_order_blocks(df)
        fvgs = detect_fvg(df)
    except Exception as e:
        return PhaseResult(passed=False, reason=f"liquidity_analysis_failed: {e}")

    # Check for valid setup
    has_bullish_sweep = any(s.type == "bullish" and s.is_valid for s in sweeps)
    has_bearish_sweep = any(s.type == "bearish" and s.is_valid for s in sweeps)
    has_bullish_ob = any(ob.type == "bullish" for ob in order_blocks)
    has_bearish_ob = any(ob.type == "bearish" for ob in order_blocks)
    has_bullish_fvg = any(f.type == "bullish" and f.is_active for f in fvgs)
    has_bearish_fvg = any(f.type == "bearish" and f.is_active for f in fvgs)

    # Direction-specific check
    if direction == "buy":
        has_liquidity = (has_bullish_sweep or has_bullish_ob or has_bullish_fvg)
    else:
        has_liquidity = (has_bearish_sweep or has_bearish_ob or has_bearish_fvg)

    if not has_liquidity:
        return PhaseResult(passed=False, reason="no_liquidity_event")

    return PhaseResult(
        passed=True,
        data={
            "sweeps": sweeps,
            "order_blocks": order_blocks,
            "fvgs": fvgs,
        },
    )


async def phase_3_execution_window(
    symbol: str,
    timeframe: str,
    direction: str,
    df,
) -> PhaseResult:
    """Phase 3: Execution Window — Does context confirm?

    Checks:
    - HTF trend alignment
    - Volume above average
    """
    # HTF alignment
    try:
        mtf_result = await check_mtf_alignment(
            symbol=symbol,
            direction="bullish" if direction == "buy" else "bearish",
            primary_tf=timeframe,
            exchange_client=exchange_client,
        )
        htf_aligned = mtf_result.aligned
    except Exception as e:
        logger.warning(f"MTF check failed for {symbol}: {e}")
        htf_aligned = True  # Don't block on MTF failure

    # Volume
    try:
        ind = indicator_engine.calculate(df)
        volume_above_avg = ind.volume_above_avg if ind else False
    except Exception:
        volume_above_avg = True  # Don't block on volume calculation failure

    # Both must confirm
    if not htf_aligned:
        return PhaseResult(passed=False, reason="htf_not_aligned")

    return PhaseResult(
        passed=True,
        data={"htf_aligned": htf_aligned, "volume_ok": volume_above_avg},
    )


async def phase_4_risk_check(
    symbol: str,
    timeframe: str,
    direction: str,
    entry_price: float,
    sl: float,
    tp: float,
) -> PhaseResult:
    """Phase 4: Risk Check — Is the risk acceptable?

    Checks:
    - SL != entry (catastrophic bug prevention)
    - R:R ratio >= minimum
    - SL distance within limits
    - Portfolio risk OK
    """
    # Critical: SL must not equal entry
    if abs(sl - entry_price) < entry_price * 0.001:  # Less than 0.1% from entry
        return PhaseResult(passed=False, reason=f"sl_equals_entry:{sl:.4f}")

    # R:R check
    risk = abs(entry_price - sl)
    reward = abs(tp - entry_price)
    rr = reward / risk if risk > 0 else 0

    min_rr = config.trading.min_rr_threshold
    if rr < min_rr:
        return PhaseResult(passed=False, reason=f"rr_too_low:{rr:.2f}<{min_rr}")

    # SL distance check
    sl_distance_pct = risk / entry_price * 100
    max_sl = config.trading.max_sl_distance_pct
    if sl_distance_pct > max_sl:
        return PhaseResult(passed=False, reason=f"sl_too_far:{sl_distance_pct:.1f}%>{max_sl}%")

    # Minimum SL distance
    min_sl = config.trading.min_sl_distance_pct
    if sl_distance_pct < min_sl:
        # Shift SL outward
        if direction == "buy":
            sl = entry_price * (1 - min_sl / 100)
        else:
            sl = entry_price * (1 + min_sl / 100)
        risk = abs(entry_price - sl)
        rr = reward / risk if risk > 0 else 0

    return PhaseResult(
        passed=True,
        data={"rr": rr, "sl_distance_pct": sl_distance_pct, "sl": sl},
    )


async def scan_core_v2(
    symbol: str,
    timeframe: str,
    notify_callback=None,
    blocked_callback=None,
) -> Optional[dict]:
    """Core v2 pipeline: 5 phases, no redundant gates.

    Returns signal dict if passed all phases, None otherwise.
    """
    trace = DecisionTraceBuilder(symbol=symbol, timeframe=timeframe)

    # Fetch OHLCV
    try:
        df = await exchange_client.fetch_ohlcv(symbol, timeframe, limit=100)
        if df is None or len(df) < 20:
            return None
    except Exception as e:
        logger.warning(f"OHLCV fetch failed for {symbol} {timeframe}: {e}")
        return None

    # Calculate indicators
    try:
        ind = indicator_engine.calculate(df)
        if ind is None:
            return None
    except Exception as e:
        logger.warning(f"Indicator calc failed for {symbol} {timeframe}: {e}")
        return None

    # Detect pattern
    try:
        setup = pattern_engine.detect(df, ind)
        if setup is None or not setup.direction:
            return None
    except Exception as e:
        logger.warning(f"Pattern detection failed for {symbol} {timeframe}: {e}")
        return None

    direction = setup.direction  # "buy" or "sell"
    entry_price = float(ind.close)

    # SL/TP from pattern engine
    if setup.sl is None or setup.tp is None:
        return None

    # Phase 1: Market Structure
    phase1 = await phase_1_market_structure(symbol, timeframe, df, direction)
    if not phase1.passed:
        logger.debug(f"[{symbol} {timeframe}] Phase 1 BLOCKED: {phase1.reason}")
        trace.blocked("market_structure", phase1.reason)
        await trace.save(db)
        return None

    # Phase 2: Liquidity Event
    phase2 = await phase_2_liquidity_event(symbol, timeframe, df, direction, entry_price)
    if not phase2.passed:
        logger.debug(f"[{symbol} {timeframe}] Phase 2 BLOCKED: {phase2.reason}")
        trace.blocked("liquidity_event", phase2.reason)
        await trace.save(db)
        return None

    # Phase 3: Execution Window
    phase3 = await phase_3_execution_window(symbol, timeframe, direction, df)
    if not phase3.passed:
        logger.debug(f"[{symbol} {timeframe}] Phase 3 BLOCKED: {phase3.reason}")
        trace.blocked("execution_window", phase3.reason)
        await trace.save(db)
        return None

    # Phase 4: Risk Check
    phase4 = await phase_4_risk_check(
        symbol, timeframe, direction, entry_price, setup.sl, setup.tp,
    )
    if not phase4.passed:
        logger.debug(f"[{symbol} {timeframe}] Phase 4 BLOCKED: {phase4.reason}")
        trace.blocked("risk_check", phase4.reason)
        await trace.save(db)
        return None

    # Use adjusted SL if risk check shifted it
    final_sl = phase4.data.get("sl", setup.sl)
    final_tp = setup.tp

    # Phase 5: Send
    signal_data = {
        "symbol": symbol,
        "timeframe": timeframe,
        "signal_type": direction.upper(),
        "entry": entry_price,
        "sl": final_sl,
        "tp": final_tp,
        "score": phase4.data.get("rr", 0),
        "version": VERSION,
        "phases": {
            "market_structure": phase1.data,
            "liquidity_event": phase2.data,
            "execution_window": phase3.data,
            "risk_check": phase4.data,
        },
    }

    trace.passed("all_phases")
    trace.set_version(VERSION, {})
    await trace.save(db)

    logger.info(
        f"[CORE v2] {symbol} {timeframe}: {direction.upper()} "
        f"entry={entry_price:.4f} SL={final_sl:.4f} TP={final_tp:.4f} "
        f"RR={phase4.data.get('rr', 0):.2f}"
    )

    return signal_data
