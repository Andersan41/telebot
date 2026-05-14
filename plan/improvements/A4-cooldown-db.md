# A4. Cooldown в БД (переживает рестарт)

> **Статус**: ✅ сделано
> **Приоритет**: 🔴 **critical** — без этого cooldown не работает в Docker/CI
> (любой рестарт обнуляет `_last_signal_time`).
> **Зависимости**: нет.

**Цель**: сейчас `_last_signal_time` в `scheduler/scanner.py:18` — модульный `dict`, при
рестарте обнуляется. Критично: если процесс перезапускается каждый час (Docker/CI),
cooldown не работает вообще. Хранить в `bot_settings`.

**Файлы и точные места**:

| Файл                           | Что делать                                                                        |
|--------------------------------|-----------------------------------------------------------------------------------|
| `storage/database.py:125-144`  | рядом с `get_setting`/`set_setting` добавить `get_cooldown`/`set_cooldown`        |
| `scheduler/scanner.py:18-46`   | удалить модульный dict, переписать `_is_cooldown_active`/`_set_cooldown` на async |
| `scheduler/scanner.py:61, 186` | заменить вызовы на `await ...`                                                    |
| `tests/test_scanner.py`        | переписать `TestCooldown` на мок `db.get_cooldown`/`db.set_cooldown`              |

**Предусловия**:

- В `storage/database.py:5` уже есть `from datetime import datetime, timezone`. Только
  добавь к импорту `Optional` (он уже импортирован на строке 6 — проверь).
- В `scheduler/scanner.py:6` уже есть `from datetime import datetime, timezone, timedelta`.
  Импортировать ничего не надо.

**Пошагово**:

1. **БД-методы** (`storage/database.py`, под `set_setting` на строке 144):
   ```python
   async def get_cooldown(
       self, symbol: str, timeframe: str
   ) -> Optional[datetime]:
       key = f"cooldown:{symbol}:{timeframe}"
       val = await self.get_setting(key, "")
       if not val:
           return None
       try:
           return datetime.fromisoformat(val)
       except ValueError:
           # Битый формат — игнорируем, как будто cooldown нет
           return None

   async def set_cooldown(
       self, symbol: str, timeframe: str, ts: datetime
   ) -> None:
       key = f"cooldown:{symbol}:{timeframe}"
       await self.set_setting(key, ts.isoformat())
   ```
   Используется существующая таблица `bot_settings` (см. строки 33-38 модели `BotSetting`).
   Новую таблицу заводить **не нужно**.

2. **Scanner** (`scheduler/scanner.py`):

   2.1. **Удали** строки 17-18:
   ```python
   # Словарь для cooldown: {symbol_timeframe: last_signal_time}
   _last_signal_time: dict[str, datetime] = {}
   ```

   2.2. **Замени** функции `_is_cooldown_active` и `_set_cooldown` (строки 35-46):
   ```python
   async def _is_cooldown_active(symbol: str, timeframe: str) -> bool:
       last = await db.get_cooldown(symbol, timeframe)
       if last is None:
           return False
       # Защита от TZ-naive значений, если БД отдала naive datetime
       if last.tzinfo is None:
           last = last.replace(tzinfo=timezone.utc)
       delta = datetime.now(timezone.utc) - last
       return delta < timedelta(minutes=config.signal_cooldown_minutes)


   async def _set_cooldown(symbol: str, timeframe: str) -> None:
       await db.set_cooldown(symbol, timeframe, datetime.now(timezone.utc))
   ```

   2.3. В `scan_symbol` (`scheduler/scanner.py:61`) замени:
   ```python
   if _is_cooldown_active(symbol, timeframe):
   ```
   на:
   ```python
   if await _is_cooldown_active(symbol, timeframe):
   ```

   2.4. На строке 186 замени:
   ```python
   _set_cooldown(symbol, timeframe)
   ```
   на:
   ```python
   await _set_cooldown(symbol, timeframe)
   ```

3. **Тесты** (`tests/test_scanner.py`):

   3.1. Найди фикстуру `clear_cooldown` (если есть). Раньше она чистила модульный dict —
   теперь dict удалён. Замени на:
   ```python
   from unittest.mock import AsyncMock
   import pytest

   @pytest.fixture
   def mock_cooldown(monkeypatch):
       """Подменяет db.get_cooldown / db.set_cooldown на in-memory dict."""
       store: dict[tuple[str, str], "datetime"] = {}

       async def fake_get(symbol, timeframe):
           return store.get((symbol, timeframe))

       async def fake_set(symbol, timeframe, ts):
           store[(symbol, timeframe)] = ts

       monkeypatch.setattr("scheduler.scanner.db.get_cooldown", fake_get)
       monkeypatch.setattr("scheduler.scanner.db.set_cooldown", fake_set)
       return store
   ```

   3.2. Тесты `TestCooldown::test_*` — обяжи их использовать `mock_cooldown` и
   `@pytest.mark.asyncio`. Пример:
   ```python
   @pytest.mark.asyncio
   async def test_cooldown_blocks_repeat(mock_cooldown):
       from scheduler.scanner import _is_cooldown_active, _set_cooldown
       await _set_cooldown("BTC/USDT", "1h")
       assert await _is_cooldown_active("BTC/USDT", "1h") is True

   @pytest.mark.asyncio
   async def test_cooldown_other_symbol_independent(mock_cooldown):
       from scheduler.scanner import _is_cooldown_active, _set_cooldown
       await _set_cooldown("BTC/USDT", "1h")
       assert await _is_cooldown_active("ETH/USDT", "1h") is False
   ```

**Edge cases**:

- БД не инициализирована при самом первом `scan_symbol` — `get_setting` (строка 125) вернёт
  default `""`; `get_cooldown` → `None`; `_is_cooldown_active` → `False`. OK.
- В `bot_settings` лежит мусор (битый ISO-формат) — `try/except ValueError` в `get_cooldown`
  возвращает `None`. Cooldown будет «перезаписан» при следующем сигнале.
- TZ-naive datetime — guard `if last.tzinfo is None: replace(tzinfo=timezone.utc)`
  оставлен **намеренно**, не убирай.

**Готовность**:

- `pytest tests/test_scanner.py::TestCooldown -v` — все зелёные.
- `pytest -v` целиком зелёный.
- Ручной тест:
    1. Запусти бот, дождись сигнала (или дёрни `/scan` через меню).
    2. В SQLite: `sqlite3 data/signals.db "select key, value from bot_settings where key like 'cooldown:%'"`
       — должна быть запись.
    3. Перезапусти процесс. Повторный `/scan` для того же символа в течение
       `SIGNAL_COOLDOWN_MINUTES` не должен выдать сигнал (лог: `Cooldown active: ...`).
