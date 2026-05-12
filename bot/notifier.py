"""
bot/notifier.py — Отправка сигналов в Telegram канал
"""
import html
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
from loguru import logger
from config.settings import config
from strategy.signal_engine import SignalResult
from context.scorer import ContextVerdict

_bot: Bot = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        _bot = Bot(token=config.telegram.token)
    return _bot


def format_context_block(verdict: ContextVerdict) -> str:
    """Форматирует контекстный блок для Telegram сообщения."""
    verdict_emoji = {
        "CONFIRMED": "✅",
        "WEAK": "🟡",
        "CONFLICTED": "⚠️",
        "BLOCKED": "🚫",
    }
    emoji = verdict_emoji.get(verdict.verdict, "❓")

    lines = [f"\n📊 <b>Контекст рынка:</b>"]

    snap = verdict.snapshot
    if snap is not None:
        if snap.fear_greed_value is not None:
            fg_emoji = "⚠️" if snap.fear_greed_value < 25 or snap.fear_greed_value > 75 else "😐"
            lines.append(
                f"├ Fear & Greed: {snap.fear_greed_value} ({html.escape(snap.fear_greed_label or '')}) {fg_emoji}"
            )
        if snap.funding_rate is not None:
            fr = snap.funding_rate * 100
            fr_emoji = "✅" if (fr < 0) else "⚠️"
            lines.append(f"├ Funding: {fr:.3f}% {fr_emoji}")
        if snap.long_short_ratio is not None:
            ls_emoji = "✅" if snap.long_short_ratio < 0.7 else "⚠️"
            lines.append(f"├ Long/Short: {snap.long_short_ratio:.2f} {ls_emoji}")
        if snap.open_interest_delta is not None:
            oi_emoji = "✅" if snap.open_interest_delta > 0 else "⚠️"
            lines.append(f"├ OI: +{snap.open_interest_delta:.1f}% {oi_emoji}")
        if snap.news_sentiment_score is not None:
            if snap.news_sentiment_score > 0.2:
                news_emoji = "😊"
                news_label = "позитивные"
            elif snap.news_sentiment_score < -0.2:
                news_emoji = "😟"
                news_label = "негативные"
            else:
                news_emoji = "😐"
                news_label = "нейтральные"
            lines.append(f"└ Новости: {news_label} {news_emoji}")

    lines.append(
        f"\n🔍 Вердикт: {verdict.verdict} "
        f"(уверенность {verdict.confidence:.0%})"
    )

    if verdict.supporting:
        for s in verdict.supporting:
            lines.append(f"  ✅ {html.escape(s)}")

    if verdict.opposing:
        for o in verdict.opposing:
            lines.append(f"  ⚠️ {html.escape(o)}")

    return "\n".join(lines)


async def send_signal(result: SignalResult, context_verdict: ContextVerdict = None):
    """Отправляем сигнал в канал"""
    if not config.telegram.channel_id:
        logger.warning("TELEGRAM_CHANNEL_ID not set, skipping notification")
        return

    try:
        bot = get_bot()
        text = result.format_message()
        if context_verdict is not None and config.context_enabled:
            text += format_context_block(context_verdict)
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
                text=f"⚠️ <b>Ошибка бота:</b>\n<code>{html.escape(message)}</code>",
                parse_mode=ParseMode.HTML,
            )
    except Exception as e:
        logger.error(f"Error sending admin alert: {e}")
