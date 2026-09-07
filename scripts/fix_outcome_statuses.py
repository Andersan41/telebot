"""
scripts/fix_outcome_statuses.py — Fix broken outcome statuses from position manager.

The position manager used to store raw reasons (TP3_FULL, TIME_STOP, FLIP_BIAS,
SWEEP_BREACH) as SignalOutcome.status. Stats only count HIT_TP/HIT_SL/EXPIRED,
so these trades were invisible. This script normalizes existing data.

Run once: python scripts/fix_outcome_statuses.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, update
from loguru import logger
from storage.database import db, SignalOutcome, Signal


# Statuses that need normalization
BROKEN_STATUSES = {"TP1_FULL", "TP2_FULL", "TP3_FULL", "TIME_STOP", "FLIP_BIAS", "SWEEP_BREACH"}


def _normalize(reason: str, net_pnl: float | None) -> str:
    if reason.startswith("TP") and reason.endswith("_FULL"):
        return "HIT_TP"
    if reason == "TIME_STOP":
        return "EXPIRED"
    if net_pnl is not None and net_pnl > 0:
        return "HIT_TP"
    if net_pnl is not None and net_pnl < 0:
        return "HIT_SL"
    return reason


async def fix_outcomes():
    await db.init()
    async with db._session_factory() as session:
        # Find all broken outcomes
        result = await session.execute(
            select(SignalOutcome).where(SignalOutcome.status.in_(BROKEN_STATUSES))
        )
        broken = result.scalars().all()

        if not broken:
            logger.info("No broken outcomes found.")
            return

        logger.info(f"Found {len(broken)} outcomes with broken statuses")

        fixed = 0
        for outcome in broken:
            new_status = _normalize(outcome.status, outcome.pnl_pct)
            old_status = outcome.status
            outcome.status = new_status
            fixed += 1
            logger.info(
                f"  #{outcome.id} signal_id={outcome.signal_id}: "
                f"{old_status} -> {new_status} (pnl={outcome.pnl_pct})"
            )

        await session.commit()
        logger.info(f"Fixed {fixed} outcomes.")


if __name__ == "__main__":
    asyncio.run(fix_outcomes())
