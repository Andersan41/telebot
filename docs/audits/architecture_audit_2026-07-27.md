# 🏗 Бот-аудит: Trading Signal Bot

**Версия стратегии:** 2.4.0 (`config/settings.py:15`)  
**Дата аудита:** 2026-07-27  
**Цель:** Инвентаризация архитектуры и параметров для последующего анализа/оптимизации

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
```

### 1.2 Модули и зависимости

| Модуль | Назначение | Ключевые файлы |
|--------|-----------|----------------|
| `main.py` | Точка входа, lock, init | `main.py:1-188` |
| `config/` | Централизованная конфигурация | `settings.py:1-958`, `logger.py:1-74` |
| `data/` | Получение OHLCV через ccxt | `exchange_client.py:1-415` |
| `indicators/` | Расчёт индикаторов | `engine.py:1-240` |
| `strategy/` | Ядро стратегии (22 файла) | `pattern_engine.py`, `feature_builder.py`, `probability_engine.py`, `signal_engine.py`, `decision_engine.py`, `hypothesis.py`, `trade_engine.py`, `trade_plan.py`, `market_phase_engine.py`, `market_thesis_engine.py`, `scenario_engine.py`, `scenario_memory.py`, `scenario_invalidator.py`, `entry_trigger.py`, `invalidation.py`, `levels.py`, `transition_model.py`, `weight_manager.py`, `weights.py`, `trade_thesis.py` |
| `scheduler/` | Планировщик и сканер | `tasks.py:1-110`, `scanner.py:1-1399`, `core_v2.py:1-337`, `outcome_tracker.py:1-415`, `circuit_breaker.py:1-87`, `shadow.py` |
| `risk/` | Управление рисками | `engine.py:1-266`, `dynamic_risk.py`, `market_regime.py`, `volatility_regime.py`, `no_trade_zones.py`, `news_filter.py` |
| `context/` | Контекст рынка | `fetcher.py`, `analyzer.py`, `scorer.py` |
| `liquidity/` | Анализ ликвидности | `sweep.py`, `order_blocks.py`, `fvg.py`, `candle_quality.py`, `equal_levels.py`, `external.py`, `ob_state.py` |
| `market_structure/` | Рыночная структура | `structure.py`, `htf_bias.py`, `htf_bias_v2.py`, `premium_discount.py` |
| `storage/` | SQLite БД | `database.py:1-1169+`, `trace.py` |
| `bot/` | Telegram | `handlers.py:1-170`, `notifier.py:1-246`, `admin.py`, `rate_limit.py`, `menu.py` |
| `monitoring/` | Prometheus метрики | `metrics.py:1-37` |
| `analytics/` | Аналитика (16 файлов) | `daily_report.py`, `gate_funnel.py`, `performance.py`, `entry_delay.py`, `counterfactual.py`, `calibration.py` и др. |
| `ml/` | ML модели | `train_model.py`, `auto_retrain.py`, `build_dataset.py`, `triple_barrier.py`, `validate_oos.py` |
| `derivatives/` | Funding/OI/SMT | `smt_divergence.py` |
| `web/` | Веб-дашборд | `server.py` |

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
| `aiohttp` | 3.9.5 | HTTP |
| `httpx` | <0.28 | Telegram transport |
| `numpy` | 2.2.6+ | Научные вычисления |

### 1.4 Точки входа

| Путь | Тип | Описание |
|------|-----|---------|
| `main.py:178` | Entry | Запуск бота (asyncio) |
| `scheduler/scanner.py:1369` | Scan cycle | `run_scan_cycle()` — вызывается планировщиком |
| `scheduler/tasks.py:26-33` | Cron | Сканирование каждые 15 мин (:02, :17, :32, :47) |
| `scheduler/outcome_tracker.py:350` | Background | Фоновый трекинг исходов каждые 300с |
| `scheduler/tasks.py:36-43` | Cron | Ежедневный отчёт в 00:05 UTC |
| `scheduler/tasks.py:46-53` | Cron | ML retrain в 03:00 UTC |
| `backtest/engine.py` | CLI | Бэктест (console / telegram) |

---

## 2. Данные и рынок

### 2.1 Инструменты

- **Источник:** `.env` `SYMBOLS` + динамические через `/addsymbol` (`config/settings.py:66-68`)
- **По умолчанию:** `BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,XRP/USDT` (из `.env.example:23`)
- **Рынок:** Perpetual swap (BingX/Bybit), реже spot/future (`config/settings.py:47`)
- **Формат ccxt:** маппинг `BTC/USDT` → `BTC/USDT:USDT` (`exchange_client.py:25-41`)

### 2.2 Таймфреймы

| Параметр | Значение | Откуда |
|---------|----------|--------|
| `PRIMARY_TIMEFRAMES` | `1h,4h` | `.env.example:24` |
| `CONFIRM_TIMEFRAME` | `15m` | `.env.example:25` |
| `CANDLES_LIMIT` | 200 | `.env.example:67` |
| MTF lookback | 1d,4h,1h | `.env.example:89` |

### 2.3 Тип данных

- **OHLCV** — основной источник (`exchange_client._fetch_ohlcv_raw:122-190`)
- **Taker buy volume** — только Binance futures (`exchange_client._fetch_taker_buy_volumes:192-219`)
- **Funding rate** — отдельный запрос (context/fetcher)
- **Open Interest** — отдельный запрос (derivatives)

### 2.4 Частота и обработка ошибок

- **Опрос:** каждые 15 мин по крону (`scheduler/tasks.py:28`)
- **Cooldown дублей:** 45 мин in-memory (`config/settings.py:641`)
- **Retry OHLCV:** до 3 попыток с exponential backoff (`exchange_client.py:126-190`)
- **Rate limit:** ccxt `enableRateLimit=True` + Semaphore(1) (`exchange_client.py:53,92`)
- **Drop последней свечи:** `df.iloc[:-1]` (`exchange_client.py:305`)
- **Fallback при недоступности символа:** `skip` с логом (`exchange_client.py:136-141`)
- **Paginated OHLCV:** для больших датасетов (`exchange_client.fetch_ohlcv_paginated:310-392`)

---

## 3. Система фильтров (порядок в pipeline)

### 3.1 Pipeline v2 (scan_symbol_v2) — `scheduler/scanner.py:216-1362`

Pipeline — **последовательный** (AND). Каждый гейт — **hard block**. Порядок:

| № | Фильтр/Гейт | Логика | Параметры | Откуда | Строка |
|---|---|---|---|---|---|
| 0.1 | **Cooldown** | Если `signal_cooldown_minutes` не прошёл → BLOCK | `SIGNAL_COOLDOWN_MINUTES=45`, `SIGNAL_COOLDOWN_TF_MULTIPLIER=2.0` | `.env`, DB `bot_settings` | `scanner.py:235-241` |
| 0.2 | **Portfolio Risk** | `active_count >= max_active_signals (3)` или `portfolio_risk >= max_portfolio_risk_pct (3%)` → BLOCK | `MAX_ACTIVE_SIGNALS=3`, `MAX_PORTFOLIO_RISK_PCT=3.0` | `.env` | `scanner.py:246-263` |
| 0.3 | **Data Integrity** | OHLCV/indicators unavailable → BLOCK | — | — | `scanner.py:266-274` |
| 1 | **Pattern Engine** | Не обнаружен ICT setup (reversal или continuation) → BLOCK | `PATTERN_REQUIRE_BOS_OR_SWEEP=true`, `PATTERN_REQUIRE_OB_OR_FVG=true` | `.env` | `scanner.py:328-336` |
| 1.4a | **Sweep Required** (reversal) | Нет sweep → BLOCK | — | — | `scanner.py:350-360` |
| 1.4b | **Displacement Required** (reversal) | Нет displacement при `reversal_require_displacement=true` → BLOCK | `REVERSAL_REQUIRE_DISPLACEMENT=true` | `.env` | `scanner.py:362-370` |
| 1.4c | **MSS Required** (reversal) | Нет MSS (CHoCH) → BLOCK | — | — | `scanner.py:372-381` |
| 1.4d | **BOS Required** (continuation) | Нет BOS → BLOCK | — | — | `scanner.py:383-394` |
| 1.4e | **Entry Zone** (soft) | Если `require_entry_zone=true` и `entry_armed=false` → BLOCK | `REQUIRE_ENTRY_ZONE=false` | `.env` | `scanner.py:397-413` |
| 1.45 | **HTF Bias** (continuation) | Если continuation против HTF bias и `htf_hard_gate=true` → BLOCK, иначе penalty 0.85x | `HTF_BIAS_V2=true`, `HTF_HARD_GATE=true` | `.env` | `scanner.py:442-572` |
| 3 | **min_p_tp** | `P(TP) < MIN_P_TP (0.0)` → BLOCK (отключено) | `MIN_P_TP=0.0` | `.env` | `scanner.py:1094-1104` |
| 4 | **Risk Engine** | R:R < min (1.5), SL вне лимитов (0.25-5.0%), SL vs ATR → BLOCK | `RISK_ENGINE_MIN_RR=1.5`, `RISK_ENGINE_SL_MIN_PCT=0.25`, `RISK_ENGINE_SL_MAX_PCT=5.0` | `.env` | `scanner.py:1113-1141` |
| 4.5 | **Entry Trigger** | Цена вне entry-зоны hypothesis → BLOCK (только для DecisionEngine) | — | — | `scanner.py:1147-1178` |
| 6 | **Dedup** | Тот же direction в течение cooldown → BLOCK | `SIGNAL_COOLDOWN_MINUTES=45` | `.env` | `scanner.py:1218-1248` |

### 3.2 Pipeline v2 (core_v2) — `scheduler/core_v2.py:225-337`

Альтернативный pipeline: 5 фаз → Market Structure → Liquidity Event → Execution Window → Risk Check → Send.  
Не вызывается из `run_scan_cycle()` — вероятно резервный/экспериментальный.

### 3.3 Фильтры в SignalEngine (старый pipeline)

Старый pipeline `scan_symbol()` всё ещё существует (`AGENTS.md:46-47`), но не используется — `run_scan_cycle()` вызывает `scan_symbol_v2()`.

### 3.4 Комбинация фильтров

Все гейты — **AND** (последовательные hard gates). Никаких весов или скоринга между гейтами — либо PASS (идём дальше), либо BLOCK (возврат None).  
Scoring происходит ТОЛЬКО внутри FeatureBuilder/ProbabilityEngine (для ранжирования, не для блокировки).

---

## 4. Условия сигнала

### 4.1 Вход — ICT Setup Detection (`strategy/pattern_engine.py:117-213`)

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

- **Per `symbol_timeframe`** (`scanner.py:117-132`): проверяется из DB (`bot_settings` таблица)
- **Базовая длительность:** `SIGNAL_COOLDOWN_MINUTES=45` (`config/settings.py:641`)
- **TF-множитель:** `SIGNAL_COOLDOWN_TF_MULTIPLIER=2.0` → effective = `max(base, tf_minutes × 2.0)` (`scanner.py:63-66`)
- **Cross-direction cooldown:** половина от базового (`scanner.py:1241-1246`)
- **Сброс при рестарте:** in-memory (1.5 bucket) — в DB не сбрасывается? Нет, cooldown ПИШЕТСЯ в DB (`db.set_cooldown`), так что живёт между рестартами.

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
├ Fear & Greed: 45 (Neutral) 😐
├ Funding: -0.003% ✅
├ Long/Short: 1.02 ⚠️
├ OI: +2.1% ✅
└ Новости: нейтральные 😐

🔍 Вердикт: CONFIRMED (уверенность 85%)
  ✅ Bullish order flow
```

### 5.2 Размер позиции

Рассчитывается в `risk/engine.py:98-262`:
- **Kelly fraction:** `max(0, min((p × b - q) / b, 0.20))` (half-Kelly с cap)
- **Масштабирование:** confidence модели → scenario score → stability → volatility → MSS quality → SL distance
- **Базовый риск:** 1.0% (`RISK_ENGINE_BASE_RISK_PCT=1.0`)
- **Клиппинг:** `[0.1%, 2.0%]` (`config/risk_engine.py:591-593`)
- **Portfolio constraint:** max 3 открытых сигнала, max 3% суммарного риска

---

## 6. Учёт результатов

### 6.1 Есть — развёрнутая система

| Компонент | Что хранит | Таблица |
|----------|-----------|--------|
| `Signal` | Все сигналы (BUY/SELL) | `signals` |
| `SignalOutcome` | Результат (HIT_TP/HIT_SL/EXPIRED) | `signal_outcomes` |
| `SignalCandidate` | Каждый прогон (pass/fail) | `signal_candidates` |
| `DecisionTrace` | Полный трейс каждого прогона | `decision_traces` |
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

---

## 7. Риски и слабые места (экспертная оценка)

### 7.1 Look-ahead bias / Repaint

| Риск | Статус | Комментарий |
|------|--------|-------------|
| **Drop последней свечи** | ✅ Исправлено | `df.iloc[:-1]` в `exchange_client.py:305` |
| **Swing-детекция** | ⚠️ **Частично** | Использует последнюю цену, но BOS/CHoCH определяются по закрытым свечам |
| **Использование будущих данных в OB/FVG** | ⚠️ **Возможно** | `ob_bos_lookahead=20`, `ob_retest_max_lookahead=30` — смотрят ВПЕРЁД в свечах |
| **SuperTrend repaint** | ⚠️ | pandas-ta SuperTrend не repaint на закрытых данных, но нужно верифицировать |
| **Sweep detection** | ⚠️ | Использует `sweep_lookback=50` — корректно, если только по закрытым свечам |

### 7.2 Магические числа и hardcoded значения

| Где | Значение | Проблема |
|-----|---------|----------|
| `exchange_client.py:305` | `df.iloc[:-1]` | Захардкожено (разумно) |
| `scheduler/scanner.py:38-41` | `_TF_MINUTES` словарь | Захардкожен |
| `strategy/probability_engine.py:340` | clamp [20, 85] | Магические числа |
| `risk/engine.py:190` | kelly cap 0.20 | Half-Kelly hardcoded |
| `scheduler/circuit_breaker.py:20-22` | 3 losses, 30 min pause, 60 min window | Hardcoded, не в `.env` |
| `scheduler/scanner.py:466-477` | htf_bias_penalty = 0.85 | Магическое число |
| `strategy/probability_engine.py:220-251` | Веса компонент (3.0, 4.0, 1.5...) | Hardcoded rules weights |
| `strategy/pattern_engine.py:113` | `ob_proximity_pct: float = 2.0` | Можно в `.env` (уже есть `PATTERN_OB_PROXIMITY_PCT`) |

### 7.3 Проблемы надёжности

| Проблема | Серьёзность | Описание |
|----------|-------------|----------|
| **Circuit breaker** hardcoded params | Низкая | Параметры не в `.env`, требуют правки кода |
| **Cooldown** не для cross-direction | Средняя | Cross-direction использует `/2` от cooldown — неконфигурируемо |
| **Windows asyncio** | Низкая | `WindowsSelectorEventLoopPolicy()` — workaround |
| **Telegram HTML** | Средняя | Баги с `<` в строках — `html.escape()` (документировано в `AGENTS.md`) |
| **singleton state** в context | Средняя | Кэши не сбрасываются между тестами (`AGENTS.md:76-78`) |
| **Outcome tracker race** | Низкая | `SignalOutcome` может дублироваться при быстрых закрытиях |

### 7.4 Отсутствие

| Пробел | Критичность |
|--------|-------------|
| **Production-бэктеста нет** — backtest engine есть, но нет регулярного walk-forward | Средняя |
| **Нет стоп-лосса на уровне портфеля** (только суммарный риск) | Низкая |
| **Нет интеграции с реальным исполнением** — только сигналы | Критическая (для реальной торговли) |
| **Нет проверки корреляции между одновременно открытыми сигналами** | Средняя |

---

## 8. Сводная таблица ВСЕХ настраиваемых параметров

### 8.1 Торговые параметры

| Параметр | Текущее значение | Файл:строка | Влияет | Оптимизировать? |
|----------|-----------------|-------------|--------|:---:|
| `EMA_FAST` | 8 | `config/settings.py:80` | EMA fast period | Да |
| `EMA_SLOW` | 21 | `config/settings.py:82` | EMA slow period | Да |
| `EMA_TREND` | 55 | `config/settings.py:84` | EMA trend period | Да |
| `MIN_EMA_SPREAD_PCT` | 0.20 | `config/settings.py:86` | Мин. разброс EMA | Да |
| `RSI_PERIOD` | 10 | `config/settings.py:96` | RSI period | Да |
| `RSI_OVERBOUGHT` | 72 | `config/settings.py:98` | Уровень перекупленности | Да |
| `RSI_OVERSOLD` | 28 | `config/settings.py:100` | Уровень перепроданности | Да |
| `RSI_BULL_MIN` | 55 | `config/settings.py:102` | Мин. RSI для бычьей зоны | Да |
| `RSI_BEAR_MAX` | 45 | `config/settings.py:104` | Макс. RSI для медвежьей зоны | Да |
| `MACD_FAST` | 8 | `config/settings.py:108` | Быстрая MACD | Да |
| `MACD_SLOW` | 21 | `config/settings.py:110` | Медленная MACD | Да |
| `MACD_SIGNAL` | 5 | `config/settings.py:112` | Сигнальная MACD | Да |
| `ADX_PERIOD` | 14 | `config/settings.py:122` | ADX period | Да |
| `ADX_MIN` | 26 | `config/settings.py:124` | ADX мин. (тренд/флэт) | Да |
| `ATR_PERIOD` | 14 | `config/settings.py:136` | ATR period | Да |
| `ATR_MULTIPLIER_SL` | 1.5 | `config/settings.py:138` | ATR × SL | Да |
| `ATR_MULTIPLIER_TP` | 3.0 | `config/settings.py:140` | ATR × TP | Да |
| `SUPERTREND_PERIOD` | 10 | `config/settings.py:164` | SuperTrend period | Да |
| `SUPERTREND_MULTIPLIER` | 2.5 | `config/settings.py:166` | SuperTrend multiplier | Да |
| `VOLUME_FACTOR` | 1.5 | `config/settings.py:170` | Объём > SMA × factor | Да |
| `VOLUME_SMA_PERIOD` | 20 | `config/settings.py:172` | SMA объёма | Да |
| `CANDLES_LIMIT` | 200 | `config/settings.py:202` | Глубина OHLCV | Да |
| `MIN_SL_DISTANCE_PCT` | 1.0 | `config/settings.py:148` | Мин. SL от entry | Да |
| `MAX_SL_DISTANCE_PCT` | 10.0 | `config/settings.py:150` | Макс. SL от entry | Да |
| `STOP_HUNT_BUFFER_PCT` | 0.5 | `config/settings.py:154` | Буфер за уровнем | Да |
| `MAX_OB_DISTANCE_PCT` | 3.0 | `config/settings.py:156` | Макс. дист. OB от entry | Да |
| `MIN_RR_THRESHOLD` | 1.5 | `config/settings.py:152` | Мин. R:R | Да |

### 8.2 Риск-параметры

| Параметр | Значение | Файл:строка | Влияет | Опт.? |
|----------|---------|-------------|--------|:----:|
| `VOLATILITY_LOW_THRESHOLD` | 0.8 | `config/settings.py:306` | Порог низкой волатильности | Да |
| `VOLATILITY_HIGH_THRESHOLD` | 6.0 | `config/settings.py:308` | Порог высокой волатильности | Да |
| `RISK_STRONG_PCT` | 1.0 | `config/settings.py:316` | Риск для strong сигнала | Да |
| `RISK_MODERATE_PCT` | 0.5 | `config/settings.py:318` | Риск для moderate | Да |
| `NO_TRADE_MIN_ATR_PCT` | 0.6 | `config/settings.py:324` | Мин. ATR для торговли | Да |
| `MAX_ACTIVE_SIGNALS` | 3 | `config/settings.py:663` | Макс. открытых сигналов | Да |
| `MAX_PORTFOLIO_RISK_PCT` | 3.0 | `config/settings.py:665` | Суммарный риск | Да |
| `RISK_ENGINE_MIN_RR` | 1.5 | `config/settings.py:583` | R:R финальный гейт | Да |
| `RISK_ENGINE_SL_MIN_PCT` | 0.25 | `config/settings.py:585` | Мин. SL % (hard) | Да |
| `RISK_ENGINE_SL_MAX_PCT` | 5.0 | `config/settings.py:587` | Макс. SL % (hard) | Да |
| `RISK_ENGINE_BASE_RISK_PCT` | 1.0 | `config/settings.py:589` | Базовый риск/сделку | Да |

### 8.3 Structurы и ликвидность

| Параметр | Значение | Опт.? |
|----------|---------|:----:|
| `SWEEP_LOOKBACK` | 50 | Да |
| `SWEEP_MIN_VOLUME_RATIO` | 1.8 | Да |
| `SWEEP_MAX_RECLAIM_CANDLES` | 2 | Да |
| `OB_MIN_DISPLACEMENT_PCT` | 2.5 | Да |
| `OB_MIN_VOLUME_RATIO` | 1.8 | Да |
| `OB_MAX_AGE_CANDLES` | 35 | Да |
| `FVG_MIN_SIZE_PCT` | 0.4 | Да |
| `DISTANCE_FILTER_MIN_PCT` | 1.2 | Да |
| `MTF_REQUIRED_ALIGNMENT` | 2 | Да |
| `STRUCTURE_LOOKBACK` | 50 | Да |

### 8.4 ML/Scoring

| Параметр | Значение | Опт.? |
|----------|---------|:----:|
| `CONFIDENCE_STRONG_THRESHOLD` | 65 | Да |
| `CONFIDENCE_MODERATE_THRESHOLD` | 40 | Да |
| `MIN_SCORE_FOR_SIGNAL` | 2 | Да |
| `PROBABILITY_MIN_SAMPLES_FOR_ML` | 100 | Да |
| `MIN_P_TP` | 0.0 (выкл) | Да |
| `TECH_CONFIDENCE_BLEND` | 0.6 | Да |
| `MARKET_CONFIDENCE_BLEND` | 0.4 | Да |
| `HISTORICAL_WR_BLEND` | 0.4 | Да |

### 8.5 Filter toggles

| Параметр | Значение | Опт.? |
|----------|---------|:----:|
| `ADX_FILTER_ENABLED` | true | Нет (on/off) |
| `EMA_ALIGNMENT_ENABLED` | true | Нет (on/off) |
| `TRIGGER_REQUIRED` | true | Нет (on/off) |
| `CANDLE_CLOSE_ENABLED` | true | Нет (on/off) |
| `COMPRESSION_ENABLED` | true | Нет (on/off) |
| `BLOCK_COMPRESSION_REGIME` | true | Нет (on/off) |
| `HTF_BIAS_V2` | true | **Да** (feature flag) |
| `PREMIUM_DISCOUNT` | false | **Да** (рекомендовано) |
| `REQUIRE_ENTRY_ZONE` | false | **Да** |
| `USE_TESTNET` | false | Нет (on/off) |

### 8.6 Расписание

| Параметр | Значение | Опт.? |
|----------|---------|:----:|
| `SCAN_MINUTES` | 2,17,32,47 | Да |
| `SIGNAL_COOLDOWN_MINUTES` | 45 | Да |
| `SIGNAL_COOLDOWN_TF_MULTIPLIER` | 2.0 | Да |
| `OUTCOME_CHECK_INTERVAL_SECONDS` | 300 | Да |

### 8.7 Circuit Breaker (hardcoded, не в .env)

| Параметр | Значение | Где | Опт.? |
|----------|---------|-----|:----:|
| `CIRCUIT_BREAKER_LOSS_THRESHOLD` | 3 | `circuit_breaker.py:20` | **Да** (вынести в .env) |
| `CIRCUIT_BREAKER_PAUSE_MINUTES` | 30 | `circuit_breaker.py:21` | **Да** (вынести в .env) |
| `CIRCUIT_BREAKER_WINDOW_MINUTES` | 60 | `circuit_breaker.py:22` | **Да** (вынести в .env) |
| `FUNDING_RATE_8H` | 0.0001 | `outcome_tracker.py:27` | **Да** |
| `SYMBOL_FETCH_FAIL_THRESHOLD` | 3 | `outcome_tracker.py:31` | **Да** |
| `SYMBOL_FETCH_COOLDOWN_SECONDS` | 600 | `outcome_tracker.py:32` | **Да** |

---

## 9. Вопросы к владельцу

### [НЕЯСНО]

1. **Какой период работы бота в продакшене?** Сколько сигналов уже сгенерировано? Есть ли статистика winrate/performance?

2. **Какой бэктест проводился?** `AGENTS.md` упоминает A/B тест HTF Bias V2 (90d/1h BTC+ETH), но нет общего бэктеста.

3. **Бот торгует реально или только сигналит?** Из кода — только сигналы в Telegram. Никаких ордеров на бирже.

4. **Какая биржа используется фактически?** `.env.example:11` — `EXCHANGE=bingx`, но ключи BINANCE. 
   `exchange_client.py:203` — для taker buy volume только Binance. Реально BingX или Binance?

5. **Есть ли `PROBABILITY_MODEL_PATH` (models/probability_model.pkl)?** Если нет — используется rules fallback. Какое качество правил?

6. **Какие параметры Circuit Breaker оптимальны?** 3 losses → 30 min pause — не менялись? Может быть слишком агрессивно.

7. **Используется ли `BLOCK_COMPRESSION_REGIME=true`?** В WR 37.7% compression не имеет edge — все compression-сигналы блокируются.

8. **`PREMIUM_DISCOUNT=false`** — из A/B показал PF 1.28 → 0.91. Планируется ли пересмотр после 500+ сделок?

9. **Какой `MARKET_TYPE` используется?** swap (perpetual futures) или spot? Влияет на funding cost в трекинге.

10. **`confirm_tf_enabled`** — в `AGENTS.md` написано, что 15m confirmation TF удалён. Но параметр остался в конфиге. Он активен?

---

## 10. Рекомендованные следующие шаги

### Топ-5 гипотез по улучшению

| # | Гипотеза | Ожидаемый эффект | Сложность | Обоснование |
|---|----------|-----------------|-----------|-------------|
| 1 | **ML-модель на historical outcomes** | Высокий (PF +20-40%) | Средняя | Правила в `probability_engine.py` — временные. Нужно накопить 100+ outcomes и обучить XGBoost. Код уже есть (`ml/`, `auto_retrain.py`). |
| 2 | **Активировать `MIN_P_TP` (0.40+)** | Средний (WR +5-10pp) | Низкая | `MIN_P_TP=0.0` — гейт отключён. Даже 0.40 отсечёт низкокачественные сигналы. Начать с 0.30 и постепенно повышать. |
| 3 | **Walk-forward оптимизация параметров** | Высокий (PF +15-30%) | Высокая | 50+ параметров, большинство не оптимизированы. Нужен walk-forward на 1-2 года данных. Особенно ADX_MIN, ATR_ множители, EMA периоды. |
| 4 | **Добавить portfolio correlation check** | Средний (Sharpe +0.2-0.5) | Средняя | Нет проверки, что 3 открытых сигнала — не все по BTC и ETH. Добавить корреляционную матрицу портфеля. |
| 5 | **Вынести Circuit Breaker в .env** | Низкий (надёжность) | Низкая | Hardcoded параметры `circuit_breaker.py:20-22`. Вынести в конфиг и подобрать через бэктест. |

### Второстепенные улучшения

- **Убрать hardcoded penalty 0.85** (`scanner.py:477,493,540,556`) — сделать параметром `.env`
- **Сделать cross-direction cooldown** конфигурируемым (`scanner.py:1241`, сейчас `/2`)
- **Добавить stop-loss на уровне портфеля** (максимальный дневной убыток)
- **Верифицировать look-ahead** в `ob_bos_lookahead=20` и `ob_retest_max_lookahead=30`
