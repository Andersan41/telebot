"""
scripts/daily_reason_report.py — Daily audit reason code distribution.

Usage:
    python scripts/daily_reason_report.py [--days 1] [--top 20]
"""
import asyncio
import argparse
from datetime import datetime, timezone, timedelta
from storage.database import db


async def main(days: int = 1, top: int = 20):
    await db.init()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with db._session_factory() as session:
        from sqlalchemy import text
        result = await session.execute(
            text("""
                SELECT reason_code, passed, COUNT(*) as cnt
                FROM signal_audit_log
                WHERE ts_event >= :cutoff
                GROUP BY reason_code, passed
                ORDER BY cnt DESC
                LIMIT :limit
            """),
            {"cutoff": cutoff, "limit": top},
        )
        rows = result.fetchall()

    if not rows:
        print(f"No audit entries in the last {days} day(s).")
        return

    total = sum(r[2] for r in rows)
    print(f"\n{'='*60}")
    print(f"  Daily Reason Report — last {days} day(s)")
    print(f"  Generated: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*60}")
    print(f"{'Reason Code':<30} {'Status':<8} {'Count':>6} {'%':>7}")
    print(f"{'-'*60}")
    for reason, passed, cnt in rows:
        status = "PASS" if passed else "BLOCK"
        pct = cnt / total * 100 if total > 0 else 0
        print(f"{reason:<30} {status:<8} {cnt:>6} {pct:>6.1f}%")
    print(f"{'-'*60}")
    print(f"{'TOTAL':<39} {total:>6}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily reason code report")
    parser.add_argument("--days", type=int, default=1, help="Look back N days")
    parser.add_argument("--top", type=int, default=20, help="Show top N reasons")
    args = parser.parse_args()
    asyncio.run(main(days=args.days, top=args.top))
