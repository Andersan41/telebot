"""
bot/menu.py — Inline keyboard navigation menu
Adapted from test_bingx/menu.py for python-telegram-bot v20.x
"""
import html
from typing import Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from loguru import logger

from config.settings import config, get_active_symbols
from indicators.engine import indicator_engine, IndicatorValues
from strategy.signal_engine import signal_engine, SignalType, SignalResult
from data.exchange_client import exchange_client

WAITING: dict[int, str] = {}


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Анализ токена", callback_data="m:analyze"),
            InlineKeyboardButton("📊 Индикаторы", callback_data="m:pick_token"),
        ],
        [
            InlineKeyboardButton("📡 Авто-скан всех", callback_data="m:scan_all"),
            InlineKeyboardButton("⚙️ Настройки", callback_data="m:settings"),
        ],
    ])


def token_list_keyboard(cb_prefix: str = "token") -> InlineKeyboardMarkup:
    symbols = get_active_symbols()
    rows = []
    for i in range(0, len(symbols), 3):
        row = [
            InlineKeyboardButton(
                s.replace("/USDT", ""),
                callback_data=f"{cb_prefix}:{s}"
            )
            for s in symbols[i:i+3]
        ]
        rows.append(row)
    if cb_prefix == "analyze":
        rows.append([InlineKeyboardButton("✏️ Свой токен", callback_data="m:custom_token")])
    rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="m:back")])
    return InlineKeyboardMarkup(rows)


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Главное меню", callback_data="m:back")]
    ])


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False) -> None:
    text = (
        "📡 <b>Trading Signal Bot</b>\n\n"
        f"Отслеживаю <b>{len(get_active_symbols())}</b> токенов\n"
        f"Таймфреймы: <b>{', '.join(config.trading.primary_timeframes)}</b>\n"
        f"Подтверждение: <b>{config.trading.confirm_timeframe}</b>\n"
        f"Cooldown: <b>{config.signal_cooldown_minutes} мин</b>"
    )
    kb = main_menu_keyboard()
    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id
    message_id = query.message.message_id

    from bot.rate_limit import get_limiter
    limiter = get_limiter(update.effective_user.id)
    if not limiter.has_capacity():
        await query.answer("⏳ Слишком часто, подожди 10 секунд", show_alert=True)
        return

    await query.answer()

    async with limiter:
        if data == "m:back":
            await send_main_menu(update, context, edit=True)
            return

        if data == "m:analyze":
            kb = token_list_keyboard("analyze")
            await query.edit_message_text(
                "✏️ Введите тикер токена (например: <b>BTC</b> или <b>BTCUSDT</b>):\n\n"
                "Или выберите из списка ниже:",
                reply_markup=kb, parse_mode=ParseMode.HTML
            )
            return

        if data == "m:custom_token":
            WAITING[chat_id] = "analyze"
            await query.edit_message_text(
                "✏️ <b>Анализ своего токена</b>\n\n"
                "Введите тикер токена, например:\n"
                "  • <code>BTC</code>\n"
                "  • <code>BTCUSDT</code>\n"
                "  • <code>ETH/USDT</code>\n\n"
                "Если не указана пара — добавится /USDT.",
                reply_markup=back_keyboard(), parse_mode=ParseMode.HTML
            )
            return

        if data == "m:pick_token":
            await query.edit_message_text(
                "Выберите токен:", reply_markup=token_list_keyboard("token")
            )
            return

        if data == "m:scan_all":
            await query.edit_message_text(
                f"⏳ Полный анализ {len(get_active_symbols())} токенов…",
                reply_markup=None
            )
            text = await _do_scan_all()
            await query.edit_message_text(text, reply_markup=back_keyboard(), parse_mode=ParseMode.HTML)
            return

        if data == "m:settings":
            text = _format_settings()
            await query.edit_message_text(text, reply_markup=back_keyboard(), parse_mode=ParseMode.HTML)
            return

        if data.startswith("analyze:"):
            symbol = data.split(":", 1)[1]
            await query.edit_message_text(
                f"⏳ Анализирую <b>{symbol}</b>…", parse_mode=ParseMode.HTML
            )
            result = await _do_full_analysis(symbol)
            try:
                await query.edit_message_text(result, reply_markup=back_keyboard(), parse_mode=ParseMode.HTML)
            except Exception as e:
                logger.error(f"HTML edit error for {symbol}: {e}")
                logger.error(f"Result text (first 500 chars): {result[:500]}")
                await query.edit_message_text(
                    result.replace("<", "&lt;").replace(">", "&gt;"),
                    reply_markup=back_keyboard(), parse_mode=ParseMode.HTML
                )
            return

        if data.startswith("token:"):
            symbol = data.split(":", 1)[1]
            await query.edit_message_text(
                f"⏳ Индикаторы для <b>{symbol}</b>…", parse_mode=ParseMode.HTML
            )
            text = await _indicator_view(symbol)
            await query.edit_message_text(text, reply_markup=back_keyboard(), parse_mode=ParseMode.HTML)
            return


async def handle_menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    chat_id = msg.chat_id
    text = (msg.text or "").strip()

    if not chat_id or not text:
        return

    if text.split("@")[0] in ("/start", "/menu"):
        await send_main_menu(update, context)
        return

    state = WAITING.pop(chat_id, None)
    if not state:
        return

    if state == "analyze":
        symbol = _normalize_symbol(text)
        m = await context.bot.send_message(chat_id, f"⏳ Анализирую <b>{symbol}</b>…", parse_mode=ParseMode.HTML)
        result = await _do_full_analysis(symbol)
        try:
            await context.bot.edit_message_text(
                result, chat_id=chat_id, message_id=m.message_id,
                reply_markup=back_keyboard(), parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"handle_menu_message HTML edit error for {symbol}: {e}")
            logger.error(f"Result text (first 500 chars): {result[:500]}")
            await context.bot.send_message(chat_id, result, reply_markup=back_keyboard())


def _normalize_symbol(text: str) -> str:
    s = text.upper().strip()
    if "/USDT" in s:
        return s.split("/")[0] + "/USDT"
    if s.endswith("USDT"):
        return s[:-4] + "/USDT"
    return s + "/USDT"


def _fmt_price(p: float) -> str:
    if p is None:
        return "—"
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:.4f}"
    if p >= 0.01:
        return f"{p:.6f}"
    return f"{p:.8f}"


def _format_settings() -> str:
    cfg = config.trading
    lines = [
        "⚙️ <b>Настройки бота</b>\n",
        f"📊 Символов: <b>{len(get_active_symbols())}</b>",
        f"⏱ Основные ТФ: <b>{', '.join(config.trading.primary_timeframes)}</b>",
        f"🔁 Подтверждение: <b>{config.trading.confirm_timeframe}</b>",
        f"⏰ Cooldown: <b>{config.signal_cooldown_minutes} мин</b>\n",
        "📐 <b>Индикаторы:</b>",
        f"  EMA: {cfg.ema_fast}/{cfg.ema_slow}/{cfg.ema_trend}",
        f"  RSI: period={cfg.rsi_period}, OB&gt;{cfg.rsi_overbought}, OS&lt;{cfg.rsi_oversold}",
        f"  MACD: {cfg.macd_fast}/{cfg.macd_slow}/{cfg.macd_signal}",
        f"  ADX: period={cfg.adx_period}, min={cfg.adx_min}",
        f"  ATR: period={cfg.atr_period}  SL×{cfg.atr_multiplier_sl}  TP×{cfg.atr_multiplier_tp}",
        f"  SuperTrend: {cfg.supertrend_period}/{cfg.supertrend_multiplier}",
        f"  Volume: ×{cfg.volume_factor} SMA",
    ]
    return "\n".join(lines)


async def _get_indicators(symbol: str, timeframe: str) -> Optional[IndicatorValues]:
    df = await exchange_client.fetch_ohlcv(symbol, timeframe, limit=config.trading.candles_limit)
    if df is None:
        return None
    return indicator_engine.calculate(df, symbol, timeframe)


async def _do_full_analysis(symbol: str) -> str:
    try:
        cfg = config.trading
        primary_tf = cfg.primary_timeframes[0]
        ind = await _get_indicators(symbol, primary_tf)
        if ind is None:
            return f"❌ Не удалось получить данные для <b>{html.escape(symbol)}</b>\n\nПроверьте тикер (пример: BTC/USDT)"
        result = signal_engine.evaluate(ind)

        # --- 15M-подтверждение (зеркало логики scheduler.scanner.scan_symbol) ---
        confirm_tf = cfg.confirm_timeframe
        confirm_status = "—"
        if result.is_actionable and confirm_tf and confirm_tf != primary_tf:
            ind_confirm = await _get_indicators(symbol, confirm_tf)
            if ind_confirm is None:
                confirm_status = f"⚠️ нет данных {confirm_tf}"
            else:
                confirm_result = signal_engine.evaluate(ind_confirm)
                if confirm_result.signal == result.signal:
                    confirm_status = f"✅ {confirm_tf} подтверждает"
                else:
                    confirm_status = (
                        f"❌ {confirm_tf}: {confirm_result.signal.value}"
                    )

        lines = []

        emoji = "🟢" if result.signal == SignalType.BUY else ("🔴" if result.signal == SignalType.SELL else "⚪")
        lines.append(f"{emoji} <b>{ind.symbol}</b> — {result.signal.value}")

        lines.append(f"\n💰 Цена: <b>{_fmt_price(ind.close)}</b>   ⏱ {ind.timeframe}")

        lines.append(f"\n📐 <b>EMA:</b>")
        lines.append(f"  {cfg.ema_fast}: {_fmt_price(ind.ema_fast)}  {cfg.ema_slow}: {_fmt_price(ind.ema_slow)}  {cfg.ema_trend}: {_fmt_price(ind.ema_trend)}")
        lines.append(f"  EMA alignment: {'бычье ↑' if ind.ema_bullish_alignment else 'медвежье ↓' if ind.ema_bearish_alignment else 'смешанное'}")

        lines.append(f"\n📊 RSI({config.trading.rsi_period}): <b>{ind.rsi:.1f}</b>")

        lines.append(f"\n⚡ <b>MACD:</b>")
        lines.append(f"  MACD: {ind.macd:.4f}  Signal: {ind.macd_signal:.4f}")
        hist_arrow = "↑" if ind.macd_hist > 0 else "↓"
        lines.append(f"  Hist: {ind.macd_hist:+.6f}  {hist_arrow}")

        lines.append(f"\n📈 ADX: <b>{ind.adx:.1f}</b>  +DI: {ind.dmi_plus:.1f}  -DI: {ind.dmi_minus:.1f}")
        if ind.trend_is_strong:
            lines.append(f"  ✅ Сильный тренд")
        else:
            lines.append(f"  ❌ Флэт (ADX &lt; {config.trading.adx_min})")

        lines.append(f"\n🔁 <b>Подтверждение {confirm_tf}:</b> {confirm_status}")

        lines.append(f"\n🌡 ATR: <b>{_fmt_price(ind.atr)}</b>")

        st_emoji = "🟢" if ind.supertrend_bullish else "🔴"
        st_label = "бычий ↑" if ind.supertrend_bullish else "медвежий ↓"
        lines.append(f"\n📉 SuperTrend: {st_emoji} {st_label}  ({_fmt_price(ind.supertrend)})")

        lines.append(f"\n📦 <b>Объём:</b>")
        lines.append(f"  Текущий: {ind.volume:,.0f}  SMA: {ind.volume_sma:,.0f}")
        vol_ratio = ind.volume / ind.volume_sma if ind.volume_sma else 1
        vol_ok = vol_ratio >= config.trading.volume_factor
        lines.append(f"  {'✅' if vol_ok else '❌'} ×{vol_ratio:.1f} от SMA (нужно ×{config.trading.volume_factor})")

        if result.is_actionable and result.sl and result.tp:
            lines.append(f"\n🛑 <b>SL:</b> {_fmt_price(result.sl)}")
            lines.append(f"🎯 <b>TP:</b> {_fmt_price(result.tp)}")
            rr = abs(result.tp - ind.close) / abs(ind.close - result.sl)
            lines.append(f"⚖️ <b>R/R:</b> 1:{rr:.2f}")

        if result.reasons:
            lines.append(f"\n📋 <b>Причины:</b>")
            for r in result.reasons:
                lines.append(f"  • {html.escape(r)}")

        if result.score > 0:
            lines.append(f"\n💪 <b>Сила сигнала:</b> {'⭐' * min(result.score, 5)} ({result.score}/8)")

        chart_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{ind.symbol.replace('/', '')}"
        lines.append(f"\n📈 <a href='{chart_url}'>Открыть график</a>")

        text = "\n".join(lines)
        logger.debug(f"Do_full_analysis output for {symbol}:\n{text}")
        return text
    except Exception as e:
        logger.error(f"Analysis error {symbol}: {e}", exc_info=True)
        return f"❌ Ошибка анализа <b>{html.escape(symbol)}</b>: {e}"


async def _indicator_view(symbol: str) -> str:
    try:
        ind = await _get_indicators(symbol, "1h")
        if ind is None:
            return f"❌ Не удалось получить данные для <b>{symbol}</b>"
        result = signal_engine.evaluate(ind)
        return _format_indicator_view(ind, result)
    except Exception as e:
        logger.error(f"Indicator view error {symbol}: {e}")
        return f"❌ Ошибка для {symbol}: {e}"


def _format_indicator_view(ind: IndicatorValues, result: SignalResult) -> str:
    emoji = "🟢" if result.signal == SignalType.BUY else ("🔴" if result.signal == SignalType.SELL else "⚪")
    signal_word = result.signal.value
    cfg = config.trading

    lines = [
        f"{emoji} <b>{ind.symbol}</b> — {signal_word}",
        f"💰 Цена: <b>{_fmt_price(ind.close)}</b>   ⏱ {ind.timeframe}",
        "",
        "📐 <b>EMA:</b>",
        f"  Fast({cfg.ema_fast}): <b>{_fmt_price(ind.ema_fast)}</b>",
        f"  Slow({cfg.ema_slow}): <b>{_fmt_price(ind.ema_slow)}</b>",
        f"  Trend({cfg.ema_trend}): <b>{_fmt_price(ind.ema_trend)}</b>",
        "",
        f"📊 RSI({cfg.rsi_period}): <b>{ind.rsi:.1f}</b>",
        "",
        "⚡ <b>MACD:</b>",
        f"  MACD: {ind.macd:.4f}",
        f"  Signal: {ind.macd_signal:.4f}",
        f"  Hist: {ind.macd_hist:+.4f}",
        "",
        f"📈 ADX: <b>{ind.adx:.1f}</b>   +DI: {ind.dmi_plus:.1f}  -DI: {ind.dmi_minus:.1f}",
        f"🌡 ATR: <b>{_fmt_price(ind.atr)}</b>",
        f"📉 SuperTrend: {'↑ бычий' if ind.supertrend_bullish else '↓ медвежий'}",
        "",
        f"📦 Объём: <b>{ind.volume:,.0f}</b>  SMA: {ind.volume_sma:,.0f}",
    ]

    if result.is_actionable:
        if result.sl:
            lines.append(f"\n🛑 <b>SL:</b> {_fmt_price(result.sl)}")
        if result.tp:
            lines.append(f"🎯 <b>TP:</b> {_fmt_price(result.tp)}")

    if result.reasons:
        lines.append(f"\n📋 <b>Причины:</b>")
        for r in result.reasons:
            lines.append(f"  • {html.escape(r)}")

    if result.score > 0:
        lines.append(f"\n💪 <b>Сила сигнала:</b> {'⭐' * min(result.score, 5)} ({result.score}/8)")

    return "\n".join(lines)


async def _do_scan_all() -> str:
    buy = []
    sell = []
    neutral = []

    for symbol in get_active_symbols():
        try:
            ind = await _get_indicators(symbol, config.trading.primary_timeframes[0])
            if ind is None:
                neutral.append(f"⚠️ {symbol.replace('/USDT', '')}: нет данных")
                continue
            result = signal_engine.evaluate(ind)
            name = symbol.replace("/USDT", "").ljust(6)
            line = f"{name} RSI={ind.rsi:5.1f}  ADX={ind.adx:4.0f}"
            if result.signal == SignalType.BUY:
                buy.append(f"🟢 {line}")
            elif result.signal == SignalType.SELL:
                sell.append(f"🔴 {line}")
            else:
                neutral.append(f"⚪ {line}")
        except Exception as e:
            neutral.append(f"⚠️ {symbol.replace('/USDT', '')}: ошибка")
            logger.warning(f"Scan error {symbol}: {e}")

    lines = [f"📡 <b>Авто-скан {len(get_active_symbols())} токенов</b>\n"]
    if buy:
        lines.append("🟢 <b>Покупка:</b>")
        lines.extend(f"  {r}" for r in buy)
    if sell:
        lines.append("\n🔴 <b>Продажа:</b>")
        lines.extend(f"  {r}" for r in sell)
    if neutral:
        lines.append("\n⚪ <b>Нейтральные:</b>")
        lines.extend(f"  {r}" for r in neutral)

    return "\n".join(lines)
