"""
scheduler/tasks.py — APScheduler задачи
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from scheduler.scanner import run_scan_cycle


class TaskScheduler:
    def __init__(self, notify_callback):
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._notify_callback = notify_callback

    def setup(self):
        """Настраиваем расписание.
        - 1H таймфрейм: запускаем каждый час в 02 минуты (после закрытия свечи)
        - 4H таймфрейм: каждые 4 часа
        - Подтверждение 15M встроено в логику scanner.py
        """
        self._scheduler.add_job(
            self._scan_job,
            CronTrigger(minute=2),   # Каждый час на 2-й минуте
            id="hourly_scan",
            name="Hourly market scan (1H)",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self._scan_job,
            CronTrigger(hour="0,4,8,12,16,20", minute=5),  # Каждые 4 часа на 5-й минуте
            id="4h_scan",
            name="4H market scan",
            max_instances=1,
            coalesce=True,
        )
        logger.info("Scheduler jobs configured")

    async def _scan_job(self):
        logger.info("Scheduler triggered: starting scan")
        try:
            await run_scan_cycle(self._notify_callback)
        except Exception as e:
            logger.error(f"Scan job error: {e}", exc_info=True)

    def start(self):
        self._scheduler.start()
        logger.info("Scheduler started")

    def stop(self):
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
