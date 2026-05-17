"""
bot/menu.py — Inline keyboard navigation menu
Adapted from test_bingx/menu.py for python-telegram-bot v20.x
"""
import html
import asyncio
from typing import Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from loguru import logger

from config.settings import config, get_active_symbols
from indicators.engine import indicator_engine, IndicatorValues
from strategy.signal_engine import signal_engine, SignalType, SignalResult
from strategy.levels import get_support_resistance, validate_levels_vs_trade
from data.exchange_client import exchange_client
from context.analyzer import context_engine
from context.scorer import context_scorer

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

        # --- Подтверждение на confirm_tf ---
        confirm_tf = cfg.confirm_timeframe
        entry_price = result.close
        if result.is_actionable and confirm_tf and confirm_tf != primary_tf:
            ind_confirm = await _get_indicators(symbol, confirm_tf)
            if ind_confirm is not None:
                confirm_result = signal_engine.evaluate(ind_confirm)
                if confirm_result.signal == result.signal:
                    entry_price = ind_confirm.close
                    result._confirmed_tf = confirm_tf
                    result.reasons.append(f"✅ Подтверждение на {confirm_tf}")
                else:
                    result.reasons.append(f"❌ {confirm_tf}: {confirm_result.signal.value} — не подтверждено")

        result.entry_price = entry_price

        # --- Уровни S/R ---
        sr_levels = {}
        for sr_tf in ['1h', '4h']:
            try:
                sr_df = await exchange_client.fetch_ohlcv(symbol, sr_tf, limit=100)
                if sr_df is not None and len(sr_df) > 0:
                    levels = get_support_resistance(sr_df, entry_price)
                    if levels['resistance'] or levels['support']:
                        sr_levels[sr_tf] = levels
            except Exception as e:
                logger.warning(f"S/R levels error {symbol} {sr_tf}: {e}")

        if sr_levels:
            result.sr_levels = sr_levels
            is_buy = result.signal == SignalType.BUY
            result.level_warnings = validate_levels_vs_trade(
                sr_levels, entry_price, result.sl, result.tp, is_buy
            )

        # --- Рыночный контекст ---
        if config.context_enabled and result.is_actionable:
            try:
                snapshot = await asyncio.wait_for(
                    context_engine.get_snapshot(symbol),
                    timeout=10.0,
                )
                context_verdict = context_scorer.score(result.signal.value, snapshot)
                result._context_score = context_verdict.score

                snap = context_verdict.snapshot
                if snap:
                    ctx_items = []
                    if snap.fear_greed_value is not None:
                        fg_score = context_scorer._score_fear_greed(snap.fear_greed_value, result.signal.value)
                        fg_emoji = "✅" if fg_score > 0 else ("⚠️" if fg_score == 0 else "🔴")
                        ctx_items.append(f"{fg_emoji} Fear & Greed: {snap.fear_greed_value} ({snap.fear_greed_label})")
                    if snap.funding_rate is not None:
                        fr_score = context_scorer._score_funding_rate(snap.funding_rate, result.signal.value)
                        fr_emoji = "✅" if fr_score > 0 else ("⚠️" if fr_score == 0 else "🔴")
                        ctx_items.append(f"{fr_emoji} Funding: {snap.funding_rate * 100:.3f}%")
                    if snap.long_short_ratio is not None:
                        ls_score = context_scorer._score_long_short(snap.long_short_ratio, result.signal.value)
                        ls_emoji = "✅" if ls_score > 0 else ("⚠️" if ls_score == 0 else "🔴")
                        ctx_items.append(f"{ls_emoji} Long/Short: {snap.long_short_ratio:.2f}")
                    if snap.open_interest_delta is not None:
                        oi_score = context_scorer._score_oi(snap.open_interest_delta, result.signal.value)
                        oi_emoji = "✅" if oi_score > 0 else ("⚠️" if oi_score == 0 else "🔴")
                        ctx_items.append(f"{oi_emoji} OI: {snap.open_interest_delta:+.1f}%")
                    result._context_items = ctx_items
            except asyncio.TimeoutError:
                logger.warning(f"Context timeout for {symbol}")
            except Exception as e:
                logger.warning(f"Context error for {symbol}: {e}")

        # --- Формируем сообщение через format_message() ---
        text = result.format_message()

        # --- Добавляем ссылку на TradingView ---
        chart_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{ind.symbol.replace('/', '')}"
        text += f"\n\n📈 <a href='{chart_url}'>Открыть график</a>"

        logger.debug(f"Do_full_analysis output for {symbol}:\n{text}")
        return text
    except Exception as e:
        logger.error(f"Analysis error {symbol}: {e}", exc_info=True)
        return f"❌ Ошибка анализа <b>{html.escape(symbol)}</b>: {e}"


async def _indicator_view(symbol: str) -> str:
    try:
        ind = await _get_indicators(symbol, "1h")
        if ind is None:
            return f"❌ Не удалось получить данные для <b>{html.escape(symbol)}</b>"

        result = signal_engine.evaluate(ind)
        result.entry_price = result.close

        # Уровни S/R (только 1h для компактности)
        try:
            sr_df = await exchange_client.fetch_ohlcv(symbol, '1h', limit=100)
            if sr_df is not None and len(sr_df) > 0:
                levels = get_support_resistance(sr_df, result.close)
                if levels['resistance'] or levels['support']:
                    result.sr_levels = {'1h': levels}
        except Exception as e:
            logger.warning(f"S/R levels error {symbol}: {e}")

        # Рыночный контекст
        if config.context_enabled and result.is_actionable:
            try:
                snapshot = await asyncio.wait_for(
                    context_engine.get_snapshot(symbol),
                    timeout=10.0,
                )
                context_verdict = context_scorer.score(result.signal.value, snapshot)
                result._context_score = context_verdict.score

                snap = context_verdict.snapshot
                if snap:
                    ctx_items = []
                    if snap.fear_greed_value is not None:
                        fg_score = context_scorer._score_fear_greed(snap.fear_greed_value, result.signal.value)
                        fg_emoji = "✅" if fg_score > 0 else ("⚠️" if fg_score == 0 else "🔴")
                        ctx_items.append(f"{fg_emoji} Fear & Greed: {snap.fear_greed_value} ({snap.fear_greed_label})")
                    if snap.funding_rate is not None:
                        fr_score = context_scorer._score_funding_rate(snap.funding_rate, result.signal.value)
                        fr_emoji = "✅" if fr_score > 0 else ("⚠️" if fr_score == 0 else "🔴")
                        ctx_items.append(f"{fr_emoji} Funding: {snap.funding_rate * 100:.3f}%")
                    if snap.long_short_ratio is not None:
                        ls_score = context_scorer._score_long_short(snap.long_short_ratio, result.signal.value)
                        ls_emoji = "✅" if ls_score > 0 else ("⚠️" if ls_score == 0 else "🔴")
                        ctx_items.append(f"{ls_emoji} Long/Short: {snap.long_short_ratio:.2f}")
                    if snap.open_interest_delta is not None:
                        oi_score = context_scorer._score_oi(snap.open_interest_delta, result.signal.value)
                        oi_emoji = "✅" if oi_score > 0 else ("⚠️" if oi_score == 0 else "🔴")
                        ctx_items.append(f"{oi_emoji} OI: {snap.open_interest_delta:+.1f}%")
                    result._context_items = ctx_items
            except asyncio.TimeoutError:
                logger.warning(f"Context timeout for {symbol}")
            except Exception as e:
                logger.warning(f"Context error for {symbol}: {e}")

        text = result.format_message()

        chart_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{ind.symbol.replace('/', '')}"
        text += f"\n\n📈 <a href='{chart_url}'>Открыть график</a>"

        return text
    except Exception as e:
        logger.error(f"Indicator view error {symbol}: {e}")
        return f"❌ Ошибка для <b>{html.escape(symbol)}</b>: {e}"


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
