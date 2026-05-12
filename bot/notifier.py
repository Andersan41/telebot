"""
bot/notifier.py — Отправка сигналов в Telegram канал
"""
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
from loguru import logger
from config.settings import config
from strategy.signal_engine import SignalResult

_bot: Bot = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=config.telegram.token)
    return _bot


async def send_signal(result: SignalResult):
    """Отправляем сигнал в канал"""
    if not config.telegram.channel_id:
        logger.warning("TELEGRAM_CHANNEL_ID not set, skipping notification")
        return

    try:
        bot = get_bot()
        text = result.format_message()
        await bot.send_message(
            chat_id=config.telegram.channel_id,
            text=text,
            parse_mode=ParseMode.HTML,
        )
        logger.info(f"Signal sent to channel: {result.signal} {result.symbol} {result.timeframe}")
    except TelegramError as e:
        logger.error(f"Telegram send error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error sending signal: {e}", exc_info=True)


async def send_error_alert(message: str):
    """Отправляем уведомление об ошибке администраторам"""
    if not config.telegram.admin_ids:
        return
    try:
        bot = get_bot()
        for admin_id in config.telegram.admin_ids:
            await bot.send_message(
                chat_id=admin_id,
                text=f"⚠️ <b>Ошибка бота:</b>\n<code>{message}</code>",
                parse_mode=ParseMode.HTML,
            )
    except Exception as e:
        logger.error(f"Error sending admin alert: {e}")
