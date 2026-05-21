"""
scheduler/circuit_breaker.py — Circuit breaker для паузы после серии losses.
"""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional
from loguru import logger

from config.settings import config
from storage.database import db


# Circuit breaker state (in-memory)
_cb_loss_count: int = 0
_cb_paused_until: Optional[datetime] = None
_cb_last_check: Optional[datetime] = None

# Configurable thresholds
CIRCUIT_BREAKER_LOSS_THRESHOLD = 3  # Pause after N consecutive losses
CIRCUIT_BREAKER_PAUSE_MINUTES = 30  # Pause duration in minutes
CIRCUIT_BREAKER_WINDOW_MINUTES = 60  # Window to count losses


def is_circuit_breaker_active() -> bool:
    """Check if circuit breaker is currently active (scanning paused)."""
    global _cb_paused_until
    if _cb_paused_until is None:
        return False
    if datetime.now(timezone.utc) > _cb_paused_until:
        _cb_paused_until = None
        _cb_loss_count = 0
        logger.info("Circuit breaker reset — scanning resumed")
        return False
    return True


async def check_recent_losses() -> None:
    """Check recent outcomes and update circuit breaker state."""
    global _cb_loss_count, _cb_paused_until, _cb_last_check

    now = datetime.now(timezone.utc)
    if _cb_last_check and (now - _cb_last_check).total_seconds() < 60:
        return  # Check at most once per minute
    _cb_last_check = now

    try:
        window_start = now - timedelta(minutes=CIRCUIT_BREAKER_WINDOW_MINUTES)
        recent_outcomes = await db.get_outcomes_since(window_start)

        if not recent_outcomes:
            _cb_loss_count = 0
            return

        # Count consecutive losses (HIT_SL)
        consecutive_losses = 0
        for outcome in reversed(recent_outcomes):
            if outcome.result == "HIT_SL":
                consecutive_losses += 1
            else:
                break  # Reset on any non-loss outcome

        _cb_loss_count = consecutive_losses

        if consecutive_losses >= CIRCUIT_BREAKER_LOSS_THRESHOLD:
            _cb_paused_until = now + timedelta(minutes=CIRCUIT_BREAKER_PAUSE_MINUTES)
            logger.warning(
                f"Circuit breaker ACTIVATED: {consecutive_losses} consecutive losses. "
                f"Scanning paused for {CIRCUIT_BREAKER_PAUSE_MINUTES} minutes "
                f"(until {_cb_paused_until.strftime('%H:%M:%S')})"
            )
    except Exception as e:
        logger.warning(f"Circuit breaker check failed: {e}")
