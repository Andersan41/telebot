
# FIX_2.md — Консолидированный план исправлений и калибровки торгового бота (15m Crypto Futures)

## Назначение

Документ предназначен для:
- LM Studio
- DeepSeek v4 Flash
- OpenCode
- Zen Agent
- локального AI coding-agent

Цель:
- устранить конфликты фильтров,
- убрать дублирование логики,
- улучшить качество сигналов,
- уменьшить lagging behavior,
- повысить качество intraday 15m сигналов,
- перестроить систему под liquidity + structure model.

---

# КРИТИЧЕСКИЕ ПРОБЛЕМЫ

## 1. Дублирование trend-фильтров

Сейчас одновременно используются:
- EMA
- Supertrend
- ADX

Все 3 фактически проверяют одно и то же:
наличие тренда.

---

## 2. MACD noise

Любой histogram > 0
считается валидным momentum.

---

## 3. MTF conflict

Strict MTF alignment блокирует liquidity reversals.

---

## 4. Compression conflict

Compression regime конфликтует с ADX filter.

---

## 5. Distance filter conflict

Distance filter блокирует sweep/reclaim entries.

---

## 6. Candle close conflict

Sweep setups конфликтуют с candle close logic.

---

# ЧТО НЕОБХОДИМО ВЫКЛЮЧИТЬ

## Убрать Supertrend из scoring

Было:

W_SUPERTREND: 5

Сделать:

W_SUPERTREND: 0

---

## Убрать MIN_SCORE_FOR_SIGNAL

Было:

MIN_SCORE_FOR_SIGNAL: 4

Сделать:

MIN_SCORE_FOR_SIGNAL: 0

---

## Убрать RSI hard rejection

RSI не должен блокировать trade.
Только penalize confidence.

---

# CONDITIONAL FILTERS

## Candle Close Filter

Было:

CANDLE_CLOSE_ENABLED: true

Нужно:

CANDLE_CLOSE_ENABLED: conditional

Логика:

if setup_type == "sweep":
    ignore_close_filter = True

---

## Dynamic ADX

if regime == "compression":
    required_adx = 18
else:
    required_adx = 24

---

## Strategy-aware MTF

if setup_type == "reversal":
    mtf_required = 1
else:
    mtf_required = 2

---

# НОВЫЕ ПАРАМЕТРЫ ДЛЯ 15M

## CORE SIGNAL ENGINE

SIGNAL_COOLDOWN_MINUTES: 45

ENTRY_TF: 15m
LOWER_CONFIRM_TF: 5m
HTF_CONFIRM_TF: 1h

ADX_FILTER_ENABLED: true
ADX_MIN: 24

TRIGGER_REQUIRED: true

CANDLE_CLOSE_ENABLED: conditional

DISTANCE_FILTER_ENABLED: true
DISTANCE_FILTER_MIN_PCT: 1.2

MTF_ENABLED: true
MTF_REQUIRED_ALIGNMENT: 2

COMPRESSION_ENABLED: true

---

# EMA

EMA_FAST: 8
EMA_SLOW: 21
EMA_TREND: 55

MIN_EMA_SPREAD_PCT: 0.20

EMA_SPREAD_ENABLED: true
EMA_SLOPE_CHECK: true

---

# RSI

RSI_PERIOD: 10

RSI_OVERBOUGHT: 72
RSI_OVERSOLD: 28

RSI_BULL_MIN: 55
RSI_BEAR_MAX: 45

---

# MACD

MACD_FAST: 8
MACD_SLOW: 21
MACD_SIGNAL: 5

MIN_MACD_PCT: 0.03

MACD_SLOPE_REQUIRED: true

---

# VOLUME

VOLUME_FACTOR: 1.5
VOLUME_SMA_PERIOD: 20

DELTA_BULLISH: 15
DELTA_BEARISH: -15

---

# VOLATILITY & RISK

VOLATILITY_FILTER_ENABLED: true

VOLATILITY_LOW_THRESHOLD: 0.8
VOLATILITY_HIGH_THRESHOLD: 6.0

DYNAMIC_RISK_ENABLED: true

RISK_STRONG_PCT: 1.0
RISK_MODERATE_PCT: 0.5

NO_TRADE_MIN_ATR_PCT: 0.6

CORRELATION_MISALIGNED_MULTIPLIER: 0.5

---

# CONTEXT

CONTEXT_BLOCK_ON_BLOCKED: true
CONTEXT_MIN_VERDICT: MODERATE

---

# WEIGHTED FACTORS

W_SUPERTREND: 0

W_EMA: 10
W_MACD: 10
W_RSI: 5

W_VOLUME: 15
W_ADX: 5
W_DMI: 5

W_BOS: 15
W_SWEEP: 10
W_OB: 10

W_BTC: 10
W_FUNDING: 5
W_OI: 10

---

# SWEEP

SWEEP_MAX_RECLAIM_CANDLES: 2
SWEEP_MIN_VOLUME_RATIO: 1.8

---

# ORDER BLOCKS

OB_MIN_DISPLACEMENT_PCT: 2.5
OB_MIN_VOLUME_RATIO: 1.8
OB_MAX_AGE_CANDLES: 35

---

# FVG

FVG_MIN_SIZE_PCT: 0.4

---

# CANDLE QUALITY

CANDLE_DISPLACEMENT_ATR_MULT: 1.5
CANDLE_MIN_BODY_PCT: 0.6

---

# SUPERTREND

SUPERTREND_PERIOD: 10
SUPERTREND_MULTIPLIER: 2.5

---

# ПРИОРИТЕТ ИСПРАВЛЕНИЙ

1. Убрать Supertrend scoring
2. Убрать MinScore
3. Перевести MACD на 8/21/5
4. Добавить MIN_MACD_PCT
5. Добавить EMA_SLOPE_CHECK
6. Сделать CANDLE_CLOSE conditional
7. Сделать dynamic ADX
8. Сделать strategy-aware MTF

---

# ГЛАВНАЯ ЦЕЛЬ

Бот должен:
- перестать торговать lagging continuation,
- начать торговать liquidity displacement,
- определять expansion after compression,
- понимать structure,
- понимать momentum quality,
- понимать directional volume,
- отличать trend от chop/range.


---

# ДОПОЛНИТЕЛЬНЫЕ АРХИТЕКТУРНЫЕ ПРАВКИ (POST-REVIEW)

## Основано на дополнительном review event-driven модели

---

# 1. НЕ УДАЛЯТЬ SCORE ПОЛНОСТЬЮ

## ПРОБЛЕМА

Полное удаление:
MIN_SCORE_FOR_SIGNAL

может привести к:
- переизбытку noise entries,
- fake sweeps,
- low quality reversals,
- резкому росту количества сигналов.

---

## НОВАЯ РЕКОМЕНДАЦИЯ

Вместо:

```yaml
MIN_SCORE_FOR_SIGNAL: 0
```

Использовать:

```yaml
MIN_WEIGHTED_SCORE: 45
```

---

## ЛОГИКА

Система должна:
оценивать качество факторов,
а не количество факторов.

---

## ВАЖНО

НЕЛЬЗЯ:
считать score по числу индикаторов.

НУЖНО:
использовать weighted event quality model.

---

# 2. RSI ПЕРЕВЕСТИ В CONTEXT MODE

## СТАРАЯ ЛОГИКА

```python
if RSI bullish:
    add_score()
```

---

## НОВАЯ ЛОГИКА

RSI:
НЕ генерирует signal.

RSI:
- определяет exhaustion,
- определяет overextension,
- уменьшает confidence.

---

## ПРИМЕР

```python
if rsi > 78:
    confidence -= 10
```

---

# 3. BOS ДОЛЖЕН ПРОХОДИТЬ DISPLACEMENT VALIDATION

## ПРОБЛЕМА

Micro BOS
создает огромное количество fake continuation.

---

## ОБЯЗАТЕЛЬНО ДОБАВИТЬ

BOS valid only if:

```python
body_size > atr * 1.2
volume_ratio > 1.5
close_beyond_structure == True
```

---

# 4. ORDER BLOCK VALIDATION

## НЕЛЬЗЯ

Считать OB:
просто последнюю bearish/bullish candle.

---

## НУЖЕН ПОЛНЫЙ PIPELINE

OB valid only if:

- есть displacement,
- есть BOS,
- есть imbalance,
- есть reclaim,
- есть reaction volume.

---

## РЕКОМЕНДУЕМАЯ ЛОГИКА

```python
if bos_confirmed
and displacement_confirmed
and fvg_present
and reclaim_valid:
    OB_VALID = True
```

---

# 5. MARKET REGIME ENGINE

## КРИТИЧЕСКИ ВАЖНО

Бот НЕ должен:
использовать одну и ту же стратегию
во всех режимах рынка.

---

## НУЖНО ВВЕСТИ

### REGIMES

| Regime | Logic |
|---|---|
| Trend | continuation |
| Compression | breakout |
| Range | mean reversion |
| Expansion | momentum |
| Reversal | sweep reclaim |

---

## REGIME DETECTION

Использовать:

- ATR
- ADX
- EMA slope
- range compression
- volatility expansion

---

# 6. REAL DELTA REQUIRED

## ПРОБЛЕМА

Approximate delta
ослабляет liquidity engine.

---

## РЕКОМЕНДАЦИЯ

Использовать:
- bid/ask delta,
- footprint delta,
- cumulative volume delta (CVD),
- aggressive buyers/sellers.

---

## ЕСЛИ НЕТ REAL DELTA

Уменьшить влияние:

```yaml
W_VOLUME: 10
```

вместо:

```yaml
W_VOLUME: 15
```

---

# 7. FACTOR ANALYTICS SYSTEM

## ОБЯЗАТЕЛЬНО ЛОГИРОВАТЬ

Для каждого сигнала:

- setup_type
- regime
- factors_triggered
- weighted_score
- context_score
- RR
- outcome
- max_drawdown
- max_favorable_excursion

---

## ЦЕЛЬ

Понять:
какие факторы реально создают edge.

---

# 8. EVENT-DRIVEN SIGNAL ENGINE

## СТАРАЯ АРХИТЕКТУРА

```text
EMA + RSI + MACD → signal
```

---

## НОВАЯ АРХИТЕКТУРА

```text
Liquidity Event
+
Structure Confirmation
+
Momentum Validation
=
Signal
```

---

# 9. НОВЫЙ SIGNAL PRIORITY

## PRIORITY ORDER

### TIER 1 (основа)

- Sweep
- BOS
- Displacement
- Volume
- Reclaim

---

### TIER 2 (подтверждение)

- EMA slope
- MACD slope
- DMI alignment

---

### TIER 3 (context)

- RSI
- Funding
- Fear & Greed
- OI

---

# 10. ЗАПРЕТ НА INDICATOR STACKING

## НЕ ДОПУСКАТЬ

Одновременного усиления score
за:

- EMA cross
- Supertrend
- MACD cross

если все они подтверждают один и тот же trend.

---

## НУЖНА NORMALIZATION LOGIC

```python
trend_confirmation_cap = 20
```

---

# 11. ОБЯЗАТЕЛЬНАЯ REGIME ADAPTATION

## TREND

- continuation entries
- EMA important
- RSI ignored

---

## RANGE

- mean reversion
- sweep important
- MACD weak

---

## COMPRESSION

- low ADX acceptable
- breakout watch
- displacement critical

---

## REVERSAL

- sweep required
- reclaim required
- MTF relaxed

---

# 12. FINAL TARGET ARCHITECTURE

## SIGNAL GENERATION

Liquidity:
- sweep
- BOS
- OB
- displacement

Structure:
- HTF bias
- reclaim
- continuation

Momentum:
- EMA slope
- MACD slope
- delta

Validation:
- context
- volatility
- regime

Execution:
- structure SL
- liquidity TP

---

# РЕАЛИЗОВАНО VS НЕ РЕАЛИЗОВАНО (AUDIT fix_2.md)

## Статус: 17 из 19 пунктов fix_2.md внедрены в код

Большинство изменений из fix_2.md уже реализованы.
Ниже — список того, что НЕ сделано или имеет расхождения.

---

## 1. Сломанные тесты (не обновлены под новые defaults)

### test_config.py

```python
# line 198 — устарело
assert s.w_supertrend == 5
# W_SUPERTREND теперь 0 — тест упадёт

# line 231 — устарело
assert settings.config.scoring.min_score_for_signal == 4
# MIN_SCORE_FOR_SIGNAL теперь 0 — тест упадёт

# line 65 — устарело
assert cfg.confirm_timeframe == "15m"
# .env переопределяет CONFIRM_TIMEFRAME=5m — тест упадёт
```

### test_context.py

```python
# line 773 — устарело
assert config.context_min_verdict == "WEAK"
# CONTEXT_MIN_VERDICT теперь "MODERATE" — тест упадёт
```

**Что делать:** обновить тесты под актуальные defaults.

---

## 2. `.env` переопределяет значения fix_2.md в обратную сторону

| Параметр | fix_2.md | `.env` | Статус |
|----------|----------|--------|--------|
| `MIN_SCORE_FOR_SIGNAL` | `0` | `5` | `.env` не соответствует плану |
| `RSI_BULL_MIN` | `55` | `50` | `.env` ослабляет условие |
| `RSI_BEAR_MAX` | `45` | `50` | `.env` ослабляет условие |

**Что делать:** синхронизировать `.env` с fix_2.md либо зафиксировать намеренное отклонение.

---

## 3. Volatility threshold mismatch

- `config/settings.py` (строки 268-270): `VOLATILITY_LOW=0.8`, `VOLATILITY_HIGH=6.0`
- `risk/volatility_regime.py` (строки 33-38): hardcoded fallback `LOW=1.0`, `HIGH=4.0`

Два разных источника defaults — это баг. При отсутствии `.env` переменных значения разойдутся.

**Что делать:** убрать hardcoded fallback из `volatility_regime.py`, читать из `config.settings`.

---

## 4. CANDLE_CLOSE_ENABLED — тип bool, а не str "conditional"

```python
# settings.py
candle_close_enabled: bool  # True/False
```

Логика в `signal_engine.py` уже условная (skip для sweep), но конфиг принимает только `true/false`, а не строку `"conditional"`.

**Что делать:** либо оставить как есть (логика верна), либо заменить тип на `Literal["on", "off", "conditional"]`.

---

## 5. Что из fix_3.md (POST-REVIEW) ещё НЕ внедрено

### RSI в CONTEXT MODE

Текущий код всё ещё использует RSI для scoring, а не только для penalize confidence.

**Что делать:** перевести RSI из генератора сигнала в контекстный модификатор (penalty при overbought/oversold).

### BOS displacement validation

Нет проверки `body_size > atr * 1.2` и `close_beyond_structure`.

**Что делать:** добавить валидацию в `structure/detector.py` или `signal_engine.py`.

### Order Block полный pipeline

Нет проверки: displacement → BOS → FVG → reclaim → reaction volume.

**Что делать:** расширить `structure/order_blocks.py` до полного pipeline.

### Market Regime Engine

Режимы определены, но нет адаптации стратегии под regime (trend=continuation, range=mean reversion, compression=breakout).

**Что делать:** внедрить `trading/regime_adapter.py` с переключением логики входа.

### Factor Analytics System

Нет логирования per-signal метрик (setup_type, regime, factors_triggered, weighted_score, RR, outcome).

**Что делать:** добавить analytics-логгер в `signal_engine.py` или `services/signal_tracker.py`.

### Normalization (запрет indicator stacking)

Нет cap `trend_confirmation_cap = 20` для предотвращения двойного счёта за correlated индикаторы.

**Что делать:** добавить нормализацию weighted score в `signal_engine.py`.

### Real Delta

Используется approximate delta вместо bid/ask или CVD.

**Что делать:** подключить Binance WebSocket для real delta или уменьшить W_VOLUME до 10.

---

# ПРИОРИТЕТ ДОРАБОТОК (от самого срочного)

1. Починить тесты (test_config.py, test_context.py)
2. Синхронизировать `.env` с fix_2.md
3. Исправить volatility threshold mismatch (volatility_regime.py)
4. BOS displacement validation
5. RSI → context mode
6. Factor Analytics System
7. Normalization / indicator stacking cap
8. Order Block полный pipeline
9. Market Regime Engine
10. Real Delta
