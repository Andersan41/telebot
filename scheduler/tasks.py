"""
scheduler/tasks.py — APScheduler задачи

Параметры расписания берутся из config.scheduler (hot-reload safe).
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from config.settings import config
from scheduler.scanner import run_scan_cycle


class TaskScheduler:
    def __init__(self, notify_callback):
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._notify_callback = notify_callback

    def setup(self):
        """Настраиваем расписание.

        Единый джоб запускается каждые 15 минут (`scan_minutes` из конфига)
        и сканирует все primary_timeframes. Cooldown 45 мин защищает от дублей.
        """
        sc = config.scheduler
        self._scheduler.add_job(
            self._scan_job,
            CronTrigger(minute=sc.scan_minutes),
            id="scan_all_tfs",
            name="Scan all primary timeframes",
            max_instances=1,
            coalesce=True,
        )
        logger.info("Scheduler configured: scanning all TFs every 15 min")

    async def _scan_job(self, timeframes: list[str] | None = None):
        logger.info(f"Scheduler triggered: starting scan (tfs={timeframes})")
        try:
            from bot.notifier import send_signal_blocked
            await run_scan_cycle(
                self._notify_callback,
                blocked_callback=send_signal_blocked,
                timeframes=timeframes,
            )
        except Exception as e:
            logger.error(f"Scan job error: {e}", exc_info=True)

    def start(self):
        self._scheduler.start()
        logger.info("Scheduler started")

    def stop(self):
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
