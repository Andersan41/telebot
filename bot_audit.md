# ПОЛНЫЙ АУДИТ ТОРГОВОГО БОТА v2.5.0

> **Дата аудита**: 2026-09-08
> **Версия**: 2.5.0 (`config/settings.py:15`)
> **Цель**: Абсолютно полное описание архитектуры, логики, фильтров и поведения бота — для передачи другой модели ИИ с целью модернизации.
> **Стек**: Python 3.11, ccxt, pandas-ta, SQLAlchemy async, python-telegram-bot 20.x, SQLite, APScheduler
> **Стратегия**: ICT (Inner Circle Trader) — 4-layer pipeline: Pattern Engine → Feature Builder → Probability Engine → Risk Engine

---

## СОДЕРЖАНИЕ

1. [Архитектура и точки входа](#1-архитектура-и-точки-входа)
2. [Расписание и частота сканирования](#2-расписание-и-частота-сканирования)
3. [Таймфреймы и их поведение](#3-таймфреймы-и-их-поведение)
4. [Пайплайн сканирования (scan_symbol_v2) — полная карта](#4-пайплайн-сканирования-scan_symbol_v2--полная-карта)
5. [Фаза 0: Hard Gates (защита капитала)](#5-фаза-0-hard-gates-защита-капитала)
6. [Фаза 1: Pattern Engine — детекция ICT сетапов](#6-фаза-1-pattern-engine--детекция-ict-сетапов)
7. [Фаза 1.4–1.45: Setup-Type-Specific Gates](#7-фаза-14-145-setup-type-specific-gates)
8. [Фаза 1.5: Trade Engine — построение плана входа](#8-фаза-15-trade-engine--построение-плана-входа)
9. [Фаза 2: Feature Builder — сбор признаков](#9-фаза-2-feature-builder--сбор-признаков)
10. [Фаза 3: Probability Engine — оценка P(TP)](#10-фаза-3-probability-engine--оценка-ptp)
11. [Фаза 4: Risk Engine — размер позиции и защита](#11-фаза-4-risk-engine--размер-позиции-и-защита)
12. [Фаза 4.5: Entry Trigger Check](#12-фаза-45-entry-trigger-check)
13. [Фаза 5: Построение SignalResult](#13-фаза-5-построение-signalresult)
14. [Фаза 6: Dedup (антидубли)](#14-фаза-6-dedup-антидубли)
15. [Фаза 7–8: Сохранение, исполнение, уведомление](#15-фаза-78-сохранение-исполнение-уведомление)
16. [HTF Bias — высокотаймфреймовое направление](#16-htf-bias--высокотаймфреймовое-направление)
17. [Analytical Overlays (Market Thesis, Scenario, Phase)](#17-analytical-overlays-market-thesis-scenario-phase)
18. [Индикаторы — расчёт и использование](#18-индикаторы--расчёт-и-использование)
19. [Ликвидность: sweeps, order blocks, FVG](#19-ликвидность-sweeps-order-blocks-fvg)
20. [Kонтекст: Fear & Greed, Funding, Correlation](#20-контекст-fear--greed-funding-correlation)
21. [Позиционирование и управления рисками](#21-позиционирование-и-управление-рисками)
22. [Cooldown и антидублирование](#22-cooldown-и-антидублирование)
23. [Audit logging и трассировка](#23-audit-logging-и-трассировка)
24. [Все причины блокировки (46 reason codes)](#24-все-причины-блокировки-46-reason-codes)
25. [Полный реестр конфигурации](#25-полный-реестр-конфигурации)
26. [Write-only правила (нельзя удалить без анализа)](#26-write-only-правила)
27. [write-only поля конфигурации](#27-write-only-поля-конфигурации)
28. [Известные проблемы и рекомендации](#28-известные-проблемы-и-рекомендации)
29. [Changelog](#29-changelog)

---

## 1. Архитектура и точки входа

### Точка входа: `main.py`

```
main.py
  → db.init()                          # SQLite (aiosqlite)
  → refresh_runtime_symbols()          # подгрузка символов из .env
  → exchange_client.connect()          # ccxt AsyncExchange (BingX/Binance)
  → start_web_server()                 # дашборд (port 3002)
  → Application.builder().build()      # Telegram bot
  → TaskScheduler(notify_callback)     # APScheduler
  → outcome_tracker_loop()             # фоновый трекинг исходов
  → app.updater.start_polling()        # Telegram polling
```

**Lock-файл**: `.trading_bot.lock` — защита от повторного запуска. PID-проверка через `os.kill(0)`.

### Модули проекта

| Модуль | Файлов | Описание |
|--------|--------|----------|
| `config/` | `settings.py` | Все пороги в одном dataclass. Горячая перезагрузка через `reload_config()`. |
| `strategy/` | `pattern_engine.py`, `feature_builder.py`, `probability_engine.py`, `trade_engine.py`, `htf_poi.py`, `signal_engine.py`, `confirmation_engine.py`, `entry_trigger.py`, `hypothesis.py`, `decision_engine.py`, `market_thesis_engine.py`, `scenario_engine.py`, `market_phase_engine.py`, `scenario_memory.py`, `weight_manager.py`, `invalidation.py`, `trade_plan.py` | Вся логика принятия решений |
| `risk/` | `engine.py`, `position_manager.py`, `daily_limits.py`, `circuit_breaker.py`, `market_regime.py`, `volatility_regime.py` | Управление рисками и позициями |
| `indicators/` | `engine.py` | Расчёт EMA, RSI, MACD, ADX, ATR, Supertrend, Volume SMA |
| `market_structure/` | `structure.py`, `htf_bias.py`, `htf_bias_v2.py`, `premium_discount.py` | Swing points, BOS/CHoCH, HTF bias, Premium/Discount |
| `liquidity/` | `sweep.py`, `order_blocks.py`, `fvg.py`, `candle_quality.py`, `breakout_quality.py`, `ob_state.py`, `pool.py`, `equal_levels.py`, `external.py` | Все виды ликвидности |
| `context/` | `fetcher.py`, `analyzer.py`, `scorer.py` | Fear & Greed, Funding, OI, Correlation |
| `derivatives/` | `smt_divergence.py`, `funding_rate.py`, `open_interest.py` | Деривативы |
| `storage/` | `database.py`, `models.py`, `trace.py`, `audit_reasons.py` | SQLite ORM, DecisionTrace, 46 reason codes |
| `scheduler/` | `scanner.py` (2200 строк), `tasks.py`, `outcome_tracker.py`, `circuit_breaker.py` | Пайплайн, расписание, трекинг |
| `bot/` | `handlers.py`, `notifier.py` | Telegram команды и уведомления |
| `data/` | `exchange_client.py` | ccxt обёртка |
| `monitoring/` | `metrics.py` | Prometheus метрики |
| `elliott_wave/` | `analysis.py`, `wave_types.py` | Elliott Wave (мягкий фича) |

### Синглтоны

Почти все компоненты — синглтоны на уровне модуля:
```python
pattern_engine = PatternEngine()
feature_builder = FeatureBuilder()
probability_engine = ProbabilityEngine()
risk_engine = RiskEngine.from_config()
trade_engine = TradeEngine()
indicator_engine = IndicatorEngine()
context_engine = ContextEngine()
```

**Исключение**: `ContextFetcher` — имеет внутренний state (`_fng_cache`, `_trending_cache`, `_last_oi`). Тесты должны создавать свежий экземпляр.

---

## 2. Расписание и частота сканирования

### Cron-расписание (APScheduler)

| Job ID | Cron | Описание |
|--------|------|----------|
| `scan_all_tfs` | `:02, :17, :32, :47` (каждые 15 мин) | `run_scan_cycle()` — сканирует все `primary_timeframes` |
| `daily_report` | `00:05 UTC` | Ежедневный отчёт в Telegram |
| `ml_retrain` | `03:00 UTC` | Переобучение ML модели |

### Как работает цикл сканирования

```python
run_scan_cycle()
  → check_recent_losses()              # проверка circuit breaker
  → is_circuit_breaker_active()        # пропуск цикла если active
  → get_active_symbols()               # из .env: BTC/USDT,ETH/USDT,SOL/USDT
  → get_disabled_symbols()             # исключения из БД
  → for symbol × timeframe:
      scan_symbol_v2(symbol, tf, notify_callback)  # параллельно через asyncio.gather
  → funnel summary                     # статистика воронки
```

**Lock**: `_scan_lock` (asyncio.Lock) — предотвращает параллельные циклы. Если текущий цикл ещё работает, следующий пропускается.

### Множественное сканирование за цикл

За один cron-триггер сканируются **все символы × все таймфреймы** параллельно:
```python
tasks = []
for symbol in symbols:      # BTC/USDT, ETH/USDT, SOL/USDT
    for tf in tfs:          # 1h, 4h
        tasks.append(scan_symbol_v2(symbol, tf, ...))
results = await asyncio.gather(*tasks, return_exceptions=True)
```

---

## 3. Таймфреймы и их поведение

### Основные таймфреймы

| Таймфрейм | Cooldown | Поведение |
|-----------|----------|-----------|
| `1h` | 45 мин (default) | Основной TF для поиска сетапов. Частые сигналы. |
| `4h` | 45 мин (default) | Более крупные сетапы. Реже срабатывает из-за HTF фильтров. |

**Default**: `PRIMARY_TIMEFRAMES=1h,4h`

### Cooldown по TF

```
effective_cooldown = max(base_minutes=45, tf_minutes × multiplier=2.0)
1h:  max(45, 60×2.0) = 120 мин
4h:  max(45, 240×2.0) = 480 мин
```

### Multi-TF mode (опционально)

Если `SCAN_MODE=multi_tf` и `CONFIRM_TF_ENABLED=true`:
- Основной TF (1h) определяет сетап
- Confirm TF (5m) подтверждает вход свечой (engulfing/pin-bar)
- Если нет подтверждения на 5m → сигнал блокируется

**Default**: `SCAN_MODE=single_tf` (multi-TF отключён)

### HTF для Bias

Для HTF Bias V2 запрашиваются:
- `1w` (W1) — недельный bias
- `1d` (D1) — дневной bias
- `4h` (H4) — 4-часовой bias
- `1h` (H1) — для zone classification

---

## 4. Пайплайн сканирования (scan_symbol_v2) — полная карта

`scan_symbol_v2()` — основная функция, 2200 строк, содержит ~30 gate checks.

### Визуальная схема воронки

```
Symbol + Timeframe
    │
    ▼
[Phase 0.1] Cooldown ──────────────────── BLOCKED? → return None
    │
    ▼
[Phase 0.2] Portfolio Risk ────────────── BLOCKED? → return None
    │
    ▼
[Phase 0.2b] Daily Limits ────────────── BLOCKED? → return None
    │
    ▼
[Phase 0.2c] Position Limits ─────────── BLOCKED? → return None
    │
    ▼
[Phase 0.3] Fetch OHLCV + Indicators ── BLOCKED? → return None
    │
    ▼
[Phase 0.4] Volatility Filter ────────── BLOCKED? → return None
    │
    ▼
[Phase 1] Pattern Engine ─────────────── No setup? → return None
    │
    ▼
[Phase 1.4] Setup-Type Gates ─────────── BLOCKED? → return None
    │  Reversal: sweep + displacement + MSS
    │  Continuation: BOS + trend alignment
    │
    ▼
[Phase 1.41] Breakout Quality ────────── BLOCKED? → return None (if hard_gate)
    │
    ▼
[Phase 1.42] OB Retest + Mitigation ─── BLOCKED? → return None (if require_ob_retest)
    │
    ▼
[Phase 1.42] Confirmation Score ──────── BLOCKED? → return None
    │
    ▼
[Phase 1.43] Session Filter ─────────── BLOCKED? → return None (if session_hard_gate)
    │
    ▼
[Phase 1.44] SMT Divergence ──────────── soft (log only)
    │
    ▼
[Phase 1.45] HTF Bias ────────────────── BLOCKED? → return None
    │  Short in bullish HTF → block
    │  Long in bearish HTF → block
    │  Continuation vs HTF → block
    │
    ▼
[Phase 1.5] HTF POI Detection ────────── soft (SL override)
    │
    ▼
[Phase 1.5] Trade Engine ─────────────── SL/TP calculation
    │
    ▼
[Phase 1.55] Market Phase (overlay) ──── soft (analytics)
    │
    ▼
[Phase 1.6] Market Thesis (overlay) ──── soft (analytics)
    │
    ▼
[Phase 1.65] Scenario Engine (overlay) ─ soft (analytics)
    │
    ▼
[Phase 1.7] Hypothesis + Decision ────── soft (analytics)
    │
    ▼
[Phase 1.7] LTF Confirmation ─────────── BLOCKED? → return None (if multi_tf)
    │
    ▼
[Phase 2] Feature Builder ────────────── 53 features → SetupFeatures
    │
    ▼
[Phase 3] Probability Engine ─────────── P(TP) estimation
    │
    ▼
[Phase 3.1] min_p_tp Gate ────────────── BLOCKED? → return None
    │
    ▼
[Phase 4] Risk Engine ────────────────── position sizing + hard gates
    │
    ▼
[Phase 4.5] Entry Trigger ────────────── BLOCKED? → return None
    │
    ▼
[Phase 5] Build SignalResult ──────────── signal object
    │
    ▼
[Phase 6] Dedup ──────────────────────── BLOCKED? → return None
    │
    ▼
[Phase 7] Execution Filters ──────────── spread, depth, correlation
    │
    ▼
[Phase 7] TOCTOU Recheck ─────────────── portfolio recheck
    │
    ▼
[Phase 7] Save to DB ─────────────────── save signal
    │
    ▼
[Phase 8] Atomic: outcome + daily limits + cooldown
    │
    ▼
[Phase 8] Notify (Telegram) ──────────── send signal
```

---

## 5. Фаза 0: Hard Gates (защита капитала)

### 0.1 Cooldown

```python
# In ob_aware mode (default) — пропускается, обрабатывается в Phase 6
if cooldown_mode == 'ob_aware':
    return False, 0

# In strict mode — проверка БД
last = await db.get_cooldown(symbol, timeframe)
effective = max(45, tf_minutes * 2.0)
return delta < effective, effective
```

**Coob_aware**: В режиме `ob_aware` (default) ранний cooldown **всегда пропускается**. Реальная проверка — в Phase 6 (Dedup), где сравниваются OB midpoints.

### 0.2 Portfolio Risk

```python
active_count = await db.get_active_signals_count()
if active_count >= max_active_signals:  # default: 10
    return None  # PORTFOLIO_MAX_ACTIVE

portfolio_risk = await db.get_portfolio_risk_sum()
if portfolio_risk >= max_portfolio_risk_pct:  # default: 3.7%
    return None  # PORTFOLIO_MAX_RISK
```

### 0.2b Daily Limits

```python
can_trade, remaining_risk, dl_reason = daily_limits.can_open_trade(
    risk_per_trade_pct=config.risk_engine.base_risk_pct
)
# Проверяет: max_risk_per_day_pct (6%), max_trades_per_day (5), max_drawdown_daily_pct (10%)
```

### 0.2c Position Limits

```python
_active_outcomes = await db.get_open_outcomes()
_total_positions = len(_active_outcomes)
if _total_positions >= max_positions_total:  # default: 5
    return None  # POSITION_LIMIT_HIT
# Direction-specific limits проверяются позже (когда известен direction)
```

### 0.3 Fetch OHLCV + Indicators

```python
df = await exchange_client.fetch_ohlcv(symbol, timeframe, limit=200)
ind = indicator_engine.calculate(df, symbol, timeframe)
# Если df пустой или ind None → DATA_INTEGRITY_FAIL
```

**Важно**: `fetch_ohlcv` отбрасывает последнюю свечу (`df.iloc[:-1]`) — чтобы не сигнализировать по открытому бару.

### 0.4 Volatility Filter

```python
atr_pct = ind.atr / ind.close * 100
if atr_pct < 0.3 or atr_pct > 5.0:
    return None  # VOLATILITY_TOO_LOW / VOLATILITY_TOO_HIGH
```

---

## 6. Фаза 1: Pattern Engine — детекция ICT сетапов

### Два независимых пайплайна

**REVERSAL** (разворот):
```
Sweep → Displacement → MSS → [OB/FVG entry zone] → Entry
```

**CONTINUATION** (продолжение тренда):
```
Trend → Pullback → BOS → [OB/FVG retrace] → Entry
```

### Ключевые концепции

| Компонент | Описание | Как определяется |
|-----------|----------|------------------|
| **Sweep** | Прокол уровня ликвидности (stop hunt) | `liquidity.sweep.detect_sweeps()` — анализ свечных фитилей за swing levels |
| **Displacement** | Сильное движение после sweep | `candle_quality.is_displacement` — тело свечи > 1.5 ATR |
| **MSS** (Market Structure Shift) | Change of Character (CHoCH) | `market_structure.structure.analyze_structure()` — перелом структуры |
| **BOS** (Break of Structure) | Пролом структуры в направлении тренда | Тот же `analyze_structure()` |
| **Order Block** (OB) | Зона институционального.orders | `liquidity.order_blocks.detect_order_blocks()` |
| **FVG** (Fair Value Gap) | Гэп в price action | `liquidity.fvg.detect_fvg()` |

### PatternEngine.detect()

```python
# Сначала пробуем REVERSAL
reversal = self._try_reversal(sweeps, structure, candle_quality, atr, current_price)
if reversal.detected:
    setup_type = "reversal"
else:
    # Затем CONTINUATION
    continuation = self._try_continuation(structure, sweeps)
    if continuation.detected:
        setup_type = "continuation"
```

### _try_reversal() — детальный разбор

```python
# 1. Sweep required
valid_sweeps = [s for s in sweeps if s.is_valid]
# Применяются false sweep filters (§5.3):
#   - max_body_beyond_level (0.3 ATR)
#   - min_wick_beyond_level (0.1%)
#   - min_body_size (0.05%)
#   - max_pool_age_bars (100)
# Выбирается sweep с наибольшей strength

# 2. Displacement (informational, NOT a gate)
# MSS classification уже измеряет displacement >= 1 ATR

# 3. MSS required (strong CHoCH after sweep)
if structure.last_mss is not None:
    has_mss = True
    direction = "buy" if mss.type == "bullish" else "sell"
    sweep_to_mss = mss.candle_index - sweep_candle_index
```

### _try_continuation() — детальный разбор

```python
# 1. Trend required (no ranging)
if trend == "ranging":
    return rejection

# 2. BOS required
if structure.last_bos is not None:
    has_bos = True
    direction = "buy" if bos.type == "bullish" else "sell"

# 3. BOS must break the last swing (§6.3)
# Для BUY: BOS level > last swing high
# Для SELL: BOS level < last swing low

# 4. Trend alignment required
# BUY + bullish trend, SELL + bearish trend
```

### Confirmation Score (§6.4)

```python
# Weighted: BOS=2, FVG=1, OB=1. Minimum score: 2.
score = 0
if has_bos: score += 2
if has_fvg: score += 1
if has_ob:  score += 1
# BOS + что-то ещё = 3+ (проходит)
# Только BOS = 2 (проходит)
# Только FVG или OB = 1 (НЕ проходит)
```

**Замечание**: Минимум 2 означает, что **любой setup с BOS проходит** (2 ≥ 2). Это может быть слишком мягко.

### Entry Armed (мягкий статус)

```python
# Проверяется, но НЕ блокирует
# BUY: цена рядом с OB midpoint (ниже) или внутри bullish FVG
# SELL: цена рядом с OB midpoint (выше) или внутри bearish FVG
# Порог: ob_proximity_pct (2.0%)
```

---

## 7. Фаза 1.4–1.45: Setup-Type-Specific Gates

### Reversal Gates (все обязательные)

| Gate | Условие | Audit Code |
|------|---------|------------|
| Sweep Required | `has_sweep` | `SWEEP_NONE` |
| Displacement Gate | `has_displacement` (если `reversal_require_displacement=true`) | `DISPLACEMENT_MISSING` |
| MSS Gate | `has_mss` | `MSS_NONE` |

### Continuation Gates (все обязательные)

| Gate | Условие | Audit Code |
|------|---------|------------|
| BOS Gate | `has_bos` | `CONTINUATION_NO_BOS` |

### Entry Zone (мягкий/жёсткий)

```python
if not setup.entry_armed:
    if config.require_entry_zone:  # default: false
        return None  # ENTRY_ZONE_BLOCKED
    else:
        logger.debug("Entry not armed — soft mode, signal fires anyway")
```

### Confirmation Score Gate

```python
if _conf_score < 2:
    return None  # CONFIRMATION_LOW
```

### Breakout Quality (Phase 1.41)

```python
if config.breakout_quality_enabled:
    _bq = classify_breakout(df, direction, atr, oi_change_pct)
    # AMD stop-hunt detection: wick pierces range boundary but close retraces inside
    if config.breakout_quality_hard_gate:
        if _bq.verdict == "fake":
            return None  # BREAKOUT_FAKE
```

**Default**: `breakout_quality_hard_gate=false` (shadow log only).

### OB Retest + Mitigation Gate (Phase 1.42)

```python
if config.require_ob_retest:  # default: true
    # Проверки:
    # 1. OB age — если старше max_age и не retested → mitigated
    # 2. OB state (BROKEN / MITIGATED / FRESH)
    # 3. Price touched OB zone
    # 4. Confirmation candle (engulfing или pin-bar)
    if not _ob_gate_passed:
        return None  # OB_RETEST_FAILED
```

### Session Filter (Phase 1.43)

```python
if config.session_hard_gate:  # default: false
    _current_session = _detect_session()
    # Sessions: asian(0-7), london(7-12), overlap(12-16), new_york(16-21), off_hours
    if _current_session not in config.trading_sessions:
        return None  # SESSION_BLOCKED
```

**Default**: `session_hard_gate=false` (сессии не блокируют).

### HTF Bias Gate (Phase 1.45)

```
Если HTF bias = bullish:
  → BLOCK SHORT (block_short_in_bullish_htf=true)
  → CONTINUATION BUY: должен совпадать с HTF
  → REVERSAL BUY: должен совпадать с HTF

Если HTF bias = bearish:
  → BLOCK LONG (block_long_in_bearish_htf=true)
  → CONTINUATION SELL: должен совпадать с HTF
  → REVERSAL SELL: должен совпадать с HTF

Если HTF bias = neutral:
  → пропускает всё (нет directional confirmation)
```

**Audit Codes**: `HTF_SHORT_IN_BULLISH`, `HTF_LONG_IN_BEARISH`, `HTF_CONTINUATION_MISMATCH`, `HTF_REVERSAL_MISMATCH`

---

## 8. Фаза 1.5: Trade Engine — постройка плана входа

### TradeEngine.build_trade_plan()

Заменяет старый `_calculate_sl_tp()`. Подход: **Liquidity-first**.

```
1. Map liquidity (где стопы?)
2. Find idea (какой сетап?)
3. Find invalidation (где идея ломается?)
4. Find targets (куда идёт ликвидность?)
5. Calculate RR (стоит ли?)
6. Choose entry (оптимизировать RR)
```

### Определение SL (Stop Loss)

```python
# Step 1: Find invalidation level
if signal == BUY:
    invalidation = find_invalidation_buy(entry, sweep_lows, ob_lows, swing_lows, bos_level, atr)
else:
    invalidation = find_invalidation_sell(entry, sweep_highs, ob_highs, swing_highs, bos_level, atr)

# Step 2: SL = invalidation level + buffer (35% ATR)
sl_buffer = atr * 0.35
sl = invalidation.level - sl_buffer  # для BUY

# Step 3: Safety — SL за пределами текущей свечи
if sl >= candle_low:
    sl = candle_low - total_buffer  # spread + tick + 15% ATR

# Step 4: HTF POI override
if htf_poi_result.is_near:
    sl = htf_sl_level ± sl_buffer  # SL за HTF структурой
```

**SL Sources** (приоритет):
1. HTF POI (если цена рядом с D1/H4 OB/FVG)
2. Invalidation level (sweep low/high, OB low/high, swing, BOS level)
3. Candle low/high + buffer

### Определение TP (Take Profit)

```python
# Priority chain (type bonus):
targets = {
    "old_high": 2.0,     # внешняя ликвидность
    "old_low": 2.0,
    "equal_high": 1.8,   # равные уровни
    "equal_low": 1.8,
    "ob_bullish": 1.5,   # opposing OB
    "ob_bearish": 1.5,
    "fvg_bullish": 1.2,  # opposing FVG
    "fvg_bearish": 1.2,
    "swept_high": 0.5,   # swept levels
    "swept_low": 0.5,
}

# Fallback: ATR multiplier
tp = entry ± atr * atr_tp  # default: 3.0

# Path clarity check: нет сильных opposing levels между entry и target
```

### Per-TF ATR Multipliers

```python
# JSON config: {"1h": {"sl": 2.0, "tp": 4.0}, "4h": {"sl": 2.5, "tp": 5.0}}
atr_sl = cfg.atr_multipliers_per_tf.get(timeframe, {}).get("sl", 1.5)
atr_tp = cfg.atr_multipliers_per_tf.get(timeframe, {}).get("tp", 3.0)
```

---

## 9. Фаза 2: Feature Builder — сбор признаков

### SetupFeatures — 53 признака

| Категория | Признаки | Описание |
|-----------|----------|----------|
| **ICT Pattern** | `has_bos`, `has_sweep`, `has_ob`, `has_fvg`, `has_displacement`, `has_mss`, `components_count` | Компоненты сетапа |
| **Reversal** | `mss_score`, `mss_causality`, `displacement_atr_ratio`, `sweep_to_mss_bars` | Метрики разворота |
| **Pattern Metrics** | `ob_distance_pct`, `fvg_size_pct`, `sweep_reclaim_speed`, `sweep_strength` | Качество компонентов |
| **Market Structure** | `structure_trend`, `structure_bos_aligned` | Тренд и выравнивание BOS |
| **Volume** | `volume_ratio`, `volume_delta_pct`, `volume_above_avg` | Объём |
| **Volatility** | `atr`, `atr_pct`, `regime` | Волатильность и режим |
| **Indicators** | `rsi`, `adx`, `ema_spread_pct`, `dmi_diff`, `macd_hist_pct` | Сырые значения (для ML) |
| **MTF** | `mtf_aligned`, `mtf_htf_count`, `is_4h_aligned` | Multi-TF |
| **Context** | `fear_greed`, `funding_rate`, `context_score` | Контекст |
| **Risk** | `rr_ratio`, `sl_distance_pct`, `tp_distance_pct` | R:R |
| **Execution** | `session`, `candle_close_pct`, `is_reversal`, `entry_armed` | Исполнение |
| **Soft Multipliers** | `htf_alignment_score`, `premium_discount_score`, `htf_bias_penalty`, `ob_state_multiplier`, `smt_divergence_score` | Мягкие множители |
| **Elliott Wave** | `wave_confidence`, `wave_direction`, `wave_conflict`, `wave_alternatives_count`, `wave_primary_label` | Волновой анализ |

### to_vector() — для ML

```python
# Categorical encoding:
setup_type: {"reversal": 1, "continuation": -1}
structure_trend: {"bullish": 1, "bearish": -1, "ranging": 0}
regime: {"trend": 1, "expansion": 0.5, "range": -0.5, "compression": -1}
session: {"asian": 0, "london": 1, "overlap": 2, "new_york": 3, "off_hours": 4}
```

### to_reasoning() — для логов

Приоритет: MSS > Displacement > Sweep > OB > FVG > HTF > Session.
**Индикаторы (RSI, ADX, EMA) НЕ включаются** — только для ML.

---

## 10. Фаза 3: Probability Engine — оценка P(TP)

### Два режима

1. **Rules-based** (default) — эвристики до накопления 100+ trades
2. **ML-based** (XGBoost/RandomForest) — после обучения на исторических данных

### Rules-based scoring

```python
base = 50.0  # или из scenario_memory.stats.winrate

# Reversal scoring:
sweep: +3.0, displacement: +3.0, MSS: +4.0
MSS quality >70: +2.0, 50-70: +1.0
OB: +1.5, FVG: +1.0, entry_armed: +1.5

# Continuation scoring:
BOS: +3.0, structure_aligned: +2.0
OB: +1.5, FVG: +1.0, entry_armed: +1.5

# Common:
volume > 2.0x: +3.0, > 1.5x: +2.0, > 1.2x: +1.0
MTF aligned: +2.0
session (london/overlap/ny): +1.0
ATR 1-3%: +1.5, >5%: -2.0, <0.5%: -1.5
context > 0.3: +1.0, < -0.3: -1.5

# Regime-adaptive:
expansion + continuation: +2.0
trend + continuation aligned: +2.5
range + reversal: +1.5

# Soft multipliers:
winrate *= (0.5 + 0.5 × htf_alignment_score)
winrate *= (0.5 + 0.5 × premium_discount_score)
winrate *= htf_bias_penalty  # 0.8 если reversal mismatch
winrate *= ob_state_multiplier  # 0.0 = broken OB → reject

# Elliott Wave:
wave_confidence >= 0.4: winrate += wave_confidence × weight
wave_conflict: winrate *= 0.85

winrate = clamp(20.0, 85.0, winrate)
```

### ML-based prediction

```python
# Expected return mode (new):
raw_return = regressor.predict(X)  # predicted expected return
p_tp = sigmoid(raw_return)         # normalize to [0, 1]
p_tp = isotonic.predict(p_tp)      # calibrate

# Legacy mode:
p_tp = classifier.predict_proba(X)[0][1]
expected_rr = rr_model.predict(X)[0]
```

### Расчёт P(TP) → вероятность

```python
p = winrate / 100.0  # e.g. 55% → 0.55
```

### Expected Net R (A08 fix)

```python
expected_net_r = p * b - (1 - p)  # где b = R:R ratio
# Пример: p=0.55, b=2.0 → E[R] = 0.55*2 - 0.45 = 0.65
```

### Profit Factor (A08 fix)

```python
profit_factor = p * b / max(1-p, 0.01)
# Пример: p=0.55, b=2.0 → PF = 1.1 / 0.45 = 2.44
```

### Quality Label

```python
if p_tp >= 0.65: "strong"
elif p_tp >= 0.50: "moderate"
else: "weak"
```

### min_p_tp Gate (Phase 3.1)

```python
# Direction-specific thresholds:
min_p_tp = 0.30        # BUY default
min_p_tp_short = 0.40  # SELL (строже)
min_p_tp_reversal = 0.50  # REVERSAL (самый строгий)

if p_tp < effective_min_p_tp:
    return None  # MIN_P_TP
```

---

## 11. Фаза 4: Risk Engine — размер позиции и защита

### Hard Gates

```python
# 1. Portfolio limits
if active_count >= max_active_signals (10): reject
if total_risk_pct >= max_portfolio_risk_pct (3.7%): reject

# 2. Data integrity
if entry_price <= 0 or sl <= 0 or tp <= 0: reject
if risk_dist <= 0: reject

# 3. R:R minimum (с учётом fees + slippage)
round_trip_cost = (fee + slippage) * 2  # 0.1% total
effective_risk = risk_dist + cost_dist
effective_reward = reward_dist - cost_dist
rr_ratio = effective_reward / effective_risk
if rr_ratio < 2.0: reject  # RR_TOO_LOW

# 4. SL absolute limits
if sl_distance_pct < 0.25%: reject  # SL_TOO_TIGHT
if sl_distance_pct > dynamic_sl_max: reject  # SL_TOO_WIDE
# dynamic_sl_max = max(5.0%, ATR × 2.2), cap ≤ 8.0%

# 5. SL ATR multiplier
if sl_distance_pct < ATR × 2.0: reject  # SL_ATR_CONFLICT
# Если ATR-min > dynamic_max → relaxed (dead zone fix)

# 6. EV Gate (A09: оба режима)
ev = p * b - (1 - p)
if ev <= 0: reject  # NEGATIVE_EV
```

### Position Sizing

```python
# Fixed mode (default):
risk_pct = base_risk_pct  # 1.0%

# Kelly mode:
kelly = (p * b - q) / b
if kelly <= 0: reject  # NEGATIVE_EV
kelly = min(kelly, 0.20)  # half-Kelly cap
kelly *= probability.confidence
risk_pct = min(kelly * 100, base_risk_pct)

# Adjustments:
risk_pct *= scenario_adj      # [0.6, 1.2] из scenario_score
risk_pct *= stability_adj     # [0.7, 1.15] из scenario_stability
risk_pct *= vol_adj           # 0.5 if ATR>4%, 0.75 if ATR>2.5%
risk_pct *= mss_adj           # [0.8, 1.1] из mss_quality
if sl_distance < 1%: risk_pct *= 1.1
if sl_distance > 3%: risk_pct *= 0.8

risk_pct = clamp(min_risk_pct=0.1%, risk_pct, max_risk_pct=2.0%)
```

### Min Notional Check (A10 fix)

```python
risk_budget_quote = equity * risk_pct / 100.0
quantity_base = risk_budget_quote / loss_per_unit
notional_quote = quantity_base * entry_price
if notional_quote < 5.0: reject  # POSITION_SIZE_BELOW_MIN
```

---

## 12. Фаза 4.5: Entry Trigger Check

```python
# Использует Hypothesis (Decision Engine) или SimpleEntryTarget fallback
entry_trigger = EntryTrigger()
trigger_result = entry_trigger.check(
    hypothesis=_entry_target,
    current_price=entry_price,
    bid=_bid,
    ask=_ask,
)
if not trigger_result.triggered:
    return None  # ENTRY_TRIGGER_NO
```

---

## 13. Фаза 5: Построение SignalResult

```python
result = SignalResult(
    signal=SignalType.BUY/SELL,
    symbol=symbol,
    timeframe=timeframe,
    close=ind.close,
    entry_price=entry_price,
    sl=risk_decision.sl_price,
    tp=risk_decision.tp_price,
    reasons=features.to_reasoning(),
    score=features.components_count,
    # + визуальные данные для графиков
)
# Confidence cap: min(85.0, p_tp * 100)
```

---

## 14. Фаза 6: Dedup (антидубли)

### Два режима cooldown

**Strict mode** (`cooldown_mode=strict`):
```python
same_direction and within_cooldown → BLOCKED
cross_direction and within_cooldown/2 → BLOCKED
```

**OB-aware mode** (`cooldown_mode=ob_aware`, default):
```python
# Сравниваем OB midpoints:
ob_distance = abs(new_ob.midpoint - last_ob.midpoint) / last_ob.midpoint

if ob_distance > ob_proximity_pct (0.5%):
    # Different OB → skip cooldown entirely (BYPASS)
else:
    # Same OB → reduced cooldown (1/3 of full)
    reduced_cooldown = full_cooldown // 3
```

### Audit Codes

| Код | Описание |
|-----|----------|
| `DEDUP_OB` | Same OB retest, cooldown active |
| `DEDUP_SAME_DIR` | Same direction, full cooldown |
| `DEDUP_CROSS_DIR` | Cross direction, half cooldown |

---

## 15. Фаза 7–8: Сохранение, исполнение, уведомление

### Execution Filters (Phase 7)

```python
# Spread check
spread_pct = (ask - bid) / bid * 100
if spread_pct > 0.15%: reject  # SPREAD_TOO_WIDE

# Depth check (order book)
total_depth = bid_depth + ask_depth  # within 0.5% of mid
if total_depth < $10,000: reject  # DEPTH_TOO_LOW

# Correlated entry check
if correlated_symbol already open: reject  # CORRELATION_BLOCKED
```

### TOCTOU Recheck

```python
# Повторная проверка portfolio limits перед сохранением
_active_now = await db.get_active_signals_count()
if _active_now >= max_active_signals: reject  # Race condition protection
```

### Atomic Save

```python
# Phase 8: outcome + daily limits + cooldown — atomic
await db.create_outcome(saved_signal.id, risk_pct=risk_decision.risk_pct)
daily_limits.try_open_trade(risk_decision.risk_pct)
await _set_cooldown(symbol, timeframe)
await notify_callback(result, context_verdict)  # Telegram
```

---

## 16. HTF Bias — высокотаймфреймовое направление

### HTF Bias V2 (default: включён)

```python
# Анализ W1 → D1 → H4 → H1
htf_result = get_htf_bias_v2(df_1w, df_1d, df_4h, df_1h)
```

### Majority Voting

```
3/3 одинаковых → STRONG
2/3 одинаковых → MODERATE
1 directional + 2 neutral → WEAK (A06 fix)
1 agreement (pair) → WEAK
Нет соглашения → NEUTRAL
```

### Confidence (EMA-spread based)

```python
confidence = min(|EMA21 - EMA55| / price × 100 × 10, 100)
# Информационный, НЕ statistical confidence
```

### Override Logic

```
W1 конфликтует, но D1+H4 согласны → override (MODERATE)
H4 конфликтует, но W1+D1 согласны → pullback (MODERATE)
```

### HTF Bias V1 (fallback)

```python
if not config.htf_bias_v2:
    _bias_enum = get_htf_bias(df_1d, df_4h, struct_1d, struct_4h)
```

---

## 17. Analytical Overlays (Market Thesis, Scenario, Phase)

**ВАЖНО**: Это НЕ shadow engines. Их выходы (`_thesis_score`, `_thesis_stability`) влияют на sizing через Risk Engine.

### Market Phase Engine

```python
_phase_assessment = _market_phase_engine.assess(
    adx, atr_current, atr_avg, ema_fast, ema_slow, ...
)
# Phases: COMPRESSION, EXPANSION, TREND, RANGE, HIGH_VOL, LOW_VOL
```

### Market Thesis Engine

```python
# Динамический граф ликвидности (кэшируется между циклами)
_liq_graph = market_thesis_engine.build_liquidity_graph(...)
_thesis = DynamicTradeThesis(symbol, timeframe)
_thesis.update(_liq_graph, entry_price, candle_data, atr)

# Оценка сценария
_thesis_opportunity = market_thesis_engine.evaluate_trade_opportunity(...)
# thesis_opportunity.score → _thesis_score → scenario_adj в Risk Engine
```

### Scenario Engine

```python
_new_scenarios = _scenario_engine.detect_scenarios(graph, structure, phase, direction)
for scenario in _new_scenarios[:5]:
    eval_result = probability_engine.estimate_scenario(features, scenario)
    eval_result = weight_manager.adjust(eval_result, symbol, scenario.name)
```

### Hypothesis + Decision Engine

```python
_hypothesis_set = market_thesis_engine.build_hypothesis_set(graph, ...)
_decision = DecisionEngine().decide(hypothesis_set, market_state)
if _decision.trade:
    # direction, narrative_type, quality, confidence, decay_factor, utility
```

### ScenarioMemory

```python
# Records observations and expected metrics for learning
scenario_memory.record_expected(symbol, hypothesis_name, ...)
scenario_memory.record_observation(symbol, scenario_name)
```

---

## 18. Индикаторы — расчёт и использование

### IndicatorEngine.calculate()

Использует `pandas_ta` для расчёта:

| Индикатор | Период | pandas_ta функция |
|-----------|--------|-------------------|
| EMA fast | 8 | `ta.ema(close, length=8)` |
| EMA slow | 21 | `ta.ema(close, length=21)` |
| EMA trend | 55 | `ta.ema(close, length=55)` |
| RSI | 10 | `ta.rsi(close, length=10)` |
| MACD | 8/21/5 | `ta.macd(close, fast=8, slow=21, signal=5)` |
| ADX/DMI | 14 | `ta.adx(high, low, close, length=14)` |
| ATR | 14 | `ta.atr(high, low, close, length=14)` |
| Supertrend | 10/2.5 | `ta.supertrend(high, low, close, length=10, multiplier=2.5)` |
| Volume SMA | 20 | `ta.sma(volume, length=20)` |

### Вычисляемые свойства IndicatorValues

```python
ema_bullish_cross: bool     # fast пересекла slow снизу вверх
ema_bearish_cross: bool     # fast пересекла slow сверху вниз
ema_bullish_alignment: bool # fast > slow > trend
ema_bearish_alignment: bool # fast < slow < trend
macd_bullish_cross: bool    # гистограмма перешла от - к +
macd_bearish_cross: bool    # гистограмма перешла от + к -
volume_above_avg: bool      # volume > volume_sma × 1.5
trend_is_strong: bool       # adx >= 26
```

### Важно: индикаторы НЕ блокируют

В текущей архитектуре индикаторы используются **только как ML-признаки** в Feature Builder. Они НЕ участвуют в hard gates. Все фильтры based на ICT pattern (sweep, BOS, MSS, OB).

---

## 19. Ликвидность: sweeps, order blocks, FVG

### Sweeps (`liquidity.sweep`)

```python
sweeps = detect_sweeps(df, lookback=50)
# Каждый SweepEvent:
#   - type: "bullish" / "bearish"
#   - is_valid: прошёл false sweep filters
#   - strength: 0.0–1.0 (fast_reclaim + high_volume + delta_aligned + displacement)
#   - sweep_low, sweep_high: levels
#   - reclaim_candles: сколько свечей для reclaim
#   - pool_age_bars: возраст пула ликвидности
```

### False Sweep Filters (§5.3)

```python
# Фильтрация ложных sweep:
sweep_max_body_beyond_level: 0.3 ATR  # тело за пределами уровня
sweep_min_wick_beyond_level: 0.1%     # фитиль за пределами
sweep_min_body_size: 0.05%            # минимальный размер тела
sweep_max_pool_age_bars: 100          # максимальный возраст пула
```

### Order Blocks (`liquidity.order_blocks`)

```python
order_blocks = detect_order_blocks(df, lookback=100)
# Каждый OrderBlock:
#   - type: "bullish" / "bearish"
#   - high, low, midpoint
#   - is_valid: не mitigated
#   - retested: был ли ретест
#   - candle_index, timestamp
```

### OB State (`liquidity.ob_state`)

```python
# Три состояния:
OBState.FRESH     # новый, не тестировался
OBState.RETESTED  # цена вернулась, есть подтверждение
OBState.BROKEN    # цена прошла сквозь
OBState.MITIGATED # частично заполнен

# Multiplier:
FRESH → 1.0–1.2
RETESTED → 0.8–1.0
BROKEN → 0.0 (сигнал отклоняется)
```

### FVG (`liquidity.fvg`)

```python
fvgs = detect_fvg(df, lookback=100)
# Каждый FairValueGap:
#   - type: "bullish" / "bearish"
#   - top, bottom: границы гэпа
#   - is_active: не заполнен
#   - size_pct: размер как % от цены
```

### Candle Quality (`liquidity.candle_quality`)

```python
candle_quality = analyze_last_candle(df, atr_value)
# CandleQuality:
#   - is_displacement: body > 1.5 ATR
#   - body_pct, body_atr_ratio
#   - close_position: 0.0 (low) – 1.0 (high)
#   - wick_ratio
```

### Breakout Quality (`liquidity.breakout_quality`)

```python
_bq = classify_breakout(df, direction, atr, oi_change_pct)
# BreakoutQuality:
#   - verdict: "real" / "fake"
#   - score: 0–100
#   - body_pct, retention, volume_ratio
#   - triggers, warnings
```

---

## 20. Kонтекст: Fear & Greed, Funding, Correlation

### Context Fetcher

```python
snapshot = await context_engine.get_snapshot(symbol)
# Snapshot:
#   - fear_greed_value: 0–100
#   - funding_rate: float
#   - open_interest: float
#   - btc_trend: "bullish" / "bearish"
```

### Context Scorer

```python
context_verdict = context_scorer.score(direction, snapshot)
# ContextVerdict:
#   - score: [-1, 1]
#   - verdict: "BULLISH" / "BEARISH" / "NEUTRAL"
#   - reasoning: list[str]
```

### BTC Global Trend Filter

```python
if config.derivatives.btc_global_trend_filter:
    # Block BUY if BTC below daily EMA200
    # Block SELL if BTC above daily EMA200
```

### SMT Divergence

```python
_smt_result = await fetch_smt_divergence(symbol)
# SMTResult:
#   - direction: "bullish" / "bearish" / None
#   - detail: str
# Soft feature → score [-1.0, 1.0]
```

---

## 21. Позиционирование и управления рисками

### RiskConfig

| Параметр | Default | Описание |
|----------|---------|----------|
| `base_risk_pct` | 1.0% | Риск на сделку (fixed mode) |
| `max_risk_per_day_pct` | 6.0% | Макс. суммарный риск в день |
| `max_trades_per_day` | 5 | Макс. число сделок в день |
| `max_consecutive_losses` | 3 | Circuit breaker |
| `max_drawdown_daily_pct` | 10.0% | Макс. просадка в день |
| `max_positions_total` | 5 | Общее число позиций |
| `max_long_positions` | 3 | Макс. лонгов |
| `max_short_positions` | 3 | Макс. шортов |
| `max_active_signals` | 10 | Одновременных сигналов |
| `max_portfolio_risk_pct` | 3.7% | Суммарный риск портфеля |

### Circuit Breaker

```python
# Активируется после max_consecutive_losses (3) убытков подряд
# Сбрасывается через 24 часа или приircuit_breaker_reset
if is_circuit_breaker_active():
    logger.warning("Scan skipped — circuit breaker active")
    return
```

### Daily Limits (atomic)

```python
can_trade, remaining_risk, dl_reason = daily_limits.can_open_trade(risk_per_trade_pct)
# Проверяет:
# - risk_used_today + risk_per_trade > max_risk_per_day_pct
# - trades_today >= max_trades_per_day
# - drawdown_today >= max_drawdown_daily_pct
```

---

## 22. Cooldown и антидублирование

### Cooldown Matrix

| Режим | Same Direction | Cross Direction | Different OB |
|-------|---------------|-----------------|--------------|
| `strict` | Full cooldown (120m for 1h) | Half cooldown (60m) | Full cooldown |
| `ob_aware` (default) | Reduced (1/3 if same OB) | Half cooldown | **BYPASS** |

### Cooldown Duration

```
effective = max(base=45min, tf_minutes × 2.0)
1h: 120 min
4h: 480 min
```

### OB-Aware Logic

```python
if cooldown_mode == 'ob_aware' and last.ob_midpoint and new_ob:
    ob_distance = abs(new_ob.midpoint - last.ob_midpoint) / last.ob_midpoint
    if ob_distance > ob_proximity_pct (0.5%):
        # Different OB → signal allowed even within cooldown
    else:
        # Same OB → reduced cooldown (1/3)
```

---

## 23. Audit logging и трассировка

### DecisionTrace

```python
trace = DecisionTraceBuilder(symbol, timeframe)
trace.passed("cooldown")
trace.blocked("portfolio_risk", "max active signals (10/10)")
trace.set_features(features.to_vector())
trace.set_version(VERSION)
await trace.save(db, signal_id=saved_signal.id)
```

### Audit Log Table

```sql
CREATE TABLE signal_audit_log (
    id, symbol, timeframe, ts_event, config_version,
    stage, reason_code, passed,
    setup_type, direction, features_snapshot, meta,
    as_of_utc, is_final, data_age_ms
);
```

### Funnel Logging

```python
# Каждый gate логируется:
_current_funnel.log_gate(symbol, timeframe, "cooldown", "PASS")
_current_funnel.log_gate(symbol, timeframe, "portfolio_risk", "BLOCKED", "max active signals")

# Summary в конце цикла:
[FUNNEL SUMMARY] entered=6, sent=1, cooldown=2, portfolio_risk=1, risk_engine=1
```

---

## 24. Все причины блокировки (46 reason codes)

| # | Code | Stage | Описание |
|---|------|-------|----------|
| 1 | `COOLDOWN_ACTIVE` | cooldown | Cooldown не истёк |
| 2 | `PORTFOLIO_MAX_ACTIVE` | portfolio_risk | Достигнут лимит активных сигналов |
| 3 | `PORTFOLIO_MAX_RISK` | portfolio_risk | Достигнут лимит суммарного риска |
| 4 | `DAILY_LIMIT_HIT` | daily_limits | Дневной лимит (сделки/риск/drawdown) |
| 5 | `POSITION_LIMIT_HIT` | position_limits | Достигнут лимит позиций |
| 6 | `DATA_INTEGRITY_FAIL` | indicators | OHLCV/индикаторы недоступны |
| 7 | `VOLATILITY_TOO_LOW` | volatility_filter | ATR < 0.3% |
| 8 | `VOLATILITY_TOO_HIGH` | volatility_filter | ATR > 5.0% |
| 9 | `PATTERN_NO_SETUP` | pattern_engine | Нет ICT сетапа |
| 10 | `SWEEP_NONE` | pattern_engine | Sweep не обнаружен |
| 11 | `SWEEP_FALSE_FILTERED` | pattern_engine | Sweep отфильтрован |
| 12 | `DISPLACEMENT_MISSING` | displacement_gate | Нет displacement |
| 13 | `MSS_NONE` | mss_gate | MSS не обнаружен |
| 14 | `MSS_DIRECTION_UNCLEAR` | mss_gate | Направление MSS неясно |
| 15 | `CONTINUATION_RANGING` | pattern_engine | Рынок в ranging |
| 16 | `CONTINUATION_NO_BOS` | bos_gate | BOS не обнаружен |
| 17 | `CONTINUATION_BOS_NOT_BREAKING` | bos_gate | BOS не пробил swing |
| 18 | `CONTINUATION_BOS_VS_TREND` | bos_gate | BOS против тренда |
| 19 | `ENTRY_ZONE_BLOCKED` | entry_zone | Цена не в OB/FVG зоне |
| 20 | `BREAKOUT_FAKE` | breakout_quality | AMD fake-break |
| 21 | `CONFIRMATION_LOW` | confirmation_score | Score < 2 |
| 22 | `OB_RETEST_FAILED` | ob_retest | OB не прошёл retest |
| 23 | `OB_TOO_OLD` | ob_retest | OB слишком старый |
| 24 | `OB_BROKEN` | ob_retest | OB сломан |
| 25 | `OB_MITIGATED` | ob_retest | OB mitigated |
| 26 | `OB_TOO_FAR` | ob_retest | OB слишком далеко |
| 27 | `OB_NOT_RETESTED` | ob_retest | OB не retested |
| 28 | `OB_NO_CONFIRMATION` | ob_retest | Нет confirmation candle |
| 29 | `SESSION_BLOCKED` | session_filter | Вне торговой сессии |
| 30 | `HTF_SHORT_IN_BULLISH` | htf_bias | SHORT в bullish HTF |
| 31 | `HTF_LONG_IN_BEARISH` | htf_bias | LONG в bearish HTF |
| 32 | `HTF_CONTINUATION_MISMATCH` | htf_bias | Continuation vs HTF |
| 33 | `HTF_REVERSAL_MISMATCH` | htf_bias | Reversal vs HTF |
| 34 | `SL_TP_FAILED` | sl_tp | Расчёт SL/TP не удался |
| 35 | `LTF_NO_CONFIRMATION` | confirm_tf | Нет подтверждения на 5m |
| 36 | `LTF_DATA_UNAVAILABLE` | confirm_tf | 5m OHLCV недоступен |
| 37 | `MIN_P_TP` | min_p_tp | P(TP) < min threshold |
| 38 | `RR_TOO_LOW` | risk_engine | R:R < 2.0 |
| 39 | `SL_TOO_TIGHT` | risk_engine | SL < 0.25% |
| 40 | `SL_TOO_WIDE` | risk_engine | SL > dynamic max |
| 41 | `SL_ATR_CONFLICT` | risk_engine | SL < 2× ATR |
| 42 | `POSITION_SIZE_BELOW_MIN` | risk_engine | Notional < $5 |
| 43 | `NEGATIVE_EV` | risk_engine | EV ≤ 0 |
| 44 | `ENTRY_TRIGGER_NO` | entry_trigger | Entry trigger не сработал |
| 45 | `SPREAD_TOO_WIDE` | execution_filter | Spread > 0.15% |
| 46 | `DEPTH_TOO_LOW` | depth_check | Depth < $10,000 |
| 47 | `CORRELATION_BLOCKED` | correlated_entry | Корреляционный вход |

---

## 25. Полный реестр конфигурации

### TelegramConfig

| Параметр | Env | Default |
|----------|-----|---------|
| `token` | `TELEGRAM_BOT_TOKEN` | — |
| `channel_id` | `TELEGRAM_CHANNEL_ID` | — |
| `admin_ids` | `TELEGRAM_ADMIN_IDS` | — |

### ExchangeConfig

| Параметр | Env | Default |
|----------|-----|---------|
| `name` | `EXCHANGE` | `bingx` |
| `api_key` | `EXCHANGE_API_KEY` | — |
| `api_secret` | `EXCHANGE_API_SECRET` | — |
| `testnet` | `USE_TESTNET` | `false` |
| `market_type` | `MARKET_TYPE` | `swap` |

### TradingConfig

| Параметр | Env | Default |
|----------|-----|---------|
| `symbols` | `SYMBOLS` | `BTC/USDT,ETH/USDT,SOL/USDT` |
| `primary_timeframes` | `PRIMARY_TIMEFRAMES` | `1h,4h` |
| `scan_mode` | `SCAN_MODE` | `single_tf` |
| `confirm_timeframe` | `CONFIRM_TIMEFRAME` | `5m` |
| `ema_fast/slow/trend` | `EMA_FAST/SLOW/TREND` | `8/21/55` |
| `rsi_period` | `RSI_PERIOD` | `10` |
| `adx_min` | `ADX_MIN` | `26` |
| `atr_period` | `ATR_PERIOD` | `14` |
| `atr_multiplier_sl/tp` | `ATR_MULTIPLIER_SL/TP` | `1.5/3.0` |
| `candles_limit` | `CANDLES_LIMIT` | `200` |
| `min_rr_threshold` | `MIN_RR_THRESHOLD` | `1.5` |
| `max_spread_percent` | `MAX_SPREAD_PERCENT` | `0.15` |
| `min_depth_0_5_percent` | `MIN_DEPTH_0_5_PERCENT` | `10000` |
| `volatility_min/max_atr_percent` | `VOLATILITY_MIN/MAX_ATR_PERCENT` | `0.3/5.0` |

### RiskConfig

| Параметр | Env | Default |
|----------|-----|---------|
| `risk_strong_pct` | `RISK_STRONG_PCT` | `1.0` |
| `risk_moderate_pct` | `RISK_MODERATE_PCT` | `0.5` |
| `max_risk_per_day_pct` | `MAX_RISK_PER_DAY_PCT` | `6.0` |
| `max_trades_per_day` | `MAX_TRADES_PER_DAY` | `5` |
| `max_positions_total` | `MAX_POSITIONS_TOTAL` | `5` |

### RiskEngineConfig

| Параметр | Env | Default |
|----------|-----|---------|
| `min_rr_ratio` | `RISK_ENGINE_MIN_RR` | `2.0` |
| `sl_absolute_min_pct` | `RISK_ENGINE_SL_MIN_PCT` | `0.25` |
| `sl_absolute_max_pct` | `RISK_ENGINE_SL_MAX_PCT` | `5.0` |
| `base_risk_pct` | `RISK_ENGINE_BASE_RISK_PCT` | `1.0` |

### ProbabilityConfig

| Параметр | Env | Default |
|----------|-----|---------|
| `min_p_tp` | `MIN_P_TP` | `0.30` |
| `min_p_tp_short` | `MIN_P_TP_SHORT` | `0.40` |
| `min_p_tp_reversal` | `MIN_P_TP_REVERSAL` | `0.50` |

### AppConfig (Feature Flags)

| Параметр | Env | Default | Описание |
|----------|-----|---------|----------|
| `htf_hard_gate` | `HTF_HARD_GATE` | `true` | HTF bias блокирует |
| `htf_bias_v2` | `HTF_BIAS_V2` | `true` | V2 HTF bias |
| `premium_discount` | `PREMIUM_DISCOUNT` | `false` | Premium/Discount zones |
| `require_entry_zone` | `REQUIRE_ENTRY_ZONE` | `false` | Требовать OB/FVG зону |
| `require_ob_retest` | `REQUIRE_OB_RETEST` | `true` | Требовать OB retest |
| `session_hard_gate` | `SESSION_HARD_GATE` | `false` | Block outside kill zones |
| `block_neutral_htf` | `BLOCK_NEUTRAL_HTF` | `true` | Block на neutral HTF |
| `block_short_in_bullish_htf` | `BLOCK_SHORT_IN_BULLISH_HTF` | `true` | |
| `block_long_in_bearish_htf` | `BLOCK_LONG_IN_BEARISH_HTF` | `true` | |
| `risk_mode` | `RISK_MODE` | `fixed` | kelly/fixed |
| `cooldown_mode` | `COOLDOWN_MODE` | `ob_aware` | strict/ob_aware |
| `max_active_signals` | `MAX_ACTIVE_SIGNALS` | `10` | |
| `signal_cooldown_minutes` | `SIGNAL_COOLDOWN_MINUTES` | `45` | |

---

## 26. Write-only правила

Все 46 reason codes в `storage/audit_reasons.py` — write-only. Удалять коды нельзя (audit log ссылается на них).

---

## 27. write-only поля конфигурации

| Поле | Где записывается | Описание |
|------|-----------------|----------|
| `config_version` | `signal_audit_log` | Версия конфига для A/B анализа |
| `_CONFIG_VERSION` | `scheduler/scanner.py` | Bump при изменении任何 threshold |
| `VERSION` | `config/settings.py:15` | Версия стратегии |

---

## 28. Известные проблемы и рекомендации

### Критические

1. **Confirmation Score min 2**: Любой setup с BOS проходит (2 ≥ 2). Рекомендация: увеличить до 3.

2. **Premium/Discount выключен**: A/B показал ухудшение (PF 1.28→0.91). Включить после 500+ live trades.

3. **Kelly caps at base_risk_pct**: Kelly может только уменьшить риск, но не увеличить. Рекомендация: проверить, работает ли это как задумано.

### Архитектурные

4. **Context fetcher singleton state**: `_fng_cache`, `_trending_cache`, `_rss_cache`, `_last_oi`. Тесты должны создавать свежий экземпляр.

5. **`exchange_client.fetch_ohlcv` drops last candle** (`df.iloc[:-1]`) — чтобы не сигнализировать по открытому бару.

6. **`block_neutral_htf` флаг существует, но нейтральный HTF всегда пропускает** — фактически не работает.

7. **OB-aware cooldown**: В `ob_aware` режиме early cooldown gate **всегда пропускает**. Если у символа нет OB, cooldown фактически не работает.

### Инженерные

8. **pandas-ta columns**: Supertrend → `SUPERT_…` / `SUPERTd_…`; ADX → `ADX_…`, `DMP_…`, `DMN_…`. Динамический резолв.

9. **Telegram HTML**: `parse_mode=ParseMode.HTML` требует `html.escape()` на каждом динамическом подстроке — bare `<` крашит парсер.

10. **Windows asyncio**: `WindowsSelectorEventLoopPolicy` для совместимости.

---

## 29. Changelog

### v2.5.0 (2026-09-08) — Полный аудит

- Полное описание архитектуры, пайплайна, всех gate checks
- 47 reason codes задокументированы
- Все параметры конфигурации с defaults
- Write-only правила описаны
- Известные проблемы и рекомендации

### Предыдущие изменения

- **A08** (2026-09-07): `expected_rr` и `profit_factor` формулы исправлены
- **A09** (2026-09-07): EV gate для обоих risk modes
- **A10** (2026-09-07): Min-notional dimension исправлена
- **A12** (2026-09-07): Shadow → Analytical Overlays
- **A13** (2026-09-07): ExitPlan dataclass + factory
- **A15** (2026-09-07): Mirror-correct docstrings
- **A22** (2026-09-07): Full 53-feature vector in Trace
- **A06** (2026-09-07): Single-TF conviction → WEAK
