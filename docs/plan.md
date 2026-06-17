# Trading Signal Bot — Полная документация функционала

## Содержание

1. [Архитектура и модули](#1-архитектура-и-модули)
2. [Индикаторы](#2-индикаторы)
3. [Движок сигналов (Signal Engine)](#3-движок-сигналов-signal-engine)
4. [Система скоринга и confidentity](#4-система-скоринга-и-confidence)
5. [Сканер и пайплайн](#5-сканер-и-пайплайн)
6. [Рыночная структура и ликвидность](#6-рыночная-структура-и-ликвидность)
7. [Производные и корреляции](#7-производные-и-корреляции)
8. [Управление рисками](#8-управление-рисками)
9. [Контекст рынка](#9-контекст-рынка)
10. [Планировщик и крон](#10-планировщик-и-крон)
11. [Telegram-бот](#11-telegram-бот)
12. [Веб-интерфейс](#12-веб-интерфейс)
13. [База данных](#13-база-данных)
14. [Конфигурация](#14-конфигурация)
15. [Запуск и жизненный цикл](#15-запуск-и-жизненный-цикл)

---

## 1. Архитектура и модули

### Структура проекта

```
tgbot/
├── main.py                  # Точка входа
├── config/
│   ├── settings.py          # Все настройки (AppConfig, 13 вложенных dataclass)
│   └── logger.py            # Конфигурация loguru
├── indicators/
│   └── engine.py            # Расчёт индикаторов (pandas-ta)
├── strategy/
│   ├── signal_engine.py     # Оценка сигналов, фильтры, скоринг
│   └── levels.py            # Уровни поддержки/сопротивления
├── scheduler/
│   ├── tasks.py             # APScheduler, cron-задачи
│   ├── scanner.py           # Основной пайплайн сканирования (1026 строк)
│   ├── circuit_breaker.py   # Автостоп при series of losses
│   └── outcome_tracker.py   # Отслеживание TP/SL
├── bot/
│   ├── handlers.py          # Команды /start, /help, /status и т.д.
│   ├── menu.py              # Inline-меню, фильтры, анализ
│   ├── admin.py             # Админ-команды
│   ├── notifier.py          # Отправка сигналов в Telegram
│   └── rate_limit.py        # Ограничение частоты запросов
├── web/
│   ├── server.py            # aiohttp сервер, REST API, WebSocket
│   └── public/
│       ├── index.html       # Dashboard HTML
│       ├── js/app.js        # JavaScript (452 строки)
│       └── css/dashboard.css # Стили (580 строк)
├── data/
│   └── exchange_client.py   # Клиент биржи (ccxt)
├── storage/
│   └── database.py          # SQLAlchemy ORM, CRUD
├── context/
│   ├── fetcher.py           # Получение данных: F&G, Funding, OI, новости
│   ├── analyzer.py          # Сборка контекстного снимка
│   └── scorer.py            # Скоринг контекста
├── scoring/
│   └── confidence_v2.py     # Confidence Engine V2 (10 факторов)
├── liquidity/
│   ├── sweep.py             # Детекция liquidity sweeps
│   ├── order_blocks.py      # Детекция order blocks
│   ├── fvg.py               # Детекция Fair Value Gaps
│   └── candle_quality.py    # Анализ качества свечей
├── market_structure/
│   ├── structure.py         # Анализ структуры (BOS, CHoCH, тренд)
│   ├── distance_filter.py   # Фильтр расстояния до S/R
│   └── tp_path.py           # Проверка пути до TP
├── derivatives/
│   ├── btc_correlation.py   # Корреляция с BTC
│   └── eth_correlation.py   # Корреляция с ETH
├── risk/
│   ├── market_regime.py     # Детекция рыночного режима
│   ├── volatility_regime.py # Классификация волатильности
│   ├── no_trade_zones.py    # Зоны запрета торговли
│   └── dynamic_risk.py      # Динамический расчёт рисков
├── backtest/
│   ├── engine.py            # Движок бэктеста
│   └── ...
└── .env.example             # Пример переменных окружения
```

### Потоки данных

```
Exchange (OHLCV) → IndicatorEngine → SignalEngine → Scanner Pipeline → Telegram Notification
                                         ↑                                    ↓
                                   Regime/Liquidity/Structure           Web Dashboard
                                         ↑                                    ↓
                                   Context Engine                    WebSocket Broadcast
```

---

## 2. Индикаторы

**Модуль:** `indicators/engine.py` — `IndicatorEngine` (stateless, singleton `indicator_engine`)

**Библиотека:** pandas-ta

### Расчётные индикаторы

| Индикатор | pandas-ta | Параметры по умолчанию | Колонки DF |
|---|---|---|---|
| EMA Fast | `ta.ema(close, length=N)` | 8 | `ema_fast` |
| EMA Slow | `ta.ema(close, length=N)` | 21 | `ema_slow` |
| EMA Trend | `ta.ema(close, length=N)` | 55 | `ema_trend` |
| RSI | `ta.rsi(close, length=N)` | 10 | `rsi` |
| MACD | `ta.macd(close, fast, slow, signal)` | 8/21/5 | `macd`, `macd_signal`, `macd_hist` |
| ADX + DMI | `ta.adx(high, low, close, length=N)` | 14 | `adx`, `dmi_plus`, `dmi_minus` |
| ATR | `ta.atr(high, low, close, length=N)` | 14 | `atr` |
| Supertrend | `ta.supertrend(high, low, close, length, multiplier)` | 10/2.5 | `supertrend`, `supertrend_dir` |
| Volume SMA | `ta.sma(volume, length=N)` | 20 | `volume_sma` |
| Volume Delta | Ручной расчёт | — | `volume_delta_pct` |

### Volume Delta (ручной расчёт)

```python
buy_vol = df["taker_buy_volume"]
sell_vol = df["volume"] - buy_vol
delta_pct = (buy_vol - sell_vol) / df["volume"] * 100
```

Доступен только для фьючерсов (наличие `taker_buy_volume` колонки).

### Дата-класс `IndicatorValues`

Все поля:

| Поле | Тип | Описание |
|---|---|---|
| `symbol`, `timeframe` | str | Торговая пара, таймфрейм |
| `close`, `high`, `low`, `volume` | float | OHLCV последней закрытой свечи |
| `ema_fast`, `ema_slow`, `ema_trend` | float | Значения EMA |
| `ema_fast_prev`, `ema_slow_prev` | float | EMA предыдущей свечи |
| `rsi` | float | RSI |
| `macd`, `macd_signal`, `macd_hist`, `macd_hist_prev` | float | MACD |
| `adx`, `dmi_plus`, `dmi_minus` | float | ADX/DMI |
| `atr` | float | ATR |
| `supertrend`, `supertrend_direction` | float/int | Supertrend |
| `volume_sma` | float | SMA объёма |
| `volume_delta_pct` | Optional[float] | Delta объёма (%) |

### Вычисляемые свойства (computed properties)

| Свойство | Логика |
|---|---|
| `ema_bullish_cross` | `ema_fast_prev <= ema_slow_prev` AND `ema_fast > ema_slow` |
| `ema_bearish_cross` | `ema_fast_prev >= ema_slow_prev` AND `ema_fast < ema_slow` |
| `ema_bullish_alignment` | `ema_fast > ema_slow > ema_trend` |
| `ema_bearish_alignment` | `ema_fast < ema_slow < ema_trend` |
| `macd_bullish_cross` | `macd_hist_prev < 0` AND `macd_hist > 0` |
| `macd_bearish_cross` | `macd_hist_prev > 0` AND `macd_hist < 0` |
| `volume_above_avg` | `volume > volume_sma * volume_factor` |
| `trend_is_strong` | `adx >= adx_min` |
| `supertrend_bullish` | `supertrend_direction == 1` |
| `supertrend_bearish` | `supertrend_direction == -1` |

---

## 3. Движок сигналов (Signal Engine)

**Модуль:** `strategy/signal_engine.py` — `SignalEngine` (singleton `signal_engine`)

### SignalResult — все поля

| Поле | Тип | Описание |
|---|---|---|
| `signal` | SignalType | `BUY` / `SELL` / `NO_SIGNAL` |
| `symbol`, `timeframe`, `close` | str/float | Базовые данные |
| `entry_price` | Optional[float] | Цена входа (по умолчанию = close) |
| `sl`, `tp` | Optional[float] | Stop Loss / Take Profit |
| `reasons` | List[str] | Список human-readable причин |
| `score` | int | Количество причин (len(reasons)) |
| `sr_levels` | dict | Уровни S/R |
| `level_warnings` | list | Предупреждения по уровням |
| `_context_score`, `_max_context_score` | float | Контекстный скор |
| `_ema_alignment_info` | str | Инфо о спреде EMA |
| `_rsi_strength` | float | Сила RSI |
| `_factor_strengths` | Dict[str, float] | Силы 7 факторов + BUY/SELL |
| `_weighted_score` | float | Взвешенная сумма |
| `_has_trigger`, `_has_leading_trigger` | bool | Наличие триггера |
| `_regime` | Optional[str] | Рыночный режим |
| `_regime_blocked` | bool | Заблокировано режимом |
| `_confidence_v2` | Optional[ConfidenceResult] | Confidence V2 |

### Константы

| Константа | Значение | Назначение |
|---|---|---|
| `CLOSE_CONFIRMATION_BUY_MIN` | `0.6` | Для BUY: close в верхних 40% диапазона свечи |
| `CLOSE_CONFIRMATION_SELL_MAX` | `0.4` | Для SELL: close в нижних 40% диапазона свечи |

### Полная последовательность gate'ов (в порядке оценки)

```
[0] None/NaN guard ────────── FAIL → NO_SIGNAL
    (12 критических полей: rsi, adx, ema_fast, ema_slow, ema_trend,
     macd_hist, dmi_plus, dmi_minus, volume, volume_sma, atr, close)

[1] Regime: compression? ──── YES → отложить до Gate 1b

[2] ADX flat filter ───────── FAIL → NO_SIGNAL
    Toggle: adx_filter_enabled (true)
    Порог: adx < 18 (compression) или < 20 (обычно)

[3] Leading triggers ──────── Детекция: BOS / sweep / volume delta
    BOS: structure.last_bos.type (bullish/bearish)
    Sweep: sweeps с is_valid == True
    Volume Delta: volume > volume_sma * 1.5 AND delta > 15% или < -15%

[3b] Order blocks ─────────── Вспомогательная проверка (не gate)
    Ближайший OB в пределах 2% от close

[4] Trigger gate ──────────── FAIL → NO_SIGNAL
    Toggle: trigger_required (true)
    3 уровня принятия:
    1. Leading trigger (BOS/sweep/delta) → has_trigger = True
    2. Fallback: structure=None → EMA cross или MACD cross
    3. Momentum entry: supertrend_aligned + ema_aligned + ADX >= 22 + vol > avg

[5] EMA alignment gate ────── FAIL → NO_SIGNAL
    Toggle: ema_alignment_enabled (true)
    BUY: ema_fast > ema_slow > ema_trend
    SELL: ema_fast < ema_slow < ema_trend

[6] EMA spread gate ───────── FAIL → NO_SIGNAL
    Toggle: ema_spread_enabled (true)
    Порог: spread < 0.20% (min_ema_spread_pct)

[7] EMA slope gate ────────── FAIL → NO_SIGNAL (ОТКЛЮЧЁН по умолчанию)
    Toggle: ema_slope_check (false)
    Проверка: abs(current_spread) < abs(prev_spread) * 0.95 (сужение > 5%)

[1b] Compression breakout ── FAIL → NO_SIGNAL + BLOCKED
    (отложенный от Gate 1, если regime == "compression")
    Требуется ВСЁ:
    - Сильный триггер (BOS или валидный sweep)
    - Volume > volume_sma * 2.0
    - Supertrend aligned
    - ATR расширяется (atr_pct >= 0.3)

[8] Min score gate ────────── FAIL → NO_SIGNAL
    Toggle: min_score_enabled (true)
    Порог: len(reasons) < min_score_for_signal (по умолчанию 2)

[9] Candle close gate ─────── FAIL → NO_SIGNAL
    Toggle: candle_close_enabled (true)
    Пропуск для sweep setup
    BUY: close_position < 0.6 → reject
    SELL: close_position > 0.4 → reject
```

### Определение направления (priority cascade)

1. **Leading triggers** (приоритет): анализ keywords в leading_reasons
   - "бычий" / "покупки" → `"buy"`
   - "медвежий" / "продажи" → `"sell"`
2. **Lagging crosses** (fallback): EMA cross или MACD cross
3. **EMA fast vs slow** (ultimate fallback)

### 7 факторов скоринга (weighted factor model)

| Фактор | Вес по умолч. | Функция | Диапазон |
|---|---|---|---|
| Supertrend | 5 | aligned=1.0, anti=-0.5 | [-0.5, 1.0] |
| EMA | 10 | spread-based normalized | [-1.0, 1.0] |
| MACD | 10 | histogram % от цены * 10 | [-1.0, 1.0] |
| RSI | 5 | 4-уровневая шкала по зонам | [-1.0, 1.0] |
| Volume | 15 | composite volume + delta | [-0.3, 1.0] |
| ADX | 5 | linearly scaled 20→50 | [0.0, 1.0] |
| DMI | 5 | (DMI+ - DMI-) / 50 * 2 | [-1.0, 1.0] |

**Общий вес:** 5+10+10+5+15+5+5 = **55**

### Детали factor strength функций

#### Supertrend
```python
if direction == "buy" and supertrend_direction == 1:  return 1.0
if direction == "sell" and supertrend_direction == -1: return 1.0
return -0.5
```

#### EMA
```python
if aligned:
    spread = abs(ema_fast - ema_slow) / ema_slow * 100
    return min(1.0, spread / ema_strength_cap)  # ema_strength_cap=1.0
return -1.0
```

#### MACD
```python
norm = abs(macd_hist / close) * 100
if norm < min_macd_pct (0.03): return 0.0  # шумофильтр
raw = (macd_hist / close * 100) * macd_score_multiplier (10)
return clamp(raw, -1.0, 1.0)
```

#### RSI (для BUY)

| RSI | Сила |
|---|---|
| <= 28 (oversold) | 1.0 |
| 28-55 (bull zone) | 0.5 |
| 55-72 (neutral) | 0.0 |
| >= 72 (overbought) | -1.0 |

Для SELL — инверсия.

#### Volume
```python
if volume < volume_sma * 1.5: return -0.3
if delta available:
    delta_factor = min(1.0, abs(delta) / 30.0)
    s = min(1.0, 0.3 + 0.4*(vol_ratio-1) + 0.3*delta_factor)
    if delta aligned with direction: return s
    else: return -s * 0.5
return min(1.0, 0.3 + 0.4*(vol_ratio-1))  # без delta
```

#### ADX
```python
if adx < adx_min (20): return 0.0
strength = (adx - adx_min) / adx_strength_range (30)
return clamp(strength, 0.0, 1.0)
```

#### DMI
```python
diff = dmi_plus - dmi_minus
raw = (diff / dmi_norm_divisor (50)) * dmi_strength_multiplier (2)
if direction == "sell": raw = -raw
return clamp(raw, -1.0, 1.0)
```

### Confirmation Logic (`evaluate_confirm`)

Лёгкая проверка на confirmation timeframe (по умолчанию 15m):

```python
ema_aligned = (direction == 'buy' and fast > slow) or (direction == 'sell' and fast < slow)
st_aligned = (direction == 'buy' and st_dir == 1) or (direction == 'sell' and st_dir == -1)
return ema_aligned or st_aligned  # True если подтверждено
```

Данные = `None` → проходит (True).

### SL/TP Расчёт

**С ATR:**
- BUY: `sl = close - atr * 1.5`, `tp = close + atr * 3.0`
- SELL: `sl = close + atr * 1.5`, `tp = close - atr * 3.0`
- R/R ≈ 1:2

**С BOS (если доступен):**
- BUY + bullish BOS: `sl = bos_level * 0.995`, `tp = close + atr * 3.0`
- SELL + bearish BOS: `sl = bos_level * 1.005`, `tp = close - atr * 3.0`

**Fallback ATR:** если ATR = 0, используется `close * atr_fallback_pct%` (2%).

### Verdict (свойство)

1. `_regime_blocked == True` → `"BLOCKED"`
2. `_confidence_v2` задан: quality → `"STRONG"` / `"MODERATE"` / `"WEAK"`
3. Fallback по score:
   - `>= 6` → `"STRONG"`
   - `>= 4` → `"MODERATE"`
   - `>= 2` → `"WEAK"`
   - иначе → `"VERY WEAK"`

### Confidence (свойство)

1. Если `_confidence_v2`: `abs(total_score)`
2. Fallback:
   ```python
   tech_pct = score / 7
   market_pct = (context_score + 1.0) / 2.0
   blend = 0.6  # tech_confidence_blend
   confidence = tech_pct * blend + market_pct * (1 - blend)
   return confidence * 100
   ```

---

## 4. Система скоринга и Confidence

### Confidence Engine V2 (`scoring/confidence_v2.py`)

10 взвешенных факторов (общий вес = 100):

| Фактор | Вес | Функция скоринга | Диапазон |
|---|---|---|---|
| HTF Trend | 15 | `score_htf_trend(mtf_aligned, count, required)` | [-0.5, 1.0] |
| Structure | 25 | `score_structure(trend, bos, direction)` | [-0.8, 1.0] |
| Liquidity | 15 | `score_liquidity(sweeps, OB, FVG)` | [-1.0, 1.0] |
| Volume | 10 | `score_volume(above, ratio)` | [-0.3, 0.8] |
| BTC Correlation | 10 | `score_btc_correlation(allows, strong)` | [-0.8, 0.8] |
| Funding | 5 | `score_funding_from_state(state, strength, dir)` | [-0.8, 0.8] |
| OI | 5 | `score_oi_from_state(pattern, significance, dir)` | [-0.8, 0.8] |
| RSI | 5 | `score_rsi(rsi, direction, thresholds)` | [-0.8, 0.6] |
| MACD | 5 | `score_macd(hist, price, direction)` | [-1.0, 1.0] |
| ADX | 5 | `score_adx(adx, dmi+, dmi-, dir, adx_min)` | [-0.5, 2.0] |

**total_score** = sum(raw_score * weight) clamped [-100, 100]

**Quality thresholds:**
- `>= 65` → `"strong"`
- `>= 40` → `"moderate"`
- иначе → `"weak"`

### Blending с историческим winrate

```python
blended = historical_wr * 0.6 + score_confidence * 0.4
```

Применяется только когда direction = BUY или SELL и `historical_winrate` доступен.

### Factor Fingerprint

Детерминированная строка вида `"adx_strong|ema_bullish|mtf_aligned|st_bullish|vol_above"`, используемая для lookup исторического winrate в БД.

---

## 5. Сканер и пайплайн

**Модуль:** `scheduler/scanner.py` — `scan_symbol()` (1026 строк)

### Полный пайплайн (все стадии)

```
Stage 0:  Cooldown check (45 мин per symbol+TF)
Stage 1:  Fetch OHLCV + indicators (primary TF)
Stage 1.5: Market regime detection (compression/range/expansion/trend)
Stage 1.6: Early liquidity & structure analysis (sweeps, OB, structure)
Stage 1.7: Signal evaluation (signal_engine.evaluate)
Stage 2:  Confirmation on 15m (evaluate_confirm)
Stage 2.5: S/R levels (1h + 4h)
Stage 2.6: Distance filter (> 1.2% от S/R)
Stage 2.7: TP path quality (no strong obstacles)
Stage 2.8: Market structure (BOS, CHoCH, trend)
Stage 2.8b: Liquidity analysis (sweeps, OB, FVG, candle quality)
Stage 2.9: MTF alignment (>= 2 HTFs, 1 для reversal)
Stage 2.10: BTC correlation gate
Stage 2.11: ETH correlation gate
Stage 2.12: Volatility regime (ATR%)
Stage 3:   Context enrichment (F&G, funding, OI, news)
Stage 3b:  No-trade zones
Stage 3c:  Dynamic risk calculation
Stage 3.5: Confidence Engine V2
Stage 3.6: Factor fingerprint
Stage 4:   Save to database
Stage 5:   Set cooldown
Stage 6:   Notification to Telegram
```

### Cooldown

- Время: `SIGNAL_COOLDOWN_MINUTES` = 45 мин
- Ключ: `symbol + ":" + timeframe`
- Хранение: in-memory (сбрасывается при перезапуске) + DB

### Circuit Breaker

- 3 последовательных `HIT_SL` → пауза 30 минут
- Окно проверки: 60 минут
- Автосброс по истечении паузы

### Outcome Tracker

- Проверка каждые 300 секунд
- Для каждого открытого outcome: fetch 1m OHLCV
- BUY: `current >= tp` → HIT_TP, `current <= sl` → HIT_SL
- SELL: `current <= tp` → HIT_TP, `current >= sl` → HIT_SL
- PnL: `(current - entry) / entry * 100` (инвертирован для SELL)
- Истечение: > 7 дней → EXPIRED

---

## 6. Рыночная структура и ликвидность

### Structure Analysis (`market_structure/structure.py`)

**Swing Points:** локальные максимумы/минимумы в окне `2*swing_window+1`

**BOS (Break of Structure):**
- Bullish BOS: `last_high > prev_high` в bullish структуре
- Bearish BOS: `last_low < prev_low` в bearish структуре

**CHoCH (Change of Character):**
- Bullish CHoCH: `last_high > prev_high` в bearish структуре (разворот)
- Bearish CHoCH: `last_low < prev_low` в bullish структуре (разворот)

**Trend Classification:**
1. Если есть CHoCH → его тип (разворот доминирует)
2. Если есть BOS → его тип
3. Иначе: сравнение последних 2 high/low

### MTF Alignment

- Определяет HTFs старше primary TF (по секундам)
- Для каждого HTF: fetch 100 candles → analyze_structure
- Aligned: trend совпадает с направлением сигнала
- Ranging НЕ считается aligned
- Требование: >= 2 HTF aligned (для reversal: >= 1)

### Liquidity Sweeps (`liquidity/sweep.py`)

**Детекция:**
1. Найти swing highs/lows (window=5)
2. Для каждой свечи:
   - Bearish sweep: `high > swing_high` И next candle `close < swing_high`
   - Bullish sweep: `low < swing_low` И next candle `close > swing_low`

**Валидность sweep:**
- `volume_ratio > 1.5` (volume/SMA)
- `reclaim_candles <= 3`

**Strength:** 0.0-1.0
- Fast reclaim (<=3): +0.3
- High volume (>1.5x): +0.3
- Delta aligned: +0.2
- Displacement after: +0.2

### Order Blocks (`liquidity/order_blocks.py`)

**Детекция:**
1. Bearish candle + следующая с displacement >= 2.5%
2. BOS валидация: break above previous swing high (bullish) или below swing low (bearish)
3. ATR displacement >= 1.5
4. Volume ratio >= 1.5
5. Optional retest (price возвращается в OB зону)

**Валидность:** `has_bos AND displacement_atr >= 1.5 AND volume_ratio >= 1.5`

### Fair Value Gaps (`liquidity/fvg.py`)

**Детекция:**
- Bullish FVG: `candle3.low > candle1.high` (gap up)
- Bearish FVG: `candle3.high < candle1.low` (gap down)
- Минимальный размер: 0.4%

**Fill detection:**
- Bullish: `later candle.low <= FVG.top`
- Bearish: `later candle.high >= FVG.bottom`

### S/R Levels (`strategy/levels.py`)

- Swing highs/lows в окне 10
- Кластеризация: уровни в пределах 0.5% объединяются
- Фильтрация: resistance > current_price, support < current_price
- Макс. 2 уровня на TF

### Distance Filter

- LONG: blocked если resistance в пределах 1.2% выше entry
- SHORT: blocked если support в пределах 1.2% ниже entry

### TP Path Quality

- Базовый score: 15 (чистый путь)
- Препятствия: S/R levels, order blocks, FVGs
- 1 сильное = -20 (blocked), 1 слабое = +5, 2+ слабых = -10
- Blocked если score <= -20

---

## 7. Производные и корреляции

### BTC Correlation (`derivatives/btc_correlation.py`)

**BTCContext:**
- Fetch BTC/USDT 4H OHLCV (250 candles)
- EMA200 на 4H
- Structure: HH/LL count за 20 свечей
- Breakout: цена вне 20-свечного диапазона, range < 5%
- Cache: 1 час

**Blocking logic:**
- LONG blocked: `not above_ema200` OR `structure == "bearish"`
- SHORT blocked: `is_breakout and breakout_direction == "bullish"`

### ETH Correlation (`derivatives/eth_correlation.py`)

**ETHContext:**
- Fetch ETH/USDT 4H OHLCV (100 candles)
- Structure: HH/LL count за 20 свечей
- Impulsive move: last 5 candles, change > 3%, bullish ratio >= 60%
- Cache: 1 час

**Blocking logic:**
- LONG blocked: `structure == "bearish"` OR (символ ETH-correlated AND `momentum < -2.0%`)
- SHORT blocked: `is_impulsive_up` OR (символ ETH-correlated AND `structure == "bullish"`)
- ETH-correlated: `OP/USDT`, `ARB/USDT`

---

## 8. Управление рисками

### Market Regime (`risk/market_regime.py`)

**Детекция на основе:**
- ADX (trend strength)
- ATR history (volatility)
- EMA spread (trend tightness)
- Volume history

**Режимы (приоритет):**
1. Compression: ATR percentile < 20%
2. Range: ADX < 20
3. Expansion: ATR rising + volume rising
4. Trend: ADX >= 25 + EMA spread rising
5. Range (fallback)

### Volatility Regime (`risk/volatility_regime.py`)

```
ATR% = (ATR / close) * 100
Low:    ATR% < 0.8%  → allow_breakout = False
Medium: 0.8% - 6.0%  → allow_breakout = True
High:   ATR% > 6.0%  → position_size_multiplier = 0.5
```

### No-Trade Zones (`risk/no_trade_zones.py`)

**Блокирующие условия (ЛЮБОЕ = block):**
1. ATR% < 0.5% (нет momentum)
2. Market structure == "ranging"
3. BTC not aligned
4. TP blocked (obstacle on path)
5. OI extreme (extreme_long / extreme_short) с significance != "ignore"

**Неблокирующие (info only):**
- Neutral funding с weak strength (FIX M5)
- OI None/ignore (FIX P3, spot skip)

### Dynamic Risk (`risk/dynamic_risk.py`)

**Base Risk by Quality:**
| Quality | base_risk_pct |
|---|---|
| strong | 1.0% |
| moderate | 0.5% |
| weak | 0.25% |

**Multipliers:**
- High volatility: ×0.5
- BTC/ETH misaligned: ×0.5

**should_trade:** weak setups → `risk_weak_trade` (default False) → BLOCKED

---

## 9. Контекст рынка

### Context Fetcher (`context/fetcher.py`)

**Источники данных:**

| Источник | URL | Кеш | Retry |
|---|---|---|---|
| Fear & Greed | alternative.me/fng | 1 час | 3 попытки (exp backoff) |
| CoinGecko | coingecko.com/api/v3 | — | — |
| CoinGecko Trending | coingecko.com/search/trending | 30 мин | — |
| Funding Rate | Binance fapi | — | — |
| Open Interest | Binance fapi | — | warm-up |
| Long/Short Ratio | Binance fapi | — | — |
| CryptoPanic | cryptopanic.com/api | — | — |
| RSS News | CoinDesk + Cointelegraph | 5 мин | — |

### Context Scorer (`context/scorer.py`)

**Веса факторов:**

| Фактор | Вес |
|---|---|
| Fear & Greed | 0.15 |
| Funding Rate | 0.25 |
| Long/Short Ratio | 0.20 |
| Open Interest | 0.15 |
| News Sentiment | 0.05 |
| Price Trend (7d) | 0.10 |

**Verdict thresholds:**
- `score >= 0.4` → `"CONFIRMED"`
- `score >= 0.05` → `"WEAK"`
- `score >= -0.1` → `"CONFLICTED"`
- `score < -0.1` → `"BLOCKED"`

### Контекстный блок в уведомлении

```
📊 Контекст рынка:
├ Fear & Greed: {value} ({label}) {emoji}
├ Funding: {rate}% {emoji}
├ Long/Short: {ratio} {emoji}
├ OI: +{delta}% {emoji}
└ Новости: {sentiment_label} {emoji}

🔍 Вердикт: {verdict} (уверенность {confidence%})
```

---

## 10. Планировщик и крон

### TaskScheduler (`scheduler/tasks.py`)

- Библиотека: APScheduler (`AsyncIOScheduler`, timezone="UTC")
- Cron: `:02, :17, :32, :47` (каждые 15 минут)
- `max_instances=1`, `coalesce=True`
- Функция: `run_scan_cycle()` со всеми `primary_timeframes`

### Ручной скан

- `/scan` (admin) → `run_scan_cycle()` по всем primary_timeframes

---

## 11. Telegram-бот

### Команды

| Команда | Доступ | Описание |
|---|---|---|
| `/start` | Все | Главное inline-меню |
| `/help` | Все | Справка по логике |
| `/status` | Все | Состояние: символов, TF, cooldown |
| `/lastsignal` | Все | Последние 5 сигналов |
| `/symbols` | Все | Список отслеживаемых символов |
| `/scan` | Admin | Ручной запуск сканирования |
| `/settings` | Admin | Текущие настройки индикаторов |
| `/addsymbol <SYM>` | Admin | Добавить символ |
| `/removesymbol <SYM>` | Admin | Удалить символ |
| `/listsymbols` | Admin | Список символов (admin) |
| `/setparam NAME VALUE` | Admin | Изменить параметр live |
| `/disable <SYM>` | Admin | Отключить символ |
| `/enable <SYM>` | Admin | Включить символ |
| `/exportdb` | Admin | Экспорт SQLite |
| `/stats` | Admin | Статистика win rate, PnL |

### Главное меню

```
Row 1: [🔍 Анализ токена]  [📊 Индикаторы]
Row 2: [📡 Авто-скан всех]  [🔇 Signal block]
Row 3: [⚙️ Настройки]
```

### Навигация по меню

```
Main Menu
├── m:analyze → Token list → analyze:{SYMBOL} → _do_full_analysis()
│   └── m:custom_token → WAITING "analyze" → text input → _do_full_analysis()
├── m:pick_token → Token list → token:{SYMBOL} → _indicator_view()
│   └── m:custom_token_indicators → WAITING "indicators" → _indicator_view()
├── m:scan_all → _do_scan_all() → summary
├── m:signal_block → m:signal_block_toggle
└── m:settings → m:sf (фильтры) / m:sf_params_list (параметры)
    ├── m:sf → m:sf_detail:{key} / m:sf_toggle:{key}
    └── m:sf_params_list → m:sf_param_set:{key} → WAITING "sf_param:{key}"
```

### Система фильтров (Telegram)

**FILTER_META** — 20 фильтров в 2 группах:

**Ядро сигнала (signal_engine):**
- ADX (флэт), EMA alignment, EMA spread, EMA наклон, Триггер, Candle close, Min score, Компрессия, Подтверждение ТФ

**Сканер (доп. фильтры):**
- MTF alignment, Distance filter, S/R levels, TP path, BTC correlation, ETH correlation, Волатильность, No-trade зоны, Dynamic risk, Контекст, Confidence V2

**Toggle flow:**
1. Click ON/OFF → `_handle_filter_toggle(key)`
2. Flip in memory: `_get_nested_config()` → `_set_nested_config()`
3. Save to DB: `db.set_setting("filter:toggle:{key}", value)`
4. Hot-reload: `reload_filter_toggles()` → applies to live config

**Parameter set flow:**
1. Click param → WAITING state → user types value
2. Cast to type → save to DB: `db.set_setting("filter:param:{key}", value)`
3. Hot-reload

### Уведомления

**Сигнал (`send_signal`):**
```
{BUY|SELL} — {ПОКУПКА|ПРОДАЖА}
Инструмент: {symbol}
Таймфрейм: {TF} | Подтверждение: {confirm_tf}
Цена входа: {entry_price}
Stop Loss: {sl} ({sl_pct:+.2f}%)
Take Profit: {tp} ({tp_pct:+.2f}%)
R/R: 1:{rr}

📐 Уровни поддержки / сопротивления:
┌─ 4H ─
│  🔴 Сопр.: {levels}
│  🟢 Подд.: {levels}
└──────

Технические факторы ({score}/7):
  {reasons}

Итог: {verdict} | Уверенность: {confidence}%
```

**Заблокированный (`send_signal_blocked`):**
```
🚫 Сигнал заблокирован
{emoji} {BUY|SELL} {symbol} {tf}
Причина: {reason}
```

**Ошибка (`send_error_alert`):**
```
⚠️ Ошибка бота:
{html.escape(message)}
```

### Rate Limiting

- `aiolimiter.AsyncLimiter`: 5 запросов за 10 секунд на пользователя
- Ответ: "⏳ Слишком часто, подожди 10 секунд"

### WAITING state

```python
WAITING: dict[int, str]  # chat_id → state
```

| State | Установлен | Потреблён |
|---|---|---|
| `"analyze"` | `m:custom_token` | `handle_menu_message` |
| `"indicators"` | `m:custom_token_indicators` | `handle_menu_message` |
| `"sf_param:{key}"` | `m:sf_param_set:{key}` | `handle_menu_message` |

### HTML escaping

Все сообщения используют `parse_mode=ParseMode.HTML`. Динамический контент escaping через `html.escape()`. При `BadRequest` — повторный escaping всего сообщения.

---

## 12. Веб-интерфейс

### REST API

| Method | Path | Описание |
|---|---|---|
| GET | `/` | Dashboard HTML |
| GET | `/api/filters` | Состояние всех фильтров |
| POST | `/api/filters` | Переключить фильтр |
| GET | `/ws` | WebSocket endpoint |

**Hidden filters** (не отображаются в UI): `ema_slope`, `macd_slope`, `tp_path`

### WebSocket

**Клиент → Сервер:**
```json
{ "type": "subscribe", "symbol": "BTC" }
```

**Сервер → Клиент (каждые 5 сек):**
```json
{
  "type": "update",
  "symbol": "BTC/USDT",
  "price": 67234.56,
  "indicators": { "rsi": 55.3, "macd_hist": -23.3, "ema_fast": 67100, ... },
  "structure": { "trend": "bullish", "bos": {...}, "swing_highs": [...], ... },
  "liquidity": { "order_blocks": [...], "fvg": [...], "sweep": {...} },
  "levels": { "resistance": [...], "support": [...] },
  "signal": { "signal": "BUY", "score": 5, "verdict": "CONFIRMED", "confidence": 78.5, ... },
  "priceHistory": [ { "time": ..., "close": ... }, ... ]
}
```

### Dashboard Layout

1. **Header** — логотип "Trading Signal Bot"
2. **Status Bar** — pulsing dot + статус подключения
3. **Token Search** — input + quick buttons (BTC, ETH, SOL, BNB, XRP)
4. **Signal Card** — тип, score, entry/SL/TP, причины
5. **Indicator Grid** (3×2) — RSI, MACD, EMA, ADX, Supertrend, Volume
6. **Main Row** (2 колонки):
   - Left: Resistance / Support cards
   - Right: Market Analysis AI panel (verdict, regime, trend, chart, SMC)
7. **Filter Bar** — горизонтальный scroll с toggle switches

### JavaScript Functions

| Функция | Назначение |
|---|---|
| `connect()` | WebSocket connection + reconnect |
| `renderDashboard(data)` | Основной диспетчер |
| `renderIndicators(ind)` | 6 карточек индикаторов |
| `renderSignal(sig)` | Карточка сигнала |
| `renderLevelsData(levels)` | S/R уровни |
| `renderSMC(structure, liquidity)` | Smart Money панель |
| `updatePriceChart(history)` | Chart.js line chart |
| `renderVerdictFromSignal(signal, ind)` | Verdict панель |
| `loadFilters()` / `renderFilters()` / `toggleFilter()` | Фильтры |
| `subscribeToToken(symbol)` | Переключение символа |

### CSS Design System

- Background: `#0d0d0d`
- Surface: `#1a1a1a`
- Accent green: `#a3e635`
- Red: `#f87171`
- Font: Inter, 13px base
- Toggle: 36×18px, red/green slider
- Responsive: 900px (2 cols), 560px (stack)

---

## 13. База данных

**Движок:** SQLAlchemy async + aiosqlite
**URL:** `sqlite+aiosqlite:///./data/signals.db`

### Таблицы

#### signals
| Поле | Тип | Описание |
|---|---|---|
| id | Integer PK | Auto-increment |
| symbol | String(20) | Indexed |
| timeframe | String(10) | |
| signal_type | String(10) | BUY/SELL |
| close_price | Float | |
| sl | Float | nullable |
| tp | Float | nullable |
| score | Integer | |
| reasons | Text | |
| confirmed | Boolean | |
| factor_fingerprint | String(255) | Indexed |
| created_at | DateTime | UTC |
| sent_at | DateTime | |

#### bot_settings
| Поле | Тип | Описание |
|---|---|---|
| key | String(100) PK | |
| value | Text | |
| updated_at | DateTime | |

**Ключи:**
- `filter:toggle:{key}` → `"true"` / `"false"`
- `filter:param:{key}` → строковое значение
- `param:{UPPER_NAME}` → legacy format
- `dynamic_symbols` → comma-separated
- `disabled_symbols` → comma-separated
- `cooldown:{symbol}:{timeframe}` → ISO datetime

#### context_snapshots
| Поле | Тип | Описание |
|---|---|---|
| id | Integer PK | |
| symbol | String(20) | |
| signal_id | FK → signals.id | nullable |
| timestamp | DateTime | |
| verdict | String(20) | |
| confidence | Float | |
| score | Float | |
| fear_greed | Integer | |
| funding_rate | Float | |
| long_short_ratio | Float | |
| open_interest_delta | Float | |
| news_sentiment | Float | |
| raw_json | Text | |

#### signal_outcomes
| Поле | Тип | Описание |
|---|---|---|
| id | Integer PK | |
| signal_id | FK → signals.id | |
| status | String(20) | OPEN / HIT_TP / HIT_SL / EXPIRED |
| closed_at | DateTime | |
| close_price | Float | |
| pnl_pct | Float | |
| checked_at | DateTime | |

### CRUD Methods

| Метод | Описание |
|---|---|
| `save_signal(...)` | Сохранить сигнал |
| `get_last_signal(symbol, tf)` | Последний сигнал |
| `get_recent_signals(limit)` | Последние N сигналов |
| `get/set_setting(key, value)` | Key-value storage |
| `get/set_cooldown(symbol, tf)` | Cooldown management |
| `get/set_dynamic_symbols()` | Dynamic symbol list |
| `get/set_disabled_symbols()` | Disabled symbols |
| `save_context_snapshot(...)` | Контекстный снимок |
| `create_outcome(signal_id)` | Создать tracking record |
| `get_open_outcomes()` | Открытые outcomes |
| `close_outcome(...)` | Закрыть outcome |
| `get_outcome_stats()` | Статистика (win rate, PnL) |
| `get_historical_winrate(fingerprint)` | Исторический winrate по fingerprint |

---

## 14. Конфигурация

### AppConfig — 13 вложенных dataclass + top-level поля

| Dataclass | Количество полей | Ключевые параметры |
|---|---|---|
| TelegramConfig | 4 | token, channel_id, admin_ids, error_channel_id |
| ExchangeConfig | 5 | name, api_key, api_secret, testnet, market_type |
| TradingConfig | 35 | symbols, timeframes, EMA/RSI/MACD/ADX/ATR/Supertrend/Volume params, filter toggles |
| LiquidityConfig | 20+ | sweep/OB/FVG/candle quality thresholds |
| MarketStructureConfig | 12 | distance, MTF, S/R, TP path, structure params |
| RiskConfig | 18+ | volatility, position sizing, correlation, regime, no-trade, dynamic risk |
| DerivativesConfig | 12 | funding, OI, BTC/ETH correlation settings |
| ScoringConfig | 20+ | confidence thresholds, weights (13 factors), blending |
| SchedulerConfig | 1 | scan_minutes |
| RateLimitConfig | 2 | max_rate, time_period |
| NotifierConfig | 6 | thresholds for notification formatting |
| SupportResistanceConfig | 5 | SR window, max levels, clustering |
| WebConfig | 4 | port, host, enabled, update_interval |

**Top-level поля:** database_url, log_level, log_file, signal_cooldown_minutes, context_enabled, context_min_verdict, context_block_on_blocked, signal_block_notify, cryptopanic_api_key, coingecko_symbol_map_str, context_fetch_timeout

### FILTER_TOGGLE_KEYS (22 ключа)

Маппинг: `ключ → (путь_к_атрибуту, тип)`. Все boolean.

### FILTER_PARAM_KEYS (40 ключей)

Маппинг: `ключ → (путь_к_атрибуту, тип_каста)`. Типы: int, float, str.

### Hot Reload

```python
async def reload_filter_toggles():
    # 1. Iterate FILTER_TOGGLE_KEYS → db.get_setting("filter:toggle:{key}")
    # 2. Iterate FILTER_PARAM_KEYS → db.get_setting("filter:param:{key}")
    #    Fallback: db.get_setting("param:{KEY_UPPER}")
    # 3. Apply to live config via _set_nested_config()
```

### Runtime Symbols

```python
_runtime_symbols_cache = None

async def refresh_runtime_symbols():
    # Merge config.trading.symbols + db.get_dynamic_symbols()
    # Store in _runtime_symbols_cache

def get_active_symbols():
    return _runtime_symbols_cache or config.trading.symbols
```

---

## 15. Запуск и жизненный цикл

### Startup Sequence (main.py)

```
1. sys.path injection
2. Lock file (.trading_bot.lock)
3. Logger init (loguru)
4. Prometheus metrics (opt-in, port 9090)
5. Environment validation (TELEGRAM_BOT_TOKEN required)
6. Database init (db.init() → create tables + migrations)
7. Runtime symbols refresh
8. Filter toggle reload from DB
9. Exchange connection (ccxt, retry 5x)
10. Web dashboard start (port 3001)
11. Telegram Application creation (HTTPXRequest, pool=8)
12. Error handler registration
13. Handler registration (commands + callback + text)
14. Error sink setup (ERROR+ → Telegram)
15. Scheduler start (cron every 15 min)
16. Outcome tracker start (every 300s)
17. Polling start (drop_pending_updates=True)
18. Main loop (while True: sleep 3600)
```

### Graceful Shutdown

```
1. scheduler.stop()
2. exchange_client.close()
3. context_fetcher.close()
4. web_runner.cleanup()
5. app.updater.stop()
6. app.stop()
7. app.shutdown()
8. release_lock()
```

### Exchange Client

- Синхронный ccxt в executor thread
- Семафор size=1 (сериализация запросов)
- Retry: NetworkError (1,2,4s), RateLimit (5,10,20s), BadSymbol (no retry)
- **Критично:** `df.iloc[:-1]` — отбрасывает последнюю (незакрытую) свечу

### Prometheus Metrics

- `scan_duration_seconds` — время сканирования
- `signals_total` — количество сигналов по типу/символу/TF

---

## Полная таблица всех gate'ов

| # | Gate | Toggle | Default | Порог |
|---|---|---|---|---|
| 0 | Circuit Breaker | Always | — | 3 losses / 30 min pause |
| 0 | Cooldown | Always | — | 45 min per symbol+TF |
| 1 | Data Validity | Always | — | 12 критических полей |
| 2 | ADX Flat | `adx_filter_enabled` | true | ADX < 20 (18 в compression) |
| 3 | Compression | `compression_enabled` | true | 4 условия (trigger+vol+ST+ATR) |
| 4 | Trigger | `trigger_required` | true | 3 уровня: leading/fallback/momentum |
| 5 | EMA Alignment | `ema_alignment_enabled` | true | fast > slow > trend |
| 6 | EMA Spread | `ema_spread_enabled` | true | >= 0.20% |
| 7 | EMA Slope | `ema_slope_check` | **false** | сужение > 5% |
| 8 | Min Score | `min_score_enabled` | true | >= 2 |
| 9 | Candle Close | `candle_close_enabled` | true | BUY >= 60%, SELL <= 40% |
| 10 | Confirm TF | `confirm_tf_enabled` | true | 15m EMA/ST match |
| 11 | Distance | `distance_filter_enabled` | true | > 1.2% от S/R |
| 12 | TP Path | `tp_path_enabled` | **false** | score > -20 |
| 13 | MTF Alignment | `mtf_enabled` | true | >= 2 HTF (1 для reversal) |
| 14 | BTC Correlation | `btc_correlation_enabled` | true | Above EMA200, not bearish |
| 15 | ETH Correlation | `eth_correlation_enabled` | true | Not bearish, not impulsive |
| 16 | Volatility | `volatility_filter_enabled` | true | ATR% >= 0.8% |
| 17 | Context Blocked | `context_enabled` | true | verdict != BLOCKED |
| 18 | Context Min Verdict | `context_enabled` | true | verdict >= WEAK |
| 19 | No-Trade Zones | `no_trade_zones_enabled` | true | ATR, range, BTC, TP, OI |
| 20 | Dynamic Risk | `dynamic_risk_enabled` | true | should_trade (not weak) |
