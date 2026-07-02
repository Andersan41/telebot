# Signal Pipeline — Complete Reference

> Для анализа старшей моделью. Охватывает весь pipeline от OHLCV до Telegram.
> Дата: 2026-07-02
> Версия: Update 7 (new pipeline)

---

## 0. NEW ARCHITECTURE (v2 pipeline)

**Current production pipeline:** `scan_symbol_v2()` in `scheduler/scanner.py`.
Old `scan_symbol()` retained for reference.

```
Pattern Engine → Feature Builder → Probability Engine → Risk Engine → Telegram
```

### Layer 1: Pattern Engine (`strategy/pattern_engine.py`)
- Pure ICT pattern detection — no indicators, no scoring
- Setup = trigger (BOS or sweep) + confirmation (OB or FVG)
- Direction from BOS (primary) or sweep (secondary)
- Returns `ICTSetup` dataclass with boolean components

### Layer 2: Feature Builder (`strategy/feature_builder.py`)
- Collects ~35 raw features into flat vector
- Categories: ICT pattern, market structure, volume, indicators (raw), MTF, context, risk
- `to_vector()` → dict ready for ML model input
- `to_reasoning()` → human-readable supporting/opposing factors
- No scoring, no blocking — just data

### Layer 3: Probability Engine (`strategy/probability_engine.py`)
- Rules-based fallback: simple heuristics starting from historical winrate
- ML-based (XGBoost/RandomForest): replaces rules once 100+ outcomes collected
- Outputs: `p_tp` (probability of hitting TP), `expected_rr`, `profit_factor`
- `quality_label`: "strong" (≥65%), "moderate" (≥50%), "weak" (<50%)

### Layer 4: Risk Engine (`risk/engine.py`)
- **Hard gates only** (capital protection):
  - R:R minimum (default 1.5)
  - SL absolute limits (0.25%–5.0% of price)
  - Portfolio risk cap (3%)
  - Max active signals (3)
- **Soft adjustments** (affect sizing, not blocking):
  - Kelly criterion with confidence scaling
  - Volatility adjustment
  - SL distance quality bonus/penalty

### Context Integration
- `ContextScore` replaces `ContextVerdict` — score [-1, 1], never blocks
- Feeds into Probability Engine as a feature

---

## 1. OVERVIEW

```
[Trigger] → [Data Fetch] → [Indicators] → [Signal Engine] → [Gates] → [Context] → [Risk] → [Confidence] → [DB] → [Telegram]
```

**Всего модулей:** ~73 `.py` файлов
**Полный цикл:** 1 символ × 1 TF ≈ 2-5 сек (зависит от network I/O)
**Параллельность:** `asyncio.gather` по всем символам/TF

---

## 2. TRIGGERS

### 2.1 Cron scheduler
`main.py:62` → `scheduler/tasks.py`
```python
scheduler = TaskScheduler(notify_callback=send_signal)
```

| Job | Cron | Timeframes | Файл |
|-----|------|-----------|------|
| `hourly_scan` | `:02` каждый час | `["1h"]` | `tasks.py:40` |
| `4h_scan` | `0,4,8,12,16,20 :05` | `["4h"]` | `tasks.py:48` |

### 2.2 Manual `/scan`
`bot/handlers.py:106` → `cmd_scan()` — **admin only**
```python
await run_scan_cycle(send_signal)  # all primary_timeframes
```

---

## 3. SCAN CYCLE

### `scheduler/scanner.py:884` — `run_scan_cycle()`

```
1. Circuit breaker check        → строка 894
2. Get active symbols           → строка 899 (env SYMBOLS + DB dynamic - disabled)
3. Parallel scan per symbol/TF  → строка 911 (asyncio.gather)
4. Log results                  → строка 914
```

**Circuit breaker** (`circuit_breaker.py`): 3 consecutive `HIT_SL` → pause 30 min.

---

## 4. PER-SYMBOL PIPELINE

### `scheduler/scanner.py:235` — `scan_symbol(symbol, timeframe, notify_callback)`

Полный pipeline для одного `(symbol, timeframe)`. Каждый шаг может вернуть `None` (reject).

```
 1. Cooldown check              строка 241
 2. Fetch OHLCV                 строка 246 (_get_indicators → exchange_client)
 3. Calculate indicators        строка 224 (indicator_engine.calculate)
 4. Detect market regime        строка 252
 5. Early liquidity analysis    строка 259 (sweeps, OB, structure)
 6. SIGNAL ENGINE               строка 268
 7. 15m confirmation            строка 288
 8. S/R levels                  строка 312
 9. Distance filter             строка 353
10. TP path quality             строка 369
11. Structure analysis          строка 372
12. Liquidity analysis          строка 390
13. MTF alignment               строка 509
14. BTC correlation gate        строка 529
15. ETH correlation gate        строка 553
16. Volatility regime           строка 584
17. Context enrichment          строка 597
18. No-trade zones              строка 720
19. Dynamic risk                строка 751
20. Confidence V2               строка 797
21. Save to DB                  строка 833
22. Create outcome              строка 847
23. Set cooldown                строка 869
24. SEND TO TELEGRAM            строка 873
```

---

## 5. DATA FLOW — ДЕТАЛЬНО

### 5.1 Fetch OHLCV

**Файл:** `data/exchange_client.py`

```python
async def fetch_ohlcv(symbol, timeframe, limit=200) -> pd.DataFrame
```

- **Sync ccxt** в `run_in_executor` (Windows compat)
- **Retry:** exponential backoff (1s, 2s, 4s) для `ccxt.NetworkError`
- **Дроп последней свечи:** `df.iloc[:-1]` — не сигналим по открытой свече
- **Taker buy volume:** для futures через `fapiPublicGetKlines` (index 9)
- **Ошибки:** NetworkError → retry + log; ExchangeError → log + None

**DTO на выходе:**
```
columns: open, high, low, close, volume, [taker_buy_volume]
index: datetime (UTC)
len: limit - 1 (минус последняя свеча)
```

### 5.2 Indicator Calculation

**Файл:** `indicators/engine.py`

```python
indicator_engine.calculate(df, symbol, timeframe) -> IndicatorValues
```

**pandas-ta индикаторы:**

| Индикатор | Параметры | Поле в IndicatorValues |
|-----------|-----------|----------------------|
| **BBANDS** | 20, 2 | `bb_upper`, `bb_middle`, `bb_lower` |
| **Supertrend** | 10, 2.5 | `supertrend_direction` (±1), `supertrend` |
| **EMA 21** | fast period | `ema_fast` |
| **EMA 55** | slow period | `ema_slow` |
| **EMA 200** | trend period | `ema_trend` |
| **RSI** | 14 | `rsi` |
| **MACD** | 12, 26, 9 | `macd_hist`, `macd_hist_prev` |
| **ADX** | 14 | `adx`, `dmi_plus`, `dmi_minus` |
| **ATR** | 14 | `atr` |
| **Volume SMA** | 20 | `volume_sma` |

**Дополнительные поля:**
- `ema_bullish_cross`, `ema_bearish_cross`
- `volume_delta_pct` (из taker buy volume)
- `volume_above_avg`

### 5.3 Market Regime Detection

**Файл:** `risk/market_regime.py`

| Режим | Условие |
|-------|---------|
| `compression` | ATR percentile < 20% |
| `expansion` | ATR rising (5 candles) + volume > 1.2x avg |
| `trend` | ADX > 25 |
| `range` | ADX < 18 |
| `high_vol` | ATR/close > 5.0% |
| `low_vol` | ATR/close < 0.8% |

**Приоритет:** compression > expansion > trend > range > high_vol > low_vol

### 5.4 Early Liquidity/Structure Analysis

**Файлы:**
- `liquidity/sweep.py` → `detect_sweeps()`
- `liquidity/order_blocks.py` → `detect_order_blocks()`
- `market_structure/structure.py` → `analyze_structure()`

**Назначение:** Подготовить данные для structural SL/TP и trigger detection.

---

## 6. SIGNAL ENGINE — CORE

### `strategy/signal_engine.py:157` — `SignalEngine.evaluate()`

Это сердце бота. Pipeline внутри evaluate():

```
1. None/NaN guard              строка 177
2. Regime gate                 строка 202 (compression → deferred)
3. ADX flat filter             строка 218 (ADX < adx_min → NO_SIGNAL)
4. Leading triggers            строка 230 (BOS, sweeps, delta)
5. Direction determination     строка 297
6. Factor strengths            строка 315 (7 факторов)
7. Compression breakout mode   строка 341
8. Trigger gate                строка 381
9. Momentum entry mode         строка 390
10. EMA alignment gate         строка 427
11. EMA spread gate            строка 461
12. EMA slope gate             строка 477
13. Build reasons              строка 498
14. Min score gate             строка 542
15. Candle close confirmation  строка 559
16. SL/TP calculation          строка 588
17. Return SignalResult        строка 613
```

### 6.1 Gate pass logging (M1)

**Файл:** `strategy/signal_engine.py:627` — `_log_gates()`

Каждый gate логируется:
```
GATE_STATS reject symbol=X tf=1h failed=trigger|ema_alignment passed=adx=1|data_valid=1
GATE_STATS pass  symbol=X tf=1h gates=adx=1|trigger=1|ema_alignment=1|...
```

Агрегация: `scripts/analyze_gate_stats.py`

### 6.2 Factor Strengths

7 факторов, каждый `[-1.0, 1.0]`:

| Фактор | Функция | Bullish сигнал | Вес |
|--------|---------|----------------|-----|
| **Supertrend** | `_strength_supertrend` | direction=1 → +1.0; иначе -0.5 | 5 |
| **EMA** | `_strength_ema` | fast > slow > trend → spread/1.0 | 10 |
| **MACD** | `_strength_macd` | norm > 0.03% → hist/close * 10 | 10 |
| **RSI** | `_strength_rsi` | <30 → +1.0; 30-50 → +0.5; >70 → -1.0 | 5 |
| **Volume** | `_strength_volume` | vol>avg + delta>15% → 0.3-1.0 | 15 |
| **ADX** | `_strength_adx` | (adx - 20) / 30 | 5 |
| **DMI** | `_strength_dmi` | (plus-minus) / 50 * 2 | 5 |

**Weighted score:** `sum(factor * weight) / total_weight`

### 6.3 Compression Breakout Mode (M7)

**Файл:** `strategy/signal_engine.py:341`

Вместо hard block на compression → разрешаем breakout при:
1. **BOS/sweep** — strong trigger (не delta-only)
2. **ADX ≥ 25** — strong trend strength
3. **Volume ≥ 2x SMA** — liquidity expansion
4. **Supertrend aligned** — не counter-trend

### 6.4 SL/TP Calculation

**Файл:** `strategy/signal_engine.py:734` — `_calculate_sl_tp()`

```
SL = close - ATR * 1.5  (BUY)
TP = close + ATR * 3.0  (BUY)

Если есть BOS:
  SL = BOS level * 0.995
  TP = close + ATR * 3.0
```

---

## 7. POST-SIGNAL GATES

Все gates после signal_engine, в `scanner.py:scan_symbol()`:

### 7.1 Confirmation (15m)
`scanner.py:288`
- Берет `confirm_timeframe` (обычно 15m)
- Вызывает `signal_engine.evaluate()` на 15m
- Если direction не совпадает → reject
- **Это самый частый reject** (как сейчас — 100% reject)

### 7.2 S/R Levels + Distance Filter
`scanner.py:312` / `scanner.py:353`

### 7.3 TP Path Quality
`scanner.py:369`
- Оценка препятствий между entry и TP
- Блокирует если путь перекрыт

### 7.4 Structure Analysis
`scanner.py:372`
- Swing highs/lows
- Trend direction
- BOS/CHoCH detection

### 7.5 Liquidity Analysis
`scanner.py:390`
- **Sweeps** — поиск ликвидности
- **Order Blocks** — зоны реакций
- **FVG** — Fair Value Gaps
- **Candle Quality** — качество свечи

### 7.6 MTF Alignment
`scanner.py:509`
- Проверка alignment на нескольких TF
- `MTF_REQUIRED_ALIGNMENT = 2`

### 7.7 BTC Correlation Gate
`scanner.py:529`
- `fetch_btc_context()` → 4h EMA200 + trend
- Если BTC не allows long/short → reject

### 7.8 ETH Correlation Gate
`scanner.py:553`
- `fetch_eth_context()` → для альткоинов
- ETH bearish → block LONG; ETH bullish → block SHORT

### 7.9 Volatility Regime
`scanner.py:584`

---

## 8. CONTEXT ENRICHMENT

### `context/analyzer.py` — `context_engine.get_snapshot(symbol)`

Собирает:
1. **Fear & Greed Index** (кэш 1h)
2. **Funding Rate** (кэш 1h)
3. **Long/Short Ratio** (кэш 1h)
4. **Open Interest Delta** (кэш 1h per symbol)
5. **News Sentiment** (кэш 1h)

### `context/scorer.py` — `context_scorer.score()`

Выносит `ContextVerdict`:
- `CONFIRMED` — все факторы поддерживают
- `WEAK` — нейтрально
- `CONFLICTED` — факторы противоречат
- `BLOCKED` — явный запрет

### Gates в scanner.py:
```
if config.context_block_on_blocked and verdict == "BLOCKED" → reject
if verdict < CONTEXT_MIN_VERDICT → reject
```

---

## 9. RISK & EXECUTION

### 9.1 No-Trade Zones
`risk/no_trade_zones.py`
- Funding экстремумы
- High volatility
- TP path blocked
- BTC misaligned

### 9.2 Dynamic Risk
`risk/dynamic_risk.py`
- `base_risk_pct` — базовый риск в зависимости от setup_quality
- `effective_risk_pct` — скорректированный на volatility
- `should_trade` — финальное решение

### 9.3 Confidence V2
`scoring/confidence_v2.py`

10 факторов:
| Фактор | Вес | Источник |
|--------|-----|----------|
| HTF Trend | 15 | MTF alignment |
| Structure | 25 | BOS, trend direction |
| Liquidity | 15 | Sweeps, OB, FVG |
| Volume | 10 | volume ratio |
| BTC Correlation | 10 | BTC context |
| Funding | 5 | funding state |
| OI | 5 | OI pattern |
| RSI | 5 | RSI zone |
| MACD | 5 | MACD hist |
| ADX | 5 | ADX strength |

**Итог:** `quality` (strong/moderate/weak) + `confidence_pct` + `total_score`

---

## 10. PERSISTENCE

### 10.1 Database (`storage/database.py`)
- `signals` — все сигналы
- `outcomes` — SL/TP трекинг
- `context_snapshots` — контекст на момент сигнала
- `dynamic_symbols` — символы добавленные через `/addsymbol`
- `disabled_symbols` — отключенные символы
- `factor_fingerprints` — историческая WR по комбинациям факторов

### 10.2 Cooldown (`scanner.py:869`)
```python
await _set_cooldown(symbol, timeframe)
```
- In-memory dict (сбрасывается при рестарте)
- `SIGNAL_COOLDOWN_MINUTES = 60` (по умолчанию)
- Ключ: `symbol|timeframe`

---

## 11. TELEGRAM NOTIFICATION

### `bot/notifier.py:82` — `send_signal()`

```python
async send_signal(result, context_verdict=None, retries=3):
    if not channel_id → return (warning)
    text = result.format_message() + format_context_block(verdict)
    retry loop: bot.send_message(chat_id=channel_id, parse_mode=HTML)
```

**Формат сообщения:**
```
BUY — ПОКУПКА
Инструмент: BTC/USDT
Таймфрейм: 1H | Подтверждение: 15m
Цена входа: 65432.10
Stop Loss: 64800.00 (-0.97%)
Take Profit: 67200.00 (+2.70%)
R/R: 1:2.8

Технические факторы (6/7):
  BOS бычий (leading trigger) уровень 64850
  Supertrend бычий
  EMA21 пересекла EMA55 снизу вверх
  MACD бычий (norm=0.05%)
  ...

Рыночный контекст:
  ├ Fear & Greed: 45 (Neutral) 😐
  ├ Funding: -0.002% ✅
  ├ Long/Short: 0.89 ✅
  └ Новости: нейтральные 😐

Итог: MODERATE | Уверенность: 65.2%
Quality: moderate
```

### Error alerts (`send_error_alert`)
Ошибки ERROR+ уровня шлются в `error_channel_id` или администраторам.

---

## 12. BACKGROUND TASKS

### 12.1 Outcome Tracker
`scheduler/outcome_tracker.py` — каждые 5 минут
- Проверяет open outcomes
- Сравнивает текущую цену с SL/TP
- Обновляет статус: `HIT_TP`, `HIT_SL`, `EXPIRED`

### 12.2 PnL Monitor
`pnl_monitor.py` — каждые 30 секунд (отдельный standalone)
- Не запущен в `main.py` (используется outcome_tracker вместо него)

---

## 13. GATE STATISTICS (M1)

### Формат логов
```
GATE_STATS reject symbol=BTC/USDT tf=1h failed=trigger|ema_alignment passed=adx=1|data_valid=1
GATE_STATS pass symbol=BTC/USDT tf=1h gates=data_valid=1|adx=1|trigger=1|ema_alignment=1|...
```

### Агрегация
```bash
python -m scripts.analyze_gate_stats logs/bot.log --min-samples 10
```

Вывод:
- Pass rate per gate (bottleneck sorting)
- Top rejection filters
- Gate fail chain frequency (correlation analysis)
- Correlated gate pairs

---

## 14. CURRENT BOTTLENECKS

### 14.1 15m Confirmation (100% reject сейчас)
`scanner.py:294` — все сигналы режет на 15m.
**Причина:** на мелком TF нет leading trigger + ADX < adx_min.

**Варианты:**
- Ослабить trigger gate на confirm TF (требовать только cross, не sweep/BOS)
- Разрешить fallback: если нет 15m структуры → пропустить confirmation
- Сделать configurable: `CONFIRM_REQUIRED = False`

### 14.2 Multiple External API Calls
Каждый scan_symbol() делает 5-10 внешних запросов (OHLCV, BTC, ETH, OI, funding).
При 16 symbols × 2 TF = 320 запросов за цикл.

### 14.3 Context Enrichment Timeout
`scanner.py:665` — `asyncio.TimeoutError` при недоступности CoinGecko/Binance API.

### 14.4 Gate Ordering
Сейчас gates идут в порядке: ADX → trigger → EMA alignment → EMA spread → EMA slope → score → candle_close.
Не самые дешевые gates первые (напр. ADX уже расчитан, trigger дороже).

---

## 15. KEY FILES INDEX

| Файл | Назначение | Ключевые строки |
|------|-----------|-----------------|
| `main.py` | Entry point | 62 (scheduler), 75 (outcome tracker) |
| `scheduler/tasks.py` | APScheduler cron | 40, 48 |
| `scheduler/scanner.py` | Full pipeline | 235 (scan_symbol), 280 (scan_symbol_v2), 884 (run_scan_cycle) |
| `strategy/pattern_engine.py` | **NEW:** ICT pattern detection | detect() |
| `strategy/feature_builder.py` | **NEW:** Feature vector builder | build(), to_vector() |
| `strategy/probability_engine.py` | **NEW:** P(TP) estimation | predict() |
| `risk/engine.py` | **NEW:** Risk engine + Kelly sizing | evaluate() |
| `strategy/signal_engine.py` | Signal decision (old) | 157 (evaluate), 627 (gate logging) |
| `indicators/engine.py` | TA calculation | — |
| `data/exchange_client.py` | OHLCV fetching | 81 (fetch raw), 123 (fetch ohlcv) |
| `context/analyzer.py` | Market context | — |
| `context/scorer.py` | Context score (old verdict + new score) | score(), score_simple() |
| `risk/no_trade_zones.py` | Risk gates (old) | — |
| `risk/dynamic_risk.py` | Position sizing (old) | — |
| `risk/market_regime.py` | Regime detection | — |
| `scoring/confidence_v2.py` | V2 confidence | — |
| `liquidity/sweep.py` | Sweep detection | — |
| `liquidity/order_blocks.py` | OB detection | — |
| `liquidity/fvg.py` | FVG detection | — |
| `market_structure/structure.py` | Market structure | — |
| `bot/notifier.py` | Telegram sender | 82 (send_signal) |
| `bot/handlers.py` | Bot commands | 23 (admin check), 106 (cmd_scan) |
| `bot/menu.py` | Inline menu | — |
| `config/settings.py` | All config + PatternEngineConfig, ProbabilityConfig, RiskEngineConfig | — |
| `storage/database.py` | DB layer | — |
| `scheduler/outcome_tracker.py` | SL/TP tracking | 18 (check_open_outcomes) |
| `scheduler/circuit_breaker.py` | Loss protection | — |
| `scripts/analyze_gate_stats.py` | Gate analytics | — |
| `backtest/engine.py` | Backtesting (old pipeline) | — |
| `tests/test_new_pipeline.py` | Tests for new modules | — |

---

## 16. CONFIG REFERENCE (`.env`)

### Required
```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=          # канал для сигналов
SYMBOLS=BTC/USDT,ETH/USDT     # отслеживаемые символы
PRIMARY_TIMEFRAMES=1h,4h      # таймфреймы
BINANCE_API_KEY=
BINANCE_API_SECRET=
```

### Signal gates
```env
ADX_MIN=20                    # ADX flat filter
MIN_EMA_SPREAD_PCT=0.15       # мин. разница EMA
EMA_SLOPE_CHECK=true          # проверка наклона EMA
MIN_MACD_PCT=0.03             # мин. MACD от цены
VOLUME_FACTOR=1.5             # множитель объёма
MIN_SCORE_FOR_SIGNAL=4        # мин. число факторов
```

### Context
```env
CONTEXT_BLOCK_ON_BLOCKED=true
CONTEXT_MIN_VERDICT=WEAK      # BLOCKED < CONFLICTED < WEAK < CONFIRMED
```

### Risk
```env
VOLATILITY_LOW_THRESHOLD=0.8
VOLATILITY_HIGH_THRESHOLD=5.0
RISK_STRONG_PCT=1.0
RISK_MODERATE_PCT=0.5
RISK_WEAK_TRADE=false
```

### Cooldown
```env
SIGNAL_COOLDOWN_MINUTES=60
```

---

## 17. TEST COMMANDS

```bash
# Все тесты
pytest -v

# По модулям
pytest tests/test_signal.py -v
pytest tests/test_backtest.py -v
pytest tests/test_scanner.py -v
pytest tests/test_exchange_client.py -v
pytest tests/test_new_pipeline.py -v  # NEW: PatternEngine, FeatureBuilder, ProbabilityEngine, RiskEngine

# Gate stats из лога
python -m scripts.analyze_gate_stats logs/bot.log

# EMA50 vs EMA200 сравнение
python -m backtest.compare_ema_trend BTC/USDT 1h
```

---

## 18. TYPICAL SIGNAL FLOW EXAMPLE

```
BTC/USDT 1h:

1. Cron trigger (::02)
2. fetch_ohlcv(BTC/USDT, 1h, 200) → 199 candles
3. indicator_engine.calculate → IndicatorValues
4. Regime: "trend" (ADX=32)
5. detect_sweeps → [Sweep(type=bearish, level=64000)]
6. signal_engine.evaluate():
   - ADX=32 > 20 → ✅
   - Sweep detected → leading trigger ✅
   - EMA fast=65400 > slow=65000 > trend=62000 → aligned ✅
   - EMA spread = 0.62% > 0.15% ✅
   - Score = 5 ≥ 4 ✅
   - Candle close at 70% of range > 60% ✅
   → SignalResult(BUY, score=5, SL=64800, TP=67200)
7. Confirm on 15m:
   - ADX=15 < 20 → NO_SIGNAL → ❌ REJECT
8. scan_symbol returns None
9. run_scan_cycle: "Signals found: 0/32"
```

---

## 19. CURRENT ISSUES

1. **15m confirmation rejects everything** — на мелком TF rarely есть ADX+trigger
2. **Нет `/test` команды** — нельзя проверить pipeline без полного скана
3. **Context enrichment завис** при недоступности внешних API
4. **Gate ordering** — дорогие gates (context, structure) идут до дешевых
5. **Cooldown in-memory** — сбрасывается при рестарте
6. **Нет signal replay** — нельзя пересчитать сигнал на истории
