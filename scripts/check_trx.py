import asyncio, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()

async def main():
    from storage.database import db
    await db.init()
    async with db._session_factory() as s:
        from sqlalchemy import text
        # Check position lifecycle - was SL updated?
        r = await s.execute(text(
            "SELECT id, symbol, entry_price, stop_loss, close_price, close_reason, "
            "breakeven_moved, completed_targets, trailing_active, status "
            "FROM positions WHERE symbol LIKE '%TRX%' ORDER BY id DESC LIMIT 5"
        ))
        for row in r.fetchall():
            print(row)

        # Check signal outcomes
        r = await s.execute(text("PRAGMA table_info(signal_outcomes)"))
        cols = [row[1] for row in r.fetchall()]
        print("\nOutcome columns:", cols)

        r = await s.execute(text(
            "SELECT * FROM signal_outcomes WHERE signal_id = 2"
        ))
        for row in r.fetchall():
            print(row)

asyncio.run(main())
