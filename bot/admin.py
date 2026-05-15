"""
bot/admin.py — Admin-only команды управления ботом
"""
from datetime import datetime, timezone
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from loguru import logger
from config.settings import get_active_symbols, refresh_runtime_symbols
from storage.database import db


async def _ensure_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка админа — возвращает True если не админ (и отправляет сообщение)."""
    if not update.effective_user:
        return False
    from config.settings import config
    if update.effective_user.id not in config.telegram.admin_ids:
        await update.message.reply_text("\u26d4\ufe0f \u0414\u043e\u0441\u0442\u0443\u043f \u0437\u0430\u043f\u0440\u0435\u0449\u0451\u043d.")
        return False
    return True


async def addsymbol_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /addsymbol BTC/USDT")
        return
    symbol = args[0].upper()
    if "/" not in symbol:
        symbol = f"{symbol}/USDT"
    current = get_active_symbols()
    if symbol in current:
        await update.message.reply_text(f"\u0423\u0436\u0435 \u0432 \u0441\u043f\u0438\u0441\u043a\u0435: {symbol}")
        return
    new_list = current + [symbol]
    await db.set_dynamic_symbols(new_list)
    await refresh_runtime_symbols()
    await update.message.reply_text(f"\u2705 \u0414\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u043e: {symbol}\n\u0412\u0441\u0435\u0433\u043e: {len(new_list)}")


async def removesymbol_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /removesymbol BTC/USDT")
        return
    symbol = args[0].upper()
    if "/" not in symbol:
        symbol = f"{symbol}/USDT"
    current = get_active_symbols()
    if symbol not in current:
        await update.message.reply_text(f"\u041d\u0435\u0442 \u0432 \u0441\u043f\u0438\u0441\u043a\u0435: {symbol}")
        return
    new_list = [s for s in current if s != symbol]
    await db.set_dynamic_symbols(new_list)
    await refresh_runtime_symbols()
    await update.message.reply_text(f"\u2705 \u0423\u0434\u0430\u043b\u0435\u043d\u043e: {symbol}\n\u041e\u0441\u0442\u0430\u043b\u043e\u0441\u044c: {len(new_list)}")


async def listsymbols_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return
    symbols = get_active_symbols()
    text = "\U0001f4ca <b>\u0410\u043a\u0442\u0438\u0432\u043d\u044b\u0435 \u0441\u0438\u043c\u0432\u043e\u043b\u044b:</b>\n" + "\n".join(
        f"  \u2022 {s}" for s in symbols
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


# ── F4.1: /setparam ──────────────────────────────────────────────────

ALLOWED_RUNTIME_PARAMS: dict[str, type] = {
    "EMA_FAST": int, "EMA_SLOW": int, "EMA_TREND": int,
    "RSI_PERIOD": int, "RSI_OVERBOUGHT": float, "RSI_OVERSOLD": float,
    "RSI_BULL_MIN": float, "RSI_BEAR_MAX": float,
    "MACD_FAST": int, "MACD_SLOW": int, "MACD_SIGNAL": int,
    "ADX_PERIOD": int, "ADX_MIN": float,
    "ATR_PERIOD": int, "ATR_MULTIPLIER_SL": float, "ATR_MULTIPLIER_TP": float,
    "SUPERTREND_PERIOD": int, "SUPERTREND_MULTIPLIER": float,
    "VOLUME_FACTOR": float, "CANDLES_LIMIT": int,
}


async def setparam_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Usage: /setparam EMA_FAST 7")
        return
    name, raw = args[0].upper(), args[1]
    caster = ALLOWED_RUNTIME_PARAMS.get(name)
    if caster is None:
        await update.message.reply_text(
            f"\u274c \u041f\u0430\u0440\u0430\u043c\u0435\u0442\u0440 {name} \u043d\u0435 whitelisted. \u0414\u043e\u0441\u0442\u0443\u043f\u043d\u044b\u0435: "
            f"{', '.join(ALLOWED_RUNTIME_PARAMS)}"
        )
        return
    try:
        value = caster(raw)
    except ValueError:
        await update.message.reply_text(f"\u274c {raw} \u043d\u0435 \u043f\u0440\u0438\u0432\u043e\u0434\u0438\u0442\u0441\u044f \u043a {caster.__name__}")
        return
    await db.set_setting(f"param:{name}", str(value))
    await update.message.reply_text(
        f"\u2705 {name}={value}. \u041f\u0440\u0438\u043c\u0435\u043d\u0438\u0442\u0441\u044f \u043f\u043e\u0441\u043b\u0435 \u0440\u0435\u0441\u0442\u0430\u0440\u0442\u0430 \u043f\u0440\u043e\u0446\u0435\u0441\u0441\u0430 "
        f"(\u043f\u043e\u043b\u043d\u044b\u0439 live-update \u043f\u043e\u043a\u0430 \u043d\u0435 \u0440\u0435\u0430\u043b\u0438\u0437\u043e\u0432\u0430\u043d)."
    )


# ── F4.2: /disable / /enable ─────────────────────────────────────────


async def disable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return
    symbol = (context.args[0] if context.args else "").upper()
    if "/" not in symbol:
        symbol = f"{symbol}/USDT"
    disabled = await db.get_disabled_symbols() or []
    if symbol in disabled:
        await update.message.reply_text(f"\u0423\u0436\u0435 \u0432\u044b\u043a\u043b\u044e\u0447\u0451\u043d: {symbol}")
        return
    await db.set_disabled_symbols(disabled + [symbol])
    await update.message.reply_text(f"\u23f8\ufe0f {symbol} \u0432\u044b\u043a\u043b\u044e\u0447\u0451\u043d. \u0421\u043a\u0430\u043d\u0435\u0440 \u043f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u0442.")


async def enable_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return
    symbol = (context.args[0] if context.args else "").upper()
    if "/" not in symbol:
        symbol = f"{symbol}/USDT"
    disabled = await db.get_disabled_symbols() or []
    new = [s for s in disabled if s != symbol]
    await db.set_disabled_symbols(new)
    await update.message.reply_text(f"\u25b6\ufe0f {symbol} \u0432\u043a\u043b\u044e\u0447\u0451\u043d.")


# ── F4.3: /exportdb ──────────────────────────────────────────────────


async def exportdb_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _ensure_admin(update, context):
        return
    from config.settings import config
    db_path = config.database_url.replace("sqlite+aiosqlite:///", "")
    import os as _os
    import shutil
    import tempfile

    if not Path(db_path).exists():
        await update.message.reply_text("\u274c \u0424\u0430\u0439\u043b \u0431\u0430\u0437\u044b \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d: " + db_path)
        return

    size = _os.path.getsize(db_path)
    if size > 49 * 1024 * 1024:
        await update.message.reply_text(
            f"\u274c \u0424\u0430\u0439\u043b \u0441\u043b\u0438\u0448\u043a\u043e\u043c \u0431\u043e\u043b\u044c\u0448\u043e\u0439: {size / 1024 / 1024:.1f} MB > 50 MB"
        )
        return

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        shutil.copy(db_path, tmp.name)
        filename = f"signals_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.db"
        with open(tmp.name, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption="\U0001f4e6 Backup SQLite",
            )
