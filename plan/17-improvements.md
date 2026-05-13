# 9. Возможные улучшения и накопленный долг

## Недавно исправлено (см. git log)

- ✅ Funding rate — переведён на прямой HTTP `fapi/v1/premiumIndex`.
- ✅ OI delta — % изменение per-symbol через in-memory `_last_oi`.
- ✅ `CONTEXT_MIN_VERDICT` — ранговый гейт в `scanner.scan_symbol`.
- ✅ `signal_engine.format_message` — знаменатель `/6`.
- ✅ Дубль cron-джобов — `_scan_job` параметризован, 1H/4H разнесены.
- ✅ Race на `news_sentiment_score` — аккумуляция CryptoPanic+RSS после `asyncio.gather`.
- ✅ `db.save_signal(confirmed=…)` — отражает реальный результат 15M-фильтра.

---

Каждая задача ниже спроектирована как **самодостаточная спецификация** для исполнителя.
Перед началом работы — прочитай соответствующий раздел плана (`plan/0X-...md`) и упомянутый
участок кода. Не меняй ничего за пределами «Files» без отдельного согласования.

## Архитектура

### A1. Параметры индикаторов через `.env`

**Цель**: убрать жёстко зашитые числа из `TradingConfig` dataclass и сделать настройку
индикаторов возможной без правки кода (сейчас изменение, например, `ema_fast=9` требует
редактировать `config/settings.py`).

**Файлы и точные места**:

| Файл                         | Что делать                                                                 |
|------------------------------|----------------------------------------------------------------------------|
| `config/settings.py:29-61`   | переписать поля `TradingConfig` на чтение из env                           |
| `.env.example`               | добавить 20 строк под заголовком `# Indicator parameters (defaults shown)` |
| `plan/14-env-config.md`      | добавить таблицу `Indicator parameters` (var, default, type)               |
| `tests/test_config.py`       | дополнить тестами через `monkeypatch.setenv` + `importlib.reload`          |

**Предусловия (проверь до старта)**:

- В `config/settings.py:4` уже есть `import os`. Добавлять не надо.
- `load_dotenv()` вызывается на строке 9 — env-переменные читаются автоматически.
- `config = AppConfig()` (строка 97) создаёт `TradingConfig` через `field(default_factory=...)`.
  Это значит: `default_factory` зовётся при создании `AppConfig()`, env читается тогда же. OK.
- Для **примитивных** полей (`int`, `float`) `field(default_factory=...)` **не нужен** —
  используй прямое присваивание `ema_fast: int = int(os.getenv(...))`.
  `field(default_factory=...)` нужен только для mutable-дефолтов вроде `List`/`Dict`.

**Пошагово**:

1. Открой `config/settings.py:29-61`.
2. Замени каждое из 20 числовых полей на чтение из `os.getenv(...)` с дефолтом
   (передавай строку, кастуй явно — `int(...)` или `float(...)`):
   ```python
   ema_fast: int = int(os.getenv("EMA_FAST", "9"))
   ema_slow: int = int(os.getenv("EMA_SLOW", "21"))
   ema_trend: int = int(os.getenv("EMA_TREND", "50"))
   rsi_period: int = int(os.getenv("RSI_PERIOD", "14"))
   rsi_overbought: float = float(os.getenv("RSI_OVERBOUGHT", "70"))
   rsi_oversold: float = float(os.getenv("RSI_OVERSOLD", "30"))
   rsi_bull_min: float = float(os.getenv("RSI_BULL_MIN", "50"))
   rsi_bear_max: float = float(os.getenv("RSI_BEAR_MAX", "50"))
   macd_fast: int = int(os.getenv("MACD_FAST", "12"))
   macd_slow: int = int(os.getenv("MACD_SLOW", "26"))
   macd_signal: int = int(os.getenv("MACD_SIGNAL", "9"))
   adx_period: int = int(os.getenv("ADX_PERIOD", "14"))
   adx_min: float = float(os.getenv("ADX_MIN", "20"))
   atr_period: int = int(os.getenv("ATR_PERIOD", "14"))
   atr_multiplier_sl: float = float(os.getenv("ATR_MULTIPLIER_SL", "1.5"))
   atr_multiplier_tp: float = float(os.getenv("ATR_MULTIPLIER_TP", "3.0"))
   supertrend_period: int = int(os.getenv("SUPERTREND_PERIOD", "10"))
   supertrend_multiplier: float = float(os.getenv("SUPERTREND_MULTIPLIER", "3.0"))
   volume_factor: float = float(os.getenv("VOLUME_FACTOR", "1.2"))
   candles_limit: int = int(os.getenv("CANDLES_LIMIT", "200"))
   ```
   Поля `symbols`, `primary_timeframes`, `confirm_timeframe` (строки 31-37) **не трогай** —
   они уже читают env.
3. В `.env.example` добавь блок (значения = текущие дефолты):
   ```
   # Indicator parameters (defaults shown)
   EMA_FAST=9
   EMA_SLOW=21
   EMA_TREND=50
   RSI_PERIOD=14
   RSI_OVERBOUGHT=70
   RSI_OVERSOLD=30
   RSI_BULL_MIN=50
   RSI_BEAR_MAX=50
   MACD_FAST=12
   MACD_SLOW=26
   MACD_SIGNAL=9
   ADX_PERIOD=14
   ADX_MIN=20
   ATR_PERIOD=14
   ATR_MULTIPLIER_SL=1.5
   ATR_MULTIPLIER_TP=3.0
   SUPERTREND_PERIOD=10
   SUPERTREND_MULTIPLIER=3.0
   VOLUME_FACTOR=1.2
   CANDLES_LIMIT=200
   ```
4. В `plan/14-env-config.md` добавь таблицу под заголовком `## Indicator parameters`
   с колонками `Переменная | Дефолт | Тип | Описание` (20 строк).
5. В `tests/test_config.py` (файл уже существует — дополняй, не пересоздавай) добавь:
   ```python
   import importlib
   import pytest


   def test_ema_fast_from_env(monkeypatch):
       monkeypatch.setenv("EMA_FAST", "5")
       import config.settings as settings
       importlib.reload(settings)
       assert settings.config.trading.ema_fast == 5


   def test_atr_multiplier_from_env(monkeypatch):
       monkeypatch.setenv("ATR_MULTIPLIER_SL", "2.5")
       import config.settings as settings
       importlib.reload(settings)
       assert settings.config.trading.atr_multiplier_sl == 2.5


   def test_defaults_when_env_missing(monkeypatch):
       monkeypatch.delenv("EMA_FAST", raising=False)
       import config.settings as settings
       importlib.reload(settings)
       assert settings.config.trading.ema_fast == 9
   ```
   ⚠️ После теста `importlib.reload` другие модули, импортировавшие `config`, увидят
   старую копию. Если в одном файле есть тесты, читающие `config`, добавь
   `importlib.reload(settings)` без monkeypatch в фикстуру `autouse=True` для
   возврата к дефолтам.

**Edge cases**:

- Пустая строка в env (`EMA_FAST=`): `int("")` → `ValueError` на старте. Не лови — это
  конфигурационная ошибка, пусть упадёт.
- Нечисловое значение (`EMA_FAST=abc`): `ValueError`. То же — не лови.
- Бессмысленное сочетание (`RSI_BULL_MIN=80`, `RSI_OVERBOUGHT=70`): код отработает,
  просто условие RSI никогда не сработает. Валидацию **не добавляй** — это user error.

**Готовность**:

- `pytest tests/test_config.py -v` зелёный.
- `pytest -v` целиком зелёный (регрессии не появились).
- В `bot/menu.py:_format_settings` (строка 205) меню «⚙️ Настройки» показывает новые
  значения корректно — никаких правок там не нужно (читает `config.trading.*`).

---

### A2. OI delta переживает рестарт

**Цель**: сейчас при старте процесса первая дельта = 0.0, потому что `_last_oi` пустой
(см. `context/fetcher.py:26`). Подтянуть последние 2 точки из исторического эндпоинта Binance,
чтобы первая дельта была осмысленной.

**Файлы и точные места**:

| Файл                         | Что делать                                      |
|------------------------------|-------------------------------------------------|
| `context/fetcher.py:155-189` | дополнить `fetch_open_interest` warm-up-логикой |
| `tests/test_context.py`      | добавить тест на дельту при warm-up             |

**Эндпоинт**:

```
GET https://fapi.binance.com/futures/data/openInterestHist
    ?symbol=BTCUSDT&period=5m&limit=2
```

Ответ — JSON-массив с двумя элементами; берём `[-2]["sumOpenInterest"]` как «previous».
Пример: `[{"symbol":"BTCUSDT","sumOpenInterest":"82345.12","timestamp":1700000000000}, {...}]`.

**Пошагово**:

1. В `context/fetcher.py:155-189` (метод `fetch_open_interest`) **перед** строкой
   `current = float(data.get("openInterest", 0))` (строка 171) добавь условный warm-up:
   ```python
   # Warm-up: при первом запросе для символа подтянем предыдущее значение
   # из исторического эндпоинта, чтобы delta уже на первом скане была осмысленной.
   if symbol not in self._last_oi:
       try:
           hist_url = (
               f"https://fapi.binance.com/futures/data/openInterestHist"
               f"?symbol={binance_symbol}&period=5m&limit=2"
           )
           async with session.get(hist_url) as hist_resp:
               if hist_resp.status == 200:
                   hist = await hist_resp.json()
                   if isinstance(hist, list) and len(hist) >= 2:
                       self._last_oi[symbol] = float(hist[-2]["sumOpenInterest"])
                       logger.debug(f"OI warm-up {symbol}: prev={self._last_oi[symbol]}")
       except Exception as e:
           logger.warning(f"OI warm-up failed for {symbol}: {e}")
   ```
2. **Не меняй** строки 171-177 (`current = ...`, `previous = self._last_oi.get(symbol)`,
   расчёт `delta_pct`, `self._last_oi[symbol] = current`). После шага 1
   `self._last_oi[symbol]` уже будет проставлен → дальнейший код посчитает дельту относительно
   него и сразу же перезапишет на текущее.
3. **Не вызывай warm-up каждый раз** — условие `if symbol not in self._last_oi` гарантирует,
   что он отработает один раз за процесс.

**Контракт**: возвращаемый dict **не меняется**:
`{open_interest: float, open_interest_delta: float, timestamp: datetime}`.

**Edge cases**:

- `openInterestHist` лимитирован (300 req/5min на public). Один раз за символ за процесс — OK.
- Эндпоинт вернул `< 2` точек или пустой массив → пропусти warm-up,
  оставь `delta_pct = 0.0` (фолбэк к старому поведению).
- Сеть упала на warm-up → `try/except` ловит, лог `WARNING`, не пробрасывай. Главный запрос
  на `/fapi/v1/openInterest` ниже должен отработать независимо.
- Символ редкий и hist возвращает 404 → status != 200 → warm-up пропускается, `delta_pct = 0.0`.

**Тест** (`tests/test_context.py`, в `TestContextFetcher`):

```python
import pytest
from aioresponses import aioresponses


@pytest.mark.asyncio
async def test_oi_warmup_uses_historical(monkeypatch):
    from context.fetcher import ContextFetcher
    fetcher = ContextFetcher()
    with aioresponses() as m:
        m.get(
            "https://fapi.binance.com/futures/data/openInterestHist"
            "?symbol=BTCUSDT&period=5m&limit=2",
            payload=[
                {"symbol": "BTCUSDT", "sumOpenInterest": "100.0", "timestamp": 1},
                {"symbol": "BTCUSDT", "sumOpenInterest": "120.0", "timestamp": 2},
            ],
        )
        m.get(
            "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT",
            payload={"openInterest": "110.0", "symbol": "BTCUSDT", "time": 3000},
        )
        result = await fetcher.fetch_open_interest("BTC/USDT")
        await fetcher.close()
    # warm-up взял previous = 100.0 (hist[-2]); текущее 110.0; delta = +10%
    assert result is not None
    assert result["open_interest"] == 110.0
    assert abs(result["open_interest_delta"] - 10.0) < 1e-6
```

**Готовность**:

- `pytest tests/test_context.py -v` — новый тест зелёный, старые не сломались.
- Ручная проверка: запусти бот, при первом скане в логах должна быть строка
  `OI BTC/USDT: <число> (Δ +X.XX%)` где `X.XX != 0.00`.
- Sanity check вручную:
  `curl 'https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=5m&limit=2'`.

---

### A3. OI-шкала для SELL

**Цель**: `context/scorer.py:213-221` (метод `_score_oi`) сейчас игнорирует параметр `direction` —
рост OI оценивается одинаково для BUY и SELL. Это известная асимметрия
(см. `plan/08-context.md`). Задача — реализовать **рекомендуемый вариант** (см. ниже) и
синхронизировать документацию.

**Файлы**:

| Файл                        | Что делать                                             |
|-----------------------------|--------------------------------------------------------|
| `context/scorer.py:213-221` | переписать `_score_oi`                                 |
| `plan/08-context.md`        | убрать ремарку «direction игнорируется» в блоке про OI |
| `tests/test_context.py`     | добавить тест для SELL-направления                     |

**Семантика**: рост OI = деньги входят в позиции. Если цена растёт и OI растёт — деньги
покупают (подтверждение BUY). Если цена падает и OI растёт — деньги шортят (подтверждение SELL).
Падение OI = деньги выходят (закрытие позиций) — слабый сигнал в обе стороны.

> ⚠️ Принято: **используем «направлённую шкалу»**, где рост OI считается подтверждением
> текущего направления сигнала, а падение — ослаблением. Альтернатива (зеркальная шкала,
> где рост OI плох для BUY) обсуждалась и **отклонена** как менее очевидная.

**Пошагово**:

1. Открой `context/scorer.py:213-221` и **полностью замени** метод `_score_oi`:
   ```python
   def _score_oi(self, delta: float, direction: str) -> float:
       # delta — % изменение OI с прошлого скана (см. context/fetcher.py).
       # Рост OI = деньги входят в позицию: подтверждение тренда в любую сторону.
       # direction параметр сохраняется в сигнатуре, чтобы все _score_* выглядели одинаково.
       _ = direction  # явно подавляем варн «unused arg» для линтера
       if delta > 2.0:
           return 0.5
       if delta > 0.0:
           return 0.2
       if delta > -2.0:
           return -0.1
       return -0.2
   ```
   ⚠️ Не меняй сигнатуру (`delta: float, direction: str`) — `score()` (строка 87)
   зовёт метод позиционно с двумя аргументами.
2. Если хочешь явно нейтрализовать «нулевую дельту» при холодном старте (когда
   `_last_oi` ещё не наполнен), добавь первой строкой:
   ```python
   if delta == 0.0:
       return 0.0
   ```
   Иначе `delta == 0.0` попадает в `delta > -2.0 → -0.1`, давая лёгкий минус. Это допустимо;
   с задачей **A2** холодный старт исчезает, так что обязательной правки нет.
3. В `plan/08-context.md` найди строку про `Open Interest` (в таблице вердиктов).
   Замени ремарку «direction игнорируется» на «оценка идентична для BUY/SELL: рост OI
   считается подтверждением направления».

**Тест** (`tests/test_context.py::TestContextScorer`):

```python
def test_oi_delta_sell_direction():
    from context.scorer import ContextScorer
    from context.analyzer import ContextSnapshot
    scorer = ContextScorer()
    snap = ContextSnapshot(
        symbol="BTC/USDT",
        open_interest=100.0,
        open_interest_delta=5.0,  # рост OI на 5%
    )
    verdict = scorer.score("SELL", snap)
    # OI растёт → +0.5 в нормализованном score (после нормализации)
    assert verdict.score > 0
    # И аналогично должен поддержать SELL
    assert any("OI" in s for s in verdict.supporting)
```

⚠️ Зависит от полей `ContextSnapshot`. Если у dataclass нет дефолтов для остальных
полей — добавь `=None` для отсутствующих параметров (это test-only setup), либо
передай минимальный набор обязательных полей.

**Edge cases**:

- `delta == 0.0` (холодный старт) — попадает в `> -2.0` (т.е. `-0.1`). После A2 это
  перестаёт быть проблемой (warm-up).
- `delta is None` (источник недоступен) — в `scorer.score()` (строка 84) есть
  `if snapshot.open_interest_delta is not None` → `_score_oi` не вызывается.

**Готовность**:

- `pytest tests/test_context.py::TestContextScorer -v` — все тесты зелёные, включая новый.
- В `plan/08-context.md` нет упоминаний «direction игнорируется» (grep -i:
  `rg -i 'direction.*игнор' plan/`).

---

### A4. Cooldown в БД (переживает рестарт)

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

---

### A5. 15M-подтверждение в меню `_do_full_analysis`

**Цель**: меню «🔍 Анализ токена» (см. `bot/menu.py:232-299`) сейчас оценивает сигнал только
на primary_tf (`1h` по умолчанию). Пользователь видит «BUY», но scheduler этот же сигнал не
публикует, если 15M показывает противоположное направление (см. `scheduler/scanner.py:77-99`).
Привести вывод меню в соответствие со scheduler'ом — показать пользователю статус подтверждения.

**Файлы и точные места**:

| Файл                  | Что делать                                                        |
|-----------------------|-------------------------------------------------------------------|
| `bot/menu.py:232-299` | вставить блок 15M-подтверждения в `_do_full_analysis`             |
| `plan/09-bot.md`      | в разделе `_do_full_analysis` отметить, что теперь делает confirm |

**Предусловия**:

- В `bot/menu.py:225-229` уже определён `_get_indicators(symbol, timeframe)` — переиспользуем.
- `cfg = config.trading` уже инициализирован в `_do_full_analysis` (строка 234).
- `primary_tf = cfg.primary_timeframes[0]` (строка 235).

**Пошагово**:

1. В `bot/menu.py:_do_full_analysis` **после** строки 239 (`result = signal_engine.evaluate(ind)`)
   вставь блок подтверждения:
   ```python
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
   ```
2. В уже существующем блоке `lines = [...]` (формируется построчно через `lines.append`),
   **после** строки 264 (`lines.append(f"  ❌ Флэт (ADX &lt; {config.trading.adx_min})")`)
   и перед блоком ATR (строка 265) добавь:
   ```python
   lines.append(f"\n🔁 <b>Подтверждение {confirm_tf}:</b> {confirm_status}")
   ```
   ⚠️ Использовать `html.escape` тут **не нужно** — `confirm_status` собирается из контролируемых
   литералов и `confirm_result.signal.value` (`BUY`/`SELL`/`NO_SIGNAL`).
3. **Не вырезай** показ деталей сигнала, если 15M не совпало — функция называется
   `analysis`, не `signal generation`. Аналитика идёт полностью, только пометка статуса.
4. В `plan/09-bot.md` найди раздел про `_do_full_analysis` и допиши абзац:
   «Дополнительно теперь делает confirmation lookup на `confirm_timeframe`
   (по умолчанию 15M) и выводит статус подтверждения, не блокируя показ аналитики».

**Edge cases**:

- `result.signal == NO_SIGNAL` → `result.is_actionable == False` → блок не выполняется,
  `confirm_status` остаётся `"—"`. Корректно.
- `confirm_tf == primary_tf` (юзер указал `CONFIRM_TIMEFRAME=1h`) → блок не выполняется,
  `confirm_status = "—"`. Корректно — подтверждать самим собой бессмысленно.
- `confirm_tf` — пустая строка в env → `if ... confirm_tf and ...` — блок пропускается.
- `_get_indicators` возвращает `None` (нет данных на 15M) → `"⚠️ нет данных {tf}"` —
  пользователь видит честный статус, аналитика на primary не страдает.

**Готовность**:

- Запусти бот: `python main.py`. В Telegram: `/menu → 🔍 Анализ токена → BTC`.
  В ответе должна появиться строка `🔁 Подтверждение 15m: ...`.
- Сравни вывод меню и сообщение от scheduler'а (`/scan` или авто-цикл) для того же символа:
  если меню показывает `❌ 15m: SELL` при BUY на 1H — scheduler этот сигнал **не** опубликует
  (увидишь `Signal NOT confirmed on 15m: ...` в логах).
- `pytest -v` зелёный (новых тестов не требует, но регрессии не должно быть).

---

### A6. Score-формула: ADX/DMI как реальные критерии (опционально)

**Цель**: формализовать «6 факторов + ADX-фильтр» — добавить ADX/DMI как реальные баллы,
тогда max score = 8 и `format_message` снова будет отражать корректное `/N`.

> ⚠️ **Это рефакторинг, не bugfix**. Меняет чувствительность сигналов на исторических данных.
> Запускать **только** если согласован с владельцем. Если согласования нет — пропусти задачу.

**Файлы и точные места**:

| Файл                               | Что делать                                           |
|------------------------------------|------------------------------------------------------|
| `strategy/signal_engine.py:69-178` | переписать `evaluate()` (см. шаги 1-3)               |
| `strategy/signal_engine.py:57`     | заменить `({self.score}/6)` → `({self.score}/8)`     |
| `bot/menu.py:289`                  | заменить `({result.score}/6)` → `({result.score}/8)` |
| `bot/menu.py:354`                  | то же                                                |
| `plan/06-signal-engine.md`         | обновить таблицу критериев и блок-схему              |
| `plan/12-flowchart.md`             | синхронизировать ветки «score >= 4»                  |
| `tests/test_signal.py`             | обновить ожидания по `result.score`                  |

**Выбор варианта**: используем **вариант A** (ADX как `+1` и DMI direction match как `+1`,
итого max score = 8). Зеркальный вариант (`/7`, только ADX) отклонён — DMI несёт независимую
информацию о направлении и должен учитываться отдельно.

**Пошагово**:

1. В `strategy/signal_engine.py:evaluate` **после** блока «--- Объём ---»
   (строки 133-137) и **перед** блоком «=== Принятие решения ===» (строка 139) добавь:
   ```python
   # --- ADX strong trend (≥ 25 — реальный «сильный» тренд, не просто > adx_min) ---
   if ind.adx >= 25.0:
       adx_strong_reason = f"ADX={ind.adx:.1f} (strong trend ≥ 25)"
       buy_reasons.append(adx_strong_reason)
       sell_reasons.append(adx_strong_reason)

   # --- DMI direction match (ассиметричный — даёт +1 только подходящей стороне) ---
   if ind.dmi_plus > ind.dmi_minus:
       buy_reasons.append(
           f"DMI+ > DMI- (+{ind.dmi_plus - ind.dmi_minus:.1f})"
       )
   else:
       sell_reasons.append(
           f"DMI- > DMI+ (+{ind.dmi_minus - ind.dmi_plus:.1f})"
       )
   ```
2. В обоих возвратах `return SignalResult(...)` (BUY на строках 146-157, SELL на
   строках 159-170) **убери** `+ [adx_reason, dmi_reason]` из `reasons=...`. Эти причины
   теперь уже сидят в `buy_reasons` / `sell_reasons` (см. шаг 1) — повторное добавление
   создаст дубли. Стало:
   ```python
   reasons=buy_reasons,
   ```
   и
   ```python
   reasons=sell_reasons,
   ```
3. Удали локальные переменные `adx_reason` и `dmi_reason` (строки 126-131) — они больше
   не используются.
4. Обнови знаменатель `/6` → `/8`:
    - `strategy/signal_engine.py:57` — `({self.score}/6)` → `({self.score}/8)`.
    - `bot/menu.py:289` — `({result.score}/6)` → `({result.score}/8)`.
    - `bot/menu.py:354` — то же.
   Sanity: `rg -n '/6\)' strategy bot` — после правок должен ничего не находить.
5. Порог `min_score = 4` (строка 144) — **оставь как есть**. Пропорция «4 of 8» ≈ «3 of 6»,
   чувствительность чуть мягче, и это намеренный side-effect рефакторинга.
   ⚠️ Если хочешь сохранить старую жёсткость — подними `min_score` до 5 и пересчитай тесты.
6. **Тесты** (`tests/test_signal.py`):
    - Найди все `assert result.score >= 4` / `assert result.score == N` — пересчитай.
      Для типичного полного сигнала (все 6 факторов + ADX-strong + DMI-match) ожидаемый score = 8.
    - При `20 ≤ ADX < 25` (тренд между `adx_min` и 25) score уменьшается на 1.
    - Запусти `pytest tests/test_signal.py -v` и обнови ассерты под фактические числа.

**Edge cases**:

- `ind.adx >= 25` уже подразумевает `adx_min == 20` пройден (фильтр флэта на строке 73).
  Без фильтра флэта `evaluate` вернёт `NO_SIGNAL` ещё раньше — добавочный балл не успеет.
- ADX и Volume оба дают `+1` обеим сторонам — перевес определяется EMA/RSI/MACD/DMI.
- DMI равные (`dmi_plus == dmi_minus`) — попадают в `else` (SELL). Это маргинальный случай,
  но не баг; альтернатива — не давать балл никому.

**Готовность**:

- `pytest tests/test_signal.py -v` зелёный.
- В Telegram сигнал показывает `(N/8)` (где `N` ≥ 4).
- `plan/06-signal-engine.md` и `plan/12-flowchart.md` синхронизированы.
  Sanity: `rg -n '/6' plan/` — не должно быть устаревших ссылок на старый знаменатель.

## Тесты / DX

### T1. CI на GitHub Actions

**Цель**: на каждый push в любую ветку и на каждый PR запускать `pytest -v` в GitHub Actions.
Текущее состояние: тестов > 100 (`pytest --collect-only -q`), но CI отсутствует.

**Файлы (новые)**:

| Файл                       | Назначение                                  |
|----------------------------|---------------------------------------------|
| `.github/workflows/test.yml` | Описание CI-пайплайна                     |
| `requirements-dev.txt`     | Pinned dev-зависимости для тестов           |

**Пошагово**:

1. Создай `requirements-dev.txt` (если есть `pyproject.toml` с `[project.optional-dependencies]`
   — добавь туда `test = [...]` вместо отдельного файла, но не смешивай оба варианта):
   ```
   pytest>=8,<9
   pytest-asyncio>=0.23,<1
   aioresponses>=0.7,<1
   ```
2. Создай `.github/workflows/test.yml`:
   ```yaml
   name: tests
   on:
     push:
     pull_request:
   jobs:
     test:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - name: Set up Python
           uses: actions/setup-python@v5
           with:
             python-version: "3.11"
             cache: pip
         - name: Install deps
           run: |
             python -m pip install --upgrade pip
             pip install -r requirements.txt -r requirements-dev.txt
         - name: Run tests
           run: pytest -v --tb=short
   ```
3. Проверь локально перед коммитом:
   ```bash
   pip install -r requirements.txt -r requirements-dev.txt
   pytest -v
   ```
   Все тесты должны быть зелёные.
4. Запушь и убедись в Actions UI, что джоба `tests` зелёная.

**Edge cases**:

- Если `pytest-asyncio` ругается на mode → добавь в `pyproject.toml` (или `pytest.ini`):
  ```ini
  [tool.pytest.ini_options]
  asyncio_mode = "auto"
  ```
- Если есть тесты, требующие `BINANCE_API_KEY` и т.п. → они должны мокаться или скипаться
  без env. Если падают — это сигнал, что тест не изолирован, фиксь тест, а не CI.

**Готовность**:

- Бэйдж `tests passing` в Actions для push в `master`.
- Зелёная джоба для open PR.

### T2. Тесты на свежие правки

**Цель**: покрыть тестами правки, уже принятые в этой/прошлых сессиях, и закрыть пробелы.

**Файлы**: `tests/test_context.py`, `tests/test_scanner.py`.

**Предусловия**:

- `aioresponses` уже задействован в проекте (см. другие тесты в `tests/test_context.py`).
- Все тесты — async, требуют `@pytest.mark.asyncio` и `pytest-asyncio` в зависимостях.

**Подзадачи (каждая — отдельный тест)**:

1. **OI delta — стандартный путь** (`tests/test_context.py::TestContextFetcher`):
   ```python
   @pytest.mark.asyncio
   async def test_oi_delta_between_calls():
       from context.fetcher import ContextFetcher
       fetcher = ContextFetcher()
       url = "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT"
       hist_url = (
           "https://fapi.binance.com/futures/data/openInterestHist"
           "?symbol=BTCUSDT&period=5m&limit=2"
       )
       with aioresponses() as m:
           # Первый вызов: warm-up через hist (см. A2) + текущее значение
           m.get(hist_url, payload=[
               {"sumOpenInterest": "100.0", "timestamp": 1},
               {"sumOpenInterest": "100.0", "timestamp": 2},
           ])
           m.get(url, payload={"openInterest": "100.0", "time": 1000})
           # Второй вызов: hist уже не дёргается (symbol in _last_oi)
           m.get(url, payload={"openInterest": "120.0", "time": 2000})

           first = await fetcher.fetch_open_interest("BTC/USDT")
           second = await fetcher.fetch_open_interest("BTC/USDT")
           await fetcher.close()

       assert first["open_interest"] == 100.0
       assert second["open_interest"] == 120.0
       assert abs(second["open_interest_delta"] - 20.0) < 1e-6
   ```
   ⚠️ Если **A2 не сделан** — убери `m.get(hist_url, ...)` и ожидай `first["open_interest_delta"] == 0.0`.

2. **News aggregation** (`tests/test_context.py::TestContextEngine`): проверить взвешенное
   усреднение CryptoPanic + RSS:
   ```python
   @pytest.mark.asyncio
   async def test_news_sentiment_aggregation(monkeypatch):
       from context.analyzer import context_engine

       async def fake_cp(symbol):
           return {"score": -0.5, "count": 10, "positive": 2, "negative": 7}

       async def fake_rss(symbol):
           return {"score": 0.3, "count": 5, "positive": 4, "negative": 1}

       monkeypatch.setattr(
           "context.analyzer.context_fetcher.fetch_cryptopanic", fake_cp
       )
       monkeypatch.setattr(
           "context.analyzer.context_fetcher.fetch_rss_news", fake_rss
       )
       # Заглушить остальные источники, чтобы не лезть в сеть
       for fn in ["fetch_fear_greed", "fetch_coingecko", "fetch_trending",
                  "fetch_funding_rate", "fetch_open_interest",
                  "fetch_long_short_ratio"]:
           monkeypatch.setattr(
               f"context.analyzer.context_fetcher.{fn}",
               lambda *a, **kw: _async_none(),
           )

       snap = await context_engine.get_snapshot("BTC/USDT")
       # weighted: (-0.5*10 + 0.3*5) / 15 = -0.2333...
       assert abs(snap.news_sentiment_score - (-7 / 30)) < 1e-3
   ```
   `_async_none()` — хелпер, возвращающий awaitable `None`:
   ```python
   async def _async_none():
       return None
   ```
   ⚠️ Точные имена `fetch_*` сверь по `context/analyzer.py`. Возможно у вас агрегация
   уже считает по-другому — ассерт настрой под фактическую формулу из кода.

3. **MIN_VERDICT гейт** (`tests/test_scanner.py::TestScanSymbol`):
   ```python
   @pytest.mark.asyncio
   async def test_scan_blocks_on_below_min_verdict(monkeypatch):
       from scheduler import scanner as sc
       from context.scorer import ContextVerdict

       # Сигнал actionable
       fake_result = MagicMock(is_actionable=True, signal=MagicMock(value="BUY"),
                               reasons=[], close=100.0)
       monkeypatch.setattr(sc.signal_engine, "evaluate", lambda ind: fake_result)
       monkeypatch.setattr(sc, "_get_indicators",
                           AsyncMock(return_value=MagicMock()))
       # Контекст: CONFLICTED < WEAK
       monkeypatch.setattr(
           sc.context_scorer, "score",
           lambda direction, snap: ContextVerdict(
               verdict="CONFLICTED", confidence=0.05, score=0.0,
           ),
       )
       monkeypatch.setattr(
           sc.context_engine, "get_snapshot",
           AsyncMock(return_value=MagicMock()),
       )
       monkeypatch.setattr(sc.config, "context_min_verdict", "WEAK")
       monkeypatch.setattr(sc.config, "context_enabled", True)

       cb = AsyncMock()
       result = await sc.scan_symbol("BTC/USDT", "1h", cb)
       assert result is None
       cb.assert_not_awaited()
   ```

4. **Funding rate** (`tests/test_context.py::TestContextFetcher`):
   ```python
   @pytest.mark.asyncio
   async def test_funding_rate_parses_negative():
       from context.fetcher import ContextFetcher
       fetcher = ContextFetcher()
       url = "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT"
       with aioresponses() as m:
           m.get(url, payload={"lastFundingRate": "-0.0042"})
           result = await fetcher.fetch_funding_rate("BTC/USDT")
           await fetcher.close()
       assert result == pytest.approx(-0.0042)
   ```

5. **`Signal.confirmed`** (`tests/test_scanner.py::TestConfirmedFlag`):
   - Случай 1: `confirm_tf == primary_tf` → `db.save_signal(confirmed=False)`.
   - Случай 2: 15M-данные `None` → `db.save_signal(confirmed=False)`.
   - Случай 3: 15M подтверждает → `db.save_signal(confirmed=True)`.

   Шаблон:
   ```python
   @pytest.mark.asyncio
   async def test_confirmed_flag_when_primary_eq_confirm(monkeypatch):
       from scheduler import scanner as sc
       monkeypatch.setattr(sc.config.trading, "confirm_timeframe", "1h")
       # ... setup actionable signal ...
       mock_save = AsyncMock(return_value=MagicMock(id=1))
       monkeypatch.setattr(sc.db, "save_signal", mock_save)
       monkeypatch.setattr(sc.config, "context_enabled", False)
       await sc.scan_symbol("BTC/USDT", "1h", AsyncMock())
       mock_save.assert_awaited_once()
       assert mock_save.call_args.kwargs["confirmed"] is False
   ```

**Готовность**:

- `pytest tests/test_context.py tests/test_scanner.py -v` — все тесты зелёные.
- Покрытие свежих фич не оставлено пробелом (визуально проверить
  `pytest --collect-only | grep -E 'news_sentiment|min_verdict|funding|confirmed'`).

### T3. Прочее — операционные улучшения (mini-tickets)

Каждый подпункт — самостоятельный мини-тикет. Берись по приоритету (см. шпаргалку внизу).
Все они «low» и не требуют срочности; обоснование добавлено в каждом.

#### T3.1. CI/CD pipeline (деплой)

**Цель**: после зелёных тестов автоматически собрать Docker-образ и запушить в registry.

**Файлы (новые)**:

- `.github/workflows/deploy.yml`
- `Dockerfile` (если отсутствует — проверь корень репо)

**Пошагово**:

1. Минимальный `Dockerfile` (если нет):
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY . .
   CMD ["python", "main.py"]
   ```
2. Workflow `.github/workflows/deploy.yml`:
   ```yaml
   name: deploy
   on:
     push:
       branches: [master]
     workflow_run:
       workflows: [tests]
       types: [completed]
   jobs:
     build:
       if: ${{ github.event.workflow_run.conclusion == 'success' || github.event_name == 'push' }}
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: docker/setup-buildx-action@v3
         - uses: docker/login-action@v3
           with:
             registry: ghcr.io
             username: ${{ github.actor }}
             password: ${{ secrets.GITHUB_TOKEN }}
         - uses: docker/build-push-action@v5
           with:
             context: .
             push: true
             tags: |
               ghcr.io/${{ github.repository }}:latest
               ghcr.io/${{ github.repository }}:${{ github.sha }}
   ```
3. В Settings → Packages дай repo access. Образ появится в `ghcr.io/<owner>/<repo>`.

**Edge cases**:

- В образе не должно быть `.env` / `data/*.db` — добавь `.dockerignore`:
  ```
  .env
  data/
  logs/
  .git/
  __pycache__/
  tests/
  ```

#### T3.2. Мониторинг и алертинг

**Цель**: получать алёрт о падении бота, а не узнавать постфактум.

**Простой вариант** — отдельный Telegram-канал для ERROR-логов:

1. В `config/settings.py` добавь:
   ```python
   error_channel_id: str = os.getenv("TELEGRAM_ERROR_CHANNEL_ID", "")
   ```
2. В `config/logging.py` (или там, где настраивается loguru) добавь sink:
   ```python
   from loguru import logger

   if config.telegram.error_channel_id:
       async def telegram_sink(message):
           # message — Record (loguru). Берём message.record["message"]
           await application.bot.send_message(
               config.telegram.error_channel_id,
               text=f"⚠️ {message.record['message'][:3500]}",
           )
       # Уровень ERROR и выше
       logger.add(telegram_sink, level="ERROR", enqueue=True)
   ```
3. Тест: `logger.error("test alert")` — должно прилететь в канал.

**Альтернатива** — Sentry SDK: `pip install sentry-sdk`, в `main.py` до старта бота
`sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"), traces_sample_rate=0.0)`. Хватает default-конфига.

⚠️ Если выбираешь Sentry — убери Telegram-sink: получишь два уведомления на каждый ERROR.

#### T3.3. Rate limiting

**Цель**: защитить бота от спама от одного пользователя.

**Файлы**: `bot/handlers.py` или `bot/middleware.py` (новый).

**Шаги**:

1. Добавь `aiolimiter>=1.1` в `requirements.txt`.
2. Создай `bot/rate_limit.py`:
   ```python
   from collections import defaultdict
   from aiolimiter import AsyncLimiter

   # 5 событий в 10 секунд на user_id
   _limiters: dict[int, AsyncLimiter] = defaultdict(
       lambda: AsyncLimiter(max_rate=5, time_period=10)
   )

   def get_limiter(user_id: int) -> AsyncLimiter:
       return _limiters[user_id]
   ```
3. В `bot/menu.py:handle_menu_callback` (строка 72) первой строкой:
   ```python
   from bot.rate_limit import get_limiter
   limiter = get_limiter(update.effective_user.id)
   if not limiter.has_capacity():
       await query.answer("⏳ Слишком часто, подожди 10 секунд", show_alert=True)
       return
   async with limiter:
       ...  # остальная логика
   ```

**Edge cases**: память без верхней границы — для prod добавь LRU/`functools.lru_cache(maxsize=10000)`.

#### T3.4. Метрики Prometheus

**Цель**: иметь дашборд по работе бота (сигналы, длительность сканов, ошибки контекста).

**Файлы**:

- `requirements.txt` — добавь `prometheus_client>=0.20`.
- `monitoring/metrics.py` (новый).
- `main.py` — стартовать HTTP-сервер с `start_http_server`.

**Шаги**:

1. `monitoring/metrics.py`:
   ```python
   from prometheus_client import Counter, Histogram

   signals_total = Counter(
       "tgbot_signals_total",
       "Сигналы, опубликованные ботом",
       labelnames=("signal_type", "symbol", "timeframe"),
   )

   scan_duration_seconds = Histogram(
       "tgbot_scan_duration_seconds",
       "Длительность одного scan_symbol",
       labelnames=("timeframe",),
   )

   context_fetch_errors_total = Counter(
       "tgbot_context_fetch_errors_total",
       "Ошибки в контекстном модуле",
       labelnames=("source",),
   )
   ```
2. В `scheduler/scanner.py:scan_symbol` оберни тело в `Histogram.time()`:
   ```python
   from monitoring.metrics import scan_duration_seconds, signals_total
   ...
   async def scan_symbol(symbol, timeframe, notify_callback):
       with scan_duration_seconds.labels(timeframe=timeframe).time():
           ... # текущее тело
           # перед `return result`:
           signals_total.labels(
               signal_type=result.signal.value,
               symbol=symbol,
               timeframe=timeframe,
           ).inc()
           return result
   ```
3. В `context/analyzer.py` (где ловятся exceptions источников) перед `logger.warning`:
   ```python
   from monitoring.metrics import context_fetch_errors_total
   context_fetch_errors_total.labels(source="cryptopanic").inc()
   ```
4. В `main.py` до старта event loop:
   ```python
   from prometheus_client import start_http_server
   start_http_server(int(os.getenv("METRICS_PORT", "9090")))
   ```
5. Проверь: `curl localhost:9090/metrics | grep tgbot_` — должны быть строки.

**Edge cases**: если порт 9090 занят — сделай конфигурируемым (env `METRICS_PORT`, как
в коде выше). Если бот не должен слушать сеть — оставь экспорт opt-in через
`METRICS_ENABLED=false` гейт.

## Функциональность

### F1. SL/PnL трекинг открытых сигналов

**Цель**: после публикации сигнала отслеживать, достиг ли он TP или сработал SL, и
рассчитывать кумулятивную статистику (win rate, средний R/R, суммарный PnL).

> ⚠️ Объём работ большой. Если ты не уверен в архитектуре — остановись после шага 1
> (БД-таблица + миграция) и согласуй с владельцем. Без согласования дальше не иди.

**Файлы**:

| Файл                        | Что делать                                                |
|-----------------------------|-----------------------------------------------------------|
| `storage/database.py`       | новая модель `SignalOutcome`, методы CRUD                 |
| `scheduler/outcome_tracker.py` (new) | фоновая задача опроса цен                        |
| `scheduler/__init__.py`     | регистрация задачи в общий scheduler                      |
| `bot/handlers.py` или `bot/admin.py` | команда `/stats`                                 |
| `tests/test_outcome_tracker.py` (new) | unit-тесты на закрытие по TP/SL                 |

**Пошагово**:

1. **Модель в БД** (`storage/database.py`, рядом с `Signal`):
   ```python
   class SignalOutcome(Base):
       __tablename__ = "signal_outcomes"

       id = Column(Integer, primary_key=True, autoincrement=True)
       signal_id = Column(
           Integer, ForeignKey("signals.id"), nullable=False, index=True
       )
       status = Column(String(20), nullable=False, default="OPEN")
       # OPEN / HIT_TP / HIT_SL / EXPIRED / MANUAL_CLOSE
       closed_at = Column(DateTime, nullable=True)
       close_price = Column(Float, nullable=True)
       pnl_pct = Column(Float, nullable=True)
       checked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
   ```
   В `Database` добавь методы:
   ```python
   async def create_outcome(self, signal_id: int) -> "SignalOutcome":
       async with self._session_factory() as session:
           outcome = SignalOutcome(signal_id=signal_id, status="OPEN")
           session.add(outcome)
           await session.commit()
           await session.refresh(outcome)
           return outcome

   async def get_open_outcomes(self) -> list["SignalOutcome"]:
       async with self._session_factory() as session:
           result = await session.execute(
               select(SignalOutcome).where(SignalOutcome.status == "OPEN")
           )
           return list(result.scalars().all())

   async def close_outcome(
       self, outcome_id: int, status: str, close_price: float, pnl_pct: float
   ) -> None:
       async with self._session_factory() as session:
           result = await session.execute(
               select(SignalOutcome).where(SignalOutcome.id == outcome_id)
           )
           row = result.scalar_one()
           row.status = status
           row.close_price = close_price
           row.pnl_pct = pnl_pct
           row.closed_at = datetime.now(timezone.utc)
           await session.commit()
   ```
   `Base.metadata.create_all` (строки 71-74) автоматически создаст таблицу при следующем
   запуске. Миграция не нужна (sqlite + dev-стадия проекта).

2. **Создание outcome при публикации сигнала** (`scheduler/scanner.py`, после
   `saved_signal = await db.save_signal(...)` на строке 154):
   ```python
   await db.create_outcome(saved_signal.id)
   ```

3. **Фоновая задача** (`scheduler/outcome_tracker.py`, new):
   ```python
   import asyncio
   from datetime import datetime, timezone, timedelta
   from loguru import logger
   from config.settings import config
   from data.exchange_client import exchange_client
   from storage.database import db, Signal

   OUTCOME_CHECK_INTERVAL_SECONDS = int(
       __import__("os").getenv("OUTCOME_CHECK_INTERVAL_SECONDS", "300")
   )
   OUTCOME_TTL_DAYS = int(__import__("os").getenv("OUTCOME_TTL_DAYS", "7"))


   async def check_open_outcomes() -> None:
       outcomes = await db.get_open_outcomes()
       if not outcomes:
           return
       logger.debug(f"Checking {len(outcomes)} open outcomes")
       for outcome in outcomes:
           signal = await db.get_signal(outcome.signal_id)  # ← добавь get_signal в БД
           if signal is None:
               continue
           # Просроченный сигнал → EXPIRED
           age = datetime.now(timezone.utc) - signal.created_at.replace(
               tzinfo=timezone.utc
           )
           if age > timedelta(days=OUTCOME_TTL_DAYS):
               await db.close_outcome(
                   outcome.id, "EXPIRED",
                   close_price=signal.close_price, pnl_pct=0.0,
               )
               continue
           # Текущая цена через 1m свечу
           df = await exchange_client.fetch_ohlcv(signal.symbol, "1m", limit=2)
           if df is None or df.empty:
               continue
           current = float(df["close"].iloc[-1])
           hit_tp = (
               signal.signal_type == "BUY" and signal.tp and current >= signal.tp
           ) or (
               signal.signal_type == "SELL" and signal.tp and current <= signal.tp
           )
           hit_sl = (
               signal.signal_type == "BUY" and signal.sl and current <= signal.sl
           ) or (
               signal.signal_type == "SELL" and signal.sl and current >= signal.sl
           )
           if hit_tp:
               pnl = (current - signal.close_price) / signal.close_price * 100
               if signal.signal_type == "SELL":
                   pnl = -pnl
               await db.close_outcome(outcome.id, "HIT_TP", current, pnl)
               logger.info(f"Outcome HIT_TP: signal_id={signal.id} pnl={pnl:.2f}%")
           elif hit_sl:
               pnl = (current - signal.close_price) / signal.close_price * 100
               if signal.signal_type == "SELL":
                   pnl = -pnl
               await db.close_outcome(outcome.id, "HIT_SL", current, pnl)
               logger.info(f"Outcome HIT_SL: signal_id={signal.id} pnl={pnl:.2f}%")


   async def outcome_tracker_loop() -> None:
       while True:
           try:
               await check_open_outcomes()
           except Exception as e:
               logger.warning(f"Outcome tracker error: {e}")
           await asyncio.sleep(OUTCOME_CHECK_INTERVAL_SECONDS)
   ```

4. **Регистрация задачи**. В точке входа scheduler'а (`scheduler/__init__.py` или там,
   где идёт `apscheduler` setup) добавь:
   ```python
   import asyncio
   from scheduler.outcome_tracker import outcome_tracker_loop

   # Запустить как фоновую задачу при старте event loop
   asyncio.create_task(outcome_tracker_loop())
   ```
   Точное место зависит от структуры — посмотри `plan/07-scheduler.md` и текущий код
   `scheduler/`.

5. **Команда `/stats`** (`bot/handlers.py` или `bot/admin.py`):
   ```python
   from telegram import Update
   from telegram.ext import ContextTypes
   from telegram.constants import ParseMode

   @_admin_only
   async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
       stats = await db.get_outcome_stats()  # ← добавь в БД (см. ниже)
       total = stats["closed"] or 1
       win_rate = stats["wins"] / total * 100
       text = (
           f"📊 <b>Статистика сигналов</b>\n\n"
           f"Всего закрытых: <b>{stats['closed']}</b>\n"
           f"Открытых: <b>{stats['open']}</b>\n"
           f"Win rate: <b>{win_rate:.1f}%</b> ({stats['wins']}/{total})\n"
           f"Средний PnL: <b>{stats['avg_pnl']:.2f}%</b>\n"
           f"Лучший: <b>{stats['best_pnl']:.2f}%</b>\n"
           f"Худший: <b>{stats['worst_pnl']:.2f}%</b>"
       )
       await update.message.reply_text(text, parse_mode=ParseMode.HTML)
   ```
   Добавь `get_outcome_stats` в `Database`:
   ```python
   async def get_outcome_stats(self) -> dict:
       async with self._session_factory() as session:
           closed = await session.execute(
               select(SignalOutcome).where(SignalOutcome.status != "OPEN")
           )
           closed_rows = list(closed.scalars().all())
           opened = await session.execute(
               select(SignalOutcome).where(SignalOutcome.status == "OPEN")
           )
           opened_rows = list(opened.scalars().all())
       pnls = [r.pnl_pct for r in closed_rows if r.pnl_pct is not None]
       return {
           "closed": len(closed_rows),
           "open": len(opened_rows),
           "wins": sum(1 for r in closed_rows if r.status == "HIT_TP"),
           "avg_pnl": sum(pnls) / len(pnls) if pnls else 0.0,
           "best_pnl": max(pnls) if pnls else 0.0,
           "worst_pnl": min(pnls) if pnls else 0.0,
       }
   ```
   Зарегистрируй handler: `application.add_handler(CommandHandler("stats", stats_command))`.

6. **Тест** (`tests/test_outcome_tracker.py`):
    - Замокать `db.get_open_outcomes`, `db.get_signal`, `exchange_client.fetch_ohlcv`.
    - Кейсы: цена > TP (BUY) → HIT_TP с положительным PnL; цена < SL → HIT_SL;
      цена в коридоре → outcome остаётся OPEN; просроченный сигнал → EXPIRED.

**Edge cases**:

- ccxt rate limits — `fetch_ohlcv` для каждого open outcome на каждом тике может ударить
  по rate-лимиту, если открытых сигналов десятки. Если планируется > 20 open outcomes —
  батчить через `fetch_tickers` (один запрос на список символов).
- Двойное закрытие — `get_open_outcomes` фильтрует `status == "OPEN"`, после `close_outcome`
  outcome уже не вернётся.
- Биржа упала / нет данных — `fetch_ohlcv` возвращает `None`, проверка скипается, повтор через
  `OUTCOME_CHECK_INTERVAL_SECONDS`.
- Свеча 1m даёт `close` на момент закрытия минуты; реальная цена может пробить TP/SL внутри
  минуты и вернуться. Для строгости брать `high`/`low` 1m свечи, а не `close`.

**Готовность**:

- `pytest tests/test_outcome_tracker.py -v` зелёный.
- При ручном тесте: сгенерируй сигнал, дождись пока цена пробьёт TP/SL —
  `sqlite3 data/signals.db "select * from signal_outcomes"` показывает закрытие.
- `/stats` в Telegram возвращает осмысленные числа.

### F2. Поддержка futures для OHLCV

**Цель**: сейчас ccxt-клиент создан с `defaultType=spot` (`data/exchange_client.py:23`).
Для futures-стратегий нужен либо отдельный инстанс, либо переключаемый флаг.

**Файлы и точные места**:

| Файл                              | Что делать                                       |
|-----------------------------------|--------------------------------------------------|
| `config/settings.py:21-27`        | добавить поле `market_type` в `ExchangeConfig`   |
| `data/exchange_client.py:16-25`   | пробросить `defaultType` из конфига              |
| `.env.example`                    | добавить `MARKET_TYPE=spot`                      |
| `plan/14-env-config.md`           | задокументировать переменную                     |

**Пошагово**:

1. В `config/settings.py` в `@dataclass class ExchangeConfig` (строки 21-27) добавь поле:
   ```python
   market_type: str = os.getenv("MARKET_TYPE", "spot")  # spot | future
   ```
2. В `data/exchange_client.py:16-25` (метод `connect`) измени строку 23:
   ```python
   "options": {"defaultType": config.exchange.market_type},
   ```
3. В `.env.example` добавь:
   ```
   # Тип рынка для OHLCV (spot | future).
   # ⚠️ Funding rate / OI / L-S всегда читаются с fapi.binance.com независимо от этой настройки.
   MARKET_TYPE=spot
   ```
4. В `plan/14-env-config.md` под секцией `EXCHANGE` добавь строку про `MARKET_TYPE`.

**Edge cases**:

- Не все символы из `SYMBOLS` существуют на futures — `fetch_ohlcv` вернёт `None`, ничего
  страшного. В логах будет `Exchange error`.
- Funding rate / OI / Long-Short — это всегда USDT-M futures независимо от `MARKET_TYPE`
  (см. `context/fetcher.py:138, 165, 199` — там захардкожен `fapi.binance.com`).
  Это **намеренно** — спот-контекст для них бессмысленен. Не путай пользователя.
- ccxt при `defaultType=future` шлёт запросы на другой эндпоинт (`fapi`), цены будут отличаться
  от спот-цен. Это ожидаемо и нормально для futures-стратегий.

**Готовность**:

- С `MARKET_TYPE=spot` (default) — ничего не сломалось, `pytest -v` зелёный.
- С `MARKET_TYPE=future` — на старте лог `Exchange client created: binance`,
  `fetch_ohlcv` возвращает данные. Sanity:
  `python -c "import asyncio; from data.exchange_client import exchange_client; \
   async def main(): \
       await exchange_client.connect(); \
       df = await exchange_client.fetch_ohlcv('BTC/USDT', '1h', 5); \
       print(df); \
       await exchange_client.close(); \
   asyncio.run(main())"`.

### F3. Динамическое управление символами через Telegram

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

### F4. Расширение admin-команд

Три независимых мини-задачи. Все используют декоратор `_admin_only` (см. существующий
код — обычно в `bot/handlers.py` или `bot/admin.py`; если ещё нет — реализуй сначала
шаблон ниже).

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

#### F4.1. `/setparam <name> <value>` — runtime-изменение параметра

**Цель**: подкрутить `EMA_FAST`, `RSI_PERIOD` и пр. без рестарта.

**Зависимости**: задача [A1](#a1-параметры-индикаторов-через-env) должна быть выполнена
(параметры читаются из env), иначе менять негде.

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

#### F4.2. `/disable <symbol>` — временно выключить символ

**Цель**: убрать символ из сканирования, но сохранить в списке. После `/enable <symbol>`
вернуть.

**Шаги**:

1. В БД: ключ `disabled_symbols` (CSV), методы `get_disabled_symbols`/`set_disabled_symbols`
   по аналогии с F3.
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

#### F4.3. `/exportdb` — выгрузить БД админу

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

**Готовность F4**:

- `/setparam`, `/disable`, `/enable`, `/exportdb` появляются в `BotCommand`-listе
  (зарегистрированы через `application.add_handler(CommandHandler(...))`).
- Каждая команда отказывает не-админу с понятным сообщением.
- `pytest tests/test_admin_*.py -v` зелёный (если написаны).

---

## Шпаргалка по приоритетам

| Приоритет   | Задачи             | Почему                                  |
|-------------|--------------------|-----------------------------------------|
| 🔴 critical | A4 (cooldown в БД) | Без этого cooldown не работает в Docker |
| 🟠 high     | A1, T1, T2         | Эксплуатационная гибкость + регрессии   |
| 🟡 medium   | A2, A3, A5         | Качество сигналов и UX                  |
| 🟢 low      | A6, T3, F1–F4      | Новая функциональность, не баги         |
