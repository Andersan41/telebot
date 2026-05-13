# F3. Динамическое управление символами через Telegram

> **Статус**: 🔴 не сделано
> **Приоритет**: 🟢 low — UX-улучшение, не bugfix.
> **Зависимости**: нет.

**Цель**: команды `/addsymbol BTC/USDT` и `/removesymbol BTC/USDT` (admin-only) меняют
наблюдаемый список без рестарта; список переживает рестарт (хранится в `bot_settings`).

**Файлы**:

| Файл                  | Что делать                                                     |
|-----------------------|----------------------------------------------------------------|
| `storage/database.py` | добавить `get_dynamic_symbols`/`set_dynamic_symbols`           |
| `config/settings.py`  | у `TradingConfig.symbols` сделать `property`, читающий БД-кэш  |
| `bot/admin.py` (new или в существующий handlers) | команды `/addsymbol`, `/removesymbol`, `/listsymbols` |
| `tests/test_admin_symbols.py` (new) | юнит-тесты на команды                            |

**Архитектурное решение**: использовать существующую таблицу `bot_settings`
(см. `storage/database.py:33-38`), ключ `dynamic_symbols`, значение —
CSV строка `BTC/USDT,ETH/USDT,SOL/USDT`. Отдельная таблица — overkill.

**Пошагово**:

1. **БД-методы** (`storage/database.py`):
   ```python
   async def get_dynamic_symbols(self) -> Optional[list[str]]:
       """None — динамический список не задан, использовать env SYMBOLS."""
       val = await self.get_setting("dynamic_symbols", "")
       if not val:
           return None
       return [s.strip() for s in val.split(",") if s.strip()]

   async def set_dynamic_symbols(self, symbols: list[str]) -> None:
       await self.set_setting("dynamic_symbols", ",".join(symbols))
   ```

2. **Кэш в `config.trading.symbols`**. Текущее поле — `field(default_factory=...)`,
   читается из env один раз при старте. Чтобы динамически отражать БД, **не меняй** само поле;
   введи новый атрибут на уровне модуля:
   ```python
   # config/settings.py, в конце файла
   _runtime_symbols_cache: Optional[list[str]] = None

   async def refresh_runtime_symbols() -> None:
       """Перечитать список символов из БД. Зови при старте и после /addsymbol / /removesymbol."""
       global _runtime_symbols_cache
       from storage.database import db  # lazy чтобы избежать циклов импорта
       dynamic = await db.get_dynamic_symbols()
       _runtime_symbols_cache = dynamic if dynamic is not None else config.trading.symbols

   def get_active_symbols() -> list[str]:
       return _runtime_symbols_cache if _runtime_symbols_cache is not None else config.trading.symbols
   ```
   В `main.py` после `await db.init()` вызови `await refresh_runtime_symbols()`.
   В `scheduler/scanner.py` и `bot/menu.py` **постепенно** замени обращения
   `config.trading.symbols` → `get_active_symbols()`.
   ⚠️ Сначала найди все usages: `rg -n 'config\.trading\.symbols' .`. Их сейчас ~5 мест.

3. **Команды** (`bot/admin.py`, либо в существующий `bot/handlers.py`):
   ```python
   from telegram import Update
   from telegram.ext import ContextTypes
   from config.settings import get_active_symbols, refresh_runtime_symbols
   from storage.database import db

   @_admin_only
   async def addsymbol_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
       args = context.args
       if not args:
           await update.message.reply_text("Usage: /addsymbol BTC/USDT")
           return
       symbol = args[0].upper()
       if "/" not in symbol:
           symbol = f"{symbol}/USDT"
       current = get_active_symbols()
       if symbol in current:
           await update.message.reply_text(f"Уже в списке: {symbol}")
           return
       new_list = current + [symbol]
       await db.set_dynamic_symbols(new_list)
       await refresh_runtime_symbols()
       await update.message.reply_text(f"✅ Добавлено: {symbol}\nВсего: {len(new_list)}")

   @_admin_only
   async def removesymbol_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
       args = context.args
       if not args:
           await update.message.reply_text("Usage: /removesymbol BTC/USDT")
           return
       symbol = args[0].upper()
       if "/" not in symbol:
           symbol = f"{symbol}/USDT"
       current = get_active_symbols()
       if symbol not in current:
           await update.message.reply_text(f"Нет в списке: {symbol}")
           return
       new_list = [s for s in current if s != symbol]
       await db.set_dynamic_symbols(new_list)
       await refresh_runtime_symbols()
       await update.message.reply_text(f"✅ Удалено: {symbol}\nОсталось: {len(new_list)}")

   @_admin_only
   async def listsymbols_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
       symbols = get_active_symbols()
       text = "📊 <b>Активные символы:</b>\n" + "\n".join(f"  • {s}" for s in symbols)
       await update.message.reply_text(text, parse_mode="HTML")
   ```
   Зарегистрируй: `application.add_handler(CommandHandler("addsymbol", addsymbol_command))`
   и аналогично для двух других.

4. **Валидация символа** (опционально, но рекомендуется): проверить через
   `exchange_client._exchange.markets`, что такой символ существует на бирже:
   ```python
   if symbol not in exchange_client._exchange.markets:
       await update.message.reply_text(f"❌ Символ {symbol} не найден на бирже")
       return
   ```

**Edge cases**:

- Пустой `dynamic_symbols` в БД (после `/removesymbol` последнего) → `get_dynamic_symbols`
  вернёт `None` → используется env. Чтобы реально оставить пустой список — храни строку
  `__empty__` как маркер. Но обычно проще запретить удаление последнего символа.
- Гонка: между `current = get_active_symbols()` и `db.set_dynamic_symbols(new_list)` другой
  админ может добавить символ. Маловероятно, но если важно — оберни в SQLite-транзакцию.

**Готовность**:

- `pytest tests/test_admin_symbols.py -v` зелёный.
- Ручной тест: `/addsymbol DOGE/USDT` → меню «Анализ токена» показывает DOGE в списке кнопок.
- Перезапуск процесса → список сохраняется (читается из БД при старте через
  `refresh_runtime_symbols`).
