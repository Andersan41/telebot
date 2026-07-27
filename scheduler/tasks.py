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

        1. Сканирование каждые 15 минут
        2. Ежедневный отчёт в 00:05 UTC
        3. Переобучение ML модели в 03:00 UTC
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

        # Daily report at 00:05 UTC
        self._scheduler.add_job(
            self._daily_report_job,
            CronTrigger(hour=0, minute=5),
            id="daily_report",
            name="Daily trading report",
            max_instances=1,
            coalesce=True,
        )

        # Daily ML retrain at 03:00 UTC
        self._scheduler.add_job(
            self._ml_retrain_job,
            CronTrigger(hour=3, minute=0),
            id="ml_retrain",
            name="ML model retrain",
            max_instances=1,
            coalesce=True,
        )

        logger.info("Scheduler configured: scanning every 15 min, daily report at 00:05 UTC, ML retrain at 03:00 UTC")

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

    async def _daily_report_job(self):
        logger.info("Scheduler triggered: generating daily report")
        try:
            from analytics.daily_report import generate_and_save, generate_summary
            from bot.notifier import get_bot
            from telegram.constants import ParseMode

            filepath = await generate_and_save()
            logger.info(f"Daily report saved: {filepath}")

            # Send summary to Telegram
            summary = await generate_summary()
            bot = get_bot()
            if bot and config.telegram.channel_id:
                await bot.send_message(
                    chat_id=config.telegram.channel_id,
                    text=summary,
                    parse_mode=ParseMode.HTML,
                )
                logger.info("Daily report summary sent to Telegram")
        except Exception as e:
            logger.error(f"Daily report job error: {e}", exc_info=True)

    async def _ml_retrain_job(self):
        logger.info("Scheduler triggered: ML model retrain")
        try:
            from ml.auto_retrain import retrain_ml_model
            result = await retrain_ml_model()
            if result:
                logger.info("ML model retrained successfully")
            else:
                logger.info("ML retrain skipped (insufficient data)")
        except Exception as e:
            logger.error(f"ML retrain job error: {e}", exc_info=True)

    def start(self):
        self._scheduler.start()
        logger.info("Scheduler started")

    def stop(self):
        self._scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
