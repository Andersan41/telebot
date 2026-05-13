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

        - 1H таймфрейм: каждый час в `:02` минуты (после закрытия часовой свечи)
        - 4H таймфрейм: каждые 4 часа в `:05` (после закрытия 4-часовой свечи)

        Каждый джоб запускает `run_scan_cycle` только для своего таймфрейма,
        чтобы не дублировать работу.
        """
        self._scheduler.add_job(
            self._scan_job,
            CronTrigger(minute=2),
            id="hourly_scan",
            name="Hourly market scan (1H)",
            max_instances=1,
            coalesce=True,
            kwargs={"timeframes": ["1h"]},
        )
        self._scheduler.add_job(
            self._scan_job,
            CronTrigger(hour="0,4,8,12,16,20", minute=5),
            id="4h_scan",
            name="4H market scan",
            max_instances=1,
            coalesce=True,
            kwargs={"timeframes": ["4h"]},
        )
        logger.info("Scheduler jobs configured")

    async def _scan_job(self, timeframes: list[str] | None = None):
        logger.info(f"Scheduler triggered: starting scan (tfs={timeframes})")
        try:
            await run_scan_cycle(self._notify_callback, timeframes=timeframes)
        except Exception as e:
            logger.error(f"Scan job error: {e}", exc_info=True)

    def start(self):
        self._scheduler.start()
        logger.info("Scheduler started")

    def stop(self):
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
