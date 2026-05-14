"""
main.py — Точка входа. Запускает бота и планировщик.
"""
import asyncio
import sys
import os

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger
import config.logger  # noqa — инициализирует логгер

from telegram.ext import Application
from config.settings import config
from data.exchange_client import exchange_client
from storage.database import db
from bot.handlers import register_handlers
from bot.notifier import send_signal, send_error_alert
from scheduler.tasks import TaskScheduler


async def main():
    logger.info("=" * 60)
    logger.info("  Trading Signal Bot starting...")
    logger.info("=" * 60)

    # Проверяем обязательные переменные
    if not config.telegram.token:
        logger.error("TELEGRAM_BOT_TOKEN is not set! Check .env file.")
        sys.exit(1)

    # Инициализируем БД
    await db.init()

    # Подключаемся к бирже
    await exchange_client.connect()

    # Создаём Telegram Application
    app = Application.builder().token(config.telegram.token).build()
    register_handlers(app)

    # Настраиваем планировщик
    scheduler = TaskScheduler(notify_callback=send_signal)
    scheduler.setup()
    scheduler.start()

    logger.info(f"Bot configured:")
    logger.info(f"  Exchange: {config.exchange.name}")
    logger.info(f"  Symbols: {', '.join(config.trading.symbols)}")
    logger.info(f"  Timeframes: {', '.join(config.trading.primary_timeframes)}")
    logger.info(f"  Confirmation TF: {config.trading.confirm_timeframe}")
    logger.info(f"  Channel: {config.telegram.channel_id}")

    try:
        # Запускаем бота в режиме polling
        logger.info("Starting Telegram bot (polling mode)...")
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)

        logger.info("✅ Bot is running. Press Ctrl+C to stop.")

        # Держим event loop живым
        while True:
            await asyncio.sleep(3600)

    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown signal received")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        await send_error_alert(str(e))
    finally:
        logger.info("Shutting down...")
        scheduler.stop()
        await exchange_client.close()
        if app.running:
            await app.stop()
        await app.shutdown()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        logger.error(f"Fatal: {e}", exc_info=True)
        sys.exit(1)
