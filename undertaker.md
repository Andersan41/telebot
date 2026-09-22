# undertaker.md — Полная механика работы сканера

> Автогенерация из кода. Дата: 2026-09-16. Все ссылки на актуальный код.

---

## 1. Источник данных

### 1.1 Биржа / API

| Параметр | Значение | Файл:строка |
|----------|----------|-------------|
| Библиотека | `ccxt` (sync) | `data/exchange_client.py:10` |
| Биржа (дефолт) | **BingX** | `config/settings.py:39` — `EXCHANGE=bingx` |
| Тип рынка | **swap** (перпетуалы) | `config/settings.py:47` — `MARKET_TYPE=swap` |
| Создание инстанса | `getattr(ccxt_sync, name)(...)` | `data/exchange_client.py:84-93` |
| API keys | `EXCHANGE_API_KEY` / `EXCHANGE_API_SECRET` | `config/settings.py:41-43` |
| Rate limit | `enableRateLimit: True` (встроенный ccxt) | `data/exchange_client.py:88` |
| Таймаут | 30 сек | `data/exchange_client.py:89` |
| Сериализация | `asyncio.Semaphore(1)` — один запрос за раз | `data/exchange_client.py:127` |

### 1.2 Таймфреймы

| TF | Назначение | Лимит свечей | Файл:строка |
|----|-----------|-------------|-------------|
| `1h`, `4h` | **Primary** — основное сканирование | 200 | `config/settings.py:70-72`, `scanner.py:214-217` |
| `1d` | HTF POI + HTF Bias | 60 | `scanner.py:920` |
| `4h` | HTF POI (доп.) | 60 | `scanner.py:921` |
| `1w` | HTF Bias V2 | 60 | `scanner.py:944` |
| `1h` | HTF Bias V2 (доп.) | 60 | `scanner.py:948` |
| `15m` (или `5m`) | LTF Confirmation | 100 | `scanner.py:1226-1227` |

- Primary TF: `PRIMARY_TIMEFRAMES=1h,4h` → `config/settings.py:70-72`
- Confirm TF: `CONFIRM_TIMEFRAME=15m` → `config/settings.py:76`
- Все свечи: `CANDLES_LIMIT=200` → `config/settings.py:206`
- Последняя (открытая) свеча отбрасывается: `df.iloc[:-1]` → `data/exchange_client.py:357`

### 1.3 Интервал цикла

| Параметр | Значение | Файл:строка |
|----------|----------|-------------|
| Cron | `minute=2,17,32,47` (каждые 15 мин) | `scheduler/tasks.py:28` |
| Дефолт | `SCAN_MINUTES=2,17,32,47` | `config/settings.py:541` |
| Защита от параллельности | `_scan_lock.locked()` → skip | `scanner.py:2296-2298` |
| Circuit breaker | Проверяется перед сканом | `scanner.py:2300-2302` |

### 1.4 Список пар

| Источник | Файл:строка |
|----------|-------------|
| `.env` → `SYMBOLS=BTC/USDT,ETH/USDT,...` | `config/settings.py:66-68` |
| Динамические (через `/addsymbol`) | `config/settings.py:986-1002` — `refresh_runtime_symbols()` |
| Disabled (через `/disable`) | `scanner.py:2306-2307` — `db.get_disabled_symbols()` |
| Итого: `get_active_symbols()` | `config/settings.py:1009-1010` |

**Формула:** `active = (env_symbols + db_dynamic) - db_disabled`

### 1.5 Обработка ошибок API

| Тип ошибки | Ретраи | Задержка | Файл:строка |
|------------|--------|----------|-------------|
| `BadSymbol`, `BadRequest` | **Нет** → `None` | — | `exchange_client.py:182-186` |
| `RateLimitExceeded`, `DDoSProtection` | 3 попытки | `5 × 2^attempt` (5с, 10с, 20с) | `exchange_client.py:187-202` |
| `NetworkError` | 3 попытки | `2^attempt` (1с, 2с, 4с) | `exchange_client.py:203-218` |
| `ExchangeError` | **Нет** → `None` | — | `exchange_client.py:219-221` |
| Загрузка markets (стартап) | 5 попыток | `5 × 2^attempt` (5с→40с) | `exchange_client.py:96-122` |
| BingX error codes | 14 кодов → human-readable | — | `exchange_client.py:17-48` |

---

## 2. Индикаторы и расчёты

### 2.1 Полный список

| # | Индикатор | pandas_ta функция | Файл:строка |
|---|-----------|-------------------|-------------|
| 1 | EMA (×3) | `ta.ema()` | `indicators/engine.py:128-130` |
| 2 | RSI | `ta.rsi()` | `indicators/engine.py:133` |
| 3 | MACD | `ta.macd()` | `indicators/engine.py:136-147` |
| 4 | ADX + DMI | `ta.adx()` | `indicators/engine.py:150-162` |
| 5 | ATR | `ta.atr()` | `indicators/engine.py:165` |
| 6 | Supertrend | `ta.supertrend()` | `indicators/engine.py:179-197` |
| 7 | Volume SMA | `ta.sma()` | `indicators/engine.py:168` |
| 8 | Volume Delta % | ручной расчёт | `indicators/engine.py:171-176` |

### 2.2 Детализация по каждому

#### EMA (Exponential Moving Average)

| Параметр | Дефолт | Env | Файл:строка |
|----------|--------|-----|-------------|
| Fast | **8** | `EMA_FAST` | `settings.py:82` |
| Slow | **21** | `EMA_SLOW` | `settings.py:84` |
| Trend | **55** | `EMA_TREND` | `settings.py:86` |
| Min spread % | **0.20** | `MIN_EMA_SPREAD_PCT` | `settings.py:88` |
| Slope check | **True** | `EMA_SLOPE_CHECK` | `settings.py:90` |
| Strength cap | **1.0** | `EMA_STRENGTH_CAP` | `settings.py:94` |

Расчёт: `ta.ema(df["close"], length=N)` → `indicators/engine.py:128-130`

Производные:
- `ema_bullish_cross`: `fast_prev <= slow_prev AND fast > slow` → `engine.py:68`
- `ema_bearish_cross`: `fast_prev >= slow_prev AND fast < slow` → `engine.py:73`
- `ema_bullish_alignment`: `fast > slow > trend` → `engine.py:78`
- `ema_bearish_alignment`: `fast < slow < trend` → `engine.py:83`

#### RSI (Relative Strength Index)

| Параметр | Дефолт | Env | Файл:строка |
|----------|--------|-----|-------------|
| Period | **10** | `RSI_PERIOD` | `settings.py:98` |
| Overbought | **72** | `RSI_OVERBOUGHT` | `settings.py:100` |
| Oversold | **28** | `RSI_OVERSOLD` | `settings.py:102` |
| Bull Min | **55** | `RSI_BULL_MIN` | `settings.py:104` |
| Bear Max | **45** | `RSI_BEAR_MAX` | `settings.py:106` |

Расчёт: `ta.rsi(df["close"], length=10)` → `indicators/engine.py:133`

#### MACD

| Параметр | Дефолт | Env | Файл:строка |
|----------|--------|-----|-------------|
| Fast | **8** | `MACD_FAST` | `settings.py:110` |
| Slow | **21** | `MACD_SLOW` | `settings.py:112` |
| Signal | **5** | `MACD_SIGNAL` | `settings.py:114` |
| Min MACD % | **0.03** | `MIN_MACD_PCT` | `settings.py:116` |
| Score multiplier | **10** | `MACD_SCORE_MULTIPLIER` | `settings.py:118` |

Расчёт: `ta.macd(close, fast=8, slow=21, signal=5)` → `indicators/engine.py:136-147`
Производные: `macd_bullish_cross` (histogram crossover), `macd_bearish_cross` → `engine.py:88-95`

#### ADX + DMI

| Параметр | Дефолт | Env | Файл:строка |
|----------|--------|-----|-------------|
| Period | **14** | `ADX_PERIOD` | `settings.py:124` |
| Min (trend filter) | **26** | `ADX_MIN` | `settings.py:126` |
| Strong threshold | **22** | `ADX_STRONG` | `settings.py:128` |
| Strength range | **30** | `ADX_STRENGTH_RANGE` | `settings.py:130` |
| Filter enabled | **True** | `ADX_FILTER_ENABLED` | `settings.py:186` |

Расчёт: `ta.adx(high, low, close, length=14)` → `indicators/engine.py:150-162`
Производная: `trend_is_strong = adx >= 26` → `engine.py:102`

#### ATR (Average True Range)

| Параметр | Дефолт | Env | Файл:строка |
|----------|--------|-----|-------------|
| Period | **14** | `ATR_PERIOD` | `settings.py:138` |
| SL multiplier | **1.5** | `ATR_MULTIPLIER_SL` | `settings.py:140` |
| TP multiplier | **3.0** | `ATR_MULTIPLIER_TP` | `settings.py:142` |
| Fallback % | **2.0** | `ATR_FALLBACK_PCT` | `settings.py:146` |
| Volatility min | **0.3%** | `VOLATILITY_MIN_ATR_PERCENT` | `settings.py:218` |
| Volatility max | **5.0%** | `VOLATILITY_MAX_ATR_PERCENT` | `settings.py:220` |

Расчёт: `ta.atr(high, low, close, length=14)` → `indicators/engine.py:165`

#### Supertrend

| Параметр | Дефолт | Env | Файл:строка |
|----------|--------|-----|-------------|
| Period | **10** | `SUPERTREND_PERIOD` | `settings.py:166` |
| Multiplier | **2.5** | `SUPERTREND_MULTIPLIER` | `settings.py:168` |

Расчёт: `ta.supertrend(high, low, close, length=10, multiplier=2.5)` → `indicators/engine.py:179-197`
Производные: `supertrend_bullish = direction == 1`, `supertrend_bearish = direction == -1` → `engine.py:106-111`

#### Volume

| Параметр | Дефолт | Env | Файл:строка |
|----------|--------|-----|-------------|
| SMA period | **20** | `VOLUME_SMA_PERIOD` | `settings.py:174` |
| Volume factor | **1.5** | `VOLUME_FACTOR` | `settings.py:172` |
| Delta bullish | **15** | `DELTA_BULLISH` | `settings.py:176` |
| Delta bearish | **-15** | `DELTA_BEARISH` | `settings.py:178` |

Расчёт:
- `volume_sma = ta.sma(volume, length=20)` → `engine.py:168`
- `volume_delta_pct = (buy_vol - sell_vol) / volume * 100` → `engine.py:171-176`
- `volume_above_avg = volume > volume_sma * 1.5` → `engine.py:98`

### 2.3 Внешние индикаторы (за пределами engine.py)

| Индикатор | Параметры | Файл:строка |
|-----------|-----------|-------------|
| BTC EMA200 | period=200, TF=4h | `derivatives/btc_correlation.py:75` |
| HTF Bias V2 EMA | 21/55 на W1, D1, H4, H1 | `market_structure/htf_bias_v2.py:63-64` |
| Market Regime ADX | trend=25, range=20 | `risk/market_regime.py`, `settings.py:398-400` |
| Volume Profile | POC, VAH, VAL | `liquidity/volume_profile.py:62-176` |

### 2.4 Как индикаторы комбинируются

**Новый паттерн (v2):** Индикаторы — **сырые ML-фичи**, НЕ гейты.

```
Pattern Engine (чистый price action) → Feature Builder (собирает ~35 фич)
→ Probability Engine (rules или XGBoost) → Risk Engine (финальный фильтр)
```

Комментарий в коде: `strategy/feature_builder.py:162` — *"Indicators are included as raw ML features, NOT as gates"*

**Веса (legacy weighted factor model):**

| Фактор | Вес | Файл:строка |
|--------|-----|-------------|
| EMA | 10 | `settings.py:484` |
| MACD | 10 | `settings.py:486` |
| Volume | 15 | `settings.py:490` |
| BOS | 15 | `settings.py:492` |
| Sweep | 10 | `settings.py:494` |
| OB | 10 | `settings.py:496` |
| Supertrend | 5 | `settings.py:482` |
| RSI | 5 | `settings.py:488` |
| ADX | 5 | `settings.py:498` |
| DMI | 5 | `settings.py:500` |
| BTC | 10 | `settings.py:502` |
| Funding | 5 | `settings.py:504` |
| OI | 10 | `settings.py:506` |
| **Итого** | **115** | |

---

## 3. Логика входа / сигнала

### 3.1 ICT Pattern Engine

**Точка входа:** `PatternEngine.detect()` → `strategy/pattern_engine.py:148-260`

#### REVERSAL: Sweep → Displacement → MSS

**Step 1 — Sweep** (mandatory):
- `pattern_engine.py:280-299` — фильтрация `is_valid`, `passes_false_sweep_filters()`
- **BUY sweep** (`liquidity/sweep.py:189-211`): `current.low < swing_low.price AND current.close > swing_low.price`
- **SELL sweep** (`liquidity/sweep.py:165-187`): `current.high > swing_high.price AND current.close < swing_high.price`
- **Validity** (`sweep.py:51-54`): `reclaim_candles <= 2` (дефолт)
- **False sweep filters** (`sweep.py:56-103`):
  - `max_body_beyond_level` (% ATR)
  - `min_wick_beyond_level` = 0.1% цены
  - `min_body_size` = 0.05% цены
  - `max_pool_age_bars` = 100
- **Strength scoring** (`sweep.py:106-122`): fast_reclaim(0.3) + high_volume(0.3) + delta_aligned(0.2) + displacement(0.2) = max 1.0

**Step 2 — Displacement** (informational, НЕ гейт):
- `pattern_engine.py:307-319` — `candle_quality.is_displacement`
- Комментарий: *"not a gate for MSS setups"*

**Step 3 — MSS** (soft gate):
- `pattern_engine.py:321-373` — проверяет `structure.last_mss`
- **Направление:** bullish MSS → "buy", bearish MSS → "sell" (lines 338-341)
- **Без MSS:** возвращает `detected=True` (reversal всё ещё детектится!) с `rejection_reason="reversal: sweep only (no MSS)"` (line 349-362)

**Что такое MSS** (`market_structure/structure.py:122-232`):
- Классифицированный CHoCH. Критерии (line 204-208):
  1. Sweep reference в causal window (10 баров)
  2. Displacement >= 0.2 ATR
  3. Reclaim <= 2 бара
- **MSS quality score** (line 84-119): sweep_strength(20) + displacement_atr(20) + reclaim_speed(20) + volume(20) + htf_aligned(20) = max 100

#### CONTINUATION: Trend + BOS

**Step 1 — Trend** (mandatory):
- `pattern_engine.py:411-416` — `trend == "ranging"` → `detected=False`

**Step 2 — BOS** (mandatory):
- `pattern_engine.py:418-443` — проверяет `structure.last_bos`

**Step 3 — BOS breaks last swing:**
- `pattern_engine.py:445-474` — для bullish BOS: `structure.last_bos.level > _last_swing_before.price` (line 454)

**Step 4 — Trend alignment:**
- `pattern_engine.py:477-489` — BOS direction = trend direction

**Что такое BOS** (`market_structure/structure.py:283-395`):
- Break of Structure = подтверждение тренда
- Bullish BOS: higher high во время bullish trend
- Bearish BOS: lower low во время bearish trend

### 3.2 Entry Zones (НЕ гейты, только информационно)

**OB Detection** (`pattern_engine.py:502-530`):
- Temporal binding: OB после sweep (line 519-521)
- `ob.is_valid AND ob.direction matches setup.direction`

**FVG Detection** (`pattern_engine.py:532-546`):
- Temporal binding: FVG после sweep (line 536-538)
- `f.is_active AND f.direction matches setup.direction`

**Entry Armed** (`pattern_engine.py:548-570`):
- Цена в пределах `ob_proximity_pct` (2.0%) от OB midpoint (line 561)
- Или в пределах `ob_proximity_pct` от FVG midpoint (line 567)
- **SOFT** — логируется, но не блокирует

### 3.3 Confirmation Score

```python
# strategy/pattern_engine.py:103-114
score = 0
if self.has_bos:   score += 2
if self.has_fvg:   score += 1
if self.has_ob:    score += 1
return score  # max = 4
```

**Gate** (`scanner.py:706-723`): `confirmation_score < 2` → BLOCKED

### 3.4 Components Count (Score)

```python
# strategy/pattern_engine.py:572-593
def _build_components(self, setup):
    components = []
    if setup.setup_type == "reversal":
        if setup.has_sweep:       components.append("Sweep")
        if setup.has_displacement: components.append("Displacement")
        if setup.has_mss:         components.append("MSS")
    elif setup.setup_type == "continuation":
        if trend in ("bullish","bearish"): components.append("Trend")
        if setup.has_bos:         components.append("BOS")
    if setup.has_ob:              components.append("OB")
    if setup.has_fvg:             components.append("FVG")
    if setup.entry_armed:         components.append("EntryArmed")
    return components
```

**Максимальный score:**
- Reversal: Sweep + Displacement + MSS + OB + FVG + EntryArmed = **6**
- Continuation: Trend + BOS + OB + FVG + EntryArmed = **5**

**Gate** (`scanner.py:588-603`): `components_count < MIN_SCORE_FOR_SIGNAL` (default 2)

### 3.5 SL/TP Calculation

**Entry price:** `entry = float(ind.close)` → `trade_engine.py:53`

#### SL — Приоритет источников (trade_engine.py:94-208):

| Приоритет | Источник | Файл:строка |
|-----------|----------|-------------|
| 1 | Sweep extreme (sweep low/high) | `invalidation.py:34-112` |
| 2 | OB boundary (ob.low / ob.high) | `invalidation.py` |
| 3 | Swing point (fractal) | `invalidation.py` |
| 4 | BOS level | `invalidation.py` |
| 5 | ATR fallback: `entry ± atr × 1.5` | `invalidation.py` |

**SL Buffer** (`trade_engine.py:137-144`):
```python
if invalidation.type in ("sweep_extreme", "ob_boundary", "swing_point", "structure_break"):
    sl_buffer = atr * 0.5    # structural levels
else:
    sl_buffer = atr * 0.25   # ATR fallback
```

**Candle Safety** (`trade_engine.py:151-186`):
- Если SL внутри текущей свечи → `total_buffer = spread_buffer + tick_buffer + atr × 0.15`

**HTF POI Override** (`trade_engine.py:188-208`):
- Если цена рядом с HTF POI → `sl = htf_sl ± sl_buffer`

#### TP — Приоритет источников (trade_engine.py:210-239):

| Приоритет | Источник | Score bonus |
|-----------|----------|-------------|
| 1 | External Liquidity (EQH/EQL) | 2.0 |
| 2 | Opposing OB midpoint | 1.5 |
| 3 | Active FVG boundary | 1.2 |
| 4 | Swing structure | — |
| 5 | ATR fallback: `entry ± atr × 3.0` | 0.3 |

**Минимальная дистанция TP:** `atr × 1.0` (line 363)

**RR Validation** (`trade_engine.py:278-287`): `reward < risk × 1.0` → REJECTED

### 3.6 HTF Bias

**V2** (дефолт ON) — `market_structure/htf_bias_v2.py:88-172`:

- **EMA 21/55** на W1, D1, H4, H1 (line 63-64)
- Bullish: `price > ema21 > ema55` (line 68)
- Bearish: `price < ema21 < ema55` (line 70)
- **Majority voting** (line 108-143): 3 TF = STRONG, 2 TF = MODERATE
- **Override** (line 146-158): D1+H4 > W1, W1+D1 > H4

**Gate** (`scanner.py:965-1026`):
- SHORT в bullish HTF → BLOCKED (hard)
- LONG в bearish HTF → BLOCKED (hard)
- Continuation vs HTF mismatch → BLOCKED (hard)
- Reversal vs HTF mismatch → penalty 0.85 (soft)

---

## 4. Все гейты в pipeline (порядок проверок)

| # | Гейт | Файл:строка | Условие | Порог |
|---|------|-------------|---------|-------|
| 0.1 | **Cooldown** | `scanner.py:312-323` | `delta < max(45, tf_min × 2.0)` | 45-480 мин |
| 0.2 | **Max Active Signals** | `scanner.py:326-336` | `active_count >= 10` | 10 |
| 0.2 | **Max Portfolio Risk** | `scanner.py:337-347` | `risk_pct >= 3.7%` | 3.7% |
| 0.2b | **Daily Limits** | `scanner.py:349-363` | `can_open_trade() == False` | 6% risk, 5 trades/day |
| 0.2c | **Position Limits** | `scanner.py:365-397` | `_total >= 10` | 10 |
| 0.3 | **Data Integrity** | `scanner.py:399-410` | `ind is None` | OHLCV доступен |
| 0.4 | **Volatility** | `scanner.py:423-438` | `atr% < 0.3 OR > 5.0` | [0.3%, 5.0%] |
| 0.4b | **Compression** | `scanner.py:440-452` | `regime == "compression"` | Hard gate |
| 1.0 | **Pattern Engine** | `scanner.py:546-582` | `setup.detected == False` | |
| 1.0b | **Score Gate** | `scanner.py:588-603` | `score < 2` | MIN_SCORE=2 |
| 1.4a | **Sweep Required** (reversal) | `scanner.py:614-626` | `not has_sweep` | |
| 1.4a | **Displacement** (reversal) | `scanner.py:628-639` | `not has_displacement` | Config-gated |
| 1.4a | **MSS Gate** (reversal) | `scanner.py:641-649` | SOFT — log only | |
| 1.4a | **BOS Gate** (continuation) | `scanner.py:651-665` | `not has_bos` | |
| 1.4b | **BOS Retest** | `scanner.py:667-682` | `bars_since_bos < 2` | |
| 1.4c | **Entry Zone** | `scanner.py:684-704` | `not entry_armed` | Config-gated |
| 1.42 | **Confirmation Score** | `scanner.py:706-723` | `score < 2` | BOS=2,FVG=1,OB=1 |
| 1.41 | **Breakout Quality** | `scanner.py:737-798` | `verdict == "fake"` | Config-gated |
| 1.42 | **OB Retest** | `scanner.py:800-895` | `config.require_ob_retest` | |
| 1.43 | **Session Filter** | `scanner.py:899-917` | Not in active sessions | Config-gated |
| 1.5 | **HTF Bias** | `scanner.py:941-1026` | Direction vs HTF mismatch | Hard/soft |
| 1.5 | **Trade Plan SL/TP** | `scanner.py:1144-1171` | `sl is None OR tp is None` | |
| 1.6 | **Entry Trigger** | `scanner.py:1175-1209` | `not triggered` | proximity=0.3% |
| 1.7 | **LTF Confirmation** | `scanner.py:1211-1281` | Optional 15m check | |
| 3 | **Probability Engine** | `scanner.py:1763-1804` | `p_tp < min_p_tp` | min=0.30-0.50 |
| 4 | **Risk Engine** | `scanner.py:1822-1865` | `should_trade == False` | R:R≥2.5, SL bounds |
| 4.5 | **Entry Trigger 2** | `scanner.py:1871-1929` | Hypothesis-based | |
| 6 | **Dedup** | `scanner.py:1978-2057` | Same symbol within cooldown | |
| 7 | **Max Spread** | `scanner.py:2077-2090` | `spread > 0.15%` | |
| 7 | **Min Depth** | `scanner.py:2092-2116` | `< $10,000` в 0.5% | |
| 7 | **Correlated Entry** | `scanner.py:2118-2135` | Уже есть позиция | |
| 7 | **TOCTOU Recheck** | `scanner.py:2139-2159` | `active_now >= max` | |
| 7 | **Daily Limits Reserve** | `scanner.py:2161-2172` | `try_open_trade()` | |

### Risk Engine — детально (`risk/engine.py:57-373`):

| # | Gate | Строка | Условие | Порог |
|---|------|--------|---------|-------|
| 1 | Geometry | `153-161` | Не `SL<entry<TP` | |
| 2 | **R:R Minimum** | `196-202` | `rr < 2.5` | min_rr_ratio=2.5 |
| 3a | **SL Min %** | `204-210` | `sl% < 0.25%` | 0.25% |
| 3b | **SL Max %** | `212-224` | `sl% > max(3%, ATR%×2.2)` | clamp ≤ 8% |
| 3c | **SL ATR Min** | `226-242` | `sl% < ATR% × 2.0` | |
| 4 | **EV Gate** | `246-255` | `ev <= 0` | |
| 5 | **Position Sizing** | `260-288` | Kelly half / fixed 1% | |

**Fee-adjusted RR** (`engine.py:172-184`):
```python
fee = 0.05%     # exchange_fee_pct
slip = 0.05%    # slippage_pct
round_trip = (fee + slip) × 2
effective_risk = risk_dist + entry × round_trip
effective_reward = max(0, reward_dist - entry × round_trip)
rr = effective_reward / effective_risk
```

---

## 5. Антиспам / Дедупликация

### Cooldown

```python
# scanner.py:133-136
def get_cooldown_minutes(timeframe, base_minutes, multiplier):
    tf_minutes = _TF_MINUTES.get(timeframe, 60)
    return max(base_minutes, int(tf_minutes * multiplier))
```

- `SIGNAL_COOLDOWN_MINUTES = 45` → `settings.py:747`
- `SIGNAL_COOLDOWN_MULTIPLIER = 2.0` → `settings.py:749`
- **1h TF:** `max(45, 60×2) = 120 мин`
- **4h TF:** `max(45, 240×2) = 480 мин`
- In-memory only → сбрасывается при рестарте

### OB-Aware Mode (`scanner.py:1996-2034`):

- `cooldown_mode = 'ob_aware'` → `settings.py:752`
- Если оба сигнала делят OB (dist ≤ 0.5%) → кулдаун = `full / 3`
- Если разные OB → кулдаун полностью обходится

### Dedup:

- **Same direction** + within cooldown → BLOCKED (`DEDUP_SAME_DIR`)
- **Cross direction** + within cooldown/2 → BLOCKED (`DEDUP_CROSS_DIR`)

---

## 6. Уведомления

### 6.1 Формат Telegram-сообщения

**Точка сборки:** `strategy/signal_engine.py:135-222` — `SignalResult.format_message()`

| Поле | Пример | Строка |
|------|--------|--------|
| Direction + header | `🟢 BUY — ПОКУПКА — BTC/USDT` | 143-145 |
| HTF Context | `HTF Context: STRONG BULLISH (W1✓ D1✓ H4✓)` | 148-160 |
| Zone type | `Zone: DISCOUNT (fib 0.38)` | 163-166 |
| HTF POI | `🎯 HTF POI: D1 OB bullish (1.2% от цены)` | 171-177 |
| Timeframe | `Таймфрейм: 1H` | 179 |
| Entry | `Entry: 65432.1` | 180 |
| Stop Loss | `SL: 64800.0 (-0.97%)` + source tag | 182-187 |
| Take Profit | `TP: 67200.0 (+2.70%)` | 188-190 |
| Risk:Reward | `RR: 1:2.8` | 191-193 |
| Zone Quality | `Zone Quality: 1.2x (discount entry)` | 196-197 |
| Confidence | `Confidence: 72/100` | 199-204 |
| Elliott Wave | `🌊 Вна: impulse (1-2-3-4-5) 🟢 бычий (85%)` | 206-221 |

### 6.2 Триггер отправки

```
main.py:115 → notify_callback=send_signal
tasks.py:61 → run_scan_cycle(notify_callback)
scanner.py:2270-2273 → notify_callback(result, context_verdict)
notifier.py:91 → send_signal(result, verdict)
notifier.py:98 → bot.send_message(chat_id, text, parse_mode=HTML)
```

**Условие:** Сигнал прошёл ВСЕ гейты в pipeline.

### 6.3 HTML форматирование

- ParseMode: `ParseMode.HTML` → `notifier.py:98`
- `<b>`, `<code>`, `<a href>` теги
- **Обязательно:** `html.escape()` на каждом динамическом подстроке → `AGENTS.md`
- Ошибка `<` без escape → краш Telegram parser

### 6.4 Channel / Chat ID

| Назначение | Env var | Файл |
|------------|---------|------|
| Основной канал | `TELEGRAM_CHANNEL_ID` | `settings.py:25` |
| Error канал | `TELEGRAM_ERROR_CHANNEL_ID` | `settings.py:31` |
| Admin IDs | `TELEGRAM_ADMIN_IDS` | `settings.py:27-29` |

### 6.5 Обработка ошибок отправки

| Сценарий | Действие | Файл:строка |
|----------|----------|-------------|
| TelegramError | Retry × 3, delay 2^attempt (1с, 2с, 4с) | `notifier.py:102-106` |
| Все ретраи исчерпаны | ERROR log | `notifier.py:108` |
| Не-TG ошибка | ERROR log + send_error_alert admin'у | `notifier.py:109-115` |
| Channel ID не задан | WARNING + skip | `notifier.py:86-88` |
| Close notification fail | WARNING + silent | `outcome_tracker.py:175-176` |

### 6.6 Close Notifications

**Точка:** `scheduler/outcome_tracker.py:121-176` — `_send_close_notification()`

| Статус | Эмодзи | Метка |
|--------|--------|-------|
| HIT_TP | ✅ | Тейк Профит |
| HIT_SL | 🛑 | Стоп Лосс |
| TIME_STOP | ⏰ | Тайм Стоп |
| FLIP_BIAS | 🔄 | Смена Тренда |
| SWEEP_BREACH | 💥 | Пробой Уровня |

Интервал проверки: `OUTCOME_CHECK_INTERVAL_SECONDS = 300` (5 мин) → `outcome_tracker.py:21-23`

---

## 7. Псевдокод полного pipeline

```
SCAN CYCLE (каждые 15 мин):
  for symbol in get_active_symbols():        # env + dynamic - disabled
    for tf in primary_timeframes:            # [1h, 4h]
      scan_symbol_v2(symbol, tf)

scan_symbol_v2(symbol, tf):
  # ═══ PHASE 0: Hard Gates ═══
  IF cooldown_active(symbol, tf):           RETURN None  # max(45, tf_min×2)
  IF active_count >= max_active_signals:    RETURN None  # 10
  IF portfolio_risk >= max_risk_pct:        RETURN None  # 3.7%
  IF daily_limit_exceeded:                  RETURN None  # 6%/5 trades
  IF total_positions >= max_positions:      RETURN None  # 10
  IF indicators_unavailable:                RETURN None  # OHLCV fail
  IF atr% < 0.3 OR atr% > 5.0:            RETURN None  # volatility
  IF regime == "compression":               RETURN None  # block_compression

  # ═══ PHASE 1: Pattern Engine ═══
  setup = pattern_engine.detect(sweeps, obs, structure, fvgs, ...)
  IF NOT setup.detected:                    RETURN None

  IF setup.components_count < 2:            RETURN None  # score gate

  # ═══ PHASE 1.4: Setup-Type Gates ═══
  IF reversal:
    IF NOT has_sweep:                       RETURN None
    IF NOT has_displacement:                RETURN None  # config-gated
    # MSS = soft (log only)
  IF continuation:
    IF NOT has_bos:                         RETURN None
    IF bars_since_bos < 2:                  RETURN None

  IF confirmation_score < 2:                RETURN None  # BOS=2,FVG=1,OB=1

  # ═══ PHASE 1.5: HTF Bias ═══
  IF sell AND htf_bias == bullish:          RETURN None  # hard block
  IF buy AND htf_bias == bearish:           RETURN None  # hard block

  # ═══ PHASE 1.5-1.6: Trade Plan + Entry ═══
  trade_plan = build_trade_plan(ind, direction, structure, ...)
  IF sl is None OR tp is None:              RETURN None
  IF NOT entry_trigger.triggered:           RETURN None

  # ═══ PHASE 2: Feature Builder ═══
  features = feature_builder.build(ind, structure, ...)

  # ═══ PHASE 3: Probability Engine ═══
  probability = probability_engine.predict(features)
  IF probability.p_tp < min_p_tp:           RETURN None  # 0.30-0.50

  # ═══ PHASE 4: Risk Engine ═══
  decision = risk_engine.evaluate(entry, sl, tp, probability, portfolio)
  IF NOT decision.should_trade:             RETURN None
  #   R:R >= 2.5, SL in [0.25%, max(3%,ATR×2.2)], EV > 0, Kelly sizing

  # ═══ PHASE 6: Dedup ═══
  IF same_signal_within_cooldown:           RETURN None
  #   OB-aware: same OB → cooldown/3, different OB → bypass

  # ═══ PHASE 7: Execution Filters ═══
  IF spread > 0.15%:                        RETURN None
  IF depth < $10,000 in 0.5%:              RETURN None
  IF correlated_position_exists:            RETURN None
  # TOCTOU recheck portfolio limits

  # ═══ SEND ═══
  save_signal_to_db()
  send_signal_to_telegram(result)
  notify_callback(result, verdict)
```

---

## 8. Таблица: индикатор → параметры → роль

| Индикатор | Параметры | Роль в сигнале |
|-----------|-----------|----------------|
| EMA Fast | period=8 | ML фича, trend alignment |
| EMA Slow | period=21 | ML фича, trend alignment, HTF Bias |
| EMA Trend | period=55 | ML фича, HTF Bias |
| RSI | period=10, OB=72, OS=28 | ML фича (НЕ гейт) |
| MACD | fast=8, slow=21, signal=5 | ML фича, momentum |
| ADX | period=14, min=26 | ML фича, trend strength |
| DMI | derived from ADX | ML фича, direction |
| ATR | period=14 | SL/TP расчёт, volatility filter |
| Supertrend | period=10, mult=2.5 | Legacy weighted score (вес=5) |
| Volume SMA | period=20 | ML фича, volume filter |
| Volume Delta | taker buy vs sell | ML фича, delta alignment |
| BTC EMA200 | period=200, TF=4h | Global trend filter |
| HTF EMA 21/55 | W1, D1, H4, H1 | HTF Bias V2 |
| Volume Profile | POC, VAH, VAL | ML фича, zone detection |

---

## 9. TODO / Заглушки / Временные значения

| Что | Где | Статус |
|-----|-----|--------|
| `CLASSIC_INDICATORS_MODE = "soft"` | `settings.py:702-703` | Не задействован в v2 pipeline |
| RSI/ADX/MACD как гейты |舊 weighted model | Заменены на ML фичи в v2 |
| Confirmation TF (15m/5m) | `scanner.py:1211-1281` | Optional, config-gated |
| Session Filter | `scanner.py:899-917` | Config-gated, default OFF |
| Breakout Quality hard gate | `scanner.py:737-798` | Config-gated, default OFF (shadow only) |
| OB Retest hard gate | `scanner.py:800-895` | Config-gated |
| SMT Divergence | `scanner.py:725-735` | Soft, no blocking |
| `MAX_ACTIVE_SIGNALS=10` | `.env:79` | Поднят для data collection |
| `MAX_POSITIONS_TOTAL=10` | `settings.py:370` | Поднят для data collection |
| Cooldown in-memory | `scanner.py` | Сбрасывается при рестарте |
| Kelly capped at 10% | `risk/engine.py:278` | Hard cap |
| Fee = 0.05%, Slippage = 0.05% | `risk/engine.py:172-184` | Заходано в config |
