# 🔍 Полный аудит: Trading Signal Bot

**Версия стратегии:** 2.5.0 (`config/settings.py:15`)  
**Дата аудита:** 2026-08-27  
**Цель:** Полная инвентаризация архитектуры, параметров, зависимостей и рисков

---

## 1. Общая архитектура

### 1.1 Поток данных (v2 — ICT Core Pipeline)

```
Exchange (ccxt)
  │
  ▼ fetch_ohlcv()
ExchangeClient ──► IndicatorEngine ──► IndicatorValues (EMA/RSI/MACD/ADX/ATR/Supertrend)
  │                     │
  │                     ▼
  │               PatternEngine (ICT Setup)
  │               ┌─ Reversal: Sweep → Displacement → MSS → OB/FVG
  │               └─ Continuation: Trend → BOS → OB/FVG
  │                     │
  │                     ▼
  │               FeatureBuilder ──► SetupFeatures (~35 raw features)
  │                     │
  │                     ▼
  │               ProbabilityEngine (Rules или ML)
  │                     │
  │                     ▼
  │               RiskEngine (Capital protection + Kelly sizing)
  │                     │
  │                     ▼
  │               SignalResult ──► DB (signals) ──► Telegram (notifier)
  │                     │
  │               OutcomeTracker (фон: SL/TP трекинг)
  │                     │
  │               Shadow Mode: MarketPhaseEngine → ScenarioEngine → TradeThesisManager
  │                           HypothesisEngine → DecisionEngine
```

### 1.2 Модули и зависимости

| Модуль | Назначение | Ключевые файлы | Строк |
|--------|-----------|----------------|-------|
| `main.py` | Точка входа, lock, init | `main.py:1-188` | 188 |
| `config/` | Централизованная конфигурация | `settings.py:1-1050`, `logger.py` | 1050+ |
| `data/` | Получение OHLCV через ccxt | `exchange_client.py` | 415+ |
| `indicators/` | Расчёт индикаторов | `engine.py` | 240+ |
| `strategy/` | Ядро стратегии (22+ файла) | `pattern_engine.py`, `feature_builder.py`, `probability_engine.py`, `signal_engine.py`, `decision_engine.py`, `hypothesis.py`, `trade_engine.py`, `trade_plan.py`, `market_phase_engine.py`, `market_thesis_engine.py`, `scenario_engine.py`, `scenario_memory.py`, `scenario_invalidator.py`, `entry_trigger.py`, `invalidation.py`, `levels.py`, `transition_model.py`, `weight_manager.py`, `weights.py`, `trade_thesis.py` | 10000+ |
| `scheduler/` | Планировщик и сканер | `tasks.py`, `scanner.py:1-1866`, `core_v2.py`, `outcome_tracker.py`, `circuit_breaker.py`, `shadow.py` | 3000+ |
| `risk/` | Управление рисками | `engine.py:1-287`, `dynamic_risk.py`, `market_regime.py`, `volatility_regime.py`, `no_trade_zones.py`, `news_filter.py`, `daily_limits.py` | 1500+ |
| `context/` | Контекст рынка | `fetcher.py`, `analyzer.py`, `scorer.py` | 800+ |
| `liquidity/` | Анализ ликвидности | `sweep.py`, `order_blocks.py`, `fvg.py`, `candle_quality.py`, `equal_levels.py`, `external.py`, `external_liquidity.py`, `ob_state.py`, `pool.py`, `breakout_quality.py` | 3000+ |
| `market_structure/` | Рыночная структура | `structure.py`, `htf_bias.py`, `htf_bias_v2.py`, `premium_discount.py` | 1500+ |
| `storage/` | SQLite БД | `database.py:1-1291`, `trace.py:1-273` | 1564+ |
| `bot/` | Telegram | `handlers.py:1-171`, `notifier.py:1-246`, `admin.py:1-442`, `rate_limit.py:1-21`, `menu.py:1-1022` | 1902 |
| `monitoring/` | Prometheus метрики | `metrics.py:1-37` | 37 |
| `analytics/` | Аналитика (16 файлов) | `daily_report.py`, `gate_funnel.py`, `performance.py`, `entry_delay.py`, `counterfactual.py`, `calibration.py`, `factor_stats.py`, `distributions.py`, `drift_report.py`, `feature_drift.py`, `full_report.py`, `sl_tp_analysis.py`, `trace_export.py`, `trades_export.py`, `version_compare.py`, `evolution.py` | 5000+ |
| `ml/` | ML модели (10 файлов) | `train_model.py`, `auto_retrain.py`, `build_dataset.py`, `triple_barrier.py`, `validate_oos.py`, `cache_ohlcv.py`, `ab_compare.py`, `analyze_winrate.py`, `_check_ds.py`, `config.py` | 3000+ |
| `derivatives/` | Funding/OI/SMT | `smt_divergence.py` | 200+ |
| `web/` | Веб-дашборд | `server.py:1-431` | 431 |
| `backtest/` | Бэктест (14 файлов) | `engine.py`, `cache_ohlcv.py`, `funnel.py`, `run_abn.py`, `run_r6.py`, `run_r6_batch.py`, `run_new_pipeline.py`, `run_funnel.py`, `run_breakout_quality.py`, `run_breakout_gate_ab.py`, `run_breakout_event.py`, `edge_discovery.py`, `compare_ema_trend.py`, `smc_visualizer.pine` | 4000+ |
| `analysis/` | Исследовательские скрипты | `factor_analysis_v2.py`, `probability_model.py` | 1000+ |

### 1.3 Зависимости (requirements.txt:1-21)

| Библиотека | Версия | Назначение |
|-----------|--------|-----------|
| `ccxt` | 4.2.15 | Биржевой API |
| `python-telegram-bot` | 20.7 | Telegram |
| `pandas` / `pandas-ta` | 2.2+ / 0.4+ | OHLCV + индикаторы |
| `apscheduler` | 3.10.4 | Планировщик |
| `sqlalchemy` + `aiosqlite` | 2.0.23 / 0.19 | SQLite |
| `loguru` | 0.7.2 | Логирование |
| `prometheus_client` | 0.20+ | Метрики |
| `aiolimiter` | 1.1+ | Rate limiting |
| `aiohttp` | 3.9.5 | HTTP + WebSocket |
| `httpx` | <0.28 | Telegram transport |
| `numpy` | 2.2.6+ | Научные вычисления |
| `python-dotenv` | 1.0.0 | .env загрузка |
| `pytz` | 2023.3 | Часовые пояса |
| `feedparser` | 6.0+ | RSS парсинг |

### 1.4 Точки входа

| Путь | Тип | Описание |
|------|-----|---------|
| `main.py:178` | Entry | Запуск бота (asyncio) |
| `scheduler/scanner.py:223` | Scan cycle | `scan_symbol_v2()` — основной пайплайн |
| `scheduler/tasks.py:26-33` | Cron | Сканирование каждые 15 мин (:02, :17, :32, :47) |
| `scheduler/outcome_tracker.py:350` | Background | Фоновый трекинг исходов каждые 300с |
| `scheduler/tasks.py:36-43` | Cron | Ежедневный отчёт в 00:05 UTC |
| `scheduler/tasks.py:46-53` | Cron | ML retrain в 03:00 UTC |
| `backtest/engine.py` | CLI | Бэктест (console / telegram) |
| `web/server.py` | HTTP/WS | WebSocket-дашборд |

---

## 2. Данные и рынок

### 2.1 Инструменты

- **Источник:** `.env` `SYMBOLS` + динамические через `/addsymbol` (`config/settings.py:66-68`)
- **По умолчанию:** `BTC/USDT,ETH/USDT,SOL/USDT` (из `config/settings.py:67`)
- **Рынок:** Perpetual swap (BingX/Bybit), spot/future (`config/settings.py:47`)
- **Формат ccxt:** маппинг `BTC/USDT` → `BTC/USDT:USDT` (`exchange_client.py:25-41`)

### 2.2 Таймфреймы

| Параметр | Значение | Откуда |
|---------|----------|--------|
| `PRIMARY_TIMEFRAMES` | `1h,4h` | `config/settings.py:70-71` |
| `CONFIRM_TIMEFRAME` | `5m` | `config/settings.py:76` |
| `SCAN_MODE` | `single_tf` | `config/settings.py:74` |
| `CANDLES_LIMIT` | 200 | `config/settings.py:204` |

### 2.3 Тип данных

- **OHLCV** — основной источник
- **Taker buy volume** — только Binance futures
- **Funding rate** — отдельный запрос (context/fetcher)
- **Open Interest** — отдельный запрос (derivatives)
- **Fear & Greed** — Alternative.me API
- **News sentiment** — CryptoPanic API + RSS (CoinDesk, Cointelegraph)
- **Long/Short ratio** — Binance fapi

### 2.4 Частота и обработка ошибок

- **Опрос:** каждые 15 мин по крону (`scheduler/tasks.py:28`)
- **Cooldown дублей:** 45 мин in-memory + DB (`config/settings.py:721`)
- **TF-множитель cooldown:** `max(base, tf_minutes × 2.0)` (`scanner.py:63-66`)
- **OB-aware cooldown:** `cooldown_mode=ob_aware` (reduced cooldown для OB retests)
- **Retry OHLCV:** до 3 попыток с exponential backoff
- **Rate limit:** ccxt `enableRateLimit=True` + Semaphore(1)
- **Drop последней свечи:** `df.iloc[:-1]`
- **Fallback при недоступности символа:** `skip` с логом
- **Paginated OHLCV:** для больших датасетов

---

## 3. Система фильтров (порядок в pipeline)

### 3.1 Pipeline v2 (scan_symbol_v2) — `scheduler/scanner.py:223-1866`

Pipeline — **последовательный** (AND). Каждый гейт — **hard block**. Порядок:

| № | Фильтр/Гейт | Логика | Параметры | Строка |
|---|---|---|---|---|
| 0.1 | **Cooldown** | Если `signal_cooldown_minutes` не прошёл → BLOCK | `SIGNAL_COOLDOWN_MINUTES=45`, `SIGNAL_COOLDOWN_TF_MULTIPLIER=2.0` | `scanner.py:242-250` |
| 0.2 | **Portfolio Risk** | `active_count >= max_active_signals (3)` или `portfolio_risk >= max_portfolio_risk_pct (3%)` → BLOCK | `MAX_ACTIVE_SIGNALS=3`, `MAX_PORTFOLIO_RISK_PCT=3.0` | `scanner.py:253-270` |
| 0.2b | **Daily Limits** | Дневные лимиты риска → BLOCK | Из `risk/daily_limits.py` | `scanner.py:272-284` |
| 0.2c | **Position Limits** | Макс. число позиций → BLOCK | `config.risk.max_positions_total` | `scanner.py:286-307` |
| 0.3 | **Data Integrity** | OHLCV/indicators unavailable → BLOCK | — | `scanner.py:309-318` |
| 0.4 | **Volatility Filter** | ATR% вне диапазона → BLOCK | `VOLATILITY_MIN_ATR_PERCENT=0.3`, `VOLATILITY_MAX_ATR_PERCENT=5.0` | `scanner.py:320-332` |
| 1 | **Pattern Engine** | Не обнаружен ICT setup → BLOCK | `PATTERN_REQUIRE_BOS_OR_SWEEP=true`, `PATTERN_REQUIRE_OB_OR_FVG=true` | `scanner.py:334+` |
| 1.4a | **Sweep Required** (reversal) | Нет sweep → BLOCK | — | — |
| 1.4b | **Displacement Required** (reversal) | Нет displacement при `reversal_require_displacement=true` → BLOCK | `REVERSAL_REQUIRE_DISPLACEMENT=true` | — |
| 1.4c | **MSS Required** (reversal) | Нет MSS (CHoCH) → BLOCK | — | — |
| 1.4d | **BOS Required** (continuation) | Нет BOS → BLOCK | — | — |
| 1.4e | **Entry Zone** (soft) | Если `require_entry_zone=true` и `entry_armed=false` → BLOCK | `REQUIRE_ENTRY_ZONE=false` | — |
| 1.45 | **HTF Bias** (continuation) | Если continuation против HTF bias и `htf_hard_gate=true` → BLOCK | `HTF_BIAS_V2=true`, `HTF_HARD_GATE=true` | — |
| 1.5 | **Session Gate** | Вне trading sessions → BLOCK | `SESSION_HARD_GATE=true`, `TRADING_SESSIONS=london,ny` | — |
| 1.6 | **OB Retest** | OB не подтверждён ретестом → BLOCK | `REQUIRE_OB_RETEST=true` | — |
| 1.7 | **Hypothesis + Decision** | Shadow mode: MarketPhaseEngine → ScenarioEngine → DecisionEngine | `SHADOW_MODE=true` | `scanner.py:1198-1294` |
| 2 | **Breakout Quality** | Shadow log (не блокирует по умолчанию) | `BREAKOUT_QUALITY_HARD_GATE=false` | — |
| 3 | **min_p_tp** | `P(TP) < MIN_P_TP` → BLOCK | `MIN_P_TP=0.30`, `MIN_P_TP_SHORT=0.40`, `MIN_P_TP_REVERSAL=0.50` | — |
| 4 | **Risk Engine** | R:R < min (2.0), SL вне лимитов (0.25-5.0%) → BLOCK | `RISK_ENGINE_MIN_RR=2.0`, `RISK_ENGINE_SL_MIN_PCT=0.25`, `RISK_ENGINE_SL_MAX_PCT=5.0` | — |
| 4.5 | **Entry Trigger** | Цена вне entry-зоны hypothesis → BLOCK (только для DecisionEngine) | — | — |
| 5 | **Volatility Scale** | ATR-based position sizing adjustment | `volatility_low_threshold=0.8`, `volatility_high_threshold=6.0` | — |
| 6 | **Dedup** | Тот же direction в течение cooldown → BLOCK | `SIGNAL_COOLDOWN_MINUTES=45` | — |

### 3.2 Pipeline v2 (core_v2) — `scheduler/core_v2.py`

Альтернативный pipeline: 5 фаз → Market Structure → Liquidity Event → Execution Window → Risk Check → Send.  
**Не вызывается** из `run_scan_cycle()` — резервный/экспериментальный.

### 3.3 Комбинация фильтров

Все гейты — **AND** (последовательные hard gates). Никаких весов или скоринга между гейтами — либо PASS (идём дальше), либо BLOCK (возврат None).  
Scoring происходит ТОЛЬКО внутри FeatureBuilder/ProbabilityEngine (для ранжирования, не для блокировки).

---

## 4. Условия сигнала

### 4.1 Вход — ICT Setup Detection (`strategy/pattern_engine.py:118-532`)

**REVERSAL** (сначала проверяется):
1. **Sweep** — свип ликвидности (`pattern_engine.py:225-244`)
2. **Displacement** — свеча с большим телом (информационно, не гейт) (`pattern_engine.py:249-258`)
3. **MSS (CHoCH)** — Market Structure Shift после sweep (`pattern_engine.py:261-296`)
4. **Entry zone** — OB или FVG (мягкая проверка, не гейт) (`pattern_engine.py:379-406`)

**CONTINUATION** (fallback, если reversal не найден):
1. **Trend required** — не ranging (`pattern_engine.py:326-331`)
2. **BOS** — Break of Structure (`pattern_engine.py:339-354`)
3. **Trend alignment** — BOS совпадает с trend (`pattern_engine.py:357-368`)
4. **Entry zone** — OB или FVG (мягкая проверка)

### 4.2 SL/TP — ICT Priority Chain (`strategy/signal_engine.py:181-398`)

**SL Priority:**
1. Order Block (OB.low для BUY, OB.high для SELL + buffer 0.5%)
2. Fractal/Swing Point
3. BOS level
4. ATR fallback (entry ± ATR × 1.5)

**TP Priority:**
1. External Liquidity (EQH/EQL)
2. Opposing Order Block
3. Active FVG
4. Swing structure (противоположный swing)
5. ATR fallback (entry ± ATR × 3.0)

**Validation:** SL/TP всегда на правильной стороне от entry.

### 4.3 Анти-дубли / Cooldown

- **Per `symbol_timeframe`** (проверяется из DB `bot_settings`)
- **Базовая длительность:** `SIGNAL_COOLDOWN_MINUTES=45`
- **TF-множитель:** `SIGNAL_COOLDOWN_TF_MULTIPLIER=2.0` → effective = `max(base, tf_minutes × 2.0)`
- **OB-aware cooldown:** `cooldown_mode=ob_aware` — reduced cooldown для OB retests
- **Cross-direction cooldown:** половина от базового
- **Сохраняется в DB** — живёт между рестартами

---

## 5. Параметры сигнала

### 5.1 Формат Telegram-сообщения

Формируется в `SignalResult.format_message()` (`signal_engine.py:120-178`):

```
{🟢/🔴} {BUY/SELL} — {ПОКУПКА/ПРОДАЖА} — BTC/USDT
HTF Context: STRONG BULLISH (W1✓ D1✓ H4✓)
Zone: DISCOUNT (fib 0.62)
Таймфрейм: 1H
Entry: <code>12345.67</code>
SL: <code>12200.00</code> (-1.18%)
TP: <code>12800.00</code> (+3.68%)
RR: 1:3.1
Confidence: 68/100

📊 <b>Контекст рынка:</b>
├ Fear & Greed: 45 (Neutral)
├ Funding: -0.003%
├ Long/Short: 1.02
├ OI: +2.1%
└ Новости: нейтральные

🔍 Вердикт: CONFIRMED (уверенность 85%)
  ✅ Bullish order flow
```

### 5.2 Размер позиции

Рассчитывается в `risk/engine.py:99-287`:
- **Kelly fraction:** `max(0, min((p × b - q) / b, 0.20))` (half-Kelly с cap)
- **Масштабирование:** confidence модели → scenario score → stability → volatility → MSS quality → SL distance
- **Базовый риск:** 1.0% (`RISK_ENGINE_BASE_RISK_PCT=1.0`)
- **Клиппинг:** `[0.1%, 2.0%]`
- **Portfolio constraint:** max 3 открытых сигнала, max 3% суммарного риска
- **Risk modes:** `kelly` или `fixed` (`RISK_MODE=fixed`)

---

## 6. Учёт результатов

### 6.1 Развёрнутая система

| Компонент | Что хранит | Таблица |
|----------|-----------|--------|
| `Signal` | Все сигналы (BUY/SELL) | `signals` |
| `SignalOutcome` | Результат (HIT_TP/HIT_SL/EXPIRED/MANUAL_CLOSE) | `signal_outcomes` |
| `SignalCandidate` | Каждый прогон (pass/fail) | `signal_candidates` |
| `DecisionTrace` | Полный трейс каждого прогона (25+ gate-колонок) | `decision_traces` |
| `ContextSnapshotModel` | Контекстные снимки | `context_snapshots` |
| `BotSetting` | Ключ-значение (настройки, коулдауны) | `bot_settings` |
| `ScenarioMemory` | In-memory статистика сценариев | — |

### 6.2 Outcome Tracker

**Фоновый процесс** (`outcome_tracker.py:350-356`):
- Проверка каждые 300 секунд (`OUTCOME_CHECK_INTERVAL_SECONDS=300`)
- TTL 7 дней → EXPIRED
- **PnL рассчитывается с вычетом:** комиссия (0.05% × 2), проскальзывание (0.05% × 2), funding (0.01%/8h)
- **MFE/MAE** — рассчитывается и сохраняется
- **Telegram-уведомление** при закрытии (TP/SL)
- **ScenarioMemory** — запись исхода для ML

### 6.3 Статистический анализ

- `analytics/performance.py` — метрики WR, PF, Sharpe и т.д.
- `analytics/gate_funnel.py` — воронка гейтов (какой гейт сколько режет)
- `analytics/counterfactual.py` — «что если отключить гейт X?»
- `analytics/calibration.py` — калибровка моделей
- `analytics/daily_report.py` — ежедневный отчёт в Telegram
- `analytics/evolution.py` — автоматическая оптимизация весов через walk-forward
- `analytics/feature_drift.py` — детекция дрифта фичей (PSI, KS test)

---

## 7. ML Pipeline

### 7.1 компоненты (`ml/`)

| Файл | Назначение | Статус |
|------|-----------|--------|
| `config.py` | Конфигурация: пути, гиперпараметры, 47 имён фичей | Активен |
| `cache_ohlcv.py` | Кэширование 4h OHLCV из BingX (parquet) | Активен |
| `triple_barrier.py` | ATR/structural labeling: TP/SL/EXPIRED assignment | Активен |
| `build_dataset.py` | Реплей v2 пайплайна на исторических данных → feature dataset | Активен |
| `train_model.py` | XGBoost (300 trees, max_depth=3) + IsotonicRegression калибровка | Активен |
| `ab_compare.py` | Holdout A/B сравнение текущей vs новой модели | Активен |
| `auto_retrain.py` | Оркестратор: cache → label → build → train (cron 03:00 UTC) | Активен |
| `validate_oos.py` | Walk-forward и temporal split валидация | Активен |
| `analyze_winrate.py` | Per-feature-group winrate анализ | Активен |

### 7.2 Модель

- **Тип:** XGBClassifier (300 деревьев, max_depth=3)
- **Калибровка:** IsotonicRegression
- **Путь:** `models/probability_model.pkl` (526 KB, обучена 19 Jul 2026)
- **Фичи:** 47 штук (indicators, structure, liquidity, context)
- **Fallback:** Rules-based когда < 100 outcomes

---

## 8. Риски и слабые места

### 8.1 Look-ahead bias / Repaint

| Риск | Статус | Комментарий |
|------|--------|-------------|
| **Drop последней свечи** | ✅ Исправлено | `df.iloc[:-1]` |
| **Swing-детекция** | ⚠️ **Частично** | BOS/CHoCH определяются по закрытым свечам |
| **OB lookback** | ⚠️ **Возможно** | `ob_bos_lookback=20`, `ob_retest_history=30` — смотрят ВПЕРЁД |
| **SuperTrend repaint** | ⚠️ | pandas-ta SuperTrend не repaint на закрытых данных |
| **Sweep detection** | ⚠️ | `sweep_lookback=50` — корректно, если только по закрытым свечам |

### 8.2 Магические числа и hardcoded значения

| Где | Значение | Проблема |
|-----|---------|----------|
| `exchange_client.py:305` | `df.iloc[:-1]` | Захардкожено (разумно) |
| `scanner.py:38-41` | `_TF_MINUTES` словарь | Захардкожен |
| `risk/engine.py:190` | kelly cap 0.20 | Half-Kelly hardcoded |
| `circuit_breaker.py:20-22` | 3 losses, 30 min pause, 60 min window | Hardcoded, не в `.env` |
| `scanner.py:466-477` | htf_bias_penalty = 0.85 | Магическое число |
| `probability_engine.py:220-251` | Веса компонент (3.0, 4.0, 1.5...) | Hardcoded rules weights |

### 8.3 Проблемы надёжности

| Проблема | Серьёзность | Описание |
|----------|-------------|----------|
| **Circuit breaker** hardcoded params | Низкая | Параметры не в `.env`, требуют правки кода |
| **Cooldown cross-direction** | Средняя | Cross-direction использует `/2` от cooldown — неконфигурируемо |
| **Windows asyncio** | Низкая | `WindowsSelectorEventLoopPolicy()` — workaround |
| **Telegram HTML** | Средняя | Баги с `<` в строках — `html.escape()` |
| **singleton state** в context | Средняя | Кэши не сбрасываются между тестами |
| **Outcome tracker race** | Низкая | `SignalOutcome` может дублироваться при быстрых закрытиях |
| **Session gate hardcoded** | Средняя | Trading sessions (london,ny) — не оптимизированы |
| **confirm_tf_enabled** | Средняя | Параметр остался в конфиге, но 15m TF удалён из pipeline |

### 8.4 Отсутствие

| Пробел | Критичность |
|--------|-------------|
| **Production-бэктеста нет** — backtest engine есть, но нет регулярного walk-forward | Средняя |
| **Нет стоп-лосса на уровне портфеля** (только суммарный риск) | Низкая |
| **Нет интеграции с реальным исполнением** — только сигналы | Критическая (для реальной торговли) |
| **Нет проверки корреляции между одновременно открытыми сигналами** | Средняя |
| **Нет circuit breaker в .env** — hardcoded | Низкая |

---

## 9. Сводная таблица ВСЕХ настраиваемых параметров

### 9.1 Торговые параметры

| Параметр | Текущее значение | Файл:строка | Оптимизировать? |
|----------|-----------------|-------------|:---:|
| `EMA_FAST` | 8 | `config/settings.py:82` | Да |
| `EMA_SLOW` | 21 | `config/settings.py:84` | Да |
| `EMA_TREND` | 55 | `config/settings.py:86` | Да |
| `MIN_EMA_SPREAD_PCT` | 0.20 | `config/settings.py:88` | Да |
| `EMA_SLOPE_CHECK` | true | `config/settings.py:90` | Нет (on/off) |
| `SWEEP_PENALTY_ENABLED` | true | `config/settings.py:92` | Нет (on/off) |
| `EMA_STRENGTH_CAP` | 1.0 | `config/settings.py:94` | Да |
| `RSI_PERIOD` | 10 | `config/settings.py:98` | Да |
| `RSI_OVERBOUGHT` | 72 | `config/settings.py:100` | Да |
| `RSI_OVERSOLD` | 28 | `config/settings.py:102` | Да |
| `RSI_BULL_MIN` | 55 | `config/settings.py:104` | Да |
| `RSI_BEAR_MAX` | 45 | `config/settings.py:106` | Да |
| `MACD_FAST` | 8 | `config/settings.py:110` | Да |
| `MACD_SLOW` | 21 | `config/settings.py:112` | Да |
| `MACD_SIGNAL` | 5 | `config/settings.py:114` | Да |
| `MIN_MACD_PCT` | 0.03 | `config/settings.py:116` | Да |
| `MACD_SCORE_MULTIPLIER` | 10 | `config/settings.py:118` | Да |
| `MACD_SLOPE_CHECK` | false | `config/settings.py:120` | Нет (on/off) |
| `ADX_PERIOD` | 14 | `config/settings.py:124` | Да |
| `ADX_MIN` | 26 | `config/settings.py:126` | Да |
| `ADX_STRONG` | 22 | `config/settings.py:128` | Да |
| `ADX_STRENGTH_RANGE` | 30 | `config/settings.py:130` | Да |
| `DMI_NORM_DIVISOR` | 50 | `config/settings.py:132` | Да |
| `DMI_STRENGTH_MULTIPLIER` | 2 | `config/settings.py:134` | Да |
| `ATR_PERIOD` | 14 | `config/settings.py:138` | Да |
| `ATR_MULTIPLIER_SL` | 1.5 | `config/settings.py:140` | Да |
| `ATR_MULTIPLIER_TP` | 3.0 | `config/settings.py:142` | Да |
| `ATR_FALLBACK_PCT` | 2.0 | `config/settings.py:146` | Да |
| `MIN_SL_DISTANCE_PCT` | 1.0 | `config/settings.py:150` | Да |
| `MAX_SL_DISTANCE_PCT` | 10.0 | `config/settings.py:152` | Да |
| `MIN_RR_THRESHOLD` | 1.5 | `config/settings.py:154` | Да |
| `STOP_HUNT_BUFFER_PCT` | 0.5 | `config/settings.py:156` | Да |
| `MAX_OB_DISTANCE_PCT` | 3.0 | `config/settings.py:158` | Да |
| `EXCHANGE_FEE_PCT` | 0.05 | `config/settings.py:160` | Нет (константа) |
| `SLIPPAGE_PCT` | 0.05 | `config/settings.py:162` | Нет (константа) |
| `SUPERTREND_PERIOD` | 10 | `config/settings.py:166` | Да |
| `SUPERTREND_MULTIPLIER` | 2.5 | `config/settings.py:168` | Да |
| `VOLUME_FACTOR` | 1.5 | `config/settings.py:172` | Да |
| `VOLUME_SMA_PERIOD` | 20 | `config/settings.py:174` | Да |
| `DELTA_BULLISH` | 15 | `config/settings.py:176` | Да |
| `DELTA_BEARISH` | -15 | `config/settings.py:178` | Да |
| `VOLUME_DELTA_NORM` | 50 | `config/settings.py:180` | Да |
| `COMPRESSION_VOLUME_FACTOR` | 2.0 | `config/settings.py:182` | Да |
| `CANDLES_LIMIT` | 200 | `config/settings.py:204` | Да |

### 9.2 Риск-параметры

| Параметр | Значение | Файл:строка | Опт.? |
|----------|---------|-------------|:----:|
| `RISK_ENGINE_MIN_RR` | 2.0 | `config/settings.py:635` | Да |
| `RISK_ENGINE_SL_MIN_PCT` | 0.25 | `config/settings.py:637` | Да |
| `RISK_ENGINE_SL_MAX_PCT` | 5.0 | `config/settings.py:639` | Да |
| `RISK_ENGINE_BASE_RISK_PCT` | 1.0 | `config/settings.py:641` | Да |
| `RISK_ENGINE_MIN_RISK_PCT` | 0.1 | `config/settings.py:643` | Да |
| `RISK_ENGINE_MAX_RISK_PCT` | 2.0 | `config/settings.py:645` | Да |
| `VOLATILITY_MIN_ATR_PERCENT` | 0.3 | `config/settings.py:216` | Да |
| `VOLATILITY_MAX_ATR_PERCENT` | 5.0 | `config/settings.py:218` | Да |
| `MAX_ACTIVE_SIGNALS` | 3 | `config/settings.py:748` | Да |
| `MAX_PORTFOLIO_RISK_PCT` | 3.0 | `config/settings.py:750` | Да |
| `VOLATILITY_LOW_THRESHOLD` | 0.8 | `config/settings.py:306` | Да |
| `VOLATILITY_HIGH_THRESHOLD` | 6.0 | `config/settings.py:308` | Да |
| `RISK_STRONG_PCT` | 1.0 | `config/settings.py:316` | Да |
| `RISK_MODERATE_PCT` | 0.5 | `config/settings.py:318` | Да |
| `NO_TRADE_MIN_ATR_PCT` | 0.6 | `config/settings.py:324` | Да |

### 9.3 Ликвидность и структура

| Параметр | Значение | Опт.? |
|----------|---------|:----:|
| `SWEEP_LOOKBACK` | 50 | Да |
| `SWEEP_MIN_VOLUME_RATIO` | 1.8 | Да |
| `SWEEP_MAX_RECLAIM_CANDLES` | 2 | Да |
| `SWEEP_FAST_RECLAIM_CANDLES` | 3 | Да |
| `SWEEP_MIN_WICK_BODY_RATIO` | 2.0 | Да |
| `SWEEP_SWING_WINDOW` | 5 | Да |
| `SWEEP_MAX_CHECK_RECLAIM` | 10 | Да |
| `SWEEP_MAX_CHECK_DISPLACEMENT` | 5 | Да |
| `SWEEP_DELTA_ALIGNED_THRESHOLD` | 0.5 | Да |
| `SWEEP_MAX_BODY_BEYOND_LEVEL` | 0.3 | Да |
| `SWEEP_MIN_WICK_BEYOND_LEVEL` | 0.1 | Да |
| `SWEEP_MIN_BODY_SIZE` | 0.05 | Да |
| `SWEEP_MAX_POOL_AGE_BARS` | 100 | Да |
| `OB_MIN_DISPLACEMENT_PCT` | 2.5 | Да |
| `OB_MIN_DISPLACEMENT_ATR` | 1.5 | Да |
| `OB_MIN_VOLUME_RATIO` | 1.8 | Да |
| `OB_MAX_AGE_CANDLES` | 35 | Да |
| `OB_RETEST_REQUIRED` | false | Да |
| `OB_LOOKBACK` | 100 | Да |
| `OB_SWING_WINDOW` | 5 | Да |
| `OB_BOS_LOOKBACK` | 20 | Да |
| `OB_RETEST_HISTORY` | 30 | Да |
| `OB_MITIGATION_BUFFER_PCT` | 0.3 | Да |
| `FVG_MIN_SIZE_PCT` | 0.4 | Да |
| `FVG_LOOKBACK` | 100 | Да |
| `CANDLE_DISPLACEMENT_ATR_MULT` | 1.5 | Да |
| `CANDLE_MIN_BODY_PCT` | 0.6 | Да |
| `CANDLE_MAX_WICK_RATIO` | 0.3 | Да |
| `DISTANCE_FILTER_MIN_PCT` | 1.2 | Да |
| `MTF_REQUIRED_ALIGNMENT` | 2 | Да |
| `STRUCTURE_LOOKBACK` | 50 | Да |

### 9.4 ML/Scoring

| Параметр | Значение | Опт.? |
|----------|---------|:----:|
| `CONFIDENCE_STRONG_THRESHOLD` | 65 | Да |
| `CONFIDENCE_MODERATE_THRESHOLD` | 40 | Да |
| `MIN_SCORE_FOR_SIGNAL` | 2 | Да |
| `PROBABILITY_MIN_SAMPLES_FOR_ML` | 100 | Да |
| `MIN_P_TP` | 0.30 | Да |
| `MIN_P_TP_SHORT` | 0.40 | Да |
| `MIN_P_TP_REVERSAL` | 0.50 | Да |
| `TECH_CONFIDENCE_BLEND` | 0.6 | Да |
| `MARKET_CONFIDENCE_BLEND` | 0.4 | Да |
| `HISTORICAL_WR_BLEND` | 0.4 | Да |
| `CONFIDENCE_V2_ENABLED` | true | Нет (on/off) |

### 9.5 Filter toggles

| Параметр | Значение | Опт.? |
|----------|---------|:----:|
| `ADX_FILTER_ENABLED` | true | Нет (on/off) |
| `EMA_ALIGNMENT_ENABLED` | true | Нет (on/off) |
| `EMA_SPREAD_ENABLED` | true | Нет (on/off) |
| `TRIGGER_REQUIRED` | true | Нет (on/off) |
| `CANDLE_CLOSE_ENABLED` | true | Нет (on/off) |
| `MIN_SCORE_ENABLED` | true | Нет (on/off) |
| `COMPRESSION_ENABLED` | true | Нет (on/off) |
| `BLOCK_COMPRESSION_REGIME` | true | Нет (on/off) |
| `HTF_BIAS_V2` | true | **Да** (feature flag) |
| `HTF_HARD_GATE` | true | **Да** |
| `PREMIUM_DISCOUNT` | false | **Да** (рекомендовано) |
| `REQUIRE_ENTRY_ZONE` | false | **Да** |
| `REVERSAL_REQUIRE_DISPLACEMENT` | true | **Да** |
| `REQUIRE_OB_RETEST` | true | **Да** |
| `SESSION_HARD_GATE` | true | **Да** |
| `BLOCK_NEUTRAL_HTF` | true | **Да** |
| `BLOCK_SHORT_IN_BULLISH_HTF` | true | **Да** |
| `BLOCK_LONG_IN_BEARISH_HTF` | true | **Да** |
| `BREAKOUT_QUALITY_ENABLED` | true | Нет (on/off) |
| `BREAKOUT_QUALITY_HARD_GATE` | false | **Да** |
| `EXTERNAL_LIQUIDITY_TP` | true | Нет (on/off) |
| `OB_MITIGATION` | true | Нет (on/off) |
| `CONFIDENCE_CAP` | true | Нет (on/off) |
| `SHADOW_MODE` | true | Нет (on/off) |
| `CLASSIC_INDICATORS_MODE` | soft | **Да** |
| `RISK_MODE` | fixed | **Да** |
| `USE_TESTNET` | false | Нет (on/off) |
| `CONTEXT_ENABLED` | true | Нет (on/off) |
| `CONTEXT_BLOCK_ON_BLOCKED` | true | Нет (on/off) |
| `SIGNAL_BLOCK_NOTIFY` | true | Нет (on/off) |

### 9.6 Расписание

| Параметр | Значение | Опт.? |
|----------|---------|:----:|
| `SCAN_MINUTES` | 2,17,32,47 | Да |
| `SIGNAL_COOLDOWN_MINUTES` | 45 | Да |
| `SIGNAL_COOLDOWN_TF_MULTIPLIER` | 2.0 | Да |
| `OUTCOME_CHECK_INTERVAL_SECONDS` | 300 | Да |
| `COOLDOWN_MODE` | ob_aware | **Да** |
| `OB_PROXIMITY_PCT` | 0.5 | Да |

### 9.7 Circuit Breaker (hardcoded, не в .env)

| Параметр | Значение | Где | Опт.? |
|----------|---------|-----|:----:|
| `CIRCUIT_BREAKER_LOSS_THRESHOLD` | 3 | `circuit_breaker.py:20` | **Да** (вынести в .env) |
| `CIRCUIT_BREAKER_PAUSE_MINUTES` | 30 | `circuit_breaker.py:21` | **Да** (вынести в .env) |
| `CIRCUIT_BREAKER_WINDOW_MINUTES` | 60 | `circuit_breaker.py:22` | **Да** (вынести в .env) |
| `FUNDING_RATE_8H` | 0.0001 | `outcome_tracker.py:27` | **Да** |
| `SYMBOL_FETCH_FAIL_THRESHOLD` | 3 | `outcome_tracker.py:31` | **Да** |
| `SYMBOL_FETCH_COOLDOWN_SECONDS` | 600 | `outcome_tracker.py:32` | **Да** |

### 9.8 Контекст

| Параметр | Значение | Опт.? |
|----------|---------|:----:|
| `CONTEXT_FETCH_TIMEOUT` | 10 | Да |
| `CONTEXT_CACHE_TTL_SECONDS` | 1800 | Да |
| `FNG_EXTREME_LOW` | 20 | Да |
| `FNG_EXTREME_HIGH` | 80 | Да |
| `LONG_SHORT_RATIO_THRESHOLD` | 0.7 | Да |
| `SENTIMENT_POSITIVE_THRESHOLD` | 0.2 | Да |
| `SENTIMENT_NEGATIVE_THRESHOLD` | -0.2 | Да |
| `SEND_RETRIES` | 3 | Да |

### 9.9 S/R и Web

| Параметр | Значение | Опт.? |
|----------|---------|:----:|
| `SR_WINDOW` | 10 | Да |
| `SR_MAX_LEVELS` | 5 | Да |
| `SR_CLUSTER_THRESHOLD` | 0.005 | Да |
| `SR_MIN_DISTANCE_PCT` | 1.0 | Да |
| `SR_OHLCV_LIMIT` | 100 | Да |
| `WEB_PORT` | 3002 | Нет |
| `WEB_HOST` | 0.0.0.0 | Нет |
| `WEB_ENABLED` | true | Нет (on/off) |
| `WEB_UPDATE_INTERVAL` | 5 | Да |

### 9.10 Execution Filters

| Параметр | Значение | Опт.? |
|----------|---------|:----:|
| `MAX_SPREAD_PERCENT` | 0.15 | Да |
| `MAX_SLIPPAGE_PERCENT` | 0.1 | Да |
| `MIN_DEPTH_0_5_PERCENT` | 10000 | Да |

---

## 10. Shadow Mode компоненты

### 10.1 MarketPhaseEngine (`strategy/market_phase_engine.py`)

Определяет фазу рынка: TRENDING_UP, TRENDING_DOWN, COMPRESSION, RANGING, VOLATILE. Используется DecisionEngine для выбора лучшей гипотезы.

### 10.2 ScenarioEngine (`strategy/scenario_engine.py`)

Генерирует и оценивает альтернативные сценарии для каждого setup. Работает в shadow mode — логирует, но не блокирует.

### 10.3 TradeThesisManager (`strategy/trade_thesis.py`)

Динамические торговые тезисы с liquidity graph. Отслеживает сценарную стабильность.

### 10.4 HypothesisEngine (`strategy/hypothesis.py`)

Генерирует набор конкурирующих гипотез (BUY/SELL, reversal/continuation). Каждая гипотеза имеет: direction, narrative_type, quality, confidence, decay_factor.

### 10.5 DecisionEngine (`strategy/decision_engine.py`)

Выбирает лучшую гипотезу через utility function: `U = quality × confidence × decay × phase_weight`. Фильтрует по min_utility threshold.

### 10.6 BreakoutQuality (`liquidity/breakout_quality.py`)

Классифицирует breakout: real vs. fake (AMD stop-hunt). Shadow log по умолчанию (`BREAKOUT_QUALITY_HARD_GATE=false`).

---

## 11. Вопросы к владельцу

### [НЕЯСНО]

1. **Какой период работы бота в продакшене?** Сколько сигналов уже сгенерировано? Есть ли статистика winrate/performance?

2. **Какой бэктест проводился?** `AGENTS.md` упоминает A/B тест HTF Bias V2 (90d/1h BTC+ETH), но нет общего бэктеста.

3. **Бот торгует реально или только сигналит?** Из кода — только сигналы в Telegram. Никаких ордеров на бирже.

4. **Какая биржа используется фактически?** `.env.example:11` — `EXCHANGE=bingx`, но ключи BINANCE. Реально BingX или Binance?

5. **Есть ли `PROBABILITY_MODEL_PATH` (models/probability_model.pkl)?** Если нет — используется rules fallback. Какое качество правил?

6. **Какие параметры Circuit Breaker оптимальны?** 3 losses → 30 min pause — не менялись? Может быть слишком агрессивно.

7. **Используется ли `BLOCK_COMPRESSION_REGIME=true`?** В WR 37.7% compression не имеет edge — все compression-сигналы блокируются.

8. **`PREMIUM_DISCOUNT=false`** — из A/B показал PF 1.28 → 0.91. Планируется ли пересмотр после 500+ сделок?

9. **Какой `MARKET_TYPE` используется?** swap (perpetual futures) или spot? Влияет на funding cost в трекинге.

10. **`confirm_tf_enabled`** — в `AGENTS.md` написано, что 15m confirmation TF удалён. Но параметр остался в конфиге. Он активен?

11. **`CLASSIC_INDICATORS_MODE=soft`** — что означает "soft" режим? Блокирует ли он что-то или только логирует?

12. **`SESSION_HARD_GATE=true`** — какие именно kill zones используются? london,ny — это UTC+0 или UTC+8?

---

## 12. Рекомендованные следующие шаги

### Топ-5 гипотез по улучшению

| # | Гипотеза | Ожидаемый эффект | Сложность | Обоснование |
|---|----------|-----------------|-----------|-------------|
| 1 | **ML-модель на historical outcomes** | Высокий (PF +20-40%) | Средняя | Правила в `probability_engine.py` — временные. Нужно накопить 100+ outcomes и обучить XGBoost. Код уже есть (`ml/`, `auto_retrain.py`). Модель обучена 19 Jul 2026. |
| 2 | **Активировать `MIN_P_TP` (0.40+)** | Средний (WR +5-10pp) | Низкая | `MIN_P_TP=0.30` — гейт активен. Проверить, не блокирует ли слишком много. Начать с 0.30 и постепенно повышать. |
| 3 | **Walk-forward оптимизация параметров** | Высокий (PF +15-30%) | Высокая | 50+ параметров, большинство не оптимизированы. Нужен walk-forward на 1-2 года данных. Особенно ADX_MIN, ATR_ множители, EMA периоды. |
| 4 | **Добавить portfolio correlation check** | Средний (Sharpe +0.2-0.5) | Средняя | Нет проверки, что 3 открытых сигнала — не все по BTC и ETH. Добавить корреляционную матрицу портфеля. |
| 5 | **Вынести Circuit Breaker в .env** | Низкий (надёжность) | Низкая | Hardcoded параметры `circuit_breaker.py:20-22`. Вынести в конфиг и подобрать через бэктест. |

### Второстепенные улучшения

- **Убрать hardcoded penalty 0.85** (`scanner.py:477,493,540,556`) — сделать параметром `.env`
- **Сделать cross-direction cooldown** конфигурируемым (сейчас `/2`)
- **Добавить stop-loss на уровне портфеля** (максимальный дневной убыток)
- **Верифицировать look-ahead** в `ob_bos_lookback=20` и `ob_retest_history=30`
- **Убрать `confirm_tf_enabled`** из конфига если 15m TF удалён
- **Добавить `SESSION_KILL_ZONES`** в .env для гибкой настройки trading sessions
- **Оптимизировать `BREAKOUT_QUALITY_MIN_SCORE`** — currently 45, проверить через A/B

---

## 13. Статистика кодовой базы

| Модуль | Файлов | Примерно строк |
|--------|--------|---------------|
| `strategy/` | 22+ | 10000+ |
| `scheduler/` | 6 | 3000+ |
| `liquidity/` | 10 | 3000+ |
| `ml/` | 10 | 3000+ |
| `analytics/` | 16 | 5000+ |
| `backtest/` | 14 | 4000+ |
| `risk/` | 7 | 1500+ |
| `market_structure/` | 4 | 1500+ |
| `storage/` | 2 | 1564 |
| `bot/` | 5 | 1902 |
| `context/` | 3 | 800+ |
| `config/` | 2 | 1050+ |
| `data/` | 1 | 415+ |
| `indicators/` | 1 | 240+ |
| `web/` | 1 | 431 |
| `monitoring/` | 1 | 37 |
| `derivatives/` | 1 | 200+ |
| `analysis/` | 2 | 1000+ |
| `main.py` | 1 | 188 |
| **ИТОГО** | **~110** | **~40000+** |

---

*Аудит проведён: 2026-08-27*
*Версия бота: 2.5.0*
*Обновлено из bot_audit.md (2026-07-27)*
