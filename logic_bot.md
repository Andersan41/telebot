# ЛОГИКА БОТА — Полная карта торгового сигнала

> **Стратегия**: v2.5.0 | **Стек**: Python 3.11, ccxt, pandas-ta, SQLAlchemy async, python-telegram-bot 20.x
> **База**: SQLite (aiosqlite) | **Расписание**: APScheduler (каждые 15 мин)
> **Вход**: `main.py` → `TaskScheduler` → `run_scan_cycle()` → `scan_symbol_v2()`

---

## СОДЕРЖАНИЕ

1. [Общая архитектура](#1-общая-архитектура)
2. [Точка входа и расписание](#2-точка-входа-и-расписание)
3. [Оркестратор: run_scan_cycle](#3-оркестратор-run_scan_cycle)
4. [Основной пайплайн: scan_symbol_v2](#4-основной-пайплайн-scan_symbol_v2)
5. [Фаза 0: Hard Gates (капитальная защита)](#5-фаза-0-hard-gates)
6. [Фаза 1: Pattern Engine (ICT Setup)](#6-фаза-1-pattern-engine)
7. [Фаза 1.4: Setup-Type Specific Gates](#7-фаза-14-setup-type-specific-gates)
8. [Фаза 1.41–1.45: Дополнительные фильтры](#8-фаза-141–145-дополнительные-фильтры)
9. [Фаза 1.5: Trade Plan (SL/TP)](#9-фаза-15-trade-plan)
10. [Фаза 1.7: LTF Confirmation](#10-фаза-17-ltf-confirmation)
11. [Shadow Mode Engines (не блокируют)](#11-shadow-mode-engines)
12. [Фаза 2: Feature Builder](#12-фаза-2-feature-builder)
13. [Фаза 3: Probability Engine](#13-фаза-3-probability-engine)
14. [Фаза 4: Risk Engine](#14-фаза-4-risk-engine)
15. [Фаза 4.5: Entry Trigger](#15-фаза-45-entry-trigger)
16. [Фаза 5–6: Build SignalResult + Dedup](#16-фаза-56-build-signalsresult--dedup)
17. [Фаза 7: Execution Filters](#17-фаза-7-execution-filters)
18. [Фаза 8: Save + Notify](#18-фаза-8-save--notify)
19. [Полная карта фильтров (последовательных и параллельных)](#19-полная-карта-фильтров)
20. [Веса параметров и скоринг](#20-веса-параметров-и-скоринг)
21. [Система аудита и логирования](#21-система-аудита-и-логирования)
22. [Cooldown и Dedup логика](#22-cooldown-и-dedup-логика)
23. [Post-signal: Управление позицией](#23-post-signal-управление-позицией)
24. [Контекстные источники данных](#24-контекстные-источники-данных)
25. [Конфигурация (ключевые параметры)](#25-конфигурация)
26. [Аудит-коды (reason codes)](#26-аудит-коды)
27. [Граф потока данных ( текстовая схема)](#27-граф-потока-данных)
28. [Известные пробелы и рекомендации](#28-известные-пробелы)

---

## 1. Общая архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                        main.py (Entry Point)                     │
│  DB init → Exchange connect → Telegram bot → Scheduler start     │
└──────────┬──────────────────────────────────────┬────────────────┘
           │                                      │
           ▼                                      ▼
   ┌───────────────┐                    ┌──────────────────┐
   │ Telegram Bot   │                    │ TaskScheduler     │
   │ /scan command  │───────────────────▶│ cron :02,:17,     │
   │ /start, etc.   │                    │ :32,:47 (15 min)  │
   └───────────────┘                    └────────┬─────────┘
                                                 │
                                                 ▼
                                      ┌─────────────────────┐
                                      │ run_scan_cycle()      │
                                      │ (asyncio.gather)      │
                                      └────────┬────────────┘
                                               │
                              ┌────────────────┼────────────────┐
                              ▼                ▼                ▼
                     scan_symbol_v2()   scan_symbol_v2()   scan_symbol_v2()
                     (BTC/USDT 1h)     (BTC/USDT 4h)     (ETH/USDT 1h) ...
                              │
                              ▼
              ┌───────────────────────────────────┐
              │         4-Layer Pipeline           │
              │  Pattern → Features → Prob → Risk  │
              └───────────────────────────────────┘
```

**Ключевые модули:**

| Модуль | Файл | Строк | Назначение |
|--------|------|-------|------------|
| Pattern Engine | `strategy/pattern_engine.py` | 533 | ICT паттерны: sweep→displacement→MSS / trend→BOS |
| Feature Builder | `strategy/feature_builder.py` | 503 | ~35 признаков в плоский вектор |
| Probability Engine | `strategy/probability_engine.py` | 570 | P(TP), expected RR, profit factor |
| Risk Engine | `risk/engine.py` | 315 | Hard gates + Kelly sizing |
| Trade Engine | `strategy/trade_engine.py` | 376 | SL/TP на основе ликвидности |
| Scanner | `scheduler/scanner.py` | 2121 | Весь пайплайн scan_symbol_v2 |
| Config | `config/settings.py` | 1071 | Все параметры через .env |
| Database | `storage/database.py` | 1430 | SQLAlchemy async, 10+ таблиц |

---

## 2. Точка входа и расписание

### main.py (188 строк)

```
1. Добавляет корень проекта в sys.path
2. Lock-файл (.trading_bot.lock) — предотвращает дублирование
3. Инициализация логгера (loguru + Telegram error sink)
4. Prometheus metrics (опционально)
5. Инициализация SQLite БД + миграции
6. Загрузка runtime-символов из БД
7. Подключение к бирже через ccxt
8. Запуск web-сервера (афишный дашборд, опционально)
9. Создание Telegram Application (python-telegram-bot v20.x)
10. Регистрация всех хендлеров (bot/handlers.py)
11. Создание и запуск TaskScheduler
12. Запуск фонового outcome_tracker_loop (SL/TP мониторинг)
13. Telegram polling с retry при конфликтах
```

### Scheduler (scheduler/tasks.py, 110 строк)

| Задача | Cron | Описание |
|--------|------|----------|
| `scan_all_tfs` | `2,17,32,47` (каждые 15 мин) | Сканирует все символы × таймфреймы |
| `daily_report` | `00:05 UTC` | Дневной отчёт |
| `ml_retrain` | `03:00 UTC` | Переобучение ML-модели |

**Circuit Breaker** (`scheduler/circuit_breaker.py`): 3 последовательных SL → пауза 30 мин. Сбрасывается после паузы.

---

## 3. Оркестратор: run_scan_cycle

**Файл**: `scheduler/scanner.py`, строки 2087–2121

```python
async def run_scan_cycle(notify_callback, blocked_callback=None, timeframes=None):
```

**Алгоритм:**
1. Проверка блокировки `_scan_lock` — если цикл уже идёт, ПРОПУСК (нет пересечений)
2. Проверка circuit breaker — если активен, ПРОПУСК
3. Получение активных символов (`get_active_symbols()`) минус отключённые из БД
4. Таймфреймы: переданные аргументом или `config.trading.primary_timeframes` (по умолчанию `["1h", "4h"]`)
5. Сброс счётчика воронки `_current_funnel`
6. Создание задачи `scan_symbol_v2(symbol, tf, notify_callback)` для каждой пары (символ, TF)
7. **Параллельное выполнение** через `asyncio.gather(*tasks, return_exceptions=True)`
8. Подсчёт результатов, логирование воронки

**Важно:** Все (символ, TF) пары сканируются **параллельно**, но один символ+TF не дублируется (lock).

---

## 4. Основной пайплайн: scan_symbol_v2

**Файл**: `scheduler/scanner.py`, строки 280–2080

Это **единственный** активный пайплайн. Старый `scan_symbol` удалён.

**Общая структура (порядок严格执行):**

```
Phase 0:  Hard Gates (капитальная защита)       ← последовательные, любой блокирует
Phase 1:  Pattern Engine (ICT Setup)             ← последовательные
Phase 1.4: Setup-Type Gates                     ← последовательные
Phase 1.41-1.45: Доп. фильтры                   ← последовательные (некоторые опциональные)
Phase 1.5: Trade Plan (SL/TP)                   ← последовательные
Phase 1.7: LTF Confirmation                     ← опциональный
Shadow:   Market Phase + Thesis + Hypothesis     ← параллельные, НЕ блокируют
Phase 2:  Feature Builder                        ← вычисление (не фильтр)
Phase 3:  Probability Engine                     ← последовательный
Phase 4:  Risk Engine                            ← последовательный
Phase 4.5: Entry Trigger                         ← последовательный
Phase 5:  Build SignalResult                     ← сборка
Phase 6:  Dedup                                  ← последовательный
Phase 7:  Execution Filters                      ← последовательные
Phase 8:  Save + Notify                          ← финализация
```

---

## 5. Фаза 0: Hard Gates (капитальная защита)

**Строки 296–402.** Последовательная проверка. **Любой** сбой = мгновенный `return None`.

| # | Проверка | Блокировка | Audit Code | Описание |
|---|----------|------------|------------|----------|
| 0.1 | Cooldown | `COOLDOWN_ACTIVE` | Если в `ob_aware` режиме — ПРОПУСКАЕТ (отложено до Phase 6). В `strict` — полная проверка |
| 0.2 | Portfolio: max active signals | `PORTFOLIO_MAX_ACTIVE` | `active_count >= config.max_active_signals` (default 3) |
| 0.2 | Portfolio: max risk % | `PORTFOLIO_MAX_RISK` | `portfolio_risk >= config.max_portfolio_risk_pct` (default 3.7%) |
| 0.2b | Daily limits | `DAILY_LIMIT_HIT` | Проверка 5 условий: remaining risk, trades count, consecutive losses, drawdown, profit target |
| 0.2c | Position limits | `POSITION_LIMIT_HIT` | `_total_positions >= config.risk.max_positions_total` (default 5) |
| 0.3 | Fetch OHLCV + Indicators | `DATA_INTEGRITY_FAIL` | `_get_indicators()` — загрузка свечей и расчёт индикаторов. Если нет данных → BLOCK |
| 0.4 | Volatility filter | `VOLATILITY_TOO_LOW/HIGH` | `atr_pct < vol_min (0.3%)` или `atr_pct > vol_max (5.0%)` |

**Ключевой момент:** Все проверки в Фазе 0 — это **последовательные hard gates**. Порядок важен: сначала дешёвые проверки (cooldown, portfolio), потом дорогие (OHLCV fetch).

---

## 6. Фаза 1: Pattern Engine (ICT Setup)

**Строки 404–518.** Чистые вычисления, последовательные проверки.

### 6.1 Подготовка данных

```python
_df_clean = df.dropna(subset=["open", "high", "low", "close", "volume"])
```

### 6.2 Детекция ICT-компонентов

| Компонент | Функция | Модуль | Lookback |
|-----------|---------|--------|----------|
| Sweep (ликвидность) | `detect_sweeps()` | `liquidity/sweep.py` | 50 свечей |
| Order Blocks | `detect_order_blocks()` | `liquidity/order_blocks.py` | 100 свечей |
| Fair Value Gaps | `detect_fvg()` | `liquidity/fvg.py` | config `fvg_lookback` |
| Candle Quality | `analyze_last_candle()` | `liquidity/candle_quality.py` | Последняя свеча |

### 6.3 Привязка OB к Sweep

Для каждого валидного sweep выполняется **обратный поиск** OB (`find_ob_for_sweep`, lookback=20):
- Направление OB совпадает с направлением sweep
- Дедупликация: timestamp + тип + midpoint proximity

### 6.4 Анализ рыночной структуры

```python
structure = analyze_structure(
    _df_clean, lookback=50, sweeps=sweeps,
    displacement_atr=_disp_atr, reclaim_bars=_reclaim, atr_value=ind.atr,
)
```

**`analyze_structure()`** (`market_structure/structure.py`):
1. Находит swing points (HH/HL/LH/LL) через локальные экстремумы (окно 2*swing_window+1)
2. Определяет BOS (Break of Structure) и CHoCH (Change of Character)
3. Классифицирует тренд: bullish / bearish / ranging
4. Классифицирует CHoCH как **MSS** (Market Structure Shift) если:
   - Sweep в causal window (10 бар, exponential decay half-life=3)
   - Displacement >= 0.2 ATR
   - Reclaim <= 2 бар

### 6.5 Pattern Engine — detect()

```python
setup = pattern_engine.detect(
    sweeps=sweeps, order_blocks=order_blocks, structure=structure,
    fvgs=fvgs, candle_quality=candle_quality,
    current_price=ind.close, atr=ind.atr,
)
```

**Два.pipeline:**

#### REVERSAL (приоритет):
```
Sweep → Displacement → MSS
```
1. **Sweep** обязателен. Фильтр false sweeps (`passes_false_sweep_filters`). Выбирается самый сильный sweep.
2. **Displacement** — informational only (не gate). Чтение из `candle_quality`.
3. **MSS** обязателен. Должен быть `structure.last_mss` (strong CHoCH). Направление = тип MSS.

#### CONTINUATION (fallback):
```
Trend → BOS
```
1. **Trend** обязателен (не ranging).
2. **BOS** обязателен. Должен быть `structure.last_bos`. Валидация: BOS ломает последний swing перед pullback.
3. **Alignment** — направление BOS совпадает с трендом.

**Output**: `ICTSetup` dataclass:
- `detected: bool` — найден ли setup
- `direction: "buy" / "sell"`
- `setup_type: "reversal" / "continuation"`
- Компоненты: `has_sweep`, `has_displacement`, `has_mss`, `has_bos`, `has_ob`, `has_fvg`
- `mss_score` (0–100), `mss_causality` (0–1, exponential decay)
- `confirmation_score` — взвешенный: BOS=2, FVG=1, OB=1
- `entry_armed` — цена рядом с OB/FVG midpoint (soft)

---

## 7. Фаза 1.4: Setup-Type Specific Gates

**Строки 520–625.** Последовательные.

| Проверка | Reversal | Continuation | Audit Code |
|----------|----------|--------------|------------|
| Sweep required | `has_sweep` обязателен | — | `SWEEP_NONE` |
| Displacement | Если `config.reversal_require_displacement=True` → `has_displacement` обязателен | — | `DISPLACEMENT_MISSING` |
| MSS required | `has_mss` обязателен | — | `MSS_NONE` |
| BOS required | — | `has_bos` обязателен | `CONTINUATION_NO_BOS` |
| Entry Zone | `config.require_entry_zone` → `entry_armed` обязателен | То же | `ENTRY_ZONE_BLOCKED` |
| Confirmation Score | `confirmation_score >= 2` | То же | `CONFIRMATION_LOW` |

**Confirmation Score** — взвешенная сумма компонентов:
- BOS = 2 балла
- FVG = 1 балл
- OB = 1 балл
- Минимум = 2 для прохождения

---

## 8. Фаза 1.41–1.45: Дополнительные фильтры

### 1.41 Breakout Quality (строки 639–700)

**Модуль**: `liquidity/breakout_quality.py` (202 строки)

Определяет, реальный ли breakout или AMD stop-hunt (fake).

**Алгоритм:**
1. Находит settled range boundary (swing high/low за lookback свечей, исключая последние 2)
2. Проверяет: CLOSE за boundary → real, только WICK → fake
3. Скоринг 0–100:
   - body >= 0.5 за boundary → +40
   - retention >= 2 (с consecutive closes) → +20
   - displacement_atr >= 1.0 → +15
   - volume_ratio >= 1.8 → +15
   - OI подтверждает направление → +15
   - Штрафы: body < 0.5 → −25, retention < 2 → −15

**Вердикт**: score >= 55 → "real". body >= 0.5 + score >= 25 → "real". Иначе → "ambiguous".

**Gate**: Если `config.breakout_quality_hard_gate=True` и verdict="fake" → `BREAKOUT_FAKE`. По умолчанию **OFF** (shadow log only).

### 1.42 OB Retest + Mitigation (строки 702–797)

**Если `config.require_ob_retest=True`** (default: True):

1. **OB age**: если OB старше `max_age` и не retested → mitigated → BLOCK
2. **OB state** (`get_ob_state()`): BROKEN / MITIGATED / VALID
   - BROKEN → BLOCK
   - MITIGATED → BLOCK
3. **Price returned to OB zone**: `ob.low <= last_close <= ob.high` или `ob.retested`
4. **Confirmation candle**: engulfing (body > prev body + close above/below prev open) или pin-bar (wick_ratio > 0.6, body/range < 0.3)

**Audit codes**: `OB_RETEST_FAILED`, `OB_TOO_OLD`, `OB_BROKEN`, `OB_MITIGATED`, `OB_TOO_FAR`, `OB_NOT_RETESTED`, `OB_NO_CONFIRMATION`

### 1.43 Session Filter / Kill Zones (строки 801–819)

**Если `config.session_hard_gate=True`** (default: False):

| Сессия | UTC Hours |
|--------|-----------|
| Asian | 0–7 |
| London | 7–12 |
| Overlap (London+NY) | 12–16 |
| New York | 16–21 |

Блокирует, если текущая сессия не в `config.trading_sessions` и не overlap.

### 1.44 SMT Divergence (строки 627–637)

**Модуль**: `derivatives/smt_divergence.py`

**Soft gate** — записывается в trace, но **НЕ блокирует**. Используется как feature для Feature Builder.

### 1.45 HTF Bias V2 (строки 843–1026)

**Модуль**: `market_structure/htf_bias_v2.py` (160 строк)

**Если `config.htf_bias_v2=True`** (default: True):

**Top-down анализ**: W1 → D1 → H4 → H1

**Метод**: EMA21/55 alignment + structure (BOS) на каждом TF.

**Majority voting на W1, D1, H4:**
- 3/3 одинаковых → STRONG
- 2/3 одинаковых → MODERATE
- W1 согласен с D1 или H4 → WEAK
- Нет соглашения → NEUTRAL

**Override логика:**
- W1 конфликтует, но D1+H4 согласны → override (MODERATE)
- H4 конфликтует, но W1+D1 согласны → pullback (MODERATE)

**Hard Gates:**
| Условие | Audit Code |
|---------|------------|
| SHORT в bullish HTF | `HTF_SHORT_IN_BULLISH` |
| LONG в bearish HTF | `HTF_LONG_IN_BEARISH` |
| Continuation не совпадает с HTF | `HTF_CONTINUATION_MISMATCH` |
| Reversal не совпадает с HTF | `HTF_REVERSAL_MISMATCH` |

### Premium/Discount Zone (строки 1028–1052)

**Если `config.premium_discount=True`** (default: False, A/B показал ухудшение):

Классификация зоны по позиции цены относительно range equilibrium (Fibonacci). **Soft** — влияет на вероятность через multiplier, не блокирует.

---

## 9. Фаза 1.5: Trade Plan (SL/TP)

**Строки 1054–1081.**

```python
trade_plan = trade_engine.build_trade_plan(
    ind=ind, direction=setup.direction, structure=structure,
    order_blocks=order_blocks, sweeps=sweeps, fvgs=fvgs,
    df=_df_clean, timeframe=timeframe, htf_poi_result=_htf_poi_result,
)
```

**Trade Engine** (`strategy/trade_engine.py`, 376 строк):

### Шаг 1: Build Liquidity Map
Конвертация structure points → SwingPoints, вызов `build_liquidity_map()`.

### Шаг 2: Find Invalidation (SL)
Приоритетный каскад (`strategy/invalidation.py`):

| Приоритет | Источник | Buy SL | Sell SL |
|-----------|----------|--------|---------|
| 1 | Sweep extreme | Ниже sweep low | Выше sweep high |
| 2 | OB boundary | Ниже OB low | Выше OB high |
| 3 | Swing point | Ниже swing low | Выше swing high |
| 4 | BOS level | Ниже BOS level | Выше BOS level |
| 5 | ATR fallback | entry − ATR × 1.5 | entry + ATR × 1.5 |

**SL Safety** (строки 139–179):
- SL должен быть за пределами текущей свечи (wick)
- Spread buffer: 0.01%
- Tick buffer: из exchange market info
- ATR buffer: 15% от ATR

**HTF POI SL Override** (строки 181–201):
Если цена рядом с HTF POI (D1/H4 OB/FVG) → SL привязывается к HTF structure level для лучшего RR.

### Шаг 3: Find Targets (TP)
Множественные кандидаты TP:
- Type bonus priority: old_high/low (2.0) > equal_high/low (1.8) > ob (1.5) > fvg (1.2) > swept (0.5)
- Минимальная дистанция TP = 1 ATR
- Проверка path clarity: нет opposing OB/FVG с strength > 0.5 между entry и target

### Шаг 4: Выбор лучшего target
`max(targets, key=lambda t: t.score)` где `score = strength × min(1.0, rr_ratio/3.0) × (1.0 if path_clear else 0.5)`

### Шаг 5: Validate
Risk Engine decides — Trade Engine только **отмечает** RR < min, но не блокирует.

**Output**: `TradePlan` dataclass: `sl`, `tp`, `sl_source`, `tp_source`, `rr_ratio`, `entry_zone`, `targets`, `liquidity_summary`

---

## 10. Фаза 1.7: LTF Confirmation

**Строки 1085–1155.** Опциональный.

**Если `config.trading.scan_mode="multi_tf"` и `config.trading.confirm_tf_enabled=True`:**

1. Загрузка свечей подтверждения (например, 5m)
2. Расчёт индикаторов на подтверждающем TF
3. `find_confirmation()` — проверка подтверждения на LTF
4. Если подтверждено → entry_price корректируется с LTF
5. Если нет → `LTF_NO_CONFIRMATION` / `LTF_DATA_UNAVAILABLE`

---

## 11. Shadow Mode Engines (НЕ блокируют)

**Строки 1157–1461.** Работают параллельно, записывают результаты, но **никогда не возвращают None**.

### Market Phase Detection (строки 1157–1189)
`MarketPhaseEngine.assess()` — определяет compression/expansion/trend/range.

### Market Thesis Engine (строки 1191–1363)
- Строит/обновляет `LiquidityGraph` (DAG ликвидности)
- Создаёт/обновляет `DynamicTradeThesis` для каждой пары symbol/timeframe
- Кеширует графы между циклами
- Оценивает конкурирующие BUY/SELL сценарии

### Hypothesis + Decision Engine (строки 1365–1461)
- Строит `HypothesisSet`
- Оценивает через `DecisionEngine.decide()`
- Записывает expected metrics в `ScenarioMemory`

---

## 12. Фаза 2: Feature Builder

**Строки 1463–1554.** Чистые вычисления (не фильтр).

```python
features = feature_builder.build(
    setup=setup, ind=ind, structure=structure, regime=regime,
    vol_regime=vol_regime, mtf_aligned=mtf_aligned, mtf_count=mtf_count,
    context_score=context_score_val, fear_greed=fear_greed_val,
    funding_rate=funding_rate_val, sl=sl, tp=tp, entry_price=entry_price,
    candle_quality=candle_quality, is_reversal=is_reversal,
    htf_bias_penalty=_htf_bias_penalty, ob_state_multiplier=_ob_state_multiplier,
    smt_divergence_score=_smt_to_score(_smt_result), wave_analysis=_wave_analysis,
)
```

### SetupFeatures (~50 raw features)

| Категория | Признаки |
|-----------|----------|
| **Setup** | `setup_type` (reversal=+1, continuation=−1) |
| **ICT Pattern** | `has_bos`, `has_sweep`, `has_ob`, `has_fvg`, `has_displacement`, `components_count` |
| **Reversal** | `has_mss`, `mss_score`, `mss_causality`, `displacement_atr_ratio`, `sweep_to_mss_bars` |
| **Pattern metrics** | `ob_distance_pct`, `fvg_size_pct`, `sweep_reclaim_speed`, `sweep_strength` |
| **Structure** | `structure_trend` (bullish=+1, bearish=−1, ranging=0), `structure_bos_aligned` |
| **Volume** | `volume_ratio` (volume/volume_sma), `volume_delta_pct`, `volume_above_avg` |
| **Volatility** | `atr`, `atr_pct`, `regime` (trend=1, range=0.5, compression=−0.5, expansion=−1) |
| **Indicators** | `rsi`, `adx`, `ema_spread_pct`, `dmi_diff`, `macd_hist_pct` |
| **MTF** | `mtf_aligned`, `mtf_htf_count` |
| **Context** | `fear_greed`, `funding_rate`, `context_score` |
| **Risk** | `rr_ratio`, `sl_distance_pct`, `tp_distance_pct` |
| **Execution** | `session` (0–4), `candle_close_pct`, `is_reversal`, `entry_armed` |
| **Soft multipliers** | `htf_alignment_score`, `premium_discount_score`, `htf_bias_penalty`, `ob_state_multiplier`, `smt_divergence_score` |
| **Elliott Wave** | `wave_confidence`, `wave_direction`, `wave_conflict`, `wave_alternatives_count`, `wave_primary_label` |
| **S/R** | `nearest_support_pct`, `nearest_resistance_pct`, `is_4h_aligned` |

### to_vector() — для ML
Конвертация в плоский dict: categorical encoding (setup_type ±1, structure_trend ±1/0, regime 1/0.5/−0.5/−1, session 0–4), booleans → ints.

### to_reasoning() — для логов
Приоритет: MSS > Displacement > Sweep > OB > FVG > HTF > Session. Индикаторы (RSI, ADX, EMA) **НЕ** включаются — только для ML.

---

## 13. Фаза 3: Probability Engine

**Строки 1621–1659.**

```python
probability = probability_engine.predict(features, symbol=symbol, scenario_name=_scenario_name)
```

### Rules-Based Estimation (`_predict_rules`, строки 146–356)

**Base rate**: `scenario_memory` stats (если >= 10 закрытых сделок) → `historical_winrate` → 50.0

#### Режимно-адаптивная корректировка:

| Режим | Continuation | Reversal |
|-------|--------------|----------|
| expansion | +2.0 | −1.5 |
| compression (with BOS) | +1.5 | −1.0 |
| trend (BOS aligned) | +2.5 | −2.0 |
| range | −1.0 | +1.5 |
| high_vol | −1.0 | −1.0 |
| low_vol (with BOS) | +1.0 | — |

#### Reversal scoring:
- sweep → +3.0
- displacement → +3.0
- MSS → +4.0
- MSS quality > 70 → +2.0 / 50–70 → +1.0
- OB → +1.5
- FVG → +1.0
- entry_armed → +1.5

#### Continuation scoring:
- BOS → +3.0
- structure aligned → +2.0
- OB → +1.5
- FVG → +1.0
- entry_armed → +1.5

#### Common scoring:
- structure alignment → +2.0
- volume > 2.0x → +3.0, > 1.5x → +2.0, > 1.2x → +1.0
- MTF aligned → +2.0
- session quality → +1.0
- ATR sweet spot (1–3%) → +1.5 / extreme penalties
- context score adjustments

#### Soft multipliers (multiplicative):
- `htf_alignment_score`: factor = `0.5 + 0.5 × score` (range 0.5–1.0)
- `premium_discount_score`: factor = `0.5 + 0.5 × score` (range 0.5–1.0)
- `htf_bias_penalty`: direct multiplier (0.8 for mismatch)
- `ob_state_multiplier`: **if <= 0.0 → p_tp=0.0 immediately (hard gate)**

#### Elliott Wave:
- confidence >= min_confidence (0.4) и нет конфликта → `confidence × weight` к winrate
- Конфликт → `conflict_penalty` multiplier (0.85)

**Final**: winrate clamped [20.0, 85.0]

### ML-Based Estimation (`_predict_ml`, строки 358–445)

- OB mitigation hard gate (multiplier <= 0 → rejected)
- Features → vector → DataFrame
- **Expected return mode**: regressor → raw_return, isotonic calibration → p_tp
- **Legacy mode**: classifier `predict_proba` → p_tp, regressor → expected_rr
- HTF bias penalty и OB mitigation как multipliers
- p_tp clamped [0.05, 0.85]

### Output: `TradeProbability`
- `p_tp` (0.0–1.0)
- `expected_rr`
- `profit_factor`
- `confidence` (0.4 rules / 0.80 ML)
- `quality_label`: strong (>=0.65), moderate (>=0.50), weak (<0.50)

### Gate: min_p_tp

```python
_effective_min_p_tp = config.probability.min_p_tp  # default 0.30
if direction == 'sell':  _effective_min_p_tp = max(_effective_min_p_tp, config.probability.min_p_tp_short)  # 0.40
if setup_type == 'reversal':  _effective_min_p_tp = max(_effective_min_p_tp, config.probability.min_p_tp_reversal)  # 0.50
```

Если `probability.p_tp < _effective_min_p_tp` → `MIN_P_TP` (BLOCK)

---

## 14. Фаза 4: Risk Engine

**Строки 1667–1714.**

```python
risk_decision = risk_engine.evaluate(
    features=features, probability=probability, portfolio=portfolio_state,
    entry_price=entry_price, sl=sl, tp=tp,
    scenario_score=_thesis_score, scenario_stability=_thesis_stability,
    mss_quality=setup.mss_score, atr=ind.atr,
)
```

### Hard Gates (порядок严格执行):

| # | Проверка | Audit Code | Описание |
|---|----------|------------|----------|
| 1 | Portfolio limits | — | `active_count >= max_active_signals` или `total_risk_pct >= max_portfolio_risk_pct` |
| 2 | Data integrity | — | `entry_price <= 0`, `sl <= 0`, `tp <= 0`, `risk_dist <= 0` |
| 3 | Fee-adjusted R:R | — | Учитывает `exchange_fee_pct` (0.05%) + `slippage_pct` (0.05%) с обеих сторон |
| 4 | Min R:R | `RR_TOO_LOW` | `rr_ratio < min_rr_ratio` (default 2.0) |
| 5 | SL absolute min | `SL_TOO_TIGHT` | `sl_distance_pct < sl_absolute_min_pct` (default 0.25%) |
| 6 | Dynamic SL max | `SL_TOO_WIDE` | `dynamic_sl_max = max(sl_absolute_max_pct, atr_pct × 2.2)`, clamped to 8% |
| 7 | SL min ATR multiplier | `SL_ATR_CONFLICT` | `sl_distance_pct < atr_pct × sl_min_atr_multiplier` (2.0). A1 fix: relaxes floor если ATR-min > dynamic max |

### Position Sizing:

#### Fixed mode (default):
```python
risk_pct = base_risk_pct  # 1.0%
```

#### Kelly mode (`RISK_MODE=kelly`):
```python
p = probability.p_tp
q = 1 - p
b = rr_ratio
kelly = (p * b - q) / b
kelly = max(0.0, min(kelly, 0.20))  # half-Kelly cap at 20%
kelly *= probability.confidence
risk_pct = min(kelly * 100, base_risk_pct)
```

### Мультипликативные корректировки (после Kelly/fixed):

| Фактор | Формула | Range |
|--------|---------|-------|
| Scenario score | `[0, 100]` → `[0.6, 1.2]` | Масштабирование |
| Scenario stability | `[0, 1]` → `[0.7, 1.15]` | Масштабирование |
| Volatility | `atr_pct > 4.0` → 0.5x, `> 2.5` → 0.75x | Снижение |
| MSS quality | `[0, 100]` → `[0.8, 1.1]` | Бонус/штраф |
| SL distance quality | `< 1.0%` → 1.1x, `> 3.0%` → 0.8x | Бонус/штраф |

**Final clamp**: `max(min_risk_pct (0.1%), min(risk_pct, max_risk_pct (2.0%)))`

### Output: `RiskDecision`
- `should_trade: bool`
- `risk_pct`, `rr_ratio`, `sl_price`, `tp_price`
- `kelly_fraction`, `volatility_adjustment`, multipliers

---

## 15. Фаза 4.5: Entry Trigger

**Строки 1716–1768.**

```python
entry_trigger = EntryTrigger()
trigger_result = entry_trigger.check(
    hypothesis=_entry_target, current_price=entry_price, bid=_bid, ask=_ask,
)
if not trigger_result.triggered:
    return None  # ENTRY_TRIGGER_NO
```

Проверяет, выполняются ли условия входа (из гипотезы или SimpleEntryTarget) при текущей цене.

---

## 16. Фаза 5–6: Build SignalResult + Dedup

### Phase 5: Build SignalResult (строки 1770–1815)

Сборка `SignalResult` dataclass со всеми данными: symbol, timeframe, direction, entry, SL, TP, reasons, score, regime, HTF data, wave confidence, etc.

### Phase 6: Dedup (строки 1817–1896)

**Последовательная проверка:**

```python
dedup_cooldown_minutes = get_cooldown_minutes(
    timeframe, config.signal_cooldown_minutes, config.signal_cooldown_tf_multiplier
)
```

**Default**: 45 мин base × 2.0 TF multiplier. Для 4h: `max(45, 240*2) = 480 мин`.

**ob_aware режим (default):**
- Сравнивает OB midpoints последнего сигнала с текущим
- **Разный OB** → пропуск cooldown (PASS) — новый OB = новый сигнал
- **Тот же OB** → reduced cooldown (1/3 от полного)

**strict режим:**
- Полный cooldown блокирует

**Cross-direction cooldown**: half-cooldown блокирует быстрые развороты.

---

## 17. Фаза 7: Execution Filters

**Строки 1898–2051.** Последовательные.

| # | Проверка | Audit Code | Описание |
|---|----------|------------|----------|
| 1 | Spread | `SPREAD_TOO_WIDE` | `(ask - bid) / bid × 100 > max_spread_percent` (default 0.15%) |
| 2 | Depth | `DEPTH_TOO_LOW` | Order book depth за 0.5% от mid < `min_depth_0_5_percent` (default $10,000) |
| 3 | Correlated entry | `CORRELATION_BLOCKED` | Если correlated символ уже имеет открытую позицию → BLOCK |

---

## 18. Фаза 8: Save + Notify

**Строки 2059–2080.**

1. `db.save_signal(...)` — сохранение сигнала в БД
2. `trace.save(db, signal_id)` — сохранение DecisionTrace
3. `_audit_log(..., "OK")` — аудит пройден
4. `db.create_outcome(signal_id, risk_pct)` — создание отслеживания исхода
5. `daily_limits.record_trade_opened(risk_pct)` — обновление дневного лимита
6. `_set_cooldown(symbol, timeframe)` — установка cooldown
7. `notify_callback(result, context_verdict)` — отправка в Telegram
8. `_current_funnel.passed += 1` — инкремент счётчика

---

## 19. Полная карта фильтров

### Последовательные (любой блокирует = return None)

```
[0.1] Cooldown
  ↓
[0.2] Portfolio: max active signals
  ↓
[0.2] Portfolio: max risk %
  ↓
[0.2b] Daily limits (5 conditions)
  ↓
[0.2c] Position limits (total)
  ↓
[0.3] OHLCV + Indicators fetch
  ↓
[0.4] Volatility filter (ATR%)
  ↓
[1.0] Pattern Engine: ICT Setup detected
  ↓
[1.4] Setup-Type Gates (sweep/displacement/MSS/BOS)
  ↓
[1.4] Confirmation Score >= 2
  ↓
[1.41] Breakout Quality (if hard_gate=True)
  ↓
[1.42] OB Retest + Mitigation (if require_ob_retest=True)
  ↓
[1.43] Session Filter (if session_hard_gate=True)
  ↓
[1.45] HTF Bias V2 (if htf_bias_v2=True)
  ↓
[1.5] Trade Plan: SL/TP calculated
  ↓
[1.7] LTF Confirmation (if multi_tf mode)
  ↓
[3.0] Probability Engine: min_p_tp
  ↓
[4.0] Risk Engine: all hard gates (R:R, SL limits)
  ↓
[4.5] Entry Trigger
  ↓
[6.0] Dedup (cooldown)
  ↓
[7.0] Execution: Spread
  ↓
[7.0] Execution: Depth
  ↓
[7.0] Execution: Correlated entry
  ↓
[8.0] Save + Notify
```

### Параллельные (НЕ блокируют, влияют на scoring)

```
[Shadow] Market Phase Detection     ─┐
[Shadow] Market Thesis Engine        ─┼─ записывают данные, не возвращают None
[Shadow] Scenario Engine             ─┤
[Shadow] Hypothesis + Decision       ─┘

[Soft] SMT Divergence               → feature для Feature Builder
[Soft] HTF Alignment Score          → multiplier для Probability Engine
[Soft] Premium/Discount Score       → multiplier для Probability Engine
[Soft] OB State Multiplier          → multiplier (0.0 = hard gate в Probability Engine)
[Soft] Elliott Wave                 → bonus/penalty для winrate
[Soft] Context Score (FNG, etc.)    → feature для Feature Builder
[Soft] MTF Alignment (soft score)   → feature
```

---

## 20. Веса параметров и скоринг

### Feature Builder: Веса признаков (для ML input)

Признаки не имеют явных весов в Feature Builder — все ~50 features передаются как есть. Веса определяются ML-моделью (XGBoost/RandomForest) или rules-based fallback.

### Rules-Based Probability: Веса (суммируются к winrate)

| Категория | Признак | Вес (базовый winrate = 50%) |
|-----------|---------|----------------------------|
| **Reversal** | sweep | +3.0 |
| | displacement | +3.0 |
| | MSS | +4.0 |
| | MSS quality > 70 | +2.0 |
| | MSS quality 50–70 | +1.0 |
| | OB | +1.5 |
| | FVG | +1.0 |
| | entry_armed | +1.5 |
| **Continuation** | BOS | +3.0 |
| | structure aligned | +2.0 |
| | OB | +1.5 |
| | FVG | +1.0 |
| | entry_armed | +1.5 |
| **Common** | structure alignment | +2.0 |
| | volume > 2.0x | +3.0 |
| | volume > 1.5x | +2.0 |
| | volume > 1.2x | +1.0 |
| | MTF aligned | +2.0 |
| | session quality | +1.0 |
| | ATR sweet spot (1–3%) | +1.5 |
| **Regime** | expansion (cont) | +2.0 |
| | expansion (rev) | −1.5 |
| | trend (cont, aligned) | +2.5 |
| | trend (rev) | −2.0 |
| | range (cont) | −1.0 |
| | range (rev) | +1.5 |
| | high_vol | −1.0 |

### Multipliers (multiplicative, после базового winrate):

| Мультипликатор | Формула | Range |
|----------------|---------|-------|
| HTF alignment | `0.5 + 0.5 × score` | 0.5–1.0 |
| Premium/discount | `0.5 + 0.5 × score` | 0.5–1.0 |
| HTF bias mismatch | 0.8 | 0.8 |
| OB state (BROKEN) | 0.0 → p_tp=0 | 0.0 |
| Elliott Wave conflict | 0.85 | 0.85 |
| Elliott Wave confidence | `confidence × weight` | +bonus |

### Risk Engine: Веса мультипликаторов

| Фактор | Формула | Range |
|--------|---------|-------|
| Scenario score | `[0, 100]` → `[0.6, 1.2]` | 0.6–1.2 |
| Scenario stability | `[0, 1]` → `[0.7, 1.15]` | 0.7–1.15 |
| Volatility (high) | 0.5 | 0.5 |
| Volatility (medium-high) | 0.75 | 0.75 |
| MSS quality | `[0, 100]` → `[0.8, 1.1]` | 0.8–1.1 |
| SL distance < 1% | 1.1 | 1.1 |
| SL distance > 3% | 0.8 | 0.8 |

### Breakout Quality: Скоринг (0–100)

| Фактор | Баллы |
|--------|-------|
| body >= 0.5 за boundary | +40 |
| retention >= 2 | +20 |
| displacement_atr >= 1.0 | +15 |
| volume_ratio >= 1.8 | +15 |
| OI confirms direction | +15 |
| body < 0.5 | −25 |
| retention < 2 | −15 |

---

## 21. Система аудита и логирования

### DecisionTraceBuilder (`storage/trace.py`)

Один `DecisionTrace` на каждый проход пайплана. Содержит:
- `gate_path` — упорядоченный JSON массив pass/fail для каждого gate
- `features_snapshot` — 25+ полей feature snapshot
- `config_snapshot` — JSON конфигурации на момент анализа
- `execution_snapshot` — микроструктура (entry candle, spread, ATR, tick size, latency)
- `hypothesis_snapshot` — данные гипотезы

### Signal Audit Log (`storage/audit_reasons.py`)

50+ структурированных reason codes. Каждый BLOCKED/PASS записывает:
- symbol, timeframe, timestamp
- stage (pipeline phase)
- reason_code (из audit_reasons.py)
- passed (bool)
- setup_type, direction
- features_snapshot (JSON)

### FunnelCounter (`scheduler/scanner.py`)

Per-scan-cycle статистика: counts entered/passed/blocked-by-gate. Логируется в конце `run_scan_cycle`.

---

## 22. Cooldown и Dedup логика

### Два механизма:

#### A. Early Cooldown Gate (Phase 0.1)
- `ob_aware` режим (default): **всегда возвращает False** — cooldown отлож Phase 6
- `strict` режим: проверяет `db.get_cooldown()` против `max(base_minutes, tf_minutes × multiplier)`

#### B. Dedup Cooldown (Phase 6)
- Запускается **после** полной оценки сигнала
- Сравнивает с последним сигналом для того же symbol+TF из БД
- **Same direction + within cooldown**:
  - `ob_aware` (default): сравнение OB midpoints. Разный OB → bypass. Тот же OB → reduced cooldown (1/3)
  - `strict`: полный cooldown блокирует
- **Cross-direction + within cooldown**: half-cooldown блокирует быстрые развороты

---

## 23. Post-signal: Управление позицией

### Outcome Tracker (`scheduler/outcome_tracker.py`, 700 строк)

Фоновый цикл (каждые 300 сек) проверяет открытые исходы:

1. Проверка текущей цены через ticker + recent candle high/low
2. **Position Management** (`risk/position_manager.py`):

| Событие | Триггер | Действие |
|---------|---------|----------|
| Breakeven | 1.5R | SL → entry + fee_buffer |
| Partial Close TP1 | 2.0R | Закрытие 25% |
| Partial Close TP2 | 3.0R | Закрытие 35%, активация trailing |
| Partial Close TP3 | 4.0R | Закрытие оставшихся 40% |
| Trailing Stop | После TP2 | ATR(14) × 1.5, не ниже breakeven |
| Sweep Breach | Close за sweep level | Early exit |
| Time Stop | >= 100 мин (опционально) | Закрытие |
| Flip Bias | BOS против позиции | Закрытие |

3. Расчёт PnL после costs (commission обе стороны, slippage обе стороны, funding для perpetuals)
4. Расчёт MFE/MAE excursion
5. Уведомление в Telegram (HIT_TP/HIT_SL/TIME_STOP/FLIP_BIAS/SWEEP_BREACH)
6. Обновление БД

---

## 24. Контекстные источники данных

### ContextFetcher (`context/fetcher.py`, 400 строк)

| # | Источник | API | Кэш | Данные |
|---|----------|-----|-----|--------|
| 1 | Fear & Greed | Alternative.me | 3600s | Индекс 0–100 + label |
| 2 | CoinGecko | CoinGecko API | — | price_change_24h/7d, volume, market_cap_rank |
| 3 | Trending | CoinGecko `/search/trending` | 1800s | Top 7 trending symbols |
| 4 | Funding Rate | ccxt unified | — | Ставка финансирования |
| 5 | Open Interest | ccxt unified | — | OI + delta % (с warm-up) |
| 6 | Long/Short Ratio | Binance fapi | — | Global L/S Account Ratio (1h) |
| 7 | CryptoPanic | CryptoPanic API | — | News sentiment score |
| 8 | RSS News | CoinDesk + CoinGecko | 300s | Keyword-based sentiment |

### Indicators (`indicators/engine.py`, 240 строк)

| Индикатор | pandas-ta | Колонки | Default |
|-----------|-----------|---------|---------|
| EMA (3) | `ema` | ema_fast, ema_slow, ema_trend | 8, 21, 55 |
| RSI | `rsi` | rsi | period=10 |
| MACD | `macd` | macd, macd_signal, macd_hist | 8, 21, 5 |
| ADX + DMI | `adx` | adx, dmi_plus, dmi_minus | period=14 |
| ATR | `atr` | atr | period=14 |
| Supertrend | `supertrend` | supertrend, supertrend_dir | period=10, multiplier=2.5 |
| Volume SMA | `sma` | volume_sma | period=20 |

### Market Structure (`market_structure/structure.py`, 788 строк)

- Swing Points (HH/HL/LH/LL)
- BOS (Break of Structure)
- CHoCH (Change of Character)
- MSS (Market Structure Shift) = strong CHoCH с sweep + displacement + reclaim
- Trend classification

---

## 25. Конфигурация

### Ключевые параметры (config/settings.py, 1071 строк)

```env
# Trading
SYMBOLS=BTC/USDT,ETH/USDT
PRIMARY_TIMEFRAMES=1h,4h
EMA_FAST=8, EMA_SLOW=21, EMA_TREND=55
RSI_PERIOD=10, RSI_OVERBOUGHT=72, RSI_OVERSOLD=28
MACD_FAST=8, MACD_SLOW=21, MACD_SIGNAL=5
ADX_PERIOD=14, ADX_MIN=26
ATR_PERIOD=14
VOLATILITY_MIN_ATR_PERCENT=0.3
VOLATILITY_MAX_ATR_PERCENT=5.0

# Risk
RISK_MODE=fixed  # or kelly
BASE_RISK_PCT=1.0
MIN_RR_RATIO=2.0
SL_ABSOLUTE_MIN_PCT=0.25
SL_ABSOLUTE_MAX_PCT=5.0
MAX_ACTIVE_SIGNALS=3
MAX_PORTFOLIO_RISK_PCT=3.7

# Filters
HTF_BIAS_V2=true
REVERSAL_REQUIRE_DISPLACEMENT=true
REQUIRE_OB_RETEST=true
BREAKOUT_QUALITY_ENABLED=true
BREAKOUT_QUALITY_HARD_GATE=false
SESSION_HARD_GATE=false
REQUIRE_ENTRY_ZONE=false
PREMIUM_DISCOUNT=false

# Cooldown
SIGNAL_COOLDOWN_MINUTES=45
SIGNAL_COOLDOWN_TF_MULTIPLIER=2.0
COOLDOWN_MODE=ob_aware

# Execution
MAX_SPREAD_PERCENT=0.15
MIN_DEPTH_0_5_PERCENT=10000
EXCHANGE_FEE_PCT=0.05
SLIPPAGE_PCT=0.05

# Probability
MIN_P_TP=0.30
MIN_P_TP_SHORT=0.40
MIN_P_TP_REVERSAL=0.50
FALLBACK_WINRATE=50.0
```

---

## 26. Аудит-коды

### Phase 0: Hard Gates
```
COOLDOWN_ACTIVE, PORTFOLIO_MAX_ACTIVE, PORTFOLIO_MAX_RISK,
DAILY_LIMIT_HIT, POSITION_LIMIT_HIT, DATA_INTEGRITY_FAIL,
VOLATILITY_TOO_LOW, VOLATILITY_TOO_HIGH
```

### Phase 1: Pattern Engine
```
PATTERN_NO_SETUP, SWEEP_NONE, SWEEP_FALSE_FILTERED,
DISPLACEMENT_MISSING, MSS_NONE, MSS_DIRECTION_UNCLEAR,
CONTINUATION_RANGING, CONTINUATION_NO_BOS,
CONTINUATION_BOS_NOT_BREAKING, CONTINUATION_BOS_VS_TREND
```

### Phase 1.4: Setup-Type
```
ENTRY_ZONE_BLOCKED
```

### Phase 1.41: Breakout Quality
```
BREAKOUT_FAKE
```

### Phase 1.42: Confirmation + OB
```
CONFIRMATION_LOW, OB_RETEST_FAILED, OB_TOO_OLD,
OB_BROKEN, OB_MITIGATED, OB_TOO_FAR,
OB_NOT_RETESTED, OB_NO_CONFIRMATION
```

### Phase 1.43: Session
```
SESSION_BLOCKED
```

### Phase 1.45: HTF Bias
```
HTF_SHORT_IN_BULLISH, HTF_LONG_IN_BEARISH,
HTF_CONTINUATION_MISMATCH, HTF_REVERSAL_MISMATCH
```

### Phase 1.5: Trade Plan
```
SL_TP_FAILED
```

### Phase 1.7: LTF
```
LTF_NO_CONFIRMATION, LTF_DATA_UNAVAILABLE
```

### Phase 3: Probability
```
MIN_P_TP
```

### Phase 4: Risk
```
RR_TOO_LOW, SL_TOO_TIGHT, SL_TOO_WIDE,
SL_ATR_CONFLICT, SL_ATR_MIN_RELAXED, EV_GATE_FAILED
```

### Phase 4.5: Entry Trigger
```
ENTRY_TRIGGER_NO
```

### Phase 6: Dedup
```
DEDUP_OB, DEDUP_SAME_DIR, DEDUP_CROSS_DIR
```

### Phase 7: Execution
```
SPREAD_TOO_WIDE, DEPTH_TOO_LOW, CORRELATION_BLOCKED
```

### Pass
```
OK
```

---

## 27. Граф потока данных

```
scan_symbol_v2(symbol, timeframe)
│
├─ Phase 0: Hard Gates
│  ├─ [0.1] Cooldown ──────────────────────────────────────── BLOCKED?
│  ├─ [0.2] Portfolio Risk (max active, max risk %) ──────── BLOCKED?
│  ├─ [0.2b] Daily Limits (5 conditions) ─────────────────── BLOCKED?
│  ├─ [0.2c] Position Limits (total) ─────────────────────── BLOCKED?
│  ├─ [0.3] Fetch OHLCV + Indicators ─────────────────────── BLOCKED?
│  └─ [0.4] Volatility (ATR% range) ──────────────────────── BLOCKED?
│
├─ Phase 1: Pattern Engine
│  ├─ detect_sweeps() ──────────────┐
│  ├─ detect_order_blocks() ────────┤
│  ├─ detect_fvg() ─────────────────┼─→ find_ob_for_sweep() (backward scan)
│  ├─ analyze_last_candle() ────────┤
│  ├─ analyze_structure() ──────────┘
│  └─ pattern_engine.detect() ───→ ICTSetup ──────────────── BLOCKED?
│
├─ Phase 1.4: Setup-Type Gates
│  ├─ Reversal: sweep + displacement + MSS ───────────────── BLOCKED?
│  ├─ Continuation: trend + BOS ──────────────────────────── BLOCKED?
│  ├─ Entry Zone (optional) ──────────────────────────────── BLOCKED?
│  └─ Confirmation Score >= 2 ────────────────────────────── BLOCKED?
│
├─ Phase 1.41: Breakout Quality (if hard_gate) ───────────── BLOCKED?
├─ Phase 1.42: OB Retest + Mitigation (if configured) ────── BLOCKED?
├─ Phase 1.43: Session Filter (if hard_gate) ─────────────── BLOCKED?
├─ Phase 1.44: SMT Divergence ─────────────── [soft, no block]
├─ Phase 1.45: HTF Bias V2 ──────────────────────────────── BLOCKED?
│
├─ Phase 1.5: HTF POI Detection
├─ Phase 1.5: Build Trade Plan (SL/TP) ──────────────────── BLOCKED?
├─ Phase 1.7: LTF Confirmation (if multi_tf) ─────────────── BLOCKED?
│
├─ Shadow: Market Phase + Thesis + Hypothesis ── [soft, no block]
│
├─ Phase 2: Feature Builder ─────── SetupFeatures (~50 features)
│
├─ Shadow: Scenario Engine ───────── [soft, no block]
│
├─ Phase 3: Probability Engine ──── P(TP), RR, PF
│  └─ min_p_tp gate ──────────────────────────────────────── BLOCKED?
│
├─ Phase 4: Risk Engine ──────────── position sizing
│  ├─ R:R fee-adjusted ──────────────────────────────────── BLOCKED?
│  ├─ SL absolute min/max ────────────────────────────────── BLOCKED?
│  ├─ SL ATR multiplier ─────────────────────────────────── BLOCKED?
│  └─ Kelly/Fixed sizing + multipliers ───────────────────── BLOCKED?
│
├─ Phase 4.5: Entry Trigger ──────────────────────────────── BLOCKED?
│
├─ Phase 5: Build SignalResult
│
├─ Phase 6: Dedup (OB-aware / strict) ────────────────────── BLOCKED?
│
├─ Phase 7: Execution Filters
│  ├─ Spread ─────────────────────────────────────────────── BLOCKED?
│  ├─ Depth ──────────────────────────────────────────────── BLOCKED?
│  └─ Correlated entry ───────────────────────────────────── BLOCKED?
│
└─ Phase 8: Save + Notify
   ├─ db.save_signal()
   ├─ trace.save()
   ├─ _audit_log(OK)
   ├─ db.create_outcome()
   ├─ daily_limits.record_trade_opened()
   ├─ _set_cooldown()
   └─ notify_callback() → Telegram
```

---

## 28. Известные пробелы и рекомендации

### Потенциальные проблемы

1. **News Filter** (`risk/news_filter.py`): Заглушка — возвращает пустой список. Нет интеграции с реальным API новостей. Рекомендация: интегрировать CryptoPanic или аналог.

2. **Long/Short Ratio** (`context/fetcher.py`): Возвращает `None` для BingX (deprecated endpoint). Только Binance. Рекомендация: альтернативный источник для BingX.

3. **Shadow Mode Engines**: Market Thesis Engine (2885 строк) и Scenario Engine (410 строк) — сложные, но не влияют на сигналы. Их данные используются только для ML-обучения и аналитики. Рекомендация: проверить, что Scenario Memory确实 накапливает данные для ML.

4. **ML-модель**: Загружается из pickle. Если модель не найдена → rules-based fallback. Количество samples для ML: >= 100. Рекомендация: мониторить количество outcome samples.

5. **Elliott Wave**: Модуль включён (`config.wave.enabled=true`), но `wave_confidence` по умолчанию может быть ниже `min_confidence` (0.4), что делает его фактически неактивным.

6. **Premium/Discount**: Выключен A/B тестом (PF 1.28→0.91). Рекомендация: включить после 500+ live trades с v2.

7. **Confirmation Score**: Минимум 2 (BOS=2 + что-то ещё). Это означает, что **любой setup с BOS проходит** (2 ≥ 2). Проверить, не нужно ли увеличить minimum.

8. **Position Limits**: `max_positions_total=5`, но `max_active_signals=3`. Разница не объяснена — видимо, positions включает все типы (OPEN/EXPIRED), а active только текущие.

9. **Cooldown ob_aware**: В `ob_aware` режиме early cooldown gate **всегда пропускает**. Если у символа нет OB (setup без OB), то cooldown фактически не работает. Рекомендация: fallback на strict для setups без OB.

10. **Kelly Criterion**: Caps at `base_risk_pct` (1.0%). Фактически Kelly может только **уменьшить** риск, но не увеличить. Рекомендация: проверить, работает ли это как задумано.

### Архитектурные рекомендации для другой модели ИИ

- **Все фильтры — последовательные**. Порядок важен: дешёвые проверки → дорогие. Не менять порядок без анализа impact.
- **Shadow engines** — не блокируют, но их данные критичны для ML. При модификации пайплана проверять, что features snapshot всё ещё корректен.
- **Audit logging** — покрывает все 35+ точек блокировки. При добавлении нового gate ОБЯЗАТЕЛЬНО добавить reason_code в `storage/audit_reasons.py`.
- **Config**: Все параметры через env vars. Добавляя параметр — добавить в `config/settings.py` и в `.env.example`.
- **Testing**: `pytest.ini` имеет `asyncio_mode = auto`. Все async тесты используют `@pytest.mark.asyncio`. sys.path.insert в conftest.py.
