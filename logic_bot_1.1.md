# ЛОГИКА БОТА v1.1.1 — Полная карта торгового сигнала

> **Версия**: v1.1.1 | **Стратегия**: v2.5.0 | **Стек**: Python 3.11, ccxt, pandas-ta, SQLAlchemy async, python-telegram-bot 20.x
> **База**: SQLite (aiosqlite) | **Расписание**: APScheduler (каждые 15 мин)
> **Вход**: `main.py` → `TaskScheduler` → `run_scan_cycle()` → `scan_symbol_v2()`
> **Аудит**: Проверено по исходному коду. ~30 gate checks, 46 reason codes, ~53 features.
> **Исправления по аудиту Astra (2026-09-07)**: A06, A08, A09, A10, A12, A13, A15, A22.

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
9. [Фаза 1.5: HTF POI Detection + Trade Plan (SL/TP)](#9-фаза-15-trade-plan)
10. [Фаза 1.7: LTF Confirmation](#10-фаза-17-ltf-confirmation)
11. [Analytical Overlays (влияют на sizing)](#11-analytical-overlays)
12. [Фаза 2: Feature Builder](#12-фаза-2-feature-builder)
13. [Фаза 3: Probability Engine](#13-фаза-3-probability-engine)
14. [Фаза 4: Risk Engine](#14-фаза-4-risk-engine)
15. [Фаза 4.5: Entry Trigger](#15-фаза-45-entry-trigger)
16. [Фаза 5–6: Build SignalResult + Dedup](#16-фаза-56-build-signalsresult--dedup)
17. [Фаза 7: Execution Filters + TOCTOU Recheck](#17-фаза-7-execution-filters)
18. [Фаза 8: Save + Notify](#18-фаза-8-save--notify)
19. [Полная карта фильтров (последовательных и параллельных)](#19-полная-карта-фильтров)
20. [Веса параметров и скоринг](#20-веса-параметров-и-скоринг)
21. [Система аудита и логирования](#21-система-аудита-и-логирования)
22. [Cooldown и Dedup логика](#22-cooldown-и-dedup-логика)
23. [Post-signal: Управление позицией](#23-post-signal-управление-позицией)
24. [Контекстные источники данных](#24-контекстные-источники-данных)
25. [Конфигурация (полный реестр параметров)](#25-конфигурация)
26. [Аудит-коды (reason codes) — полный реестр](#26-аудит-коды)
27. [Граф потока данных](#27-граф-потока-данных)
28. [Известные пробелы и рекомендации](#28-известные-пробелы)
29. [Changelog v1.1](#29-changelog)

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
| Feature Builder | `strategy/feature_builder.py` | 503 | ~53 признаков в плоский вектор |
| Probability Engine | `strategy/probability_engine.py` | 570 | P(TP), expected RR, profit factor |
| Risk Engine | `risk/engine.py` | 315 | Hard gates + Kelly sizing |
| Trade Engine | `strategy/trade_engine.py` | 376 | SL/TP на основе ликвидности |
| Scanner | `scheduler/scanner.py` | 2161 | Весь пайплайн scan_symbol_v2 |
| Config | `config/settings.py` | 1071 | Все параметры через .env |
| Database | `storage/database.py` | 1430 | SQLAlchemy async, 10+ таблиц |
| Audit Reasons | `storage/audit_reasons.py` | — | 46 reason codes |
| Trace Builder | `storage/trace.py` | — | DecisionTrace, gate_path, features_snapshot |
| Context Fetcher | `context/fetcher.py` | 400 | 8 источников контекста |
| Indicators | `indicators/engine.py` | 240 | pandas-ta расчёты |
| Market Structure | `market_structure/structure.py` | 788 | Swing, BOS, CHoCH, MSS |
| HTF Bias V2 | `market_structure/htf_bias_v2.py` | 160 | W1→D1→H4→H1 voting |
| Breakout Quality | `liquidity/breakout_quality.py` | 202 | AMD stop-hunt vs real breakout |
| SMT Divergence | `derivatives/smt_divergence.py` | — | BTC vs alts divergence |
| Outcome Tracker | `scheduler/outcome_tracker.py` | 700 | SL/TP мониторинг, position management |
| Position Manager | `risk/position_manager.py` | — | Partial close, trailing, breakeven |
| Daily Limits | `risk/daily_limits.py` | — | 5 дневных условий |
| Circuit Breaker | `scheduler/circuit_breaker.py` | — | 3 SL → пауза 30 мин |

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

**Circuit Breaker** (`scheduler/circuit_breaker.py`):
- 3 последовательных SL → пауза 30 мин.
- `check_recent_losses()` вызывается в начале каждого scan cycle.
- Если `is_circuit_breaker_active()` → scan skipped.
- Сбрасывается после паузы.

**Scan Lock** (`asyncio.Lock()`):
- Предотвращает параллельные scan cycles.
- Если уже идёт → skip trigger.

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

**Файл**: `scheduler/scanner.py`, строки 280–2161

Это **единственный** активный пайплайн. Старый `scan_symbol` удалён.

**Общая структура (порядок严格执行):**

```
Phase 0:    Hard Gates (капитальная защита)       ← последовательные, любой блокирует
Phase 1:    Pattern Engine (ICT Setup)             ← последовательные
Phase 1.4:  Setup-Type Gates                       ← последовательные
Phase 1.41-1.45: Доп. фильтры                     ← последовательные (некоторые опциональные)
Phase 1.5:  Trade Plan (SL/TP)                     ← последовательные
Phase 1.7:  LTF Confirmation                       ← опциональный
Shadow:     Market Phase + Thesis + Hypothesis      ← параллельные, НЕ блокируют
Phase 2:    Feature Builder                         ← вычисление (не фильтр)
Phase 3:    Probability Engine                      ← последовательный
Phase 4:    Risk Engine                             ← последовательный
Phase 4.5:  Entry Trigger                           ← последовательный
Phase 5:    Build SignalResult                      ← сборка
Phase 6:    Dedup                                   ← последовательный
Phase 7:    Execution Filters + TOCTOU Recheck      ← последовательные
Phase 8:    Save + Notify                           ← финализация
```

**Общее количество gate checks: ~30.**

---

## 5. Фаза 0: Hard Gates (капитальная защита)

**Строки 296–402.** Последовательная проверка. **Любой** сбой = мгновенный `return None`.

| # | Проверка | Audit Code | Описание |
|---|----------|------------|----------|
| 0.1 | Cooldown | `COOLDOWN_ACTIVE` | Если в `ob_aware` режиме — ПРОПУСКАЕТ (отложено до Phase 6). В `strict` — полная проверка |
| 0.2 | Portfolio: max active signals | `PORTFOLIO_MAX_ACTIVE` | `active_count >= config.max_active_signals` (default 3) |
| 0.2 | Portfolio: max risk % | `PORTFOLIO_MAX_RISK` | `portfolio_risk >= config.max_portfolio_risk_pct` (default 3.7%) |
| 0.2b | Daily limits (5 условий) | `DAILY_LIMIT_HIT` | См. таблицу ниже |
| 0.2c | Position limits | `POSITION_LIMIT_HIT` | `_total_positions >= config.risk.max_positions_total` (default 5) |
| 0.3 | Fetch OHLCV + Indicators | `DATA_INTEGRITY_FAIL` | `_get_indicators()` — загрузка свечей и расчёт индикаторов. Если нет данных → BLOCK |
| 0.4 | Volatility filter | `VOLATILITY_TOO_LOW/HIGH` | `atr_pct < vol_min (0.3%)` или `atr_pct > vol_max (5.0%)` |

### 5.1 Дневные лимиты (Phase 0.2b) — 5 условий

| # | Условие | Параметр | Default |
|---|---------|----------|---------|
| 1 | Remaining daily risk ≤ 0 | `max_risk_per_day_pct` | 6.0% |
| 2 | Daily trades ≥ max | `max_trades_per_day` | 5 |
| 3 | Consecutive losses ≥ max | `max_consecutive_losses` | 3 |
| 4 | Daily PnL ≤ −max drawdown | `max_drawdown_daily_pct` | 10.0% |
| 5 | Daily PnL ≥ profit target | `profit_target_daily_pct` | 10.0% |

**State Management** (`risk/daily_limits.py`):
- Сброс в полночь UTC
- `daily_risk_used_pct` накапливается с каждой сделкой, освобождается при закрытии
- `try_open_trade()`: атомарная проверка + резерв (защита от TOCTOU)
- `record_trade_closed()`: обновляет daily_pnl, освобождает risk budget, сбрасывает/инкрементирует consecutive_losses

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
- **Temporal binding**: Только OBs/FVGs, сформированные **после** sweep (`ob.timestamp >= sweep_timestamp`)

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

**Два pipeline:**

#### REVERSAL (приоритет):
```
Sweep → Displacement → MSS
```
1. **Sweep** обязателен. Фильтр false sweeps (`passes_false_sweep_filters`). Выбирается самый сильный sweep (highest strength, most recent if tied).
2. **Displacement** — informational only (не gate). Чтение из `candle_quality`. Комментарий в коде: "MSS classification already measures displacement".
3. **MSS** обязателен. Должен быть `structure.last_mss` (strong CHoCH). Направление = тип MSS.
4. **Bars between sweep and MSS** вычисляется.

#### CONTINUATION (fallback):
```
Trend → BOS
```
1. **Trend** обязателен (не ranging).
2. **BOS** обязателен. Должен быть `structure.last_bos`.
3. **BOS swing validation** (§6.3): BOS level must break the last swing in opposite direction. Bullish BOS > last swing high; bearish BOS < last swing low.
4. **Alignment** — направление BOS совпадает с трендом (buy+bullish or sell+bearish).

#### Entry Zone Detection (`_detect_entry_zones`):
- Only OBs/FVGs formed AFTER sweep (`ob.timestamp >= sweep_timestamp`)
- First valid OB matching direction → `setup.has_ob`
- First valid FVG matching direction → `setup.has_fvg`

**Output**: `ICTSetup` dataclass:
- `detected: bool` — найден ли setup
- `direction: "buy" / "sell"`
- `setup_type: "reversal" / "continuation"`
- Компоненты: `has_sweep`, `has_displacement`, `has_mss`, `has_bos`, `has_ob`, `has_fvg`
- `mss_score` (0–100), `mss_causality` (0–1, exponential decay)
- `confirmation_score` — взвешенный: BOS=2, FVG=1, OB=1
- `entry_armed` — цена рядом с OB/FVG midpoint (soft, через `ob_proximity_pct` = 2.0%)

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

**Примечание**: Минимум 2 означает, что **любой setup с BOS проходит** (2 ≥ 2). Это потенциальная проблема —详见 раздел 28.

---

## 8. Фаза 1.41–1.45: Дополнительные фильтры

### 1.41 Breakout Quality (строки 639–700)

**Модуль**: `liquidity/breakout_quality.py` (202 строки)

Определяет, реальный ли breakout или AMD stop-hunt (fake).

**Алгоритм:**
1. Находит settled range boundary (swing high/low за lookback свечей, исключая последние 2)
2. Проверяет: CLOSE за boundary → real, только WICK → fake

**Скоринг 0–100:**

| Фактор | Баллы | Триггер |
|--------|-------|---------|
| body >= 0.5 за boundary | +40 | `body_pct >= 0.5` |
| retention >= 2 | +20 | `retention >= 2` bars |
| displacement_atr >= 1.0 | +15 | `disp_atr >= 1.0` |
| volume_ratio >= 1.8 | +15 | `volume_ratio >= min_vol(1.8)` |
| OI confirms direction | +15 | OI delta aligned |
| body < 0.5 (mostly wick) | −25 | `body_pct < 0.5` |
| retention < 2 | −15 | `retention < 2` |

**Вердикт:**
- `score >= 55` → "real"
- `body_pct >= 0.5` и `score >= 25` → "real"
- `body_pct >= 0.5` и `score < 25` → "ambiguous"
- `score < 40` → "ambiguous"
- `score >= 40` (с body < 0.5) → "real"

**Gate**: Если `config.breakout_quality_hard_gate=True` и verdict="fake" → `BREAKOUT_FAKE`. По умолчанию **OFF** (shadow log only).

### 1.42 OB Retest + Mitigation (строки 702–797)

**Если `config.require_ob_retest=True`** (default: True):

1. **OB age**: если OB старше `max_age` и не retested → mitigated → BLOCK
2. **OB state** (`get_ob_state()`): BROKEN / MITIGATED / VALID
   - BROKEN → BLOCK
   - MITIGATED → BLOCK
3. **Price returned to OB zone**: `ob.low <= last_close <= ob.high` или `ob.retested`
4. **Confirmation candle**: Проверка последней свечи:
   - **Engulfing**: body > prev body + close above/below prev open
   - **Pin-bar**: wick_ratio > 0.6, body/range < 0.3

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

**Алгоритм:**
1. Fetch 4H data for BTC and altcoin (60 candles)
2. Detect swing points (20-bar lookback): swing_high, swing_low, micro-trend (EMA3 vs EMA5 of last 5 closes)
3. **Bearish SMT**: BTC bullish + altcoin bearish (alt weaker than BTC)
4. **Bullish SMT**: BTC bearish + altcoin bullish (alt stronger than BTC)
5. For BTC itself → returns neutral (SMT meaningless)
6. Cache TTL: 30 minutes
7. Score: `+1.0` (bullish), `-1.0` (bearish), `0.0` (neutral)

### 1.45 HTF Bias V2 (строки 843–1026)

**Модуль**: `market_structure/htf_bias_v2.py` (160 строк)

**Если `config.htf_bias_v2=True`** (default: True):

**Per-TF Bias Detection (`get_tf_bias`):**
1. Compute EMA21 and EMA55
2. Direction:
   - `price > ema21 > ema55` → bullish
   - `price < ema21 < ema55` → bearish
   - Otherwise → neutral
3. Confidence: `min(spread * 10, 100)` where spread = `|ema21-ema55| / price * 100`
4. Structure boost: If BOS direction matches bias → `confidence *= 1.2` (capped at 100)

**Top-down анализ**: W1 → D1 → H4 → H1

**Majority voting на W1, D1, H4:**
- 3/3 одинаковых → STRONG
- 2/3 одинаковых → MODERATE
- **A06 fix**: 1 directional + 2 neutral → WEAK (single-TF conviction)
- W1 согласен с D1 или H4 → WEAK (pair agreement)
- Нет соглашения → NEUTRAL

**A06: Confidence** — EMA-spread based, informational only (НЕ statistical confidence):
```
confidence = min(|EMA21-EMA55|/price*100*10, 100)
```
Combined: `avg(w1_conf, d1_conf, h4_conf)`. Хранится в `HTFBiasResult.confidence`.

**Override логика:**
- W1 конфликтует, но D1+H4 согласны → override (MODERATE)
- H4 конфликтует, но W1+D1 согласны → pullback (MODERATE)

**H1**: Only used for zone classification (not for bias voting)

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

## 9. Фаза 1.5: HTF POI Detection + Trade Plan (SL/TP)

**Строки 1054–1081.**

### 9.1 HTF POI Detection (Phase 1.5a)

**Модуль**: `strategy/htf_poi.py`

Multi-timeframe Points of Interest.
- Detects OB/FVG on D1, H4, W1 and checks proximity to current price.
- Если цена рядом с HTF POI → SL anchored to HTF structure level для лучшего RR.

### 9.2 Build Trade Plan (Phase 1.5b)

```python
trade_plan = trade_engine.build_trade_plan(
    ind=ind, direction=setup.direction, structure=structure,
    order_blocks=order_blocks, sweeps=sweeps, fvgs=fvgs,
    df=_df_clean, timeframe=timeframe, htf_poi_result=_htf_poi_result,
)
```

**Trade Engine** (`strategy/trade_engine.py`, 376 строк):

#### Шаг 1: Build Liquidity Map
Конвертация structure points → SwingPoints, вызов `build_liquidity_map()`.

#### Шаг 2: Find Invalidation (SL)
Приоритетный каскад (`strategy/invalidation.py`):

| Приоритет | Источник | Buy SL | Sell SL |
|-----------|----------|--------|---------|
| 1 | Sweep extreme | Ниже sweep low | Выше sweep high |
| 2 | OB boundary | Ниже OB low | Выше OB high |
| 3 | Swing point | Ниже swing low | Выше swing high |
| 4 | BOS level | Ниже BOS level | Выше BOS level |
| 5 | ATR fallback | entry − ATR × 1.5 | entry + ATR × 1.5 |

**SL Buffer**: `atr * 0.35` (35% of ATR)

**SL Safety** (строки 139–179):
- SL должен быть за пределами текущей свечи (wick)
- Spread buffer: 0.01%
- Tick buffer: из exchange market info
- ATR buffer: 15% от ATR

**ATR Per-TF Overrides**: `atr_multipliers_per_tf` dict позволяет разные SL/TP multipliers per timeframe.

#### Шаг 2.5: HTF POI SL Override
Если `htf_poi_result.is_near`:
- `htf_sl = get_htf_sl_level(htf_poi_result, direction, current_price, fallback_level=sl)`
- SL adjusts to HTF POI level ± buffer

#### Шаг 3: Find Targets (TP)
Множественные кандидаты TP:

| Тип | Type bonus |
|-----|------------|
| old_high/old_low | 2.0 |
| equal_high/equal_low | 1.8 |
| ob_bullish/ob_bearish | 1.5 |
| fvg_bullish/fvg_bearish | 1.2 |
| swept_high/swept_low | 0.5 |
| ATR fallback | 0.3 |

- Минимальная дистанция TP = 1 ATR
- Проверка path clarity: нет opposing OB/FVG с strength > 0.5 между entry и target

#### Шаг 4: Выбор лучшего target
`max(targets, key=lambda t: t.score)` где `score = strength × min(1.0, rr_ratio/3.0) × (1.0 if path_clear else 0.5)`

#### Шаг 5: Validate
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

## 11. Analytical Overlays (A12: НЕ блокируют, НО влияют на sizing)

**Строки 1157–1461.** Работают параллельно, записывают результаты, но **никогда не возвращают None**. Их выходы (`_thesis_score`, `_thesis_stability`) передаются в Risk Engine как множители размера позиции — это **активные overlay**, а не shadow.

> **A12 fix**: Переименованы из "Shadow" в "Analytical Overlays" для точного отражения поведения. `shadow_mode=True` в конфиге — устаревшее имя.

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

### SetupFeatures (~53 raw features)

| Категория | Признаки |
|-----------|----------|
| **ICT Pattern (8)** | `setup_type` (reversal=+1, continuation=−1), `has_bos`, `has_sweep`, `has_ob`, `has_fvg`, `has_displacement`, `has_mss`, `components_count` |
| **Reversal Metrics (4)** | `mss_score`, `mss_causality`, `displacement_atr_ratio`, `sweep_to_mss_bars` |
| **Pattern Metrics (4)** | `ob_distance_pct`, `fvg_size_pct`, `sweep_reclaim_speed`, `sweep_strength` |
| **Market Structure (2)** | `structure_trend` (bullish=+1, bearish=−1, ranging=0), `structure_bos_aligned` |
| **Volume (3)** | `volume_ratio` (volume/volume_sma), `volume_delta_pct`, `volume_above_avg` |
| **Volatility (2)** | `atr_pct`, `regime` (trend=1, expansion=0.5, range=−0.5, compression=−1) |
| **Indicators (5)** | `rsi`, `adx`, `ema_spread_pct`, `dmi_diff`, `macd_hist_pct` |
| **MTF (3)** | `mtf_aligned`, `mtf_htf_count`, `is_4h_aligned` |
| **Context (3)** | `fear_greed`, `funding_rate`, `context_score` |
| **Risk (3)** | `rr_ratio`, `sl_distance_pct`, `tp_distance_pct` |
| **Execution (3)** | `session` (asian=0..off_hours=4), `candle_close_pct`, `is_reversal` |
| **Entry (1)** | `entry_armed` |
| **Soft Multipliers (5)** | `htf_alignment_score`, `premium_discount_score`, `smt_divergence_score`, `htf_bias_penalty`, `ob_state_multiplier` |
| **Elliott Wave (4)** | `wave_confidence`, `wave_direction`, `wave_conflict`, `wave_label` |
| **S/R Proximity (2)** | `nearest_support_pct`, `nearest_resistance_pct` |

### to_vector() — для ML
Конвертация в плоский dict: categorical encoding (setup_type ±1, structure_trend ±1/0, regime 1/0.5/−0.5/−1, session 0–4), booleans → ints.

### A22: Полный вектор в Trace
`DecisionTraceBuilder.set_features()` сохраняет:
- `_features` — отфильтрованные 35 полей (для DB и быстрого доступа)
- `_full_feature_vector` — все 53 признака (для ML replay и переобучения)
- Полный вектор сериализуется в `hypothesis_snapshot["full_features"]`

### to_reasoning() — для логов
Приоритет: MSS > Displacement > Sweep > OB > FVG > HTF > Session. Индикаторы (RSI, ADX, EMA) **НЕ** включаются — только для ML.

---

## 13. Фаза 3: Probability Engine

**Строки 1621–1659.**

```python
probability = probability_engine.predict(features, symbol=symbol, scenario_name=_scenario_name)
```

### 13.1 Rules-Based Estimation (`_predict_rules`, строки 146–356)

**Base rate**: `scenario_memory` stats (если >= 10 закрытых сделок) → `historical_winrate` → 50.0

#### Component Edge (Reversal):
| Компонент | Вес |
|-----------|-----|
| sweep | +3.0 |
| displacement | +3.0 |
| MSS | +4.0 |
| MSS quality ≥ 70 | +2.0 |
| MSS quality 50–70 | +1.0 |
| OB | +1.5 |
| FVG | +1.0 |
| entry_armed | +1.5 |

#### Component Edge (Continuation):
| Компонент | Вес |
|-----------|-----|
| BOS | +3.0 |
| structure aligned | +2.0 |
| OB | +1.5 |
| FVG | +1.0 |
| entry_armed | +1.5 |

#### Regime Edge:
| Режим | Continuation | Reversal |
|-------|--------------|----------|
| expansion | +2.0 | −1.5 |
| compression (with BOS) | +1.5 | −1.0 |
| trend (BOS aligned) | +2.5 | −2.0 |
| range | −1.0 | +1.5 |
| high_vol | −1.0 | −1.0 |
| low_vol (with BOS) | +1.0 | — |

#### Common Scoring:
| Признак | Вес |
|---------|-----|
| structure alignment | +2.0 |
| volume > 2.0x | +3.0 |
| volume > 1.5x | +2.0 |
| volume > 1.2x | +1.0 |
| MTF aligned | +2.0 |
| session (overlap/london/ny) | +1.0 |
| ATR sweet spot (1–3%) | +1.5 |
| ATR > 5% | −2.0 |
| ATR < 0.5% | −1.5 |
| context > 0.3 | +1.0 |
| context < −0.3 | −1.5 |

#### Soft multipliers (multiplicative):
| Мультипликатор | Формула | Range |
|----------------|---------|-------|
| HTF alignment | `0.5 + 0.5 × score` | 0.5–1.0 |
| Premium/discount | `0.5 + 0.5 × score` | 0.5–1.0 |
| HTF bias mismatch | 0.8 | 0.8 |
| OB state (BROKEN) | 0.0 → p_tp=0 | 0.0 |

#### Elliott Wave:
- confidence >= min_confidence (0.4) и нет конфликта → `confidence × weight` к winrate
- Конфликт → `conflict_penalty` multiplier (0.85)

**Final**: winrate clamped [20.0, 85.0]

**Expected net R** (A08 fix): `expected_net_r = p * b - (1-p)`, где `p = winrate/100`, `b = rr_ratio`

**Profit Factor** (A08 fix): `model_pf = p * b / max(1-p, 0.01)`

### 13.2 ML-Based Estimation (`_predict_ml`, строки 358–445)

- OB mitigation hard gate (multiplier <= 0 → rejected)
- Features → vector → DataFrame
- **Expected return mode**: regressor → raw_return → sigmoid → isotonic calibration → p_tp
- **Legacy mode**: classifier `predict_proba` → p_tp, regressor → expected_rr
- HTF bias penalty и OB mitigation как multipliers
- p_tp clamped [0.05, 0.85]
- Confidence: 0.80 for ML, 0.40 for rules
- Fallback: ML exception → rules

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

### 14.1 Hard Gates (порядок严格执行):

| # | Проверка | Audit Code | Описание |
|---|----------|------------|----------|
| 1 | Portfolio: max active signals | — | `active_count >= max_active_signals` |
| 2 | Portfolio: max risk % | — | `total_risk_pct >= max_portfolio_risk_pct` |
| 3 | Data integrity | — | `entry_price <= 0`, `sl <= 0`, `tp <= 0` |
| 4 | Zero risk distance | — | `risk_dist = 0` |
| 5 | Fee-adjusted R:R | — | Учитывает `exchange_fee_pct` (0.05%) + `slippage_pct` (0.05%) с обеих сторон. Costs = `(fee + slippage) * 2` applied to both risk and reward. |
| 6 | Min R:R | `RR_TOO_LOW` | `rr_ratio < min_rr_ratio` (default 2.0) |
| 7 | SL absolute min | `SL_TOO_TIGHT` | `sl_distance_pct < sl_absolute_min_pct` (default 0.25%) |
| 8 | Dynamic SL max | `SL_TOO_WIDE` | `dynamic_sl_max = max(sl_absolute_max_pct(5.0%), atr_pct × 2.2)`, clamped to 8.0% |
| 9 | SL min ATR multiplier | `SL_ATR_CONFLICT` | `sl_distance_pct < atr_pct × sl_min_atr_multiplier` (2.0). A1 fix: relaxes floor если ATR-min > dynamic max |

### 14.2 Position Sizing:

#### EV Gate (A09: applies to BOTH fixed and Kelly):
```python
p = probability.p_tp
b = rr_ratio
expected_net_r = p * b - (1 - p)
if expected_net_r <= 0:
    return None  # NEGATIVE_EV — applies regardless of risk_mode
```

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
if kelly <= 0: return None  # NEGATIVE_EV — negative expected value
kelly = max(0.0, min(kelly, 0.20))  # half-Kelly cap at 20%
kelly *= probability.confidence
risk_pct = min(kelly * 100, base_risk_pct)
```

#### Min Notional Check (A10 fix):
```python
if portfolio.equity > 0 and entry_price > 0 and risk_dist > 0:
    risk_budget_quote = equity * risk_pct / 100.0
    loss_per_unit = abs(entry_price - sl)  # risk_dist in price units
    quantity_base = risk_budget_quote / loss_per_unit
    notional_quote = quantity_base * entry_price
    if notional_quote < min_notional_usdt (5.0):
        return None  # POSITION_SIZE_BELOW_MIN
```

### 14.3 Мультипликативные корректировки (после Kelly/fixed):

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

## 17. Фаза 7: Execution Filters + TOCTOU Recheck

**Строки 1898–2051.** Последовательные.

| # | Проверка | Audit Code | Описание |
|---|----------|------------|----------|
| 1 | Spread | `SPREAD_TOO_WIDE` | `(ask - bid) / bid × 100 > max_spread_percent` (default 0.15%) |
| 2 | Depth | `DEPTH_TOO_LOW` | Order book depth за 0.5% от mid < `min_depth_0_5_percent` (default $10,000) |
| 3 | Correlated entry | `CORRELATION_BLOCKED` | Если correlated символ уже имеет открытую позицию → BLOCK |
| 4 | **TOCTOU Recheck** | `PORTFOLIO_MAX_ACTIVE` / `PORTFOLIO_MAX_RISK` | Повторная проверка portfolio limits перед финализацией. Защита от race condition между asyncio tasks. |

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
[4.0] Risk Engine: all hard gates (R:R, SL limits, min notional)
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
[7.0+] TOCTOU Recheck: Portfolio limits
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

Признаки не имеют явных весов в Feature Builder — все ~53 features передаются как есть. Веса определяются ML-моделью (XGBoost/RandomForest) или rules-based fallback.

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
| | ATR > 5% | −2.0 |
| | ATR < 0.5% | −1.5 |
| | context > 0.3 | +1.0 |
| | context < −0.3 | −1.5 |
| **Regime** | expansion (cont) | +2.0 |
| | expansion (rev) | −1.5 |
| | trend (cont, aligned) | +2.5 |
| | trend (rev) | −2.0 |
| | range (cont) | −1.0 |
| | range (rev) | +1.5 |
| | high_vol | −1.0 |
| | low_vol (cont, BOS) | +1.0 |

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
| Volatility (high, >4.0%) | 0.5 | 0.5 |
| Volatility (medium-high, >2.5%) | 0.75 | 0.75 |
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

| Поле | Тип | Назначение |
|------|-----|------------|
| `symbol` | str | Торговая пара |
| `timeframe` | str | Entry timeframe |
| `_gates` | dict[str, bool] | Gate pass/fail results |
| `_final_stage` | str | Last gate reached |
| `_blocked_reason` | str | Why blocked (200 char max) |
| `_signal_generated` | bool | Whether signal was created |
| `_signal_type` | str | BUY/SELL |
| `_score` | int | Signal score |
| `_close_price` | float | Entry price |
| `_sl` / `_tp` | float | SL/TP levels |
| `_features` | dict | Feature snapshot (filtered by FEATURE_KEYS) |
| `_strategy_version` | str | VERSION string |
| `_config_snapshot` | str | JSON of all config params |
| `_execution_snapshot` | ExecutionSnapshot | Market microstructure at signal time |
| `_hypothesis_snapshot` | dict | Hypothesis data for ScenarioMemory |

**Gate Path**: Serialized as ordered JSON array: `["cooldown:PASS", "portfolio_risk:BLOCK:max active signals"]`

### FEATURE_KEYS (tracked in trace)

`adx`, `rsi`, `ema_short`, `ema_long`, `ema_spread_pct`, `macd_hist`, `supertrend_direction`, `volume_ratio`, `dmi_strength`, `ema_strength`, `signal_score`, `confidence`, `regime`, `direction`, `sl_source`, `tp_distance_pct`, `sl_distance_pct`, `rr_ratio`, `has_bos`, `has_sweep`, `has_ob`, `ob_distance_pct`, `context_score`, `btc_trend_strength`, `mtf_alignment_score`, `atr_pct`, `ema_slope_3`, `ema_slope_5`, `nearest_support_pct`, `nearest_resistance_pct`, `regime_confidence`, `wave_confidence`, `wave_direction`, `wave_conflict`, `wave_label`

### Signal Audit Log (`storage/audit_reasons.py`)

46 структурированных reason codes. Каждый BLOCKED/PASS записывает:
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
- `ob_aware` режим (default): **всегда возвращает False** — cooldown отложен до Phase 6
- `strict` режим: проверяет `db.get_cooldown()` против `max(base_minutes, tf_minutes × multiplier)`

#### B. Dedup Cooldown (Phase 6)
- Запускается **после** полной оценки сигнала
- Сравнивает с последним сигналом для того же symbol+TF из БД
- **Same direction + within cooldown**:
  - `ob_aware` (default): сравнение OB midpoints. Разный OB → bypass. Тот же OB → reduced cooldown (1/3)
  - `strict`: полный cooldown блокирует
- **Cross-direction + within cooldown**: half-cooldown блокирует быстрые развороты

### Cooldown Formulas:
```
dedup_cooldown_minutes = max(base_minutes, tf_minutes × multiplier)
```
- Base: `signal_cooldown_minutes` = 45
- Multiplier: `signal_cooldown_tf_multiplier` = 2.0
- Для 1h: `max(45, 60*2) = 120 мин`
- Для 4h: `max(45, 240*2) = 480 мин`

---

## 23. Post-signal: Управление позицией

### Outcome Tracker (`scheduler/outcome_tracker.py`, 700 строк)

Фоновый цикл (каждые `OUTCOME_CHECK_INTERVAL_SECONDS=300с`) проверяет открытые исходы:

**Position Lifecycle:**
1. **Creation**: `ManagedPosition` created from signal data на первом check
2. **Per-bar checks** (каждые 300с):
   - Skip if same candle as entry (prevent same-bar SL)
   - Skip if symbol on fetch-failure cooldown (3 failures → 10min cooldown)
   - Fetch current price via ticker + recent candle H/L
   - Detect last BOS for Flip Bias
   - Run `manage_position()` with all checks

### Exit Triggers (порядок приоритета, `risk/position_manager.py`)

| # | Событие | Триггер | Действие |
|---|---------|---------|----------|
| 1 | Flip Bias | BOS против позиции после entry | Close |
| 2 | Sweep Breach | Close за sweep level | Early exit |
| 3 | Time Stop | Held > TIME_STOP_MAX_MINUTES (default disabled) | Close |
| 4 | TP Hit (partial) | At TP targets | Partial or full close |

### Time-Stop по TF:
```
1m=20min, 3m=60min, 5m=100min, 15m=300min, 30m=600min,
1h=1200min(20h), 2h=2400min(40h), 4h=5760min(96h),
6h=8640min(6d), 12h=17280min(12d), 1d=28800min(20d)
```

### ExitPlan (A13: связь TradeEngine ↔ PositionManager)

**`ExitPlan`** dataclass (`risk/position_manager.py`) — иммутабельный план выхода, создаваемый до публикации сигнала. Все модули (уведомления, симулятор, риск, модель) используют один план.

| Поле | Описание |
|------|----------|
| `primary_tp_price` | Целевая TP от TradeEngine (по ликвидности) |
| `primary_tp_source` | Источник: liquidity / atr / ob / fvg |
| `initial_sl_price` | Начальный SL от TradeEngine |
| `partial_close_targets` | R-multiples → % от НАЧАЛЬНОЙ позиции |
| `breakeven_trigger_rr` | порог BE (default 1.5R) |
| `trailing_trigger_rr` | порог trailing (default 3.0R) |
| `plan_version` | версия для A/B анализа |

**Factory**: `create_exit_plan(tp_price, tp_source, sl_price, sl_source, rr_ratio)` — вызывается при построении TradePlan.

### Partial Close Logic (§8.3, через ExitPlan)
```
TP@2R → close 25%, move SL to breakeven
TP@3R → close 35%, activate trailing stop
TP@4R → close 40% (full position close)
```
Remaining: 100% → 75% → 40% → 0%

Доли `%` относятся к **начальному размеру**. `gross_r = 0.25*2 + 0.35*3 + 0.40*4 = 3.15R` до затрат.

### Breakeven Logic (§8.4)
- **Trigger**: Current R:R ≥ 1.5R (using intra-bar high/low)
- **SL**: `entry_price ± fee_buffer(0.05%)`

### Trailing Stop Logic (§8.5)
- **Activation**: After TP2 (3R), only on remaining 40%
- **Formula**: `new_sl = current_price - atr * TRAILING_ATR_MULTIPLIER(1.5)`
- Never pulls SL below breakeven
- Only moves SL in favorable direction

### PnL Calculation
- Gross: `(exit-entry)/entry * 100`
- Costs: `(fee + slippage) * 2`
- Funding: `hold_hours / 8 * FUNDING_RATE_8H * 100` (for swap/future)

### Close Reason Normalization
- `TP*_FULL` → `HIT_TP`
- `TIME_STOP` → `EXPIRED`
- `FLIP_BIAS`/`SWEEP_BREACH` → `HIT_TP` if net_pnl > 0, else `HIT_SL`

---

## 24. Контекстные источники данных

### ContextFetcher (`context/fetcher.py`, 400 строк)

| # | Источник | API | TTL | Данные | Fallback |
|---|----------|-----|-----|--------|----------|
| 1 | Fear & Greed | Alternative.me | 3600с (1ч) | Индекс 0–100 + label | None |
| 2 | CoinGecko | CoinGecko API | — | price_change_24h/7d, volume, market_cap_rank | None |
| 3 | Trending | CoinGecko `/search/trending` | 1800с (30м) | Top 7 trending symbols | [] |
| 4 | Funding Rate | ccxt unified | — | Ставка финансирования | None (BingX unsupported) |
| 5 | Open Interest | ccxt unified | — | OI + delta % (с warm-up) | None |
| 6 | Long/Short Ratio | Binance fapi | — | Global L/S Account Ratio (1h) | None (BingX deprecated) |
| 7 | CryptoPanic | CryptoPanic API | — | News sentiment score | None (needs API key) |
| 8 | RSS News | CoinDesk + CoinGecko | 300с (5м) | Keyword-based sentiment | None |

### Caching Details
- `_fng_cache`: `(data, timestamp)` tuple, 1h TTL
- `_trending_cache`: `(data, timestamp)` tuple, 30m TTL
- `_rss_cache`: `{base_currency: (data, timestamp)}` dict, 5m TTL
- `_last_oi`: `{symbol: float}` in-memory, tracks previous OI for delta calculation

### OI Warm-up
On first request for a symbol, fetches historical OI from `fetchOpenInterestHistory(timeframe="5m", limit=2)` to initialize delta calculation.

### Retry Logic
`_with_retry(fn, retries=3, delay=0.5, backoff=2)` for all network calls.

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

**Column Naming Conventions** (dynamic):
- MACD: `MACD_8_21_5`, `MACDh_8_21_5`, `MACDs_8_21_5`
- ADX: `ADX_14`, `DMP_14`, `DMN_14`
- Supertrend: `SUPERT_10_2.5`, `SUPERTd_10_2.5`

**Fallback**: `_safe_float()` replaces None/NaN/Inf with defaults. Returns None if < 2 clean rows after dropping NaN.

### Market Structure (`market_structure/structure.py`, 788 строк)

- Swing Points (HH/HL/LH/LL)
- BOS (Break of Structure)
- CHoCH (Change of Character)
- MSS (Market Structure Shift) = strong CHoCH с sweep + displacement + reclaim
- Trend classification

---

## 25. Конфигурация (полный реестр параметров)

### TradingConfig (45+ params)

| Параметр | Default | Описание |
|-----------|---------|----------|
| `symbols` | `BTC/USDT,ETH/USDT,SOL/USDT` | Символы для сканирования |
| `primary_timeframes` | `1h,4h` | Таймфреймы |
| `scan_mode` | `single_tf` | `multi_tf` включает LTF confirmation |
| `confirm_timeframe` | `5m` | Подтверждающий TF |
| `confirm_tf_enabled` | `true` | Включить LTF confirmation |
| `ema_fast` | `8` | Быстрая EMA |
| `ema_slow` | `21` | Медленная EMA |
| `ema_trend` | `55` | Трендовая EMA |
| `min_ema_spread_pct` | `0.20` | Мин. расстояние EMA% |
| `ema_slope_check` | `true` | Проверка наклона EMA |
| `sweep_penalty_enabled` | `true` | Штраф за sweep |
| `ema_strength_cap` | `1.0` | Потолок EMA strength |
| `rsi_period` | `10` | Период RSI |
| `rsi_overbought` | `72` | Перекупленность |
| `rsi_oversold` | `28` | Перепроданность |
| `rsi_bull_min` | `55` | Мин RSI для быков |
| `rsi_bear_max` | `45` | Макс RSI для медведей |
| `macd_fast` | `8` | Быстрый MACD |
| `macd_slow` | `21` | Медленный MACD |
| `macd_signal` | `5` | Signal MACD |
| `min_macd_pct` | `0.03` | Мин MACD% |
| `macd_score_multiplier` | `10` | Мультипликатор MACD |
| `macd_slope_check` | `false` | Проверка наклона MACD |
| `adx_period` | `14` | Период ADX |
| `adx_min` | `26` | Мин ADX |
| `adx_strong` | `22` | Сильный ADX |
| `adx_strength_range` | `30` | Range ADX |
| `dmi_norm_divisor` | `50` | Делитель DMI |
| `dmi_strength_multiplier` | `2` | Мультипликатор DMI |
| `atr_period` | `14` | Период ATR |
| `atr_multiplier_sl` | `1.5` | ATR× для SL |
| `atr_multiplier_tp` | `3.0` | ATR× для TP |
| `atr_multipliers_per_tf` | `{}` | Словарь ATR× per TF |
| `atr_fallback_pct` | `2.0` | ATR fallback% |
| `min_sl_distance_pct` | `1.0` | Мин SL% |
| `max_sl_distance_pct` | `10.0` | Макс SL% |
| `min_rr_threshold` | `1.5` | Мин R:R |
| `stop_hunt_buffer_pct` | `0.5` | Буфер stop hunt |
| `max_ob_distance_pct` | `3.0` | Макс расстояние до OB |
| `exchange_fee_pct` | `0.05` | Комиссия биржи |
| `slippage_pct` | `0.05` | Проскальзывание |
| `supertrend_period` | `10` | Период Supertrend |
| `supertrend_multiplier` | `2.5` | Мультипликатор Supertrend |
| `volume_factor` | `1.5` | Фактор объёма |
| `volume_sma_period` | `20` | Период SMA объёма |
| `delta_bullish` | `15` | Порог delta бычий |
| `delta_bearish` | `-15` | Порог delta медвежий |
| `volume_delta_norm` | `50` | Нормализация delta |
| `compression_volume_factor` | `2.0` | Фактор объёма при сжатии |
| `adx_filter_enabled` | `true` | ADX фильтр |
| `ema_alignment_enabled` | `true` | Выравнивание EMA |
| `ema_spread_enabled` | `true` | Расстояние EMA |
| `trigger_required` | `true` | Триггер обязателен |
| `candle_close_enabled` | `true` | Закрытие свечи |
| `min_score_enabled` | `true` | Минимальный score |
| `compression_enabled` | `true` | Compression detection |
| `block_compression_regime` | `true` | Блокировать compression |
| `candles_limit` | `200` | Лимит свечей |
| `max_spread_percent` | `0.15` | Макс spread% |
| `max_slippage_percent` | `0.1` | Макс slippage% |
| `min_depth_0_5_percent` | `10000` | Мин глубина стакана |
| `volatility_min_atr_percent` | `0.3` | Мин ATR% |
| `volatility_max_atr_percent` | `5.0` | Макс ATR% |

### AppConfig Feature Flags

| Параметр | Default | Назначение |
|-----------|---------|------------|
| `htf_hard_gate` | `true` | HTF direction filter |
| `external_liquidity_tp` | `true` | External liquidity как TP targets |
| `ob_mitigation` | `true` | OB mitigation tracking |
| `confidence_cap` | `true` | Cap confidence at 85% |
| `shadow_mode` | `true` | Shadow mode для нового пайплайна |
| `classic_indicators_mode` | `soft` | off/soft/hard |
| `risk_mode` | `fixed` | fixed/kelly |
| `htf_bias_v2` | `true` | W1→D1→H4→H1 voting |
| `premium_discount` | `false` | Premium/discount zones |
| `require_entry_zone` | `false` | Entry zone hard gate |
| `reversal_require_displacement` | `true` | Displacement required для reversal |
| `require_ob_retest` | `true` | OB retest gate |
| `session_hard_gate` | `false` | Session filter |
| `trading_sessions_str` | `london,ny` | Активные сессии |
| `block_neutral_htf` | `true` | Block neutral HTF |
| `block_short_in_bullish_htf` | `true` | Block SHORT в bullish HTF |
| `block_long_in_bearish_htf` | `true` | Block LONG в bearish HTF |
| `breakout_quality_enabled` | `true` | Breakout quality classifier |
| `breakout_quality_hard_gate` | `false` | Hard gate для fakes |
| `breakout_quality_min_score` | `45` | Info only, не используется как gate |
| `breakout_quality_lookback` | `40` | Range lookback |
| `portfolio_equity_usdt` | `0` | Min notional check |
| `signal_cooldown_minutes` | `45` | Base cooldown |
| `signal_cooldown_tf_multiplier` | `2.0` | TF multiplier |
| `cooldown_mode` | `ob_aware` | ob_aware/strict |
| `ob_proximity_pct` | `0.5` | OB dedup proximity |
| `smt_enabled` | `true` | SMT divergence feature |

### ProbabilityConfig

| Параметр | Default |
|-----------|---------|
| `model_path` | `models/probability_model.pkl` |
| `min_samples_for_ml` | `100` |
| `fallback_winrate` | `50.0` |
| `min_p_tp` | `0.30` |
| `min_p_tp_short` | `0.40` |
| `min_p_tp_reversal` | `0.50` |

### RiskEngineConfig

| Параметр | Default |
|-----------|---------|
| `min_rr_ratio` | `2.0` |
| `sl_absolute_min_pct` | `0.25` |
| `sl_absolute_max_pct` | `5.0` |
| `base_risk_pct` | `1.0` |
| `min_risk_pct` | `0.1` |
| `max_risk_pct` | `2.0` |

### RiskConfig (daily limits, regime, etc.)

| Параметр | Default |
|-----------|---------|
| `volatility_low_threshold` | `0.8` |
| `volatility_high_threshold` | `6.0` |
| `volatility_atr_period` | `14` |
| `volatility_high_multiplier` | `0.5` |
| `risk_strong_pct` | `1.0` |
| `risk_moderate_pct` | `0.5` |
| `risk_weak_trade` | `false` |
| `risk_weak_pct` | `0.25` |
| `no_trade_min_atr_pct` | `0.6` |
| `max_risk_per_day_pct` | `6.0` |
| `max_trades_per_day` | `5` |
| `max_consecutive_losses` | `3` |
| `max_drawdown_daily_pct` | `10.0` |
| `profit_target_daily_pct` | `10.0` |
| `max_positions_total` | `5` |
| `max_long_positions` | `3` |
| `max_short_positions` | `3` |
| `correlation_misaligned_multiplier` | `0.5` |
| `volatility_filter_enabled` | `true` |
| `no_trade_zones_enabled` | `true` |
| `dynamic_risk_enabled` | `true` |
| `news_filter_enabled` | `false` |
| `news_block_before_minutes` | `60` |
| `news_block_after_minutes` | `30` |
| `regime_trend_adx` | `25` |
| `regime_range_adx` | `20` |
| `regime_compression_atr_pct` | `20` |
| `regime_atr_lookback` | `100` |
| `regime_ema_spread_window` | `5` |
| `regime_ema_spread_change_pct` | `0.05` |
| `regime_rising_multiplier` | `1.1` |
| `regime_rising_window` | `10` |
| `regime_fallback_confidence` | `0.3` |
| `tp_path_blocked_threshold` | `-20` |
| `tp_path_clear_score` | `15` |
| `tp_path_obstacle_penalty` | `-10` |

### WaveConfig

| Параметр | Default |
|-----------|---------|
| `enabled` | `true` |
| `min_confidence` | `0.4` |
| `conflict_penalty` | `0.85` |
| `weight` | `1.0` |
| `max_alternatives` | `3` |
| `min_swing_atr` | `0.5` |
| `max_lookback` | `200` |

---

## 26. Аудит-коды (reason codes) — полный реестр

**Всего: 46 reason codes.**

### Phase 0: Hard Gates
```
COOLDOWN_ACTIVE = "cooldown_active"
PORTFOLIO_MAX_ACTIVE = "portfolio_max_active"
PORTFOLIO_MAX_RISK = "portfolio_max_risk"
DAILY_LIMIT_HIT = "daily_limit_hit"
POSITION_LIMIT_HIT = "position_limit_hit"
DATA_INTEGRITY_FAIL = "data_integrity_fail"
VOLATILITY_TOO_LOW = "volatility_too_low"
VOLATILITY_TOO_HIGH = "volatility_too_high"
```

### Phase 1: Pattern Engine
```
PATTERN_NO_SETUP = "pattern_no_setup"
SWEEP_NONE = "sweep_none"
SWEEP_FALSE_FILTERED = "sweep_false_filtered"
DISPLACEMENT_MISSING = "displacement_missing"
MSS_NONE = "mss_none"
MSS_DIRECTION_UNCLEAR = "mss_direction_unclear"
CONTINUATION_RANGING = "continuation_ranging"
CONTINUATION_NO_BOS = "continuation_no_bos"
CONTINUATION_BOS_NOT_BREAKING = "continuation_bos_not_breaking"
CONTINUATION_BOS_VS_TREND = "continuation_bos_vs_trend"
```

### Phase 1.4: Setup-Type
```
ENTRY_ZONE_BLOCKED = "entry_zone_blocked"
```

### Phase 1.41: Breakout Quality
```
BREAKOUT_FAKE = "breakout_fake"
```

### Phase 1.42: Confirmation + OB Retest
```
CONFIRMATION_LOW = "confirmation_low"
OB_RETEST_FAILED = "ob_retest_failed"
OB_TOO_OLD = "ob_too_old"
OB_BROKEN = "ob_broken"
OB_MITIGATED = "ob_mitigated"
OB_TOO_FAR = "ob_too_far"
OB_NOT_RETESTED = "ob_not_retested"
OB_NO_CONFIRMATION = "ob_no_confirmation"
```

### Phase 1.43: Session
```
SESSION_BLOCKED = "session_blocked"
```

### Phase 1.45: HTF Bias
```
HTF_SHORT_IN_BULLISH = "htf_short_in_bullish"
HTF_LONG_IN_BEARISH = "htf_long_in_bearish"
HTF_CONTINUATION_MISMATCH = "htf_continuation_mismatch"
HTF_REVERSAL_MISMATCH = "htf_reversal_mismatch"
```

### Phase 1.5: SL/TP
```
SL_TP_FAILED = "sl_tp_failed"
```

### Phase 1.7: LTF Confirmation
```
LTF_NO_CONFIRMATION = "ltf_no_confirmation"
LTF_DATA_UNAVAILABLE = "ltf_data_unavailable"
```

### Phase 3: Probability
```
MIN_P_TP = "min_p_tp"
```

### Phase 4: Risk Engine
```
RR_TOO_LOW = "rr_too_low"
SL_TOO_TIGHT = "sl_too_tight"
SL_TOO_WIDE = "sl_too_wide"
SL_ATR_CONFLICT = "sl_atr_conflict"
POSITION_SIZE_BELOW_MIN = "position_size_below_min"
NEGATIVE_EV = "negative_ev"
```

### Phase 4.5: Entry Trigger
```
ENTRY_TRIGGER_NO = "entry_trigger_no"
```

### Phase 6: Dedup
```
DEDUP_OB = "dedup_ob"
DEDUP_SAME_DIR = "dedup_same_dir"
DEDUP_CROSS_DIR = "dedup_cross_dir"
```

### Phase 7: Execution
```
SPREAD_TOO_WIDE = "spread_too_wide"
DEPTH_TOO_LOW = "depth_too_low"
CORRELATION_BLOCKED = "correlation_blocked"
```

### Pass
```
OK = "ok"
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
├─ Phase 2: Feature Builder ─────── SetupFeatures (~53 features)
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
│  ├─ Correlated entry ───────────────────────────────────── BLOCKED?
│  └─ TOCTOU Recheck: Portfolio ─────────────────────────── BLOCKED?
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

11. **block_neutral_htf**: Флаг существует в конфиге, но **не используется** в scanner — neutral всегда проходит. Рекомендация: либо реализовать, либо удалить флаг.

12. **SL_ATR_MIN_RELAXED**: В v1.0 документации упоминался `SL_ATR_MIN_RELAXED` audit code. В актуальном коде используется `SL_ATR_CONFLICT` с логикой relax floor если ATR-min > dynamic max.

### Исправленные проблемы (v1.1.1)

- **A08**: `expected_rr` и `profit_factor` были математически неверны (вероятность дважды) → исправлены
- **A09**: EV gate отсутствовал в fixed mode → добавлен для обоих режимов
- **A10**: Min-notional использовал неверную размерность → исправлен
- **A12**: Shadow engines влияли на sizing, но назывались "shadow" → переименованы в analytical overlays
- **A15**: Docstrings были long-only → добавлены mirror-correct описания
- **A06**: Single-TF conviction классифицировался как NEUTRAL → исправлен на WEAK

### Архитектурные рекомендации для другой модели ИИ

- **Все фильтры — последовательные**. Порядок важен: дешёвые проверки → дорогие. Не менять порядок без анализа impact.
- **Analytical Overlays (A12)** — не блокируют, но `_thesis_score` и `_thesis_stability` влияют на sizing через Risk Engine. При модификации пайплана проверять, что features snapshot всё ещё корректен. Не путать с true shadow (который действительно не влияет).
- **Audit logging** — покрывает все 46 точек блокировки. При добавлении нового gate ОБЯЗАТЕЛЬНО добавить reason_code в `storage/audit_reasons.py`.
- **Config**: Все параметры через env vars. Добавляя параметр — добавить в `config/settings.py` и в `.env.example`.
- **Testing**: `pytest.ini` имеет `asyncio_mode = auto`. Все async тесты используют `@pytest.mark.asyncio`. sys.path.insert в conftest.py.
- **TOCTOU Protection**: Phase 7 includes a portfolio recheck to prevent race conditions between asyncio tasks.
- **Dynamic column names**: pandas-ta generates column names with parameters (e.g., `MACD_8_21_5`). `indicators/engine.py` resolves them dynamically; verify prefixes on pandas-ta upgrades.

---

## 29. Changelog

### v1.1.1 (2026-09-07) — Audit Fixes (Astra A06–A22)

**Исправления кода (8 changes, 6 files):**

| ID | Приоритет | Файл | Суть |
|----|-----------|------|------|
| A08 | P0 | `strategy/probability_engine.py` | `expected_rr = p*b - (1-p)` (было `rr*p*1.1`), `PF = p*b/(1-p)` (было `p*expected_rr/q` — вероятность дважды). Исправлено в rules и ML ветках. |
| A09 | P0 | `risk/engine.py` | EV gate для **обоих** режимов: `p*rr - (1-p) <= 0 → NEGATIVE_EV`. Раньше только Kelly. |
| A10 | P0 | `risk/engine.py` | Min-notional: `quantity * entry_price` (было `equity*risk/entry` — неверная размерность). Добавлен `loss_per_unit = risk_dist`. |
| A13 | P0 | `risk/position_manager.py` | `ExitPlan` dataclass + `create_exit_plan()` factory. Связывает TradeEngine TP с PositionManager partial close. `ManagedPosition.exit_plan` field. |
| A15 | P0 | `risk/position_manager.py`, `scheduler/outcome_tracker.py` | Mirror-correct docstrings для long/short. Trailing/BE/SL уже были зеркальными — исправлены описания. |
| A12 | P1 | `scheduler/scanner.py` | `[SHADOW]` → `[OVERLAY]` (14 мест). Переименовано: shadow engines → analytical overlays. |
| A22 | P1 | `storage/trace.py` | `_full_feature_vector` — полный 53-feature вектор в `hypothesis_snapshot["full_features"]` для ML replay. |
| A06 | P1 | `market_structure/htf_bias_v2.py` | Single-TF conviction: 1 directional + 2 neutral → WEAK (было NEUTRAL). Добавлен `confidence` field. |

**Обновлённая документация:**
- Section 13: Исправлены формулы expected_rr и PF
- Section 14.2: Добавлен EV gate, исправлен min-notional
- Section 11: Shadow → Analytical Overlays
- Section 12: Добавлен A22 full feature vector
- Section 8.1.45: Обновлён voting + confidence formula
- Section 23: Добавлен ExitPlan

**Тесты**: 442 passed, 1 pre-existing failure (exchange config mismatch)

---

### v1.1.0 (2026-09-07) — Полный аудит по исходному коду
- **Audit**: Полная проверка по исходному коду (18 модулей)
- **Найдено и добавлено:**
  - TOCTOU recheck portfolio limits в Phase 7
  - Audit codes: `NEGATIVE_EV`, `POSITION_SIZE_BELOW_MIN` (не были в v1.0)
  - Min Notional Check в Risk Engine
  - Kelly negative EV blocking (kelly ≤ 0 → reject)
  - 53 features (было ~35–50 — уточнено)
  - Полный реестр 46 reason codes (было ~35)
  - Elliott Wave config params (7 params)
  - Per-TF time-stop values
  - Dynamic indicator column naming conventions
  - Trace FEATURE_KEYS (35 tracked fields)
  - Daily limits state management (atomic try_open_trade)
  - Outcome tracker fetch-failure cooldown (3 failures → 10min)
  - OB retest confirmation candle details (engulfing + pin-bar)
  - SMT Divergence algorithm details (micro-trend, 30min cache)
  - HTF Bias V2 confidence formula + BOS boost
  - Breakout Quality verdict edge cases
  - Circuit breaker integration
  - Scan lock mechanism
  - `block_neutral_htf` flag exists but unused
  - ATR per-TF overrides (`atr_multipliers_per_tf`)
  - PnL calculation details (costs, funding, MFE/MAE)
  - Close reason normalization logic
- **Исправления:**
  - `SL_ATR_MIN_RELAXED` → `SL_ATR_CONFLICT` (точное имя из кода)
  - Confirmation score min 2 → отмечена как потенциальная проблема
  - Kelly caps at `base_risk_pct` — Kelly может только уменьшить
  - Premium/Discount: PF 1.28→0.91, рекомендация включить после 500+ trades
