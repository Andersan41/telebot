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

from config.settings import config, get_active_symbols, FILTER_TOGGLE_KEYS, FILTER_PARAM_KEYS, reload_filter_toggles
from indicators.engine import indicator_engine, IndicatorValues
from strategy.signal_engine import signal_engine, SignalType, SignalResult
from strategy.levels import get_support_resistance, validate_levels_vs_trade
from data.exchange_client import exchange_client
from context.analyzer import context_engine
from context.scorer import context_scorer, ContextVerdict
from risk.market_regime import RegimeDetector, MarketRegime

WAITING: dict[int, str] = {}


def main_menu_keyboard() -> InlineKeyboardMarkup:
    block_icon = "🔇" if config.signal_block_notify else "🔇"
    block_status = "ВКЛ" if config.signal_block_notify else "ВЫКЛ"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔍 Анализ токена", callback_data="m:analyze"),
            InlineKeyboardButton("📊 Индикаторы", callback_data="m:pick_token"),
        ],
        [
            InlineKeyboardButton("📡 Авто-скан всех", callback_data="m:scan_all"),
            InlineKeyboardButton(f"{block_icon} Signal block", callback_data="m:signal_block"),
        ],
        [
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
    if cb_prefix == "token":
        rows.append([InlineKeyboardButton("✏️ Свой токен", callback_data="m:custom_token_indicators")])
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

        if data == "m:custom_token_indicators":
            WAITING[chat_id] = "indicators"
            await query.edit_message_text(
                "✏️ <b>Индикаторы своего токена</b>\n\n"
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
                "✏️ Введите тикер токена (например: <b>BTC</b> или <b>BTCUSDT</b>):\n\n"
                "Или выберите из списка ниже:",
                reply_markup=token_list_keyboard("token"), parse_mode=ParseMode.HTML
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
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔧 Фильтры сигналов", callback_data="m:sf")],
                [InlineKeyboardButton("📐 Параметры индикаторов", callback_data="m:sf_params_list")],
                [InlineKeyboardButton("◀️ Главное меню", callback_data="m:back")],
            ])
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return

        if data == "m:signal_block":
            block_status = "🟢 ВКЛ" if config.signal_block_notify else "🔴 ВЫКЛ"
            text = (
                f"🔇 <b>Signal block</b>\n\n"
                f"Уведомления о заблокированных сигналах: {block_status}\n\n"
                f"При включении бот отправляет в канал краткий анализ, "
                f"когда сигнал проходит часть условий, "
                f"но блокируется на одном из финальных этапов "
                f"(MTF, BTC/ETH корреляция, контекст, риск-фильтры и т.д.)."
            )
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        f"{'🔴 Выключить' if config.signal_block_notify else '🟢 Включить'}",
                        callback_data="m:signal_block_toggle",
                    ),
                ],
                [InlineKeyboardButton("◀️ Главное меню", callback_data="m:back")],
            ])
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return

        if data == "m:signal_block_toggle":
            from storage.database import db
            from config.settings import reload_filter_toggles
            new_val = not config.signal_block_notify
            await db.set_setting("filter:toggle:signal_block", str(new_val).lower())
            await reload_filter_toggles()
            block_status = "🟢 ВКЛ" if config.signal_block_notify else "🔴 ВЫКЛ"
            text = (
                f"🔇 <b>Signal block</b>\n\n"
                f"Уведомления о заблокированных сигналах: {block_status}\n"
            )
            kb = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        f"{'🔴 Выключить' if config.signal_block_notify else '🟢 Включить'}",
                        callback_data="m:signal_block_toggle",
                    ),
                ],
                [InlineKeyboardButton("◀️ Главное меню", callback_data="m:back")],
            ])
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return

        if data == "m:sf":
            text, kb = _format_filters_list()
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return

        if data == "m:sf_params_list":
            text, kb = _format_indicator_params()
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return

        if data.startswith("m:sf_toggle:"):
            key = data.split(":", 2)[2]
            await _handle_filter_toggle(key)
            text, kb = _format_filters_list()
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return

        if data.startswith("m:sf_detail:"):
            key = data.split(":", 2)[2]
            text, kb = _format_filter_detail(key)
            await query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
            return

        if data.startswith("m:sf_param_set:"):
            key = data.split(":", 2)[2]
            WAITING[chat_id] = f"sf_param:{key}"
            label = FILTER_PARAM_KEYS.get(key, (key, str))[0].split(".")[-1]
            await query.edit_message_text(
                f"✏️ Введите новое значение для <b>{label}</b>:\n\n"
                f"Текущее: <code>{_get_nested_config(config, FILTER_PARAM_KEYS[key][0])}</code>",
                reply_markup=_settings_back_kb(), parse_mode=ParseMode.HTML
            )
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
                safe_text = result.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;").replace('"', "&quot;")
                await query.edit_message_text(
                    safe_text,
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
            safe_text = result.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;").replace('"', "&quot;")
            await context.bot.send_message(chat_id, safe_text, reply_markup=back_keyboard(), parse_mode=ParseMode.HTML)

    if state == "indicators":
        symbol = _normalize_symbol(text)
        m = await context.bot.send_message(chat_id, f"⏳ Индикаторы для <b>{symbol}</b>…", parse_mode=ParseMode.HTML)
        result = await _indicator_view(symbol)
        try:
            await context.bot.edit_message_text(
                result, chat_id=chat_id, message_id=m.message_id,
                reply_markup=back_keyboard(), parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"handle_menu_message indicators HTML edit error for {symbol}: {e}")
            safe_text = result.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;").replace('"', "&quot;")
            await context.bot.send_message(chat_id, safe_text, reply_markup=back_keyboard(), parse_mode=ParseMode.HTML)

    if state and state.startswith("sf_param:"):
        key = state.split(":", 1)[1]
        entry = FILTER_PARAM_KEYS.get(key)
        if entry is None:
            await context.bot.send_message(chat_id, f"❌ Неизвестный параметр: {key}")
            return
        attr_path, cast_type = entry
        try:
            value = cast_type(text)
        except (ValueError, TypeError):
            await context.bot.send_message(
                chat_id,
                f"❌ Не удалось преобразовать <code>{html.escape(text)}</code> в {cast_type.__name__}",
                parse_mode=ParseMode.HTML,
            )
            return
        from storage.database import db
        await db.set_setting(f"filter:param:{key}", str(value))
        await reload_filter_toggles()
        await context.bot.send_message(
            chat_id,
            f"✅ <b>Параметр изменён</b>\n<code>{attr_path.split('.')[-1]}</code> = {value}",
            reply_markup=_settings_back_kb(),
            parse_mode=ParseMode.HTML,
        )


def _normalize_symbol(text: str) -> str:
    s = text.upper().strip()
    if "/USDT" in s:
        return s.split("/")[0] + "/USDT"
    if s.endswith("USDT"):
        return s[:-4] + "/USDT"
    return s + "/USDT"


def _calc_trend_strength(adx: float) -> float:
    """Convert ADX value to 0-100 trend strength percentage."""
    return min(max(adx * 2.0, 0.0), 100.0)


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
    lines = [
        "⚙️ <b>Настройки бота</b>\n",
        f"📊 Символов: <b>{len(get_active_symbols())}</b>",
        f"⏱ Основные ТФ: <b>{', '.join(config.trading.primary_timeframes)}</b>",
        f"🔁 Подтверждение: <b>{config.trading.confirm_timeframe}</b>",
        f"⏰ Cooldown: <b>{config.signal_cooldown_minutes} мин</b>\n",
    ]
    return "\n".join(lines)


def _format_indicator_params() -> tuple[str, InlineKeyboardMarkup]:
    sections = {
        "EMA": ["ema_fast", "ema_slow", "ema_trend", "min_ema_spread_pct"],
        "RSI": ["rsi_period", "rsi_overbought", "rsi_oversold"],
        "MACD": ["macd_fast", "macd_slow", "macd_signal"],
        "ADX": ["adx_period", "adx_min"],
        "ATR": ["atr_period", "atr_multiplier_sl", "atr_multiplier_tp"],
        "Supertrend": ["supertrend_period", "supertrend_multiplier"],
        "Volume": ["volume_factor", "volume_sma_period"],
        "Прочее": ["min_score_for_signal", "confirm_timeframe", "signal_cooldown_minutes", "distance_filter_min_pct"],
    }

    lines = ["📐 <b>Параметры индикаторов</b>\n"]
    rows: list[list[InlineKeyboardButton]] = []

    for section_name, param_keys in sections.items():
        lines.append(f"<b>{section_name}</b>")
        row_btns = []
        for pkey in param_keys:
            entry = FILTER_PARAM_KEYS.get(pkey)
            if entry is None:
                continue
            try:
                pval = _get_nested_config(config, entry[0])
                pshort = entry[0].split(".")[-1]
                lines.append(f"  • {pshort}: <code>{pval}</code>")
                row_btns.append(
                    InlineKeyboardButton(f"✏️ {pshort}", callback_data=f"m:sf_param_set:{pkey}")
                )
            except AttributeError:
                pass
        if row_btns:
            rows.append(row_btns)
        lines.append("")

    rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="m:back")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ── Filter management ────────────────────────────────────────────────

FILTER_META: dict[str, dict] = {
    "adx_filter":      {"label": "ADX (флэт)",        "group": "signal_engine"},
    "ema_alignment":   {"label": "EMA alignment",      "group": "signal_engine"},
    "ema_spread":      {"label": "EMA spread",         "group": "signal_engine"},
    "ema_slope":       {"label": "EMA наклон",         "group": "signal_engine"},
    "trigger":         {"label": "Триггер",            "group": "signal_engine"},
    "candle_close":    {"label": "Candle close",       "group": "signal_engine"},
    "min_score":       {"label": "Min score",          "group": "signal_engine"},
    "compression":     {"label": "Компрессия",         "group": "signal_engine"},
    "confirm_tf":      {"label": "Подтверждение ТФ",   "group": "signal_engine"},
    "mtf":             {"label": "MTF alignment",      "group": "scanner"},
    "distance_filter": {"label": "Distance filter",    "group": "scanner"},
    "sr_levels":       {"label": "Уровни S/R",          "group": "scanner"},
    "tp_path":         {"label": "TP path",            "group": "scanner"},
    "btc_corr":        {"label": "BTC correlation",    "group": "scanner"},
    "eth_corr":        {"label": "ETH correlation",    "group": "scanner"},
    "volatility":      {"label": "Волатильность",      "group": "scanner"},
    "no_trade_zones":  {"label": "No-trade зоны",      "group": "scanner"},
    "dynamic_risk":    {"label": "Dynamic risk",       "group": "scanner"},
    "context":         {"label": "Контекст",           "group": "scanner"},
    "confidence_v2":   {"label": "Confidence V2",      "group": "scanner"},
}

FILTER_GROUP_LABELS = {
    "signal_engine": "🧠 Ядро сигнала",
    "scanner":       "📡 Сканер",
}


def _get_filter_status(key: str) -> bool:
    """Get current on/off status of a filter toggle."""
    entry = FILTER_TOGGLE_KEYS.get(key)
    if entry is None:
        return True
    return bool(_get_nested_config(config, entry[0]))


def _get_nested_config(obj, path: str):
    parts = path.split(".")
    current = obj
    for part in parts:
        current = getattr(current, part)
    return current


def _settings_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ Назад к фильтрам", callback_data="m:sf")],
        [InlineKeyboardButton("◀️ Главное меню", callback_data="m:back")],
    ])


def _format_filters_list() -> tuple[str, InlineKeyboardMarkup]:
    lines = ["🔧 <b>Фильтры сигналов</b>\n"]
    rows: list[list[InlineKeyboardButton]] = []
    prev_group = None

    for key, meta in FILTER_META.items():
        group = meta["group"]
        if prev_group is not None and group != prev_group:
            lines.append("")
        if prev_group != group:
            lines.append(f"\n{_get_group_label_caption(group)}")
            prev_group = group

        status = _get_filter_status(key)
        icon = "🟢" if status else "🔴"
        lines.append(f"{icon} <b>{meta['label']}</b>: {'ON' if status else 'OFF'}")

        rows.append([
            InlineKeyboardButton(
                f"{icon} {meta['label']}",
                callback_data=f"m:sf_detail:{key}"
            ),
            InlineKeyboardButton(
                "ON" if status else "OFF",
                callback_data=f"m:sf_toggle:{key}",
            ),
        ])

    rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="m:back")])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _get_group_label_caption(group: str) -> str:
    labels = {
        "signal_engine": "🧠 Ядро сигнала (signal_engine)",
        "scanner": "📡 Сканер (доп. фильтры)",
    }
    return labels.get(group, group)


def _format_filter_detail(key: str) -> tuple[str, InlineKeyboardMarkup]:
    meta = FILTER_META.get(key)
    if meta is None:
        return f"❌ Неизвестный фильтр: {key}", _settings_back_kb()

    entry = FILTER_TOGGLE_KEYS.get(key)
    if entry is None:
        return f"❌ Нет данных: {key}", _settings_back_kb()

    attr_path, _ = entry
    current_val = _get_filter_status(key)
    lines = [
        f"🔧 <b>{meta['label']}</b>\n",
        f"Группа: {FILTER_GROUP_LABELS.get(meta['group'], meta['group'])}",
        f"Состояние: {'🟢 <b>ВКЛ</b>' if current_val else '🔴 <b>ВЫКЛ</b>'}\n",
    ]

    rows = [
        [
            InlineKeyboardButton(
                f"{'🔴 Выключить' if current_val else '🟢 Включить'}",
                callback_data=f"m:sf_toggle:{key}",
            ),
        ],
    ]

    rows.append([InlineKeyboardButton("◀️ Назад к фильтрам", callback_data="m:sf")])
    rows.append([InlineKeyboardButton("◀️ Главное меню", callback_data="m:back")])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _handle_filter_toggle(key: str) -> None:
    """Toggle a filter on/off in DB and reload config."""
    entry = FILTER_TOGGLE_KEYS.get(key)
    if entry is None:
        return
    attr_path, _ = entry
    current = _get_filter_status(key)
    new_value = not current
    from storage.database import db
    await db.set_setting(f"filter:toggle:{key}", str(new_value).lower())
    await reload_filter_toggles()


async def _get_indicators(symbol: str, timeframe: str) -> Optional[IndicatorValues]:
    df = await exchange_client.fetch_ohlcv(symbol, timeframe, limit=config.trading.candles_limit)
    if df is None:
        return None
    return indicator_engine.calculate(df, symbol, timeframe)


def _detect_regime(ind: IndicatorValues, df) -> Optional[MarketRegime]:
    try:
        adx = float(ind.adx) if ind.adx is not None else 20.0
        current_atr = float(ind.atr) if ind.atr is not None else 0.0
        current_volume = float(ind.volume) if ind.volume is not None else 0.0

        if len(df) >= 10:
            atr_history = []
            for _, row in df.tail(config.risk.regime_atr_lookback).iterrows():
                atr_history.append(float(row['high'] - row['low']))
        else:
            atr_history = [current_atr] * 10

        ema_fast = float(ind.ema_fast) if ind.ema_fast is not None else 0.0
        ema_slow = float(ind.ema_slow) if ind.ema_slow is not None else 0.0
        current_spread = abs(ema_fast - ema_slow) if ema_slow > 0 else 0.0
        ema_spread_history = [current_spread] * 5

        if len(df) >= 10:
            volume_history = [float(row['volume']) for _, row in df.tail(20).iterrows()]
        else:
            volume_history = [current_volume] * 10

        detector = RegimeDetector(
            adx=adx,
            atr_history=atr_history,
            ema_spread_history=ema_spread_history,
            volume_history=volume_history,
            current_atr=current_atr,
            current_volume=current_volume,
        )
        return detector.detect()
    except Exception as e:
        logger.warning(f"Regime detection failed for {symbol}: {e}")
        return None


async def _do_full_analysis(symbol: str) -> str:
    try:
        cfg = config.trading
        primary_tf = cfg.primary_timeframes[0]

        df = await exchange_client.fetch_ohlcv(symbol, primary_tf, limit=config.trading.candles_limit)
        if df is None:
            return f"❌ Не удалось получить данные для <b>{html.escape(symbol)}</b>\n\nПроверьте тикер (пример: BTC/USDT)"

        ind = indicator_engine.calculate(df, symbol, primary_tf)
        if ind is None:
            return f"❌ Ошибка расчёта индикаторов для <b>{html.escape(symbol)}</b>"

        regime = _detect_regime(ind, df)
        result = signal_engine.evaluate(ind, regime=regime)

        # --- Подтверждение на confirm_tf ---
        confirm_tf = cfg.confirm_timeframe
        entry_price = result.close if result.close is not None else ind.close
        if entry_price is None:
            entry_price = 0.0
        entry_price = float(entry_price)

        if config.trading.confirm_tf_enabled and result.is_actionable and confirm_tf and confirm_tf != primary_tf:
            ind_confirm = await _get_indicators(symbol, confirm_tf)
            if ind_confirm is not None:
                confirm_result = signal_engine.evaluate(ind_confirm)
                if confirm_result.signal == result.signal:
                    entry_price = float(confirm_result.close if confirm_result.close is not None else ind_confirm.close)
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
            sl_val = result.sl if result.sl is not None else 0.0
            tp_val = result.tp if result.tp is not None else 0.0
            result.level_warnings = validate_levels_vs_trade(
                sr_levels, entry_price, sl_val, tp_val, is_buy
            )

        # --- Рыночный контекст ---
        context_verdict = None
        if config.context_enabled:
            try:
                snapshot = await asyncio.wait_for(
                    context_engine.get_snapshot(symbol),
                    timeout=10.0,
                )

                if result.is_actionable:
                    context_verdict = context_scorer.score(result.signal.value, snapshot)
                    result._context_score = context_verdict.score
                else:
                    context_verdict = ContextVerdict(
                        verdict="NEUTRAL",
                        confidence=0.0,
                        score=0.0,
                        snapshot=snapshot,
                    )

                snap = snapshot
                dir_for_emoji = result.signal.value if result.is_actionable else None
                if snap:
                    ctx_items = []
                    if snap.fear_greed_value is not None:
                        try:
                            fg_val = int(snap.fear_greed_value)
                            if dir_for_emoji:
                                fg_score = context_scorer._score_fear_greed(fg_val, dir_for_emoji)
                                fg_emoji = "✅" if fg_score > 0 else ("⚠️" if fg_score == 0 else "🔴")
                            else:
                                fg_emoji = "📊"
                            ctx_items.append(f"{fg_emoji} Fear & Greed: {fg_val} ({snap.fear_greed_label})")
                        except (ValueError, TypeError):
                            ctx_items.append(f"⚠️ Fear & Greed: invalid value")
                    if snap.funding_rate is not None:
                        try:
                            fr_val = float(snap.funding_rate)
                            if dir_for_emoji:
                                fr_score = context_scorer._score_funding_rate(fr_val, dir_for_emoji)
                                fr_emoji = "✅" if fr_score > 0 else ("⚠️" if fr_score == 0 else "🔴")
                            else:
                                fr_emoji = "📊"
                            ctx_items.append(f"{fr_emoji} Funding: {fr_val * 100:.3f}%")
                        except (ValueError, TypeError):
                            ctx_items.append(f"⚠️ Funding: invalid value")
                    if snap.long_short_ratio is not None:
                        try:
                            ls_val = float(snap.long_short_ratio)
                            if dir_for_emoji:
                                ls_score = context_scorer._score_long_short(ls_val, dir_for_emoji)
                                ls_emoji = "✅" if ls_score > 0 else ("⚠️" if ls_score == 0 else "🔴")
                            else:
                                ls_emoji = "📊"
                            ctx_items.append(f"{ls_emoji} Long/Short: {ls_val:.2f}")
                        except (ValueError, TypeError):
                            ctx_items.append(f"⚠️ Long/Short: invalid value")
                    if snap.open_interest_delta is not None:
                        try:
                            oi_val = float(snap.open_interest_delta)
                            if dir_for_emoji:
                                oi_score = context_scorer._score_oi(oi_val, dir_for_emoji)
                                oi_emoji = "✅" if oi_score > 0 else ("⚠️" if oi_score == 0 else "🔴")
                            else:
                                oi_emoji = "📊"
                            ctx_items.append(f"{oi_emoji} OI: {oi_val:+.1f}%")
                        except (ValueError, TypeError):
                            ctx_items.append(f"⚠️ OI: invalid value")
                    result._context_items = ctx_items
            except asyncio.TimeoutError:
                logger.warning(f"Context timeout for {symbol}")
            except Exception as e:
                logger.warning(f"Context error for {symbol}: {e}")

        # --- Формируем сообщение через format_message() ---
        text = result.format_message()

        # --- Добавляем блок контекста рынка ---
        if context_verdict is not None:
            from bot.notifier import format_context_block
            text += format_context_block(context_verdict)

        # --- Добавляем ссылку на TradingView ---
        chart_url = f"https://www.tradingview.com/chart/?symbol=BINANCE:{ind.symbol.replace('/', '')}"
        text += f"\n\n📈 <a href='{chart_url}'>Открыть график</a>"

        logger.debug(f"Do_full_analysis output for {symbol}:\n{text}")
        return text
    except Exception as e:
        logger.error(f"Analysis error {symbol}: {e}", exc_info=True)
        return f"❌ Ошибка анализа <b>{html.escape(symbol)}</b>: {html.escape(str(e))}"


async def _indicator_view(symbol: str) -> str:
    try:
        cfg = config.trading
        primary_tf = cfg.primary_timeframes[0]
        ind = await _get_indicators(symbol, primary_tf)
        if ind is None:
            return f"❌ Не удалось получить данные для <b>{html.escape(symbol)}</b>\n\nПроверьте тикер (пример: BTC/USDT)"

        result = signal_engine.evaluate(ind)

        # --- Подтверждение на confirm_tf ---
        entry_price = result.close if result.close is not None else ind.close
        if entry_price is None:
            entry_price = 0.0
        entry_price = float(entry_price)

        confirm_tf = cfg.confirm_timeframe
        if config.trading.confirm_tf_enabled and result.is_actionable and confirm_tf and confirm_tf != primary_tf:
            ind_confirm = await _get_indicators(symbol, confirm_tf)
            if ind_confirm is not None:
                confirm_result = signal_engine.evaluate(ind_confirm)
                if confirm_result.signal == result.signal:
                    entry_price = float(confirm_result.close if confirm_result.close is not None else ind_confirm.close)
                    result._confirmed_tf = confirm_tf
                    result.reasons.append(f"✅ Подтверждение на {confirm_tf}")
                else:
                    result.reasons.append(f"❌ {confirm_tf}: {confirm_result.signal.value} — не подтверждено")

        result.entry_price = entry_price

        # --- Уровни S/R (1h и 4h) ---
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
            sl_val = result.sl if result.sl is not None else 0.0
            tp_val = result.tp if result.tp is not None else 0.0
            result.level_warnings = validate_levels_vs_trade(
                sr_levels, entry_price, sl_val, tp_val, is_buy
            )

        # --- Рыночный контекст ---
        if config.context_enabled:
            try:
                snapshot = await asyncio.wait_for(
                    context_engine.get_snapshot(symbol),
                    timeout=10.0,
                )

                if result.is_actionable:
                    context_verdict = context_scorer.score(result.signal.value, snapshot)
                    result._context_score = context_verdict.score

                snap = snapshot
                dir_for_emoji = result.signal.value if result.is_actionable else None
                if snap:
                    ctx_items = []
                    if snap.fear_greed_value is not None:
                        try:
                            fg_val = int(snap.fear_greed_value)
                            if dir_for_emoji:
                                fg_score = context_scorer._score_fear_greed(fg_val, dir_for_emoji)
                                fg_emoji = "✅" if fg_score > 0 else ("⚠️" if fg_score == 0 else "🔴")
                            else:
                                fg_emoji = "📊"
                            ctx_items.append(f"{fg_emoji} Fear & Greed: {fg_val} ({snap.fear_greed_label})")
                        except (ValueError, TypeError):
                            ctx_items.append(f"⚠️ Fear & Greed: invalid value")
                    if snap.funding_rate is not None:
                        try:
                            fr_val = float(snap.funding_rate)
                            if dir_for_emoji:
                                fr_score = context_scorer._score_funding_rate(fr_val, dir_for_emoji)
                                fr_emoji = "✅" if fr_score > 0 else ("⚠️" if fr_score == 0 else "🔴")
                            else:
                                fr_emoji = "📊"
                            ctx_items.append(f"{fr_emoji} Funding: {fr_val * 100:.3f}%")
                        except (ValueError, TypeError):
                            ctx_items.append(f"⚠️ Funding: invalid value")
                    if snap.long_short_ratio is not None:
                        try:
                            ls_val = float(snap.long_short_ratio)
                            if dir_for_emoji:
                                ls_score = context_scorer._score_long_short(ls_val, dir_for_emoji)
                                ls_emoji = "✅" if ls_score > 0 else ("⚠️" if ls_score == 0 else "🔴")
                            else:
                                ls_emoji = "📊"
                            ctx_items.append(f"{ls_emoji} Long/Short: {ls_val:.2f}")
                        except (ValueError, TypeError):
                            ctx_items.append(f"⚠️ Long/Short: invalid value")
                    if snap.open_interest_delta is not None:
                        try:
                            oi_val = float(snap.open_interest_delta)
                            if dir_for_emoji:
                                oi_score = context_scorer._score_oi(oi_val, dir_for_emoji)
                                oi_emoji = "✅" if oi_score > 0 else ("⚠️" if oi_score == 0 else "🔴")
                            else:
                                oi_emoji = "📊"
                            ctx_items.append(f"{oi_emoji} OI: {oi_val:+.1f}%")
                        except (ValueError, TypeError):
                            ctx_items.append(f"⚠️ OI: invalid value")
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
        return f"❌ Ошибка для <b>{html.escape(symbol)}</b>: {html.escape(str(e))}"


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
