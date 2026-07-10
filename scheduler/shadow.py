"""
scheduler/shadow.py — Shadow/paper mode for parallel version comparison.

Runs the scanner with different config presets and logs decisions
for comparison with the live version.

Usage:
    Set SHADOW_ENABLED=true in .env to enable shadow mode.
    Set SHADOW_PRESET=simplified to use the simplified gate configuration.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Optional
from loguru import logger
from config.settings import config, get_active_symbols
from storage.database import db
from scheduler.scanner import scan_symbol_v2, _current_funnel
from scheduler.circuit_breaker import is_circuit_breaker_active, check_recent_losses


# Shadow mode config
SHADOW_ENABLED = os.getenv("SHADOW_ENABLED", "false").lower() == "true"
SHADOW_VERSION = os.getenv("SHADOW_VERSION", "shadow-simplified")
SHADOW_PRESET = os.getenv("SHADOW_PRESET", "simplified")


async def run_shadow_cycle(
    notify_callback=None,
    blocked_callback=None,
    timeframes: Optional[list[str]] = None,
) -> dict:
    """Run shadow scan cycle.

    Compares original pipeline against current ICT core.
    """
    if not SHADOW_ENABLED:
        return {"status": "disabled"}

    await check_recent_losses()
    if is_circuit_breaker_active():
        logger.warning("[SHADOW] Shadow scan skipped — circuit breaker active")
        return {"status": "skipped", "reason": "circuit_breaker"}

    symbols = get_active_symbols()
    disabled = await db.get_disabled_symbols() or []
    symbols = [s for s in symbols if s not in disabled]
    tfs = timeframes if timeframes is not None else config.trading.primary_timeframes

    logger.info(f"[SHADOW] Starting shadow scan: {len(symbols)} symbols × {tfs}")

    shadow_results = []
    shadow_blocked = []
    try:
        for symbol in symbols:
            for tf in tfs:
                try:
                    result = await scan_symbol_v2(
                        symbol, tf,
                        notify_callback=None,
                        blocked_callback=None,
                    )
                    if result is not None:
                        shadow_results.append({
                            "symbol": symbol,
                            "timeframe": tf,
                            "signal_type": result.signal.value if result.signal else None,
                            "entry": result.close,
                            "sl": result.sl,
                            "tp": result.tp,
                            "score": result.score,
                            "version": SHADOW_VERSION,
                            "preset": SHADOW_PRESET,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                        logger.info(
                            f"[SHADOW] {symbol} {tf}: {result.signal.value} "
                            f"entry={result.close:.4f} SL={result.sl:.4f} TP={result.tp:.4f}"
                        )
                    else:
                        shadow_blocked.append({
                            "symbol": symbol,
                            "timeframe": tf,
                            "version": SHADOW_VERSION,
                            "preset": SHADOW_PRESET,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        })
                except Exception as e:
                    logger.warning(f"[SHADOW] Scan failed for {symbol} {tf}: {e}")
    except Exception as e:
        logger.error(f"[SHADOW] Shadow cycle failed: {e}")

    logger.info(
        f"[SHADOW] Shadow scan complete. "
        f"Signals: {len(shadow_results)}, Blocked: {len(shadow_blocked)}"
    )
    return {
        "status": "completed",
        "preset": SHADOW_PRESET,
        "signals": len(shadow_results),
        "blocked": len(shadow_blocked),
        "results": shadow_results,
        "blocked_details": shadow_blocked,
    }
