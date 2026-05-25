"""
fix_uni_to_doge.py — Заменяет UNI/USDT на DOGE/USDT в БД (dynamic_symbols + signals)
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sqlite3
from loguru import logger


def fix_database():
    db_path = "data/signals.db"
    if not os.path.exists(db_path):
        logger.info(f"Database {db_path} not found, nothing to fix")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Fix dynamic_symbols in bot_settings
    cursor.execute("SELECT value FROM bot_settings WHERE key = 'dynamic_symbols'")
    row = cursor.fetchone()
    if row:
        symbols = row[0]
        if "UNI/USDT" in symbols:
            new_symbols = symbols.replace("UNI/USDT", "DOGE/USDT")
            cursor.execute(
                "UPDATE bot_settings SET value = ? WHERE key = 'dynamic_symbols'",
                (new_symbols,),
            )
            logger.info(f"dynamic_symbols: UNI/USDT → DOGE/USDT")
            logger.info(f"  Old: {symbols}")
            logger.info(f"  New: {new_symbols}")
        else:
            logger.info("UNI/USDT not found in dynamic_symbols")
    else:
        logger.info("No dynamic_symbols in database")

    # 2. Fix signals table
    cursor.execute("SELECT COUNT(*) FROM signals WHERE symbol = 'UNI/USDT'")
    count = cursor.fetchone()[0]
    if count > 0:
        cursor.execute(
            "UPDATE signals SET symbol = 'DOGE/USDT' WHERE symbol = 'UNI/USDT'"
        )
        logger.info(f"signals: replaced {count} rows UNI/USDT → DOGE/USDT")
    else:
        logger.info("No UNI/USDT in signals table")

    # 3. Fix signal_outcomes (via signals join — just log, no action needed)
    cursor.execute("""
        SELECT COUNT(*) FROM signal_outcomes so
        JOIN signals s ON so.signal_id = s.id
        WHERE s.symbol = 'UNI/USDT'
    """)
    outcome_count = cursor.fetchone()[0]
    if outcome_count > 0:
        logger.info(f"signal_outcomes: {outcome_count} outcomes reference UNI/USDT (auto-fixed via signals update)")

    conn.commit()
    conn.close()
    logger.info("Database fix complete")


if __name__ == "__main__":
    fix_database()
