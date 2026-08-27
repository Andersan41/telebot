"""Close all open signal outcomes in DB (after manual exchange closure).

Usage: python scripts/close_all_positions.py [--dry-run]
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage.database import db, SignalOutcome
from sqlalchemy import select


async def main():
    dry_run = "--dry-run" in sys.argv

    async with db._session_factory() as session:
        result = await session.execute(
            select(SignalOutcome).where(SignalOutcome.status == "OPEN")
        )
        outcomes = list(result.scalars().all())

    if not outcomes:
        print("No open outcomes found.")
        return

    print(f"Found {len(outcomes)} open outcomes:")
    for o in outcomes:
        signal = await db.get_signal(o.signal_id)
        sym = signal.symbol if signal else "?"
        typ = signal.signal_type if signal else "?"
        print(f"  outcome_id={o.id} signal_id={o.signal_id} {sym} {typ} risk={o.risk_pct}%")

    if dry_run:
        print("\nDRY RUN — no changes made.")
        return

    for o in outcomes:
        await db.close_outcome(o.id, "EXPIRED", close_price=0.0, pnl_pct=0.0)
        print(f"  Closed outcome {o.id}")

    count = await db.get_active_signals_count()
    print(f"\nDone. Active signals now: {count}")


if __name__ == "__main__":
    asyncio.run(main())
