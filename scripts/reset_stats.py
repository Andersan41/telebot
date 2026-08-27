"""
scripts/reset_stats.py — Полный сброс статистики бота.

Удаляет все данные из таблиц БД и сбрасывает in-memory состояние.
Используй после изменения логики стратегии.
"""
import asyncio
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from storage.database import db
from loguru import logger


TABLES_TO_CLEAR = [
    "signal_outcomes",
    "signals",
    "signal_candidates",
    "decision_traces",
    "context_snapshots",
    "bot_settings",
]


def _reset_sqlite_db(db_path: str) -> None:
    """Direct sqlite3 cleanup (covers both async engines)."""
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path)
    total = 0
    for table in TABLES_TO_CLEAR:
        try:
            cursor = conn.execute(f"DELETE FROM {table}")
            total += cursor.rowcount
            try:
                conn.execute(f"DELETE FROM sqlite_sequence WHERE name='{table}'")
            except Exception:
                pass
        except Exception:
            pass
    conn.commit()
    conn.close()
    logger.info(f"  {db_path}: удалено {total} строк (total)")


async def reset():
    logger.info("=== ПОЛНЫЙ СБРОС СТАТИСТИКИ БОТА ===")

    # --- 1. Очистка БД через SQLAlchemy ---
    async with db._session_factory() as session:
        for table in TABLES_TO_CLEAR:
            try:
                result = await session.execute(text(f"DELETE FROM {table}"))
                count = result.rowcount
                try:
                    await session.execute(text(f"DELETE FROM sqlite_sequence WHERE name='{table}'"))
                except Exception:
                    pass
                logger.info(f"  [sqlalchemy] {table}: удалено {count} строк")
            except Exception as e:
                logger.warning(f"  [sqlalchemy] {table}: пропущено ({e})")
        await session.commit()

    # --- 2. Прямая очистка всех SQLite файлов ---
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel_path in ["signals.db", os.path.join("data", "signals.db")]:
        full = os.path.join(root, rel_path)
        _reset_sqlite_db(full)

    # --- 3. In-memory state ---
    from strategy.scenario_memory import scenario_memory
    scenario_memory.stats.clear()
    scenario_memory.records.clear()
    logger.info("  scenario_memory: сброшено")

    import scheduler.circuit_breaker as cb
    cb._cb_loss_count = 0
    cb._cb_paused_until = None
    cb._cb_last_check = None
    cb._cb_last_activation_time = None
    logger.info("  circuit_breaker: сброшен")

    from risk.daily_limits import daily_limits, DailyLimitsState
    daily_limits._state = DailyLimitsState()
    daily_limits._last_reset_date = None
    logger.info("  daily_limits: сброшены")

    import scheduler.scanner as scanner
    scanner._ema_spread_history.clear()
    scanner._dynamic_graphs.clear()
    scanner._dynamic_theses.clear()
    scanner._dynamic_bar_counters.clear()
    logger.info("  scanner caches: очищены")

    import scheduler.outcome_tracker as ot
    ot._symbol_fail_count.clear()
    ot._symbol_cooldown_until.clear()
    logger.info("  outcome_tracker caches: очищены")

    from liquidity.ob_state import _ob_registry, _fvg_registry
    _ob_registry.clear()
    _fvg_registry.clear()
    logger.info("  OB/FVG state trackers: очищены")

    logger.info("=== СБРОС ЗАВЕРШЁН ===")


if __name__ == "__main__":
    asyncio.run(reset())
