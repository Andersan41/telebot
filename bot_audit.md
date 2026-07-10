# bot_audit.md — Полный аудит архитектуры торгового бота

Дата: 2026-07-10
Версия стратегии: 2.4.0
Бот: Trading Signal Bot (ICT-based)

---

## 1. Общая архитектура

### 1.1 Схема потока данных

```
Биржа (ccxt) → fetch_ohlcv() → DataFrame OHLCV
    ↓
IndicatorEngine (pandas-ta) → IndicatorValues
    ↓
Liquidity модули (sweep, OB, FVG, candle_quality)
    ↓
MarketStructure (structure.py) → StructureState (BOS/CHoCH/MSS)
    ↓
PatternEngine → ICTSetup (reversal/continuation)
    ↓
FeatureBuilder → SetupFeatures (~35 features)
    ↓
ProbabilityEngine → TradeProbability (P(TP), RR)
    ↓
RiskEngine → RiskDecision (should_trade, risk_pct)
    ↓
SignalResult → format_message() → Telegram канал
```

**Параллельные shadow-процессы (логируются, НЕ влияют на сигнал):**
- MarketPhaseEngine → PhaseAssessment
- MarketThesisEngine → LiquidityGraph + DynamicTradeThesis
- HypothesisEngine + DecisionEngine → Hypothesis + Decision
- ScenarioEngine → ScenarioEvaluation

### 1.2 Модули и зависимости

| Модуль | Файл | Назначение | Зависимости |
|--------|------|------------|-------------|
| **Точка входа** | `main.py:58` | Инициализация БД, exchange, Telegram, scheduler | Все модули |
| **Конфиг** | `config/settings.py:591` | AppConfig — 15 dataclass-секций, ~170 параметров | .env |
| **Exchange Client** | `data/exchange_client.py:16` | OHLCV, ticker, market data через ccxt sync | ccxt≥4.2.15 |
| **Indicator Engine** | `indicators/engine.py:114` | EMA, RSI, MACD, ADX, ATR, Supertrend, Volume | pandas-ta≥0.4.0 |
| **Pattern Engine** | `strategy/pattern_engine.py:104` | ICT reversal/continuation detection | liquidity/* |
| **Feature Builder** | `strategy/feature_builder.py:250` | ~35 фич в плоский вектор | pattern_engine |
| **Probability Engine** | `strategy/probability_engine.py:61` | P(TP), RR, PF (rules/ML) | feature_builder |
| **Risk Engine** | `risk/engine.py:56` | Hard gates + position sizing | feature_builder + probability |
| **Signal Engine** | `strategy/signal_engine.py:152` | _calculate_sl_tp — ICT priority chain | indicators |
| **Scanner** | `scheduler/scanner.py:182` | scan_symbol_v2 — полный конвейер | Все модули |
| **Task Scheduler** | `scheduler/tasks.py:13` | APScheduler: каждые 15 мин сканирование | scanner |
| **Outcome Tracker** | `scheduler/outcome_tracker.py:332` | Фоновый трекинг TP/SL каждые 5 мин | exchange_client + db |
| **DB** | `storage/database.py:286` | SQLAlchemy + SQLite, 6 таблиц | SQLAlchemy≥2.0.23 |
| **Context** | `context/fetcher.py + analyzer.py + scorer.py` | F&G, funding, news sentiment | CoinGecko, CryptoPanic |
| **Notifier** | `bot/notifier.py:14` | Telegram отправка с HTML-экранированием | python-telegram-bot |
| **Web Dashboard** | `web/server.py` | aiohttp дашборд на порту 3001 | aiohttp |
| **Monitoring** | `monitoring/metrics.py` | Prometheus метрики | prometheus_client |

### 1.3 Внешние зависимости

| Зависимость | Версия | Назначение |
|-------------|--------|------------|
| ccxt | 4.2.15 | Биржевой API (Binance/BingX/Bybit) |
| pandas | ≥2.2.0 | DataFrames |
| pandas-ta | ≥0.4.0 | Технические индикаторы |
| python-telegram-bot | 20.7 | Telegram Bot API |
| sqlalchemy | 2.0.23 | ORM + SQLite |
| aiosqlite | 0.19.0 | Async SQLite |
| apscheduler | 3.10.4 | Cron-расписание |
| loguru | 0.7.2 | Логирование |
| aiohttp | 3.9.5 | HTTP + Web Server |
| feedparser | ≥6.0.0 | RSS новости |
| python-dotenv | 1.0.0 | .env загрузка |
| prometheus_client | ≥0.20 | Метрики Prometheus |
| aiolimiter | ≥1.1 | Rate limiting |

**Биржи:** BingX (по умолчанию), Binance, Bybit (через ccxt, `config/settings.py:39`)
**Тип рынка:** swap (perpetual futures) по умолчанию, также spot/future

### 1.4 Точки входа и планировщик

- **main.py:58** — `async def main()`: инициализация, старт Telegram polling
- **scheduler/tasks.py:18** — `TaskScheduler.setup()`:
  - `scan_all_tfs`: CronTrigger `minute=2,17,32,47` (каждые 15 мин) → `run_scan_cycle()`
  - `daily_report`: CronTrigger `hour=0, minute=5` → ежедневный отчёт
- **Админ-команды:** `/scan` — ручной запуск `run_scan_cycle()` (`bot/admin.py`)
- **outcome_tracker_loop():** фоновая задача, запускается в `main.py:130`, проверка каждые 300 секунд (`scheduler/outcome_tracker.py:21-23`)

---

## 2. Данные и рынок

### 2.1 Инструменты (Symbols)

| Параметр | Значение | Источник |
|----------|----------|----------|
| SYMBOLS | BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT, XRP/USDT | `.env.example:23` |
| Динамическое добавление | через `/addsymbol` в Telegram | `config/settings.py:842-858` |
| Отключение символов | через `/removesymbol`, хранится в `disabled_symbols` | `storage/database.py:658-666` |

Итоговый список = env SYMBOLS + dynamic (из БД) − disabled (из БД).

### 2.2 Таймфреймы

| Параметр | Значение | Источник |
|----------|----------|----------|
| PRIMARY_TIMEFRAMES | 1h, 4h | `.env.example:24` |
| CONFIRM_TIMEFRAME | 15m (отключён как gate, `confirm_tf_enabled: true`) | `.env.example:25` |
| MTF_TIMEFRAMES | 1d, 4h, 1h (для аналитики, не gate) | `.env.example:89` |
| CANDLES_LIMIT | 200 свечей на запрос | `.env.example:67` |

### 2.3 Глубина истории и тип данных

- **OHLCV:** fetch_ohlcv с лимитом 200 (`data/exchange_client.py:276-308`)
- **Paginated fetch:** до 4000 свечей (`fetch_ohlcv_paginated`, `data/exchange_client.py:310-392`)
- **Дроп последней свечи:** `df.iloc[:-1]` — защита от сигнала на открытой свече (`data/exchange_client.py:305`)
- **Дополнительно:** ticker (bid/ask/last), tick_size (`fetch_ticker_full`, `get_tick_size`)
- **Taker buy volume:** только Binance futures (`_fetch_taker_buy_volumes`, `data/exchange_client.py:192-219`)

### 2.4 Частота опроса и обработка ошибок

- **Semaphore(1)** — сериализация всех запросов к ccxt (`data/exchange_client.py:92`)
- **3 retries** с exponential backoff для fetch_ohlcv (`data/exchange_client.py:126-190`)
- **Rate limits:** специальная обработка RateLimitExceeded/DDoSProtection с backoff 5×2^attempt
- **Markets reload:** при ошибке и перед каждым fetch_ohlcv (`_ensure_markets_loaded`, `data/exchange_client.py:100-120`)
- **Outcome tracker:** после 3 последовательных ошибок — cooldown 10 мин для символа (`scheduler/outcome_tracker.py:31-34`)

---

## 3. Система фильтров (конвейер scan_symbol_v2)

Конвейер в `scheduler/scanner.py:182-1113`. Порядок строгий — последовательные gates.

### 3.1 Таблица фильтров (hard gates)

| # | Фильтр | Логика | Параметры | Хардкод/Конфиг | path:line |
|---|--------|--------|-----------|-----------------|-----------|
| 1 | **Cooldown** | Проверка `_is_cooldown_active()`: delta < effective_cooldown = max(base, tf_minutes × multiplier) | `SIGNAL_COOLDOWN_MINUTES=45`, `SIGNAL_COOLDOWN_TF_MULTIPLIER=2.0` | Конфиг | `scanner.py:96-107` |
| 2 | **Portfolio Risk** | `active_count >= max_active_signals` или `portfolio_risk >= max_portfolio_risk_pct` | `MAX_ACTIVE_SIGNALS=3`, `MAX_PORTFOLIO_RISK_PCT=3.0` | Конфиг | `scanner.py:212-229` |
| 3 | **Data Integrity** | OHLCV + IndicatorValues не None | `CANDLES_LIMIT=200` | Конфиг | `scanner.py:232-240` |
| 4 | **Pattern Engine (hard)** | `ICTSetup.detected == True` | `PATTERN_REQUIRE_BOS_OR_SWEEP=true`, `PATTERN_REQUIRE_OB_OR_FVG=true` | Конфиг | `scanner.py:284-306` |
| 5 | **Reversal Gates** | sweep → displacement → MSS (all required) | — | Хардкод (логика) | `scanner.py:316-347` |
| 6 | **Continuation Gates** | BOS + trend alignment (both required) | — | Хардкод (логика) | `scanner.py:349-377` |
| 7 | **Regime Gate** | range regime → continuation BLOCKED; reversal allowed | `REGIME_TREND_ADX=25`, `REGIME_RANGE_ADX=20`, `REGIME_COMPRESSION_ATR_PCT=20` | Конфиг | `scanner.py:389-402` |
| 8 | **SL/TP Calculation** | SL и TP не None после trade_engine | Параметры ATR/SL/TP | Конфиг | `scanner.py:423-427` |
| 9 | **Entry Trigger** | Price near entry zone + spread check | `entry_proximity_pct=0.5`, `max_spread_pct=0.1` | Хардкод (default) | `scanner.py:904-933` |
| 10 | **Risk Engine** | R:R ≥ 1.5, SL min 0.25%, SL max 5.0%, portfolio gates | `RISK_ENGINE_MIN_RR=1.5`, `RISK_ENGINE_SL_MIN_PCT=0.25`, `RISK_ENGINE_SL_MAX_PCT=5.0` | Конфиг | `scanner.py:869-900` |
| 11 | **Dedup (cooldown)** | Same direction within cooldown → block. Cross-dir within cooldown/2 → block | `SIGNAL_COOLDOWN_MINUTES=45` | Конфиг | `scanner.py:970-998` |

### 3.2 Комбинирование фильтров

- **AND-последовательность:** все gates выполняются строго по порядку. FAIL на любом → "BLOCKED" → return None
- **Funnel логгирование:** `_FunnelCounter` (`scanner.py:56-80`) трекает проходимость каждого gate
- **DecisionTrace:** каждый gate сохраняется в БД (`storage/database.py:163-284`), что позволяет пост-анализ воронки

### 3.3 Устаревшие / shadow-фильтры (не блокируют)

| Фильтр | Статус | path:line |
|--------|--------|-----------|
| MTF Alignment | analytics (soft) | `scanner.py:803-819` |
| Context Enrichment | soft (score только для информации) | `scanner.py:822-837` |
| Market Phase | SHADOW MODE — только логи | `scanner.py:433-463` |
| Market Thesis | SHADOW MODE — только логи | `scanner.py:470-637` |
| Hypothesis Engine | SHADOW MODE — только логи | `scanner.py:646-735` |
| Scenario Engine | SHADOW MODE — только логи | `scanner.py:741-794` |

---

## 4. Условия сигнала

### 4.1 Точные условия входа

Сигнал генерируется **только** при прохождении PatternEngine + setup-type gates.

**For REVERSAL (приоритетный):**
1. **Sweep** ликвидности (swing high/low с reclaim) — `pattern_engine.py:224-244`
2. **Displacement** (тело свечи ≥ 1 ATR) — `pattern_engine.py:249-258`
3. **MSS** (Market Structure Shift = CHoCH после sweep, causality decay) — `pattern_engine.py:260-296`

**For CONTINUATION (fallback):**
1. Тренд не ranging — `pattern_engine.py:326-331`
2. **BOS** (Break of Structure) — `pattern_engine.py:334-348`
3. Trend alignment (BOS направление совпадает с трендом) — `pattern_engine.py:357-368`

**Entry zones (NOT gates — только для info):**
- OB (Order Block) proximity — `pattern_engine.py:389-397`
- FVG (Fair Value Gap) — `pattern_engine.py:399-406`

### 4.2 Индикаторы

Индикаторы **НЕ являются gates** в ICT Core pipeline. Они используются только как:
1. **ML features** в FeatureBuilder (raw values → ProbabilityEngine)
2. **SL/TP calculation** (ATR)
3. **Regime detection** (ADX, ATR, Volume)

Список индикаторов (`indicators/engine.py:114-237`):

| Индикатор | Период (по умолч.) | Назначение |
|-----------|-------------------|------------|
| EMA fast | 8 | Тренд/ML feature |
| EMA slow | 21 | Тренд/ML feature |
| EMA trend | 55 | Тренд/ML feature |
| RSI | 10 | ML feature |
| MACD | 8/21/5 | ML feature |
| ADX | 14 (min 26) | Regime detection + ML feature |
| ATR | 14 | SL/TP calc + volatility |
| Supertrend | 10/2.5 | ML feature |
| Volume SMA | 20 | ML feature |

### 4.3 Подтверждения

- **Мультитаймфрейм:** MTF alignment проверяется (soft, не блокирует) через `check_mtf_alignment()` (`market_structure/structure.py`)
- **Context:** Fear & Greed, funding rate, news sentiment (soft)
- **Candle close:** последняя свеча дропается (`df.iloc[:-1]`) — защита от open candle
- **Entry Trigger:** проверка proximity к entry zone + spread (new pipeline, `strategy/entry_trigger.py`)

### 4.4 Cooldown / Анти-дубль

- **Per `symbol:timeframe`:** in-memory + DB (`scanner.py:96-111`)
- **Базовый:** `SIGNAL_COOLDOWN_MINUTES=45` мин
- **С учётом TF:** `max(base, tf_minutes × multiplier)` = для 1h: max(45, 60×2)=120 мин, для 4h: max(45, 240×2)=480 мин
- **Cross-direction cooldown:** cooldown/2 (22.5 мин) при смене направления
- **Сброс при рестарте:** in-memory часть сбрасывается

---

## 5. Параметры сигнала

### 5.1 SL/TP Формирование

ICT Priority Chain (`strategy/signal_engine.py:152-359`):

**SL (приоритет):**
1. Order Block (+ buffer 0.5%)
2. Fractal/Swing Point (+ buffer 0.5%)
3. BOS level (±0.5% buffer)
4. ATR fallback (entry ± ATR × 1.5)

**TP (приоритет):**
1. Opposing Order Block (midpoint)
2. Active FVG (boundary)
3. Swing structure (nearest swing high/low)
4. ATR fallback (entry ± ATR × 3.0)

### 5.2 Position Sizing

Рассчитывается в `risk/engine.py:171-250`:

- **Kelly fraction:** `f = (p × b − q) / b`, capped at 25% (half-Kelly)
- **Kelly scaling:** `kelly × probability.confidence`
- **Risk base:** `min(kelly × 100, 1.0%)` → затем масштабируется:
  - Scenario score adjustment: [0.6, 1.2]
  - Stability adjustment: [0.7, 1.15]
  - Volatility adjustment: 0.5 (>4% ATR), 0.75 (>2.5% ATR), 1.0
  - MSS quality: [0.8, 1.1]
  - SL distance: 1.1 (<1%), 0.8 (>3%)
- **Итоговый clamp:** [0.1%, 2.0%]

### 5.3 Формат сообщения в Telegram

Шаблон формируется в `strategy/signal_engine.py:113-149`:

```
BUY — ПОКУПКА
Инструмент: BTC/USDT
Таймфрейм: 4H
Цена входа: <code>65432.10</code>
🔴 Stop Loss: <code>64800.00</code> (-1.12%)
🟢 Take Profit: <code>67800.00</code> (+2.89%)
R/R: 1:2.6

Компоненты: 5
Качество: высокая | Уверенность: 72.3%

📊 Контекст рынка:
├ Fear & Greed: 45 (Neutral) 😐
├ Funding: -0.003% ✅
├ Long/Short: 0.65 ✅
└ Новости: нейтральные 😐

🔍 Вердикт: CONFIRMED (уверенность 85%)
  ✅ HTF trend aligned
  ✅ Volume confirms
```

HTML escaping обязателен для динамических подстрок (`html.escape()`), иначе Telegram API падает с `BadRequest`.

---

## 6. Учёт результатов

### 6.1 Что логируется

| Таблица | Содержимое | path:line |
|---------|-----------|-----------|
| `signals` | Каждый отправленный сигнал (SL, TP, score, reasons, execution snapshot) | `storage/database.py:17-55` |
| `signal_outcomes` | Результат закрытия (HIT_TP/HIT_SL/EXPIRED, PnL%, MFE/MAE) | `storage/database.py:83-96` |
| `signal_candidates` | Каждый проход evaluate() — pass или fail, все индикаторы | `storage/database.py:98-161` |
| `decision_traces` | Полная воронка: результат каждого gate, features, config snapshot | `storage/database.py:163-284` |
| `context_snapshots` | F&G, funding, OI, sentiment на момент сигнала | `storage/database.py:65-81` |
| `bot_settings` | Cooldown, dynamic_symbols, filter_toggles | `storage/database.py:57-63` |

### 6.2 Outcome Tracker

- **Фоновый процесс:** `scheduler/outcome_tracker.py:332-338`
- **Интервал:** 300 секунд (5 мин) — `OUTCOME_CHECK_INTERVAL_SECONDS`
- **TTL:** 7 дней (`OUTCOME_TTL_DAYS`)
- **Метод:** ticker + candle high/low для определения TP/SL касания
- **PnL:** net после commission (0.05% × 2) + slippage (0.05% × 2) + funding (0.01%/8h)
- **MFE/MAE:** рассчитываются при закрытии

### 6.3 ScenarioMemory

- `strategy/scenario_memory.py` — запоминает ожидаемые параметры и фактические исходы гипотез
- Используется для обучения ProbabilityEngine (ML) в будущем

### 6.4 Отчёты

- **Ежедневный отчёт:** `analytics/daily_report.py` → сохраняется в `reports/daily/` → отправляется в Telegram
- **Gate analysis:** `db.get_trace_stats()` — воронка проходимости
- **Counterfactual:** `db.get_counterfactual()` — что было бы при отключении gate

### 6.5 Критический пробел

**НЕТ автоматического бэктестинга в production-цикле.** Walk-forward и симуляции есть в скриптах (`scripts/walk_forward.py`, `scripts/gate_simulator.py`), но они не интегрированы в основной цикл. ML-модель ProbabilityEngine существует как заглушка (`try: load model; except: rules fallback`) — модель не обучена и не используется.

---

## 7. Риски и слабые места (экспертная оценка)

### 7.1 Look-ahead bias / Repaint

- **`df.iloc[:-1]`** — дроп последней свечи. Это правильная защита от open candle bias.
- **Sweep detection** использует `lookback=50` и `swing_window=5` — при правильной реализации repaint не должно быть.
- **MSS causality:** экспоненциальный decay (half-life=3) — корректно.
- **Risk:** SUPRETREND, MACD и другие индикаторы с лагом не перерисовываются (pandas-ta стандартный).
- **Потенциальная проблема:** расчет `displacement_atr_ratio` на `current_candle` (`pattern_engine.py:254-258`) может использовать незакрытую свечу, если датасет не был корректно обрезан.

### 7.2 Захардкоженные магические числа

| Число | Где | Проблема |
|-------|-----|----------|
| `base=50.0` | `probability_engine.py:136` | Стартовый winrate 50% — hardcoded |
| `half_life=3.0` | `market_structure/structure.py:74` | Экспоненциальный decay MSS |
| `capped at 25%` | `risk/engine.py:178` | Kelly cap (half-Kelly) |
| `volume_factor=1.5` | `config/settings.py:170` | Порог объёма выше SMA |
| `MIN_RR_THRESHOLD=1.5` | `.env.example:62` | Минимальный R:R |

Большинство чисел вынесены в конфиг, но логика их комбинирования (веса, пороги в ProbabilityEngine rules) — **не настраиваема через .env**.

### 7.3 Отсутствие бэктеста и метрик

- **ML-модель не обучена:** `probability_engine.py:83-101` — загружает модель, если файл существует. Файла нет → rules fallback.
- **Rules fallback** — ~200 строк невалидированных эвристик с hand-tuned весами.
- **Walk-forward анализ** существует как отдельный скрипт (`scripts/walk_forward.py`), не интегрирован.
- **Survivorship bias:** нет, данные live с биржи.
- **Selection bias:** DecisionTrace логирует все кандидаты, включая заблокированные — корректно.

### 7.4 Проблемы надёжности

| Проблема | Риск | Комментарий |
|----------|------|-------------|
| **Lock-файл** | Защита от дублей | `.trading_bot.lock` с PID — корректно |
| **Telegram conflict retries** | 5 попыток с backoff | `main.py:138-149` |
| **Send retries** | 3 попытки, exponential backoff | `bot/notifier.py:95-113` |
| **Exchange rate limit** | Semaphore(1) + retries | `data/exchange_client.py:92` |
| **Circuit breaker** | Потери > N подряд → пропуск скана | `scheduler/circuit_breaker.py` |
| **Windows compat** | `WindowsSelectorEventLoopPolicy()` | `main.py:180` |
| **Outcome tracker skip** | Пропуск при ошибках fetch | `outcome_tracker.py:192-207` |
| **Context timeout** | 10s timeout на внешние API | `scanner.py:828-830` |
| **Logger error sink** | Telegram оповещение об ошибках | `main.py:111-112` |

### 7.5 Дубли сигналов

Система cooldown защищает от дублей, но:
1. **Только in-memory** для cooldown (сбрасывается при рестарте)
2. **Dedup gate** проверяет `db.get_last_signal()` — корректно
3. **Cross-direction cooldown** = cooldown/2 — может пропустить флип

---

## 8. Сводная таблица ВСЕХ настраиваемых параметров

### 8.1 Telegram

| Параметр | Значение по умолч. | Где задан | На что влияет | Оптимизация? |
|----------|-------------------|-----------|---------------|:---:|
| TELEGRAM_BOT_TOKEN | — | .env | Авторизация | Нет |
| TELEGRAM_CHANNEL_ID | — | .env | Канал сигналов | Нет |
| TELEGRAM_ADMIN_IDS | — | .env | Админ-доступ | Нет |
| RATE_LIMIT_MAX_RATE | 5 | .env | Telegram throttle | Нет |
| RATE_LIMIT_TIME_PERIOD | 10 | .env | Telegram throttle | Нет |
| SEND_RETRIES | 3 | .env | Надёжность отправки | Нет |
| SIGNAL_BLOCK_NOTIFY | true | .env | Уведомления о блокировках | Да |

### 8.2 Exchange

| Параметр | Значение по умолч. | Где задан | На что влияет | Оптимизация? |
|----------|-------------------|-----------|---------------|:---:|
| EXCHANGE | bingx | .env | Выбор биржи | Нет |
| MARKET_TYPE | swap | .env | Спот/фьючерсы | Нет |
| USE_TESTNET | false | .env | Тестовый режим | Нет |

### 8.3 Trading

| Параметр | Значение по умолч. | Где задан | На что влияет | Оптимизация? |
|----------|-------------------|-----------|---------------|:---:|
| SYMBOLS | BTC/USDT,ETH/USDT,SOL/USDT | .env | Что сканируем | **Да** |
| PRIMARY_TIMEFRAMES | 1h,4h | .env | Таймфреймы сканирования | **Да** |
| CONFIRM_TIMEFRAME | 15m | .env | Подтверждение (отключено) | Да |
| CANDLES_LIMIT | 200 | .env | Глубина OHLCV | Да |
| SIGNAL_COOLDOWN_MINUTES | 45 | .env | Анти-дубль | **Да** |
| SIGNAL_COOLDOWN_TF_MULTIPLIER | 2.0 | .env | Cooldown для TF | **Да** |
| MAX_ACTIVE_SIGNALS | 3 | .env | Portfolio risk gate | **Да** |
| MAX_PORTFOLIO_RISK_PCT | 3.0 | .env | Portfolio risk gate | **Да** |

### 8.4 EMA

| Параметр | Значение | Где задан | Оптимизация? |
|----------|---------|-----------|:---:|
| EMA_FAST | 8 | .env | **Да** |
| EMA_SLOW | 21 | .env | **Да** |
| EMA_TREND | 55 | .env | **Да** |
| MIN_EMA_SPREAD_PCT | 0.20 | .env | Да |
| EMA_SLOPE_CHECK | false | .env | Да |

### 8.5 RSI

| Параметр | Значение | Оптимизация? |
|----------|---------|:---:|
| RSI_PERIOD | 10 | **Да** |
| RSI_OVERBOUGHT | 72 | **Да** |
| RSI_OVERSOLD | 28 | **Да** |
| RSI_BULL_MIN | 55 | Да |
| RSI_BEAR_MAX | 45 | Да |

### 8.6 MACD

| Параметр | Значение | Оптимизация? |
|----------|---------|:---:|
| MACD_FAST | 8 | **Да** |
| MACD_SLOW | 21 | **Да** |
| MACD_SIGNAL | 5 | **Да** |
| MACD_SLOPE_CHECK | false | Да |

### 8.7 ADX/DMI

| Параметр | Значение | Оптимизация? |
|----------|---------|:---:|
| ADX_PERIOD | 14 | **Да** |
| ADX_MIN | 26 | **Да** (ключевой) |
| ADX_STRONG | 22 | Да |

### 8.8 ATR / SL / TP / Risk

| Параметр | Значение | Оптимизация? |
|----------|---------|:---:|
| ATR_PERIOD | 14 | Да |
| ATR_MULTIPLIER_SL | 1.5 | **Да** |
| ATR_MULTIPLIER_TP | 3.0 | **Да** |
| MIN_RR_THRESHOLD | 1.5 | **Да** |
| MIN_SL_DISTANCE_PCT | 1.0 | Да |
| MAX_SL_DISTANCE_PCT | 10.0 | Да |
| STOP_HUNT_BUFFER_PCT | 0.5 | Да |
| VOLATILITY_LOW_THRESHOLD | 0.8 | Да |
| VOLATILITY_HIGH_THRESHOLD | 6.0 | Да |
| RISK_STRONG_PCT | 1.0 | **Да** |
| RISK_MODERATE_PCT | 0.5 | Да |
| MIN_SCORE_FOR_SIGNAL | 2 | **Да** |
| NO_TRADE_MIN_ATR_PCT | 0.6 | Да |
| REGIME_TREND_ADX | 25 | **Да** |
| REGIME_RANGE_ADX | 20 | Да |

### 8.9 Liquidity / Sweep / OB / FVG

| Параметр | Значение | Оптимизация? |
|----------|---------|:---:|
| SWEEP_LOOKBACK | 50 | Да |
| SWEEP_SWING_WINDOW | 5 | Да |
| SWEEP_MAX_RECLAIM_CANDLES | 2 | **Да** |
| SWEEP_MIN_VOLUME_RATIO | 1.8 | Да |
| OB_MIN_DISPLACEMENT_PCT | 2.5 | Да |
| OB_MIN_DISPLACEMENT_ATR | 1.5 | Да |
| OB_MIN_VOLUME_RATIO | 1.8 | Да |
| OB_MAX_AGE_CANDLES | 35 | **Да** |
| OB_LOOKBACK | 100 | Да |
| FVG_MIN_SIZE_PCT | 0.4 | Да |
| FVG_LOOKBACK | 100 | Да |

### 8.10 Scoring Weights

| Параметр | Значение | Оптимизация? |
|----------|---------|:---:|
| W_EMA | 10 | **Да** |
| W_MACD | 10 | **Да** |
| W_RSI | 5 | **Да** |
| W_VOLUME | 15 | **Да** |
| W_ADX | 5 | Да |
| W_DMI | 5 | Да |
| W_BOS | 15 | **Да** |
| W_SWEEP | 10 | **Да** |
| W_OB | 10 | **Да** |
| W_BTC | 10 | **Да** |
| W_FUNDING | 5 | Да |
| W_OI | 10 | Да |
| TECH_CONFIDENCE_BLEND | 0.6 | **Да** |
| MARKET_CONFIDENCE_BLEND | 0.4 | Да |
| HISTORICAL_WR_BLEND | 0.4 | **Да** |

### 8.11 Filter Toggles

| Параметр | По умолч. | Оптимизация? |
|----------|----------|:---:|
| ADX_FILTER_ENABLED | true | Да |
| EMA_ALIGNMENT_ENABLED | true | Да |
| TRIGGER_REQUIRED | true | Да |
| CANDLE_CLOSE_ENABLED | true | Да |
| MIN_SCORE_ENABLED | true | Да |
| COMPRESSION_ENABLED | true | Да |
| BLOCK_COMPRESSION_REGIME | true | **Да** |
| MTF_ENABLED | true | Да |
| BTC_GLOBAL_TREND_FILTER | true | **Да** |
| BTC_CORRELATION_ENABLED | true | Да |
| ETH_CORRELATION_ENABLED | true | Да |
| VOLATILITY_FILTER_ENABLED | true | Да |
| NO_TRADE_ZONES_ENABLED | true | Да |
| DYNAMIC_RISK_ENABLED | true | Да |
| NEWS_FILTER_ENABLED | false | Да |
| CONFIDENCE_V2_ENABLED | true | Да |

---

## 9. Вопросы к владельцу

1. **[НЕЯСНО] Сколько времени бот работает в live-режиме?** Насколько репрезентативны данные в БД (signals.db)? Сколько сигналов было сгенерировано, какой winrate?

2. **[НЕЯСНО] Есть ли у вас файл `models/probability_model.pkl`?** ProbabilityEngine загружает ML-модель, если файл существует. Если да — какая точность на валидации?

3. **[НЕЯСНО] Какие биржи реально используются?** Конфиг показывает BingX по умолчанию, но Binance API ключи также заданы.

4. **[НЕЯСНО] Есть ли верифицированная статистика winrate по `signal_outcomes`?** Сколько HIT_TP vs HIT_SL vs EXPIRED?

5. **[НЕЯСНО] Используются ли скрипты в `scripts/` для оптимизации?** Там есть walk_forward, gate_simulator, sweep_weights — какой-то из них дал результаты, внедрённые в продакшн?

6. **[НЕЯСНО] Какой тип аккаунта Binance/BingX?** Spot, USDT-M futures, Coin-M? MARKET_TYPE=swap предполагает perpetual futures.

7. **[НЕЯСНО] На каких символах реально были сигналы?** .env.example показывает 5 пар, но `get_active_symbols()` динамически расширяется.

8. **[НЕЯСНО] Как работает `risk/dynamic_risk.py`?** Параметр `DYNAMIC_RISK_ENABLED=true`, но я не нашёл его интеграции в `scanner.py`.

9. **[НЕЯСНО] Есть ли ручной контроль размера позиции?** Risk Engine рассчитывает риск, но не отправляет ордера на биржу (только сигналы в Telegram). Как вы реально исполняете сделки?

10. **[НЕЯСНО]** Параметр `CONFIRM_TIMEFRAME=15m` указан, но `confirm_tf_enabled` вероятно отключён в пользу ICT-пайплайна. Подтверждение на 15m реально используется?

---

## 10. Рекомендованные следующие шаги

Ранжировано по ожидаемому эффекту / сложности:

### 🔥 Шаг 1. Обучить ML-модель ProbabilityEngine (эффект: высокий, сложность: средняя)
- Собрать `signal_outcomes` (win/loss) из БД
- Подготовить датасет: features из `decision_traces` + target (HIT_TP=1, HIT_SL=0)
- Обучить XGBoost/RandomForest → `models/probability_model.pkl`
- Сравнить rules fallback vs ML на out-of-sample
- **Ожидание:** +10-20% accuracy оценки P(TP) → better position sizing

### 🔥 Шаг 2. Оптимизация cooldown per symbol/timeframe (эффект: высокий, сложность: низкая)
- Текущий `SIGNAL_COOLDOWN_MINUTES=45` не дифференцирован
- Для 4h сигналов 45 мин слишком мало (коулдаун должен быть ~480 мин)
- Для 1h — 120 мин разумно
- **Рекомендация:** `signal_cooldown_tf_multiplier=2.0` + пересмотр base_minutes

### 🔥 Шаг 3. Gate removal impact analysis (эффект: средний, сложность: низкая)
- Использовать `db.get_counterfactual()` для всех gates
- Определить, какие gates убивают профит (убирают прибыльные сигналы)
- Особенно: `block_compression_regime`, `adx_filter_enabled`, `mtf_enabled`
- **Ожидание:** 1-3 gates можно отключить, увеличив количество сигналов без потери WR

### 🔥 Шаг 4. Backtest integration в CI/CD (эффект: средний, сложность: высокая)
- Интегрировать walk-forward (`scripts/walk_forward.py`) в регулярный pipeline
- Добавить автоматический прогон при изменении `config/settings.py`
- Сравнение Sharpe, Profit Factor, Max DD между версиями
- **Ожидание:** предотвращение регресса при изменениях

### 🔥 Шаг 5. Scenario Engine — включить shadow → live (эффект: средний, сложность: высокая)
- MarketPhaseEngine + DecisionEngine работают в shadow mode
- Сравнить качество гипотез с текущим PatternEngine
- Если DecisionEngine стабильно лучше — переключить как основной
- **Ожидание:** улучшение отбора setups через narrative-weighted utility

---

*Аудит выполнен 2026-07-10. Все ссылки на строки кода валидны для ревизии main.py:188 строк, scanner.py:1150 строк, settings.py ~920 строк.*
