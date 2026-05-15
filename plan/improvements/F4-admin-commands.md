# F4. Расширение admin-команд

> **Статус**: ✅ сделано
> **Приоритет**: 🟢 low — UX-улучшения, не bugfix.
> **Зависимости**: F4.1 (`/setparam`) требует выполнения [A1](A1-indicators-env.md).
> F4.2/F4.3 — независимы.

Три независимых мини-задачи. Все используют декоратор `_admin_only` (см. существующий
код — `bot/handlers.py:22-30`; шаблон ниже на всякий случай).

**Шаблон `_admin_only`** (если отсутствует — добавь в `bot/admin.py`):
```python
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes
from config.settings import config

def _admin_only(handler):
    @wraps(handler)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in config.telegram.admin_ids:
            await update.message.reply_text("⛔ Команда доступна только админам")
            return
        return await handler(update, ctx)
    return wrapper
```

## F4.1. `/setparam <name> <value>` — runtime-изменение параметра

**Цель**: подкрутить `EMA_FAST`, `RSI_PERIOD` и пр. без рестарта.

**Зависимости**: задача [A1](A1-indicators-env.md) должна быть выполнена (параметры читаются
из env), иначе менять негде.

**Шаги**:

1. Допустимый whitelist параметров (чтобы юзер не положил процесс случайным значением).
   В `bot/admin.py`:
   ```python
   ALLOWED_RUNTIME_PARAMS = {
       "EMA_FAST": int, "EMA_SLOW": int, "EMA_TREND": int,
       "RSI_PERIOD": int, "RSI_OVERBOUGHT": float, "RSI_OVERSOLD": float,
       "RSI_BULL_MIN": float, "RSI_BEAR_MAX": float,
       "MACD_FAST": int, "MACD_SLOW": int, "MACD_SIGNAL": int,
       "ADX_PERIOD": int, "ADX_MIN": float,
       "ATR_PERIOD": int, "ATR_MULTIPLIER_SL": float, "ATR_MULTIPLIER_TP": float,
       "SUPERTREND_PERIOD": int, "SUPERTREND_MULTIPLIER": float,
       "VOLUME_FACTOR": float, "CANDLES_LIMIT": int,
   }
   ```
2. Хранение runtime-значений в `bot_settings` под ключом `param:{NAME}`. В `config/settings.py`
   надо научить `TradingConfig` читать БД при создании — но это означает, что `config` должен
   быть пересоздан после изменения. Простейший вариант: хранить значение в БД, а в коде
   индикаторов читать из конфига как раньше; после `/setparam` форсить перезагрузку через
   `importlib.reload(config.settings)`.
   ⚠️ `importlib.reload` хрупкий механизм. Если простота важнее — оставь `/setparam`
   как «обновляет БД, применится после рестарта» (что обнуляет смысл задачи). Согласуй.
3. Команда:
   ```python
   @_admin_only
   async def setparam_command(update, context):
       args = context.args
       if len(args) != 2:
           await update.message.reply_text("Usage: /setparam EMA_FAST 7")
           return
       name, raw = args[0].upper(), args[1]
       caster = ALLOWED_RUNTIME_PARAMS.get(name)
       if caster is None:
           await update.message.reply_text(
               f"❌ Параметр {name} не whitelisted. Доступные: "
               f"{', '.join(ALLOWED_RUNTIME_PARAMS)}"
           )
           return
       try:
           value = caster(raw)
       except ValueError:
           await update.message.reply_text(f"❌ {raw} не приводится к {caster.__name__}")
           return
       await db.set_setting(f"param:{name}", str(value))
       await update.message.reply_text(
           f"✅ {name}={value}. Применится после рестарта процесса "
           f"(полный live-update пока не реализован)."
       )
   ```

## F4.2. `/disable <symbol>` — временно выключить символ

**Цель**: убрать символ из сканирования, но сохранить в списке. После `/enable <symbol>`
вернуть.

**Шаги**:

1. В БД: ключ `disabled_symbols` (CSV), методы `get_disabled_symbols`/`set_disabled_symbols`
   по аналогии с [F3](F3-dynamic-symbols.md).
2. В `scheduler/scanner.py:run_scan_cycle` (строки 195-217) после получения `symbols`:
   ```python
   disabled = await db.get_disabled_symbols() or []
   symbols = [s for s in symbols if s not in disabled]
   ```
3. Команды:
   ```python
   @_admin_only
   async def disable_command(update, context):
       symbol = (context.args[0] if context.args else "").upper()
       if "/" not in symbol:
           symbol = f"{symbol}/USDT"
       disabled = await db.get_disabled_symbols() or []
       if symbol in disabled:
           await update.message.reply_text(f"Уже выключен: {symbol}")
           return
       await db.set_disabled_symbols(disabled + [symbol])
       await update.message.reply_text(f"⏸ {symbol} выключен. Сканер пропустит.")

   @_admin_only
   async def enable_command(update, context):
       symbol = (context.args[0] if context.args else "").upper()
       if "/" not in symbol:
           symbol = f"{symbol}/USDT"
       disabled = await db.get_disabled_symbols() or []
       new = [s for s in disabled if s != symbol]
       await db.set_disabled_symbols(new)
       await update.message.reply_text(f"▶ {symbol} включён.")
   ```

## F4.3. `/exportdb` — выгрузить БД админу

**Цель**: получить SQLite-файл для бэкапа/анализа.

**Шаги**:

1. Команда:
   ```python
   @_admin_only
   async def exportdb_command(update, context):
       db_path = config.database_url.replace("sqlite+aiosqlite:///", "")
       # Telegram-bot ограничения: файл до 50 MB. Проверь размер.
       import os as _os
       size = _os.path.getsize(db_path)
       if size > 49 * 1024 * 1024:
           await update.message.reply_text(
               f"❌ Файл слишком большой: {size / 1024 / 1024:.1f} MB > 50 MB"
           )
           return
       with open(db_path, "rb") as f:
           await update.message.reply_document(
               document=f,
               filename=f"signals_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M')}.db",
               caption="📦 Backup SQLite",
           )
   ```
2. ⚠️ **БД может быть locked**, если в этот момент идёт write. Простой вариант — снять
   snapshot через `sqlite3` API:
   ```python
   import shutil, tempfile
   with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
       shutil.copy(db_path, tmp.name)
       # отправляем tmp.name
   ```
   Это допустимо для маленьких БД (< 100 MB). Если БД большая — используй SQLite
   `vacuum into` или Online Backup API.

## Готовность F4

- `/setparam`, `/disable`, `/enable`, `/exportdb` появляются в `BotCommand`-listе
  (зарегистрированы через `application.add_handler(CommandHandler(...))`).
- Каждая команда отказывает не-админу с понятным сообщением.
- `pytest tests/test_admin_*.py -v` зелёный (если написаны).
