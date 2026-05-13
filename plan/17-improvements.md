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

| Файл                         | Что делать                                                                |
| ---------------------------- | ------------------------------------------------------------------------- |
| `config/settings.py:29-61`   | переписать поля `TradingConfig` на чтение из env                          |
| `.env.example`               | добавить 20 строк под заголовком `# Indicator parameters (defaults shown)` |
| `plan/14-env-config.md`      | добавить таблицу `Indicator parameters` (var, default, type)              |
| `tests/test_config.py` (new) | один тест через `monkeypatch.setenv` + `importlib.reload`                 |

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
5. Создай `tests/test_config.py` (если ещё нет — проверь `ls tests/`):
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
| ---------------------------- | ----------------------------------------------- |
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

| Файл                            | Что делать                                              |
| ------------------------------- | ------------------------------------------------------- |
| `context/scorer.py:213-221`     | переписать `_score_oi`                                  |
| `plan/08-context.md`            | убрать ремарку «direction игнорируется» в блоке про OI  |
| `tests/test_context.py`         | добавить тест для SELL-направления                      |

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

**Цель**: сейчас `_last_signal_time` в `scheduler/scanner.py` — модульный `dict`, при рестарте
обнуляется. Это критично: если процесс перезапускается каждый час (Docker/CI), cooldown не
работает вообще. Хранить в БД.

**Files**:

- `storage/database.py` — добавить методы `get_cooldown` / `set_cooldown` (либо
  использовать `BotSetting` с ключом `cooldown:{symbol}:{timeframe}`)
- `scheduler/scanner.py` — `_is_cooldown_active` / `_set_cooldown` сделать async
- `tests/test_scanner.py` — обновить тесты, патчить новые методы

**Шаги**:

1. В `storage/database.py` добавь:
   ```python
   async def get_cooldown(self, symbol: str, timeframe: str) -> Optional[datetime]:
       key = f"cooldown:{symbol}:{timeframe}"
       val = await self.get_setting(key, "")
       if not val:
           return None
       return datetime.fromisoformat(val)

   async def set_cooldown(self, symbol: str, timeframe: str, ts: datetime) -> None:
       key = f"cooldown:{symbol}:{timeframe}"
       await self.set_setting(key, ts.isoformat())
   ```
   Использует существующую таблицу `bot_settings` — отдельная таблица не нужна.
2. В `scheduler/scanner.py`:
    - Удали модульный `_last_signal_time: dict`.
    - `async def _is_cooldown_active(symbol, timeframe) -> bool`:
      ```python
      last = await db.get_cooldown(symbol, timeframe)
      if last is None:
          return False
      if last.tzinfo is None:
          last = last.replace(tzinfo=timezone.utc)
      return (datetime.now(timezone.utc) - last) < timedelta(minutes=config.signal_cooldown_minutes)
      ```
    - `async def _set_cooldown(symbol, timeframe)`:
      ```python
      await db.set_cooldown(symbol, timeframe, datetime.now(timezone.utc))
      ```
    - В `scan_symbol` все вызовы `_is_cooldown_active` / `_set_cooldown` теперь `await`-ятся.
3. Обнови `tests/test_scanner.py`:
    - Фикстура `clear_cooldown` теперь не работает с модульным dict; вместо неё нужно мокать
      `db.get_cooldown` / `db.set_cooldown` через `patch("scheduler.scanner.db")`.
    - Тесты `TestCooldown::test_*` переписать на async с мокированной БД.

**Edge cases**:

- БД не инициализирована при первом scan'е — `get_setting` вернёт пустую строку (есть default),
  `_is_cooldown_active` вернёт False. OK.
- TZ-naive `datetime` в БД — выше есть guard `if last.tzinfo is None: replace(tzinfo=utc)`.
  Не убирай его.

**Готовность**:

- `pytest tests/test_scanner.py::TestCooldown -v` зелёный.
- Ручной тест: запустить бот, дождаться сигнала, перезапустить процесс, убедиться что cooldown
  всё ещё активен (повторный `/scan` для того же символа не выдаёт сигнал).

---

### A5. 15M-подтверждение в меню `_do_full_analysis`

**Цель**: меню «🔍 Анализ токена» сейчас оценивает сигнал только на primary_tf (`1h` по умолчанию).
Пользователь видит «BUY», но scheduler этот же сигнал не публикует, если 15M показывает
противоположное направление. Привести меню в соответствие со scheduler'ом.

**Files**:

- `bot/menu.py` — функция `_do_full_analysis(symbol)`
- `plan/09-bot.md` — синхронизировать описание

**Шаги**:

1. В `_do_full_analysis` (после `result = signal_engine.evaluate(ind)`) добавь блок
   подтверждения, аналогичный scanner'у:
   ```python
   confirm_tf = cfg.confirm_timeframe
   confirm_status = "—"  # для UI
   if result.is_actionable and confirm_tf and confirm_tf != primary_tf:
       ind_confirm = await _get_indicators(symbol, confirm_tf)
       if ind_confirm is not None:
           confirm_result = signal_engine.evaluate(ind_confirm)
           if confirm_result.signal == result.signal:
               confirm_status = f"✅ {confirm_tf} подтверждает"
           else:
               confirm_status = f"❌ {confirm_tf}: {confirm_result.signal.value}"
       else:
           confirm_status = f"⚠️ нет данных {confirm_tf}"
   ```
2. Добавь в выводимый текст (например после строки про ADX/трэнд):
   ```python
   lines.append(f"\n🔁 <b>Подтверждение:</b> {confirm_status}")
   ```
3. **Не отменяй** показ деталей сигнала, если 15M не совпало — пользователь хочет видеть всю
   аналитику; просто пометь несовпадение. (Это `analysis`, не `signal generation`.)
4. Обнови `plan/09-bot.md`: раздел `_do_full_analysis` — теперь делает confirmation lookup.

**Edge cases**:

- `result.signal == NO_SIGNAL` — confirmation не нужен, оставь `confirm_status = "—"` или
  пропусти блок целиком.
- `confirm_tf == primary_tf` — то же.

**Готовность**:

- Запусти бот, нажми «🔍 Анализ токена» для BTC. В ответе должна появиться строка
  «🔁 Подтверждение: …».
- Сравни вывод меню с поведением scheduler'а для того же символа — направление и наличие
  «✅ Подтверждение на …» в `reasons` должны коррелировать.

---

### A6. Score-формула: ADX/DMI как реальные критерии (опционально)

**Цель**: формализовать «6 факторов + ADX-фильтр» либо ввести ADX/DMI как реальные баллы
(тогда max score = 7 или 8, и `format_message` снова покажет `/N`).

**Files**:

- `strategy/signal_engine.py` — `evaluate()` и `format_message()`
- `bot/menu.py` — `({score}/N)` в двух местах
- `plan/06-signal-engine.md` — обновить таблицу и блок-схему
- `plan/12-flowchart.md` — обновить

**Шаги (вариант A — ADX strong-trend как +1, DMI direction match как +1)**:

1. После блока «--- Объём ---» в `evaluate`:
   ```python
   # --- ADX как критерий силы тренда (≥ 25 = strong) ---
   if ind.adx >= 25.0:
       buy_reasons.append(f"ADX={ind.adx:.1f} (strong trend)")
       sell_reasons.append(f"ADX={ind.adx:.1f} (strong trend)")

   # --- DMI direction match ---
   if ind.dmi_plus > ind.dmi_minus:
       buy_reasons.append(f"DMI+ > DMI- (+{ind.dmi_plus - ind.dmi_minus:.1f})")
   else:
       sell_reasons.append(f"DMI- > DMI+ (+{ind.dmi_minus - ind.dmi_plus:.1f})")
   ```
2. Удали `adx_reason` и `dmi_reason` из `reasons + [adx_reason, dmi_reason]` (теперь
   они уже в buy_reasons/sell_reasons).
3. `format_message` и `bot/menu.py`: знаменатель `/6` → `/8` (если оба варианта добавлены) либо
   `/7` (только ADX).
4. `min_score` остаётся 4 — пропорция чувствительности «4 of 8» ≈ «3 of 6», станет немного мягче.
   Можно поднять до 5.

**Edge cases**:

- ADX >= 25 уже неявно подразумевает >= 20 (фильтр флэта), так что для тренда добавляются
  баллы за обе стороны. Volume + ADX оба = +1 в обе стороны. Победитель всё равно определяется
  перевесом.
- Если поднимаешь `min_score` до 5 — пересчитай ожидания в `tests/test_signal.py`.

**Готовность**:

- Все тесты в `tests/test_signal.py::TestSignalCriteria` зелёные.
- Если изменён max score — обнови ассерты `result.score >= 4` на новый порог.

> ⚠️ Это рефакторинг, не bugfix. Запускать только если согласован с владельцем — меняет
> чувствительность сигналов на исторических данных.

## Тесты / DX

### T1. CI на GitHub Actions

**Цель**: на каждый push прогонять `pytest -v`.

**Files**:

- `.github/workflows/test.yml` (new)
- `requirements-dev.txt` (new) — pytest, pytest-asyncio, aioresponses

**Шаги**:

1. Создай `requirements-dev.txt`:
   ```
   pytest>=8
   pytest-asyncio>=0.23
   aioresponses>=0.7
   ```
2. Создай `.github/workflows/test.yml`:
   ```yaml
   name: tests
   on: [push, pull_request]
   jobs:
     test:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with: { python-version: "3.11" }
         - run: pip install -r requirements.txt -r requirements-dev.txt
         - run: pytest -v
   ```
3. Проверь локально: `pip install -r requirements-dev.txt && pytest -v` — все тесты зелёные.

### T2. Тесты на новые формулы

**Цель**: покрыть тестами правки, внесённые в этой сессии.

**Files**: `tests/test_context.py`, `tests/test_scanner.py`

**Шаги**:

1. **OI delta**: в `TestContextFetcher` добавь тест, который дважды дёргает
   `fetch_open_interest` с разными значениями `openInterest` через `aioresponses` и проверяет,
   что вторая дельта = ожидаемый процент.
2. **News aggregation**: в `TestContextEngine` добавь тест, где CryptoPanic возвращает
   `{score: -0.5, count: 10}`, RSS — `{score: +0.3, count: 5}`. Ожидание:
   `news_sentiment_score = (-0.5*10 + 0.3*5) / 15 ≈ -0.233`.
3. **MIN_VERDICT гейт**: в `TestScanSymbol` добавь тест, где `context_scorer.score` возвращает
   `CONFLICTED`, `config.context_min_verdict = "WEAK"`, `mock_signal_result.is_actionable = True`
   — ожидание: `result is None`.
4. **Funding rate**: тест на `fetch_funding_rate` с моком `aioresponses`, payload
   `{"lastFundingRate": "-0.0042"}` — ожидание `-0.0042`.
5. **`Signal.confirmed`**: проверь, что при `confirm_tf == primary_tf` или при недоступности
   15M-данных `db.save_signal` зовётся с `confirmed=False`. Используй `mock_db.save_signal.call_args`.

### T3. Прочее (только перечислением — детали по запросу)

- **CI/CD** — деплой через GitHub Actions + Docker push в registry.
- **Мониторинг/алертинг** — Sentry или просто отдельный канал для ошибок.
- **Rate limiting** — `python-telegram-bot` имеет встроенный `ContextTypes`, либо `aiolimiter`.
- **Метрики Prometheus** — `prometheus_client`, endpoint `:9090/metrics`, экспортировать
  `signals_total`, `scan_duration_seconds`, `context_fetch_errors_total`.

## Функциональность

### F1. SL/PnL трекинг открытых сигналов

**Цель**: после публикации сигнала отслеживать, достиг ли он TP или сработал SL, и
рассчитывать кумулятивную статистику.

**Объём работ большой** — отдельная задача с собственным design doc'ом. Минимум:

1. Таблица `signal_outcomes(signal_id FK, status [OPEN/HIT_TP/HIT_SL], closed_at, pnl_pct)`.
2. Фоновая задача в scheduler, которая раз в N минут опрашивает текущие цены для открытых
   сигналов и закрывает их по факту.
3. Команда `/stats` для админа: win rate, средний R/R, PnL.

### F2. Поддержка futures для OHLCV

**Цель**: сейчас ccxt-клиент создан с `defaultType=spot`. Для futures-стратегий нужен отдельный
инстанс или флаг.

**Файлы**: `data/exchange_client.py`, `config/settings.py`.

**Шаги**:

1. В `ExchangeConfig` добавь `market_type: str = os.getenv("MARKET_TYPE", "spot")`.
2. В `connect()` пробрось `"options": {"defaultType": config.exchange.market_type}`.
3. Описать в `plan/14-env-config.md` и `.env.example`.

### F3. Динамическое управление символами через Telegram

**Цель**: команда `/addsymbol BTC/USDT` / `/removesymbol BTC/USDT` (admin-only) с
персистентностью в БД.

**Объём**: средний. Использовать `BotSetting` для хранения списка либо отдельную таблицу.

### F4. Расширение admin-команд

- `/setparam <name> <value>` — runtime-изменение параметра индикатора.
- `/disable <symbol>` — временно выключить символ без удаления.
- `/exportdb` — выгрузить БД (для бэкапа/анализа).

Все — admin-only через существующий декоратор `_admin_only`.

---

## Шпаргалка по приоритетам

| Приоритет   | Задачи             | Почему                                  |
|-------------|--------------------|-----------------------------------------|
| 🔴 critical | A4 (cooldown в БД) | Без этого cooldown не работает в Docker |
| 🟠 high     | A1, T1, T2         | Эксплуатационная гибкость + регрессии   |
| 🟡 medium   | A2, A3, A5         | Качество сигналов и UX                  |
| 🟢 low      | A6, T3, F1–F4      | Новая функциональность, не баги         |
