# Trading Signal Bot — Полный функциональный план

## 1. Архитектура (общая схема)

```
main.py (точка входа, async event loop)
 ├── config/         (.env → dataclass singleton, loguru)
 ├── data/           (ccxt async → OHLCV DataFrame)
 ├── indicators/     (pandas-ta: 6 индикаторов)
 ├── strategy/       (7 критериев → BUY/SELL/NO_SIGNAL)
 ├── scheduler/      (APScheduler cron + scanner цикл)
 ├── context/        (внешние источники: F&G, CoinGecko, Binance, новости)
 ├── bot/            (Telegram: команды, меню, нотификации)
 └── storage/        (SQLAlchemy async → SQLite)
```

### Ключевые принципы
- Все компоненты — синглтоны (один instance на весь процесс)
- Полностью асинхронный (asyncio, ccxt async, aiosqlite)
- `.env` → dataclass Config (читается при импорте `config/settings.py`)
- Цикл обработки: **Fetch → Calculate → Evaluate → Confirm → Enrich → Save → Notify**

---

## 2. Модули и их функционал

### 2.1 `main.py` — Точка входа
**Что делает:**
- Добавляет корень проекта в `sys.path`
- Импортирует `config.logger` (инициализирует loguru: консоль + файл с ротацией 10MB)
- Инициализирует БД (`db.init()` — создаёт таблицы)
- Подключается к бирже (`exchange_client.connect()`)
- Создаёт `Application` от python-telegram-bot, регистрирует обработчики
- Настраивает и запускает `TaskScheduler` (APScheduler)
- Запускает polling (с `drop_pending_updates=True`)
- Держит event loop через `asyncio.sleep(3600)`
- Обрабатывает shutdown: останавливает scheduler, exchange, бота, app

**При каких условиях:**
- Всегда при запуске `python main.py`
- Должен быть `TELEGRAM_BOT_TOKEN` в .env — иначе `sys.exit(1)`
- При `KeyboardInterrupt` / `SystemExit` — graceful shutdown
- При любой другой ошибке — `send_error_alert()` админам

---

### 2.2 `config/settings.py` — Конфигурация
**Что делает:**
- Загружает `.env` через `python-dotenv`
- Маппит переменные окружения в dataclasses: `TelegramConfig`, `ExchangeConfig`, `TradingConfig`, `AppConfig`
- `AppConfig` — обёртка со всеми конфигами + database_url, log_level, signal_cooldown_minutes
- Предоставляет синглтон `config = AppConfig()`
- Парсит `COINGECKO_SYMBOL_MAP` (строка вида `BTC/USDT:bitcoin,ETH/USDT:ethereum`) в словарь

**Настраиваемые параметры:**
- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`, `TELEGRAM_ADMIN_IDS`
- Exchange: `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `USE_TESTNET`, `EXCHANGE`
- Trading: `SYMBOLS`, `PRIMARY_TIMEFRAMES`, `CONFIRM_TIMEFRAME`
- Индикаторы: `ema_fast/slow/trend`, `rsi_period/overbought/oversold/bull_min/bear_max`, `macd_fast/slow/signal`, `adx_period/min`, `atr_period/multiplier_sl/multiplier_tp`, `supertrend_period/multiplier`, `volume_factor`, `candles_limit`
- Context: `CONTEXT_ENABLED`, `CONTEXT_MIN_VERDICT`, `CONTEXT_BLOCK_ON_BLOCKED`, `CRYPTOPANIC_API_KEY`, `COINGECKO_SYMBOL_MAP`
- Прочее: `DATABASE_URL`, `LOG_LEVEL`, `LOG_FILE`, `SIGNAL_COOLDOWN_MINUTES`

**При каких условиях:**
- На старте при импорте `config.settings`
- Если не заданы обязательные переменные — используются дефолты (токен будет пустым → main.py упадёт)

---

### 2.3 `config/logger.py` — Логирование
**Что делает:**
- Настраивает loguru: цветной вывод в консоль + файл с ротацией и сжатием
- Формат: `timestamp | level | module:line - message`

**При каких условиях:**
- Выполняется при импорте (нет явного вызова)

---

### 2.4 `data/exchange_client.py` — Клиент биржи
**Что делает:**
- `connect()` — создаёт ccxt асинхронный exchange (Binance spot)
- `close()` — закрывает соединение
- `fetch_ohlcv(symbol, timeframe, limit)` — получает OHLCV, конвертирует в pd.DataFrame с колонками `timestamp, open, high, low, close, volume`
  - timestamp → datetime UTC (index)
  - dropna, astype(float)
  - **Удаляет последнюю (незакрытую) свечу** (`df.iloc[:-1]`)
  - Обрабатывает `ccxt.NetworkError`, `ccxt.ExchangeError`, общие исключения
- `fetch_all_symbols(timeframe, limit)` — запускает `fetch_ohlcv` для всех символов параллельно через `asyncio.gather`
  - Возвращает `dict[symbol → DataFrame]`

**При каких условиях:**
- `connect()` — на старте main.py
- `close()` — при shutdown
- `fetch_ohlcv()` — вызывается scheduler/scanner и menu при анализе
- Возвращает `None` при ошибке или пустых данных

---

### 2.5 `indicators/engine.py` — Расчёт индикаторов
**Что делает:**
- `calculate(df, symbol, timeframe)` → `IndicatorValues` для последней закрытой свечи
- Рассчитывает через pandas-ta:
  1. **EMA** — 9/21/50 (`ema_fast`, `ema_slow`, `ema_trend`) + prev значения для пересечения
  2. **RSI** — период 14
  3. **MACD** — 12/26/9 (macd, signal, histogram) + prev histogram для пересечения
  4. **ADX + DMI** — период 14 (adx, dmi_plus, dmi_minus)
  5. **ATR** — период 14
  6. **Volume SMA** — 20 период
  7. **Supertrend** — 10/3.0 (значение + направление: 1 = up, -1 = down)

- Вычисляемые свойства `IndicatorValues`:
  - `ema_bullish_cross` — fast пересекла slow снизу вверх
  - `ema_bearish_cross` — fast пересекла slow сверху вниз
  - `ema_bullish_alignment` — fast > slow > trend
  - `ema_bearish_alignment` — fast < slow < trend
  - `macd_bullish_cross` — гистограмма перешла с отрицательной на положительную
  - `macd_bearish_cross` — гистограмма перешла с положительной на отрицательную
  - `volume_above_avg` — объём > SMA × volume_factor (1.2)
  - `trend_is_strong` — ADX >= adx_min (20)
  - `supertrend_bullish` / `supertrend_bearish`

**При каких условиях:**
- Данных должно быть >= `candles_limit // 2` (100 свечей)
- После расчёта удаляются строки с NaN по `ema_fast, ema_slow, rsi, adx, atr`
- Если чистых данных < 2 → возвращает None

---

### 2.6 `strategy/signal_engine.py` — Логика сигналов
**Что делает:**
- `evaluate(indicator_values)` → `SignalResult(BUY/SELL/NO_SIGNAL)`

**7 критериев для BUY:**
1. Supertrend восходящий
2. EMA alignment бычье (fast > slow > trend)
3. EMA fast > slow (или пересечение снизу вверх)
4. RSI в зоне силы (50–70)
5. MACD гистограмма положительная (или пересечение вверх)
6. ADX >= 20 (сильный тренд) — **глобальный фильтр, без него NO_SIGNAL**
7. Объём выше среднего

**7 критериев для SELL:**
1. Supertrend нисходящий
2. EMA alignment медвежье (fast < slow < trend)
3. EMA fast < slow (или пересечение сверху вниз)
4. RSI в зоне слабости (30–50)
5. MACD гистограмма отрицательная (или пересечение вниз)
6. ADX >= 20
7. Объём выше среднего

**Логика принятия решения:**
- ADX < 20 → NO_SIGNAL (флэт, игнорируем)
- BUY_score >= 4 И BUY_score > SELL_score → BUY
- SELL_score >= 4 И SELL_score > BUY_score → SELL
- Иначе → NO_SIGNAL

**SL/TP расчёт (через ATR):**
- BUY: SL = close - ATR × 1.5, TP = close + ATR × 3.0
- SELL: SL = close + ATR × 1.5, TP = close - ATR × 3.0
- Округляется до 8 знаков

**Форматирование сообщения:**
- `format_message()` → HTML для Telegram:
  - Эмодзи + тип сигнала (🟢 BUY / 🔴 SELL)
  - Инструмент, таймфрейм, цена
  - Entry price, SL, TP, R/R (risk/reward)
  - Список причин (каждое совпавшее условие)
  - Сила сигнала: ⭐ (score/7)

**При каких условиях:**
- Должен быть получен валидный `IndicatorValues` от `indicator_engine.calculate()`

---

### 2.7 `scheduler/tasks.py` — Планировщик
**Что делает:**
- Использует `AsyncIOScheduler` (timezone=UTC)
- Две cron-задачи:
  1. **1H таймфрейм**: каждый час в `:02` минуты (после закрытия часовой свечи)
  2. **4H таймфрейм**: `0,4,8,12,16,20 * * *` в `:05` минуты
- `max_instances=1, coalesce=True` — не запускает новый, если предыдущий не завершён
- `setup()` — конфигурирует задачи
- `start()` / `stop()` — управление жизненным циклом

**При каких условиях:**
- `start()` — в main.py после настройки
- `stop()` — при shutdown
- Каждая задача вызывает `run_scan_cycle(notify_callback)`

---

### 2.8 `scheduler/scanner.py` — Цикл сканирования
**Что делает (полный пайплайн):**

**Шаг 1 — Сбор данных:** `exchange_client.fetch_ohlcv(symbol, timeframe)` → `indicator_engine.calculate(df)`

**Шаг 2 — Оценка:** `signal_engine.evaluate(indicator_values)` → SignalResult

**Шаг 3 — Подтверждение на 15M:** Если сигнал есть и confirm_timeframe ≠ primary:
- Загружаем 15M данные для того же символа
- Оцениваем на 15M тот же engine
- Если направление сигнала на 15M **не совпадает** с основным → сигнал отклоняется
- Если совпадает → добавляется причина "✅ Подтверждение на {confirm_tf}", entry_price = close на 15M

**Шаг 4 — Контекстное обогащение (если CONTEXT_ENABLED):**
- Запускается `context_engine.get_snapshot(symbol)` (timeout 10s)
- `context_scorer.score()` → вердикт (CONFIRMED/WEAK/CONFLICTED/BLOCKED)
- Если `CONTEXT_BLOCK_ON_BLOCKED=True` и вердикт BLOCKED → сигнал отклоняется
- Сохраняется снимок в БД (один раз до сохранения сигнала, второй — с signal_id)

**Шаг 5 — Сохранение в БД:** `db.save_signal(...)` → сигнал с логами, SL, TP, score

**Шаг 6 — Cooldown:** Запоминается время последнего сигнала для `{symbol}_{timeframe}`
- Длительность: `SIGNAL_COOLDOWN_MINUTES` (по умолчанию 60)
- Если cooldown активен — `scan_symbol()` возвращает None без проверки

**Шаг 7 — Уведомление:** `notify_callback(result, context_verdict)` → отправка в Telegram

**Масштабирование:**
- `run_scan_cycle()` обходит все символы × все таймфреймы параллельно (`asyncio.gather`)
- Сигналы считаются: `signals_found / total_tasks`

**При каких условиях:**
- Вызывается из `_scan_job()` по расписанию
- Вызывается из `cmd_scan()` (ручной запуск админом)
- Каждый символ × таймфрейм — отдельная корутина

---

### 2.9 `context/` — Контекстное обогащение

#### `context/fetcher.py` — HTTP-клиенты
**Что делает:**
- Использует `aiohttp.ClientSession` (timeout 8s)
- Кеширование запросов с TTL
- **8 источников данных:**

1. **Alternative.me Fear & Greed Index** — `GET /fng/?limit=1`, кеш 3600s
2. **CoinGecko market data** — `GET /coins/{coin_id}`, цена 24h/7d, объём, cap rank
3. **CoinGecko trending** — `GET /search/trending`, кеш 1800s
4. **Binance Funding Rate** — через ccxt `exchange.fetch_funding_rate()`
5. **Binance Open Interest** — `GET fapi/v1/openInterest?symbol=BTCUSDT`
6. **Binance Long/Short Ratio** — `GET futures/data/globalLongShortAccountRatio`
7. **CryptoPanic News** (если есть API key) — анализ голосов (positive/negative)
8. **RSS News** — CoinDesk + Cointelegraph RSS, эвристический сентимент (словари позитивных/негативных слов)

#### `context/analyzer.py` — Сбор данных
**Что делает:**
- `get_snapshot(symbol)` → `ContextSnapshot`
- Запускает все fetcher'ы параллельно через `asyncio.gather`
- Собирает: F&G, CoinGecko, trending, funding rate, OI, L/S, новости
- Ошибки отдельных источников не фатальны — записываются в `snapshot.errors`

#### `context/scorer.py` — Оценка и вердикт
**Что делает:**
- `score(signal_direction, snapshot)` → `ContextVerdict`

**Взвешенная система:**
| Параметр | Вес | BUY условия | SELL условия |
|---|---|---|---|
| Fear & Greed | 0.15 | <25 → +0.8, ≥80 → -0.8 | >80 → +0.8, <25 → -0.8 |
| Funding Rate | 0.25 | < -0.5% → +0.9, >2% → -0.9 | >2% → +0.9, < -0.5% → -0.9 |
| Long/Short | 0.20 | <0.7 → +0.7, >1.2 → -0.6 | >1.2 → +0.7, <0.7 → -0.6 |
| Open Interest Δ | 0.15 | >2% → +0.5, <-2% → -0.2 | Любое направление — одинаково |
| News Sentiment | 0.15 | Прямая передача score | Прямая передача score |
| Price Trend 7d | 0.10 | >5% → +0.5, <-5% → -0.5 | <-5% → +0.5, >5% → -0.5 |

**Вердикты** (по итоговому score, диапазон [-1.0, 1.0]):
- `score >= 0.4` → CONFIRMED (рынок подтверждает)
- `score >= 0.1` → WEAK (слабая поддержка)
- `score >= -0.1` → CONFLICTED (разнонаправленные сигналы)
- `score < -0.1` → BLOCKED (рынок против)

**При каких условиях:**
- Вызывается из `scanner.py` если `CONTEXT_ENABLED=True`
- Если `CONTEXT_BLOCK_ON_BLOCKED=True`, BLOCKED отменяет сигнал
- Timeout 10 секунд на весь сбор

---

### 2.10 `bot/handlers.py` — Обработчики команд
**Что делает:**
- `/start` — отправляет главное меню (inline keyboard)
- `/help` — справка по командам и логике сигналов
- `/status` — статус бота: кол-во символов, таймфреймы, cooldown
- `/lastsignal` — последние 5 сигналов из БД (с эмодзи + время UTC)
- `/symbols` — список отслеживаемых символов
- `/scan` — **admin-only**: ручной запуск `run_scan_cycle()` (выполняется синхронно с ожиданием)
- `/settings` — **admin-only**: текущие настройки индикаторов
- **Role check**: декоратор `_admin_only` проверяет `user_id in TELEGRAM_ADMIN_IDS`

**При каких условиях:**
- Пользователь отправляет команду в личку боту
- Для admin-команд — проверка прав, иначе "⛔ Доступ запрещён."

---

### 2.11 `bot/menu.py` — Инлайн-меню
**Что делает:**
- **Главное меню** (4 кнопки):
  1. 🔍 Анализ токена — выбирает токен → полный разбор (все индикаторы, SL/TP, сигнал)
  2. 📊 Индикаторы — выбирает токен → компактный просмотр всех индикаторов
  3. 📡 Авто-скан всех — `_do_scan_all()`: BUY/SELL/NEUTRAL для всех символов (RSI, ADX)
  4. ⚙️ Настройки — текущие параметры

- **Анализ своего токена**: пользователь может ввести текстом тикер (BTC, BTCUSDT, ETH/USDT) → нормализуется в формат XXX/USDT → полный анализ
- **Callback'и**: `m:analyze`, `m:pick_token`, `m:scan_all`, `m:settings`, `analyze:SYMBOL`, `token:SYMBOL`, `m:custom_token`, `m:back`
- Полный анализ включает: EMA alignment, RSI, MACD, ADX, ATR, Supertrend, Volume, SL/TP, R/R, список причин, TradingView ссылка
- `_do_scan_all()`: для каждого символа — RSI + ADX + сигнал (BUY/SELL/NEUTRAL)

**При каких условиях:**
- Пользователь нажимает кнопки в меню
- При вводе произвольного текста (не команды) — проверяется состояние WAITING

---

### 2.12 `bot/notifier.py` — Уведомления
**Что делает:**
- `send_signal(result, context_verdict)` — отправляет сигнал в Telegram-канал:
  - Форматирует через `result.format_message()` (HTML)
  - Если есть `context_verdict` — добавляет блок контекста:
    - Fear & Greed с эмодзи
    - Funding Rate (long/short позиции)
    - Long/Short Ratio
    - Open Interest Δ
    - News Sentiment
    - Итоговый вердикт + уверенность + поддерживающие/противодействующие факторы
  - Отправляет через `bot.send_message(parse_mode=ParseMode.HTML)`
- `send_error_alert(message)` — отправляет ERROR всем админам

**При каких условиях:**
- `send_signal()` — из scanner.py после успешного прохождения всех этапов
- `send_error_alert()` — из main.py при фатальной ошибке, из scanner.py при ошибке джобы

---

### 2.13 `storage/database.py` — База данных
**Что делает:**
- SQLAlchemy 2.0 async engine (aiosqlite)
- **3 таблицы:**

1. **`signals`**:
   - id (PK), symbol, timeframe, signal_type (BUY/SELL), close_price
   - sl, tp, score, reasons (Text, \n-joined)
   - confirmed (bool), created_at, sent_at

2. **`bot_settings`**:
   - key (PK), value (Text), updated_at

3. **`context_snapshots`**:
   - id (PK), symbol (indexed), signal_id (FK → signals.id, nullable)
   - timestamp, verdict, confidence, score
   - fear_greed, funding_rate, long_short_ratio, open_interest_delta, news_sentiment
   - raw_json (Text)

**Методы:**
- `save_signal()` — сохраняет сигнал, возвращает модель с id
- `get_last_signal(symbol, timeframe)` — последний сигнал по паре
- `get_recent_signals(limit)` — N последних
- `get_setting(key, default)` / `set_setting(key, value)` — настройки
- `save_context_snapshot()` — сохраняет снимок контекста

**При каких условиях:**
- `init()` — при старте main.py (создание таблиц)
- Остальные — вызовы из scanner.py и handlers.py

---

## 3. Полный пайплайн сигнала (пошагово)

```
APScheduler cron tick (:02 или :05)
  │
  ├── run_scan_cycle(notify_callback)
  │     │
  │     ├── [Параллельно] scan_symbol(symbol, tf, callback) для каждого symbol × timeframe
  │     │     │
  │     │     ├── 1. Проверка cooldown (60 мин) → если активен, возврат None
  │     │     │
  │     │     ├── 2. fetch_ohlcv() → indicator_engine.calculate() → IndicatorValues
  │     │     │     Если None → возврат None
  │     │     │
  │     │     ├── 3. signal_engine.evaluate() → SignalResult
  │     │     │     Если NO_SIGNAL → возврат None
  │     │     │
  │     │     ├── 4. Подтверждение на 15M
  │     │     │     │  fetch_ohlcv(15m) → evaluate()
  │     │     │     ├── Сигнал не совпадает → отмена, возврат None
  │     │     │     └── Сигнал совпадает → entry_price, причина
  │     │     │
  │     │     ├── 5. Контекстное обогащение
  │     │     │     │  context_engine.get_snapshot(symbol) → ContextSnapshot
  │     │     │     │  context_scorer.score(signal_direction, snapshot) → ContextVerdict
  │     │     │     │  Сохранение snapshot в БД (без signal_id)
  │     │     │     ├── Вердикт BLOCKED + CONTEXT_BLOCK_ON_BLOCKED → отмена
  │     │     │     └── Иначе → вердикт в уведомлении
  │     │     │
  │     │     ├── 6. db.save_signal() → сохранение сигнала
  │     │     │
  │     │     ├── 7. Сохранение snapshot с signal_id (если контекст был)
  │     │     │
  │     │     ├── 8. Установка cooldown
  │     │     │
  │     │     └── 9. notify_callback(result, context_verdict) → send_signal()
  │     │
  │     └── Логирование: "Signals found: X/Y"
```

---

## 4. Блок-схема принятия решения (Signal Engine)

```
IndicatorValues
  │
  ├── ADX < 20?
  │     └── YES → NO_SIGNAL ("Флэт, игнорируется")
  │
  ├── Supertrend bullish?
  ├── EMA alignment bullish?
  ├── EMA fast > slow?
  ├── RSI 50-70?
  ├── MACD hist > 0?
  └── Volume above avg?
        │
        ├── BUY_score >= 4 И BUY > SELL → BUY + SL/TP (ATR)
        ├── SELL_score >= 4 И SELL > BUY → SELL + SL/TP (ATR)
        └── Иначе → NO_SIGNAL
```

---

## 5. Правила Telegram-форматирования

- **HTML-разметка**: `parse_mode=ParseMode.HTML` для всех сообщений
- **Экранирование**: все динамические строки — через `html.escape()` (особенно ADX < 20, R/R расчёты)
- **Ошибки HTML**: в `_do_full_analysis()` двойная обработка — при ошибке отправляется с экранированными `<` `>`
- **Лимиты**: сообщения не должны превышать ~4096 символов (Telegram)

---

## 6. Конфигурация .env (полный список)

```env
# Обязательные
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=
SYMBOLS=BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,XRP/USDT
PRIMARY_TIMEFRAMES=1h,4h
BINANCE_API_KEY=
BINANCE_API_SECRET=

# Опциональные
USE_TESTNET=false
TELEGRAM_ADMIN_IDS=123456789
CONFIRM_TIMEFRAME=15m
DATABASE_URL=sqlite+aiosqlite:///./data/signals.db
LOG_LEVEL=INFO
LOG_FILE=logs/bot.log
SIGNAL_COOLDOWN_MINUTES=60

# Контекстный модуль
CONTEXT_ENABLED=true
CONTEXT_MIN_VERDICT=WEAK
CONTEXT_BLOCK_ON_BLOCKED=true
CRYPTOPANIC_API_KEY=
COINGECKO_SYMBOL_MAP=BTC/USDT:bitcoin,ETH/USDT:ethereum,SOL/USDT:solana,BNB/USDT:binance-coin,XRP/USDT:ripple
```

---

## 7. Известные особенности (gotchas)

1. **Последняя свеча удаляется** перед расчётом индикаторов — предотвращает ложные сигналы
2. **ADX < 20 = флэт** — безусловный фильтр, сигнал не генерируется
3. **Score 4/7** — минимальный порог, но 4 условия могут совпасть и для BUY, и для SELL; решает перевес
4. **15M подтверждение** — не пропускает сигнал, если младший таймфрейм даёт противоположное направление
5. **Cooldown 60 мин** — на пару `symbol_timeframe`; на каждый таймфрейм свой счётчик
6. **Context блокировка** — если вердикт BLOCKED, сигнал НЕ отправляется (при CONTEXT_BLOCK_ON_BLOCKED=true)
7. **Funding Rate через ccxt** — синхронный вызов внутри асинхронного кода (неблокирующий, т.к. ccxt использует aiohttp)
8. **RSS без API-ключа** — работает всегда; CryptoPanic — только с ключом
9. **Переменные индикаторов** — задаются в коде `config/settings.py` (не через .env); для изменения нужно редактировать код
10. **Graceful shutdown** — порядок: scheduler.stop() → exchange.close() → app.updater.stop() → app.stop() → app.shutdown()
11. **Только spot рынок** — ccxt настроен на spot, не futures. Но OI и funding rate берутся с fapi.binance.com

---

## 8. Команды Telegram (полный список)

| Команда | Доступ | Описание |
|---|---|---|
| `/start` | Все | Главное меню с inline-кнопками |
| `/help` | Все | Справка |
| `/status` | Все | Статус бота |
| `/lastsignal` | Все | Последние 5 сигналов |
| `/symbols` | Все | Список символов |
| `/scan` | Admin | Ручной запуск сканирования |
| `/settings` | Admin | Настройки индикаторов |

---

## 9. Возможные улучшения (отмеченные в коде)

- Нет CI/CD
- Админ-команды ограничены (только /scan, /settings)
- Нет мониторинга / алертинга по ошибкам (кроме фатальных в main.py)
- Нет Rate limiting защиты команд
- Нет экспорта метрик (Prometheus)
- Нет стоп-лосс трекинга (бот не следит за открытыми позициями)
- Нет поддержки futures (только spot)
- Funding Rate — синхронный вызов ccxt внутри async
- Нет тестов на context-модуль (только tech-индикаторы)
- Нет динамического изменения символов через Telegram
- Нет PnL статистики по сигналам
