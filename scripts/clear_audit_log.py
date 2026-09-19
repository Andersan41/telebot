"""
scripts/clear_audit_log.py — Clear signal_audit_log table.

Usage on server:
    cd /path/to/tgbot
    python scripts/clear_audit_log.py

Optional: --hours N to keep only last N hours (default: clear all).
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from storage.database import db
from sqlalchemy import text


async def main():
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else None

    async with db._session_factory() as session:
        if hours:
            result = await session.execute(
                text("DELETE FROM signal_audit_log WHERE ts_event < datetime('now', '-' || :hours || ' hours')"),
                {"hours": hours}
            )
            print(f"Deleted {result.rowcount} rows older than {hours} hours")
        else:
            result = await session.execute(text("DELETE FROM signal_audit_log"))
            print(f"Deleted {result.rowcount} rows (all)")

        count = await session.execute(text("SELECT COUNT(*) FROM signal_audit_log"))
        print(f"Remaining: {count.scalar()} rows")
        await session.commit()


asyncio.run(main())
