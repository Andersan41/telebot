# H3: Double Scoring Audit — Полный разбор архитектуры принятия решений

**Дата:** 2025-01-23
**Статус:** Factual audit, NO refactoring proposed

---

## ЭТАП 1. ТОЧКИ ПРИНЯТИЯ РЕШЕНИЙ

### 1.1 signal_engine

| Атрибут | Значение |
|---------|----------|
| **Файл** | `strategy/signal_engine.py` |
| **Класс** | `SignalEngine` |
| **Метод** | `evaluate()` (line 185) |
| **Возвращает** | `SignalResult` с полем `signal: SignalType` |
| **Значения** | `SignalType.BUY` / `SignalType.SELL` / `SignalType.NO_SIGNAL` |
| **Дополнительно** | `score: int` (кол-во supporting reasons, 0-7) |
| **Синглтон** | `signal_engine = SignalEngine()` (line 952) |

Дополнительный метод:
- `evaluate_confirm()` (line 745) — облегчённая проверка для confirmation timeframe (15m). Возвращает `bool`.

### 1.2 confidence_v2

| Атрибут | Значение |
|---------|----------|
| **Файл** | `scoring/confidence_v2.py` |
| **Класс** | `ConfidenceEngineV2` |
| **Метод** | `compute()` (line 71) |
| **Возвращает** | `ConfidenceResult` |
| **Поля** | `total_score: float` (-100..100), `quality: "strong"/"moderate"/"weak"`, `recommendation: "BUY"/"SELL"/"NO_SIGNAL"` |
| **Синглтон** | `confidence_engine_v2 = ConfidenceEngineV2()` (line 303) |

Веса confidence_v2 (10 факторов, сумма=100):
```
HTF Trend: 20, Structure: 15, Liquidity: 20, Volume: 5,
BTC correlation: 15, Funding: 5, OI: 5, RSI: 5, MACD: 5, ADX: 5
```

### 1.3 context_scorer (не confidence_v2!)

| Атрибут | Значение |
|---------|----------|
| **Файл** | `context/scorer.py` |
| **Класс** | `ContextScorer` |
| **Метод** | `score()` (line 43) |
| **Возвращает** | `ContextVerdict` |
| **Поля** | `verdict: "CONFIRMED"/"WEAK"/"CONFLICTED"/"BLOCKED"`, `score: float` (-1.0..1.0), `confidence: float` |
| **Синглтон** | `context_scorer = ContextScorer()` (line 312) |

Веса context_scorer (6 факторов):
```
Fear&Greed: 0.15, Funding: 0.25, L/S: 0.20, OI: 0.15, News: 0.05, PriceTrend: 0.10
```

### 1.4 dynamic_risk (risk_manager)

| Атрибут | Значение |
|---------|----------|
| **Файл** | `risk/dynamic_risk.py` |
| **Функция** | `calculate_risk()` (line 85) |
| **Возвращает** | `RiskParams` |
| **Поля** | `setup_quality`, `base_risk_pct`, `effective_risk_pct`, `should_trade: bool` |
| **Ключевое** | `should_trade` возвращает `False` если quality=="weak" и `risk_weak_trade=false` |

### 1.5 outcome_tracker

| Атрибут | Значение |
|---------|----------|
| **Файл** | `scheduler/outcome_tracker.py` |
| **Функция** | `check_open_outcomes()` (line 25) |
| **Возвращает** | `None` (side effect: обновляет БД) |
| **Роль** | Фоновый трекинг SL/TP. НЕ участвует в принятии решений. |

### 1.6 scanner (оркестратор)

| Атрибут | Значение |
|---------|----------|
| **Файл** | `scheduler/scanner.py` |
| **Функция** | `scan_symbol()` (line 255), `run_scan_cycle()` (line 1185) |
| **Возвращает** | `Optional[SignalResult]` |
| **Роль** | Оркестратор: вызывает все модули, применяет фильтры, сохраняет результат |

---

## ЭТАП 2. CALL CHAIN

```
run_scan_cycle()                            [scanner.py:1185]
  └─ scan_symbol(symbol, tf, ...)           [scanner.py:255]
       │
       ├─ [1] _is_cooldown_active()         [scanner.py:215]
       │    └─ return None (BLOCK)
       │
       ├─ [2] _get_indicators()             [scanner.py:229]
       │    └─ indicator_engine.calculate()
       │
       ├─ [3] _detect_regime()              [scanner.py:173]
       │    └─ RegimeDetector.detect()
       │
       ├─ [4] signal_engine.evaluate_confirm()  [scanner.py:314]
       │    (15m confirmation — до основного evaluate)
       │    └─ return False → return None (BLOCK)
       │
       ├─ [5] signal_engine.evaluate()      [scanner.py:336]
       │    ├─ Gate: None/NaN guard          [line 207]
       │    ├─ Gate: regime compression      [line 233]
       │    ├─ Gate: ADX flat filter         [line 248]
       │    ├─ Gate: supertrend alignment    [line 400]
       │    ├─ Gate: trigger required        [line 494]
       │    ├─ Gate: EMA alignment           [line 523]
       │    ├─ Gate: EMA spread              [line 543]
       │    ├─ Gate: EMA slope               [line 559]
       │    ├─ Gate: min_score               [line 647]
       │    ├─ Gate: candle close            [line 675]
       │    └─ RETURN: SignalResult(NO_SIGNAL) or SignalResult(BUY/SELL)
       │
       ├─ [6] check_distance_filter()       [scanner.py:411]
       │    └─ return blocked=True → return None (BLOCK)
       │
       ├─ [7] evaluate_tp_path()            [scanner.py:429]
       │    └─ blocked=True → return None (BLOCK)
       │
       ├─ [8] check_mtf_alignment()         [scanner.py:652]
       │    └─ not aligned → return None (BLOCK)
       │
       ├─ [9] fetch_btc_context()           [scanner.py:681]
       │    └─ not allows_long/short → return None (BLOCK)
       │
       ├─ [10] fetch_eth_context()          [scanner.py:716]
       │    └─ not allows_long/short → return None (BLOCK)
       │
       ├─ [11] classify_volatility()        [scanner.py:751]
       │    └─ not allow_breakout → return None (BLOCK)
       │
       ├─ [12] context_scorer.score()       [scanner.py:776]
       │    ├─ verdict=BLOCKED → return None (BLOCK)
       │    └─ verdict < CONTEXT_MIN_VERDICT → return None (BLOCK)
       │
       ├─ [13] check_news_block()           [scanner.py:880]
       │    └─ blocked=True → return None (BLOCK)
       │
       ├─ [14] SL distance guard            [scanner.py:898]
       │    └─ too far → return None (BLOCK)
       │
       ├─ [15] R:R guard                    [scanner.py:926]
       │    └─ rr < min_rr → return None (BLOCK)
       │
       ├─ [16] check_no_trade_zones()       [scanner.py:975]
       │    └─ blocked=True → return None (BLOCK)
       │
       ├─ [17] calculate_risk()             [scanner.py:1001]
       │    └─ should_trade=False → return None (BLOCK)
       │
       ├─ [18] confidence_engine_v2.compute()  [scanner.py:1063]
       │    └─ result._confidence_v2 = conf_v2 (ONLY display/risk, NO block)
       │
       ├─ [19] Dedup cooldown               [scanner.py:1100]
       │    └─ same_direction + within_cooldown → return None (BLOCK)
       │
       ├─ [20] db.save_signal()             [scanner.py:1128]
       │
       └─ [21] notify_callback()            [scanner.py:1169]
            └─ send_signal() → Telegram
```

**Ключевой факт:** confidence_engine_v2.compute() вызывается на step [18], ПОСЛЕ всех блокирующих фильтров. Он НЕ может отменить уже прошедший все фильтры сигнал.

---

## ЭТАП 3. КТО ГЕНЕРИРУЕТ СИГНАЛ

**Ответ: A) signal_engine генерирует BUY/SELL**

Точное место в коде:

```python
# strategy/signal_engine.py, line 661
signal_type = SignalType.BUY if direction == "buy" else SignalType.SELL
```

Это единственный момент, где определяется направление сигнала. `direction` устанавливается на lines 340-372 на основе:
1. Leading trigger direction (BOS/sweep/delta) — line 341
2. EMA cross / MACD cross — line 355
3. EMA alignment fallback — line 360

`confidence_v2` НЕ генерирует BUY/SELL. Он принимает `direction` как input:
```python
# scoring/confidence_v2.py, line 71
def compute(self, direction: Literal["BUY", "SELL", "NO_SIGNAL"], ...) -> ConfidenceResult:
```

В scanner.py:
```python
# scheduler/scanner.py, line 1025
direction_v2 = result.signal.value  # "BUY" or "SELL" — берётся из signal_engine
```

---

## ЭТАП 4. КТО МОЖЕТ ЗАБЛОКИРОВАТЬ СИГНАЛ

Полный список блокирующих фильтров:

| # | Условие | Файл | Функция/Строка | Может ли confidence_v2 отменить? |
|---|---------|------|----------------|----------------------------------|
| 1 | Cooldown активен | scanner.py | `_is_cooldown_active()` :215 | Нет |
| 2 | None/NaN в данных | signal_engine.py | `evaluate()` :207 | Нет |
| 3 | Compression без breakout | signal_engine.py | `evaluate()` :414 | Нет |
| 4 | ADX < adx_min | signal_engine.py | `evaluate()` :248 | Нет |
| 5 | Supertrend misaligned | signal_engine.py | `evaluate()` :400 | Нет |
| 6 | Нет триггера | signal_engine.py | `evaluate()` :494 | Нет |
| 7 | EMA alignment fail | signal_engine.py | `evaluate()` :523 | Нет |
| 8 | EMA spread узкий | signal_engine.py | `evaluate()` :543 | Нет |
| 9 | EMA slope weakening | signal_engine.py | `evaluate()` :559 | Нет |
| 10 | min_score < порога | signal_engine.py | `evaluate()` :647 | Нет |
| 11 | Candle close fail | signal_engine.py | `evaluate()` :675 | Нет |
| 12 | 15m confirmation fail | scanner.py | `evaluate_confirm()` :314 | Нет |
| 13 | Distance filter | scanner.py | `check_distance_filter()` :411 | Нет |
| 14 | TP path blocked | scanner.py | `evaluate_tp_path()` :429 | Нет |
| 15 | MTF alignment fail | scanner.py | `check_mtf_alignment()` :652 | Нет |
| 16 | BTC correlation blocks | scanner.py | `fetch_btc_context()` :681 | Нет |
| 17 | ETH correlation blocks | scanner.py | `fetch_eth_context()` :716 | Нет |
| 18 | Low volatility | scanner.py | `classify_volatility()` :757 | Нет |
| 19 | Context BLOCKED | scanner.py | `context_scorer.score()` :824 | Нет |
| 20 | Context < MIN_VERDICT | scanner.py | `_verdict_passes_min()` :836 | Нет |
| 21 | News filter | scanner.py | `check_news_block()` :880 | Нет |
| 22 | SL too far | scanner.py | :898 | Нет |
| 23 | R:R too low | scanner.py | :926 | Нет |
| 24 | No-trade zone | scanner.py | `check_no_trade_zones()` :975 | Нет |
| 25 | Dynamic risk: weak setup | scanner.py | `calculate_risk()` :1013 | **Да** (косвенно) |
| 26 | Dedup cooldown | scanner.py | :1100 | Нет |

**Важно:** confidence_v2 НЕ имеет собственного блокирующего фильтра. Единственное косвенное влияние — через `risk_params.should_trade` (step 25), где `setup_quality` берётся из `result.verdict` (line 1000), а `result.verdict` использует `confidence_v2.quality` (line 73-75 signal_engine.py).

---

## ЭТАП 5. РОЛЬ CONFIDENCE_V2

### Фактический анализ по коду:

**5.1 Только отображение в Telegram — ДА (частично)**

`confidence_v2` участвует в формировании Telegram-сообщения:
- `SignalResult.verdict` (line 70-84 signal_engine.py): если `_confidence_v2` установлен, использует его quality
- `SignalResult.confidence` (line 87-98): если `_confidence_v2` установлен, использует его `confidence_pct`
- `format_message()` (line 176-180): выводит quality label

Доказательство:
```python
# signal_engine.py, line 73
if self._confidence_v2 is not None:
    q = self._confidence_v2.quality
    return {"strong": "СИЛЬНЫЙ", "moderate": "УМЕРЕННЫЙ", "weak": "СЛАБЫЙ"}.get(q, "СЛАБЫЙ")
```

**5.2 Влияет на размер риска — ДА**

scanner.py line 1000:
```python
setup_quality = result.verdict.lower() if result.verdict.lower() in ("strong", "moderate", "weak") else "moderate"
risk_params = calculate_risk(setup_quality=setup_quality, ...)
```

`result.verdict` берёт quality из `confidence_v2.quality` (line 73-75 signal_engine.py).

**5.3 Блокирует сигналы — НЕ ПРЯМО**

confidence_v2 сам по себе НЕ блокирует сигналы. Однако есть косвенный путь:
- `confidence_v2.quality` → `result.verdict` → `setup_quality` → `risk_params.should_trade`
- Если quality=="weak" и `risk_weak_trade=false` → `should_trade=False` → BLOCK

scanner.py line 1013:
```python
if config.risk.dynamic_risk_enabled and not risk_params.should_trade:
    # ... return None (BLOCK)
```

**5.4 Меняет направление сигнала — НЕТ**

confidence_v2 принимает direction как input, не меняет его.

**5.5 Используется только для аналитики — ЧАСТИЧНО**

Да, для `factor_fingerprint` и `historical_winrate` (Task 6.1).

**5.6 Используется в cooldown — НЕТ**

Cooldown использует `config.signal_cooldown_minutes`, не confidence_v2.

**5.7 Используется в outcome tracking — НЕТ**

outcome_tracker проверяет TP/SL, не confidence.

---

## ЭТАП 6. РОЛЬ SIGNAL_ENGINE

### Какие решения принимает signal_engine:

```
signal_engine.evaluate()
│
├─ ВХОД: IndicatorValues + regime + sweeps + order_blocks + structure
│
├─ GATES (каждый может вернуть NO_SIGNAL):
│   ├─ None/NaN guard
│   ├─ Regime gate (compression → breakout check)
│   ├─ ADX flat filter (adx < adx_min → NO_SIGNAL)
│   ├─ Supertrend alignment (st_str < -0.3 → NO_SIGNAL)
│   ├─ Trigger gate (no trigger → NO_SIGNAL)
│   ├─ EMA alignment gate
│   ├─ EMA spread gate
│   ├─ EMA slope gate
│   ├─ Min score gate (score < min_score → NO_SIGNAL)
│   └─ Candle close confirmation gate
│
├─ SCORING:
│   ├─ 7 factor strengths: Supertrend, EMA, MACD, RSI, Volume, ADX, DMI
│   ├─ weighted_score = Σ(strength × weight)
│   ├─ score = count(supporting_reasons)
│   └─ confidence_v2 = ConfidenceResult (DISPLAY ONLY)
│
└─ ВЫХОД: SignalResult(signal=BUY/SELL/NO_SIGNAL, score=0..7, ...)
```

### Thresholds:

| Параметр | Значение по умолчанию | Источник |
|----------|----------------------|----------|
| adx_min | 20 (18 для compression) | config.trading.adx_min |
| min_score_for_signal | 2 | config.scoring.min_score_for_signal |
| trigger_required | true | config.trading.trigger_required |
| ema_alignment_enabled | true | config.trading.ema_alignment_enabled |
| ema_spread_enabled | true | config.trading.ema_spread_enabled |
| candle_close_enabled | true | config.trading.candle_close_enabled |

### Финальный verdict:

```python
# signal_engine.py, line 661
signal_type = SignalType.BUY if direction == "buy" else SignalType.SELL

# Все gates пройдены → BUY или SELL
# Любой gate провален → NO_SIGNAL
```

---

## ЭТАП 7. ПРОВЕРКА КОНФЛИКТОВ

### Case A: signal_engine = BUY, confidence_v2 = weak

```
signal_engine: score=4, direction=buy → BUY (проходит min_score=2)
confidence_v2: quality="weak" → result.verdict = "СЛАБЫЙ"

Что произойдёт:
1. result.signal = BUY ✓
2. result.verdict = "СЛАБЫЙ" (из confidence_v2)
3. setup_quality = "weak" (line 1000 scanner.py)
4. risk_params.should_trade = risk_weak_trade (config param)
   - Если risk_weak_trade=true → TRADE с reduced risk
   - Если risk_weak_trade=false → BLOCK
5. Telegram: "BUY — ПОКУПКА | Итог: СЛАБЫЙ | Уверенность: X%"
```

**Конфликт:** signal_engine считает сигнал проходящим (score=4 ≥ min_score=2), но confidence_v2 оценивает его как "weak". Решение о блокировке зависит от `risk_weak_trade`.

### Case B: signal_engine = BUY, confidence_v2 = strong

```
signal_engine: score=6, direction=buy → BUY
confidence_v2: quality="strong" → result.verdict = "СИЛЬНЫЙ"

Что произойдёт:
1. result.signal = BUY ✓
2. result.verdict = "СИЛЬНЫЙ"
3. setup_quality = "strong"
4. risk_params: base_risk = RISK_STRONG_PCT (1.0%)
5. Telegram: "BUY — ПОКУПКА | Итог: СИЛЬНЫЙ | Уверенность: X%"
```

**Согласованность:** оба источника дают сильный сигнал.

### Case C: signal_engine = SELL, confidence_v2 = ...?

`confidence_v2` не может вернуть направление, отличное от signal_engine. Он принимает `direction=result.signal.value` (line 1025 scanner.py). Поэтому "SELL + STRONG_LONG" невозможно.

### Case D: signal_engine = BUY (score=2), confidence_v2 = weak

```
signal_engine: score=2, direction=buy → BUY (проходит min_score=2 ровно)
confidence_v2: quality="weak" → verdict="СЛАБЫЙ"

Конфликт: слабый по очкам + слабый по confidence → может быть заблокирован через risk
```

### Case E: signal_engine = BUY, context_scorer = BLOCKED

```
signal_engine: BUY
context_scorer: verdict="BLOCKED" (score < -0.1)

Что произойдёт:
1. context_scorer.score() возвращает BLOCKED (line 776 scanner.py)
2. CONTEXT_BLOCK_ON_BLOCKED=true → return None (BLOCK)
3. Сигнал НЕ отправляется
```

**Конфликт:** signal_engine одобрил, но контекст рынка заблокировал.

### Матрица конфликтов:

| signal_engine | confidence_v2 | context_scorer | risk | Итог |
|---------------|---------------|----------------|------|------|
| BUY (score≥2) | strong | CONFIRMED | should_trade=True | **BUY** |
| BUY (score≥2) | moderate | CONFIRMED | should_trade=True | **BUY** |
| BUY (score≥2) | weak | CONFIRMED | risk_weak_trade=True | **BUY** (reduced) |
| BUY (score≥2) | weak | CONFIRMED | risk_weak_trade=False | **BLOCK** (risk) |
| BUY (score≥2) | strong | BLOCKED | — | **BLOCK** (context) |
| BUY (score≥2) | strong | WEAK | — | **BLOCK** (if MIN_VERDICT=WEAK+) |
| BUY (score≥2) | moderate | CONFLICTED | — | **BLOCK** (if MIN_VERDICT>CONFLICTED) |
| NO_SIGNAL | — | — | — | **NO_SIGNAL** |

---

## ЭТАП 8. КАРТА ВЛИЯНИЯ

| Компонент | Генерирует сигнал | Блокирует сигнал | Меняет риск | Только отображение |
|-----------|-------------------|------------------|-------------|-------------------|
| **signal_engine** | **ДА** (BUY/SELL/NO_SIGNAL) | **ДА** (10 gates) | Нет | Нет |
| **confidence_v2** | Нет | **НЕ ПРЯМО** (косвенно через risk) | **ДА** (setup_quality) | **ДА** (verdict label, confidence%) |
| **context_scorer** | Нет | **ДА** (BLOCKED, MIN_VERDICT) | Нет | **ДА** (отображение контекста) |
| **dynamic_risk** | Нет | **ДА** (should_trade) | **ДА** (effective_risk_pct) | Нет |
| **outcome_tracker** | Нет | Нет | Нет | Нет (только аналитика) |
| **notifier** | Нет | Нет | Нет | **ДА** (форматирование) |

---

## ЭТАП 9. ГЛАВНЫЙ ВЕРДИКТ

### 1. Кто реально принимает решение о входе?

**signal_engine.evaluate()** — единственный источник решения BUY/SELL/NO_SIGNAL.

Решение принимается на line 661 signal_engine.py:
```python
signal_type = SignalType.BUY if direction == "buy" else SignalType.SELL
```

Все последующие фильтры в scanner.py могут ТОЛЬКО отменить (return None), но не изменить направление.

### 2. Существует ли double scoring?

**ДА, существует в трёх формах:**

**Форма 1: Два параллельных ConfidenceResult**

- `signal_engine.evaluate()` создаёт `ConfidenceResult` на lines 712-728 с 7 факторами (Supertrend, EMA, MACD, RSI, Volume, ADX, DMI) — **DISPLAY ONLY**
- `confidence_engine_v2.compute()` создаёт `ConfidenceResult` на line 1063 scanner.py с 10 факторами (HTF Trend, Structure, Liquidity, Volume, BTC, Funding, OI, RSI, MACD, ADX) — **DISPLAY + RISK**

Второй `ConfidenceResult` перезаписывает первый (line 1092: `result._confidence_v2 = conf_v2`). Фактически используется только信心_v2.

**Форма 2: Два системы quality labels**

- `SignalEngine.verdict` (line 70-84 signal_engine.py): если `_confidence_v2 is None`, использует `score` thresholds (≥6 strong, ≥4 moderate, ≥2 weak)
- `confidence_v2.quality`: использует `total_score` thresholds из конфига (quality_strong_threshold, quality_moderate_threshold)

Когда `_confidence_v2 is not None` (в production всегда), `SignalEngine.verdict` **полностью заменяется** на `confidence_v2.quality`. Это **скрытое дублирование** — два разных алгоритма для одного label.

**Форма 3: Три разных системы подсчёта "confidence"**

1. `SignalResult.confidence` (line 87-98 signal_engine.py): `abs(total_score)` из信心_v2
2. `ContextVerdict.confidence` (line 169 scorer.py): `abs(final_score)` из context_scorer
3. `SignalResult.score` (line 644 signal_engine.py): `count(supporting_reasons)` — не связан с confidence

### 3. Если да, то где именно конфликт?

**Конфликт 1: Веса factor strengths в signal_engine vs信心_v2**

Signal engine использует:
```
Supertrend: w_supertrend, EMA: w_ema, MACD: w_macd, RSI: w_rsi,
Volume: w_volume, ADX: w_adx, DMI: w_dmi
```

Confidence_v2 использует:
```
HTF Trend: 20, Structure: 15, Liquidity: 20, Volume: 5,
BTC: 15, Funding: 5, OI: 5, RSI: 5, MACD: 5, ADX: 5
```

Это **другие факторы с другими весами**. RSI/MACD/ADX имеют вес 10 в signal_engine, но 5 в信心_v2. Supertrend и EMA (вес 15 каждый в signal_engine) вообще отсутствуют в信心_v2 как отдельные факторы.

**Конфликт 2: Min score vs confidence quality**

- signal_engine: `score ≥ 2` → BUY (line 647)
- confidence_v2: `quality` определяется по `abs(total_score)` с порогами из конфига

Прохождение min_score=2 не гарантирует "moderate" или "strong" в信心_v2. Возможна ситуация: score=2 (BUY), но confidence="weak".

**Конфликт 3: Verdict label vs score label**

Если信心_v2 отсутствует (exception на line 727), verdict использует score:
```python
s = self.score
if s >= 6: return "СИЛЬНЫЙ"
elif s >= 4: return "УМЕРЕННЫЙ"
elif s >= 2: return "СЛАБЫЙ"
```

Но в production信心_v2 почти всегда присутствует, поэтому этот fallback редко срабатывает.

### 4. Есть ли дублирование логики?

**ДА:**

1. **RSI scoring:** `_strength_rsi()` в signal_engine (line 858) и `score_rsi()` в信心_v2 (line 240) — разная логика
2. **MACD scoring:** `_strength_macd()` в signal_engine (line 839) и `score_macd()` в信心_v2 (line 263) — разная нормализация
3. **ADX scoring:** `_strength_adx()` в signal_engine (line 902) и `score_adx()` в信心_v2 (line 282) — разные пороги
4. **Volume scoring:** `_strength_volume()` в signal_engine (line 885) и `score_volume()` в信心_v2 (line 194) — разная логика
5. **Quality labels:** два разных алгоритма (score-based vs total_score-based)

### 5. Есть ли противоречивые пороги?

**ДА:**

1. **ADX filter:** signal_engine блокирует при `adx < 20`.信心_v2 может поставить `score_adx = 0.0` при `adx ∈ [17, 20]` (line 291: "near threshold — neutral, not penalized"). Но signal_engine уже заблокировал до этого.

2. **Min score:** signal_engine требует `score ≥ 2`.信心_v2 не имеет аналогичного порога — он всегда вычисляется для уже прошедшего сигнал.

3. **Quality thresholds:** `quality_strong_threshold` и `quality_moderate_threshold` в конфиге определяют信心_v2 quality. Но `score ≥ 6` (для "СИЛЬНЫЙ" в fallback) — это количество supporting reasons, а信心_v2 использует `abs(total_score)` — взвешенную сумму. Разные метрики.

### 6. Может ли confidence_v2 отменять решение signal_engine?

**НЕПРЯМО — ДА, через dynamic_risk.**

Цепочка:
```
confidence_v2.quality = "weak"
  → result.verdict = "СЛАБЫЙ"
  → setup_quality = "weak"
  → risk_params.should_trade = risk_weak_trade (config)
  → Если risk_weak_trade=false → BLOCK
```

Но если `risk_weak_trade=true` (по умолчанию `false`), то信心_v2 **не может** отменить решение signal_engine.

### 7. Может ли signal_engine игнорировать confidence_v2?

**ДА — полностью.**

signal_engine создаёт自己的ConfidenceResult (lines 712-728) и возвращает SignalResult. Он не знает о信心_v2.compute() в scanner.py.信心_v2 вызывается ПОСЛЕ signal_engine и перезаписывает result._confidence_v2 (line 1092 scanner.py).

---

## ЭТАП 10. ИТОГОВЫЙ ДОКУМЕНТ

### Call Graph

```
┌─────────────────────────────────────────────────────────────┐
│                      scanner.scan_symbol()                  │
│                                                             │
│  ┌──────────────┐    ┌──────────────────────┐               │
│  │ cooldown     │───▶│ indicators           │               │
│  │ check        │    │ engine.calculate()   │               │
│  └──────────────┘    └──────────┬───────────┘               │
│                                 │                           │
│                    ┌────────────▼────────────┐               │
│                    │ signal_engine.evaluate()│               │
│                    │                         │               │
│                    │  10 gates:              │               │
│                    │  ├─ data_valid          │               │
│                    │  ├─ regime              │               │
│                    │  ├─ adx                 │               │
│                    │  ├─ supertrend          │               │
│                    │  ├─ trigger             │               │
│                    │  ├─ ema_alignment       │               │
│                    │  ├─ ema_spread          │               │
│                    │  ├─ ema_slope           │               │
│                    │  ├─ min_score           │               │
│                    │  └─ candle_close        │               │
│                    │                         │               │
│                    │  RETURN: BUY/SELL/NO    │               │
│                    └────────────┬────────────┘               │
│                                 │                           │
│                    ┌────────────▼────────────┐               │
│                    │ Post-evaluate filters:  │               │
│                    │  ├─ distance_filter     │               │
│                    │  ├─ tp_path             │               │
│                    │  ├─ mtf_alignment       │               │
│                    │  ├─ btc_correlation     │               │
│                    │  ├─ eth_correlation     │               │
│                    │  ├─ volatility          │               │
│                    │  ├─ context_scorer      │               │
│                    │  ├─ news_filter         │               │
│                    │  ├─ sl_distance         │               │
│                    │  ├─ rr_guard            │               │
│                    │  ├─ no_trade_zones      │               │
│                    │  └─ dynamic_risk        │               │
│                    └────────────┬────────────┘               │
│                                 │                           │
│                    ┌────────────▼────────────┐               │
│                    │ confidence_v2.compute() │               │
│                    │  (DISPLAY + RISK ONLY)  │               │
│                    │  → result._confidence_v2│               │
│                    └────────────┬────────────┘               │
│                                 │                           │
│                    ┌────────────▼────────────┐               │
│                    │ save + notify_callback  │               │
│                    │ → send_signal()         │               │
│                    │ → Telegram              │               │
│                    └─────────────────────────┘               │
└─────────────────────────────────────────────────────────────┘
```

### Decision Tree

```
                    signal_engine.evaluate()
                           │
              ┌────────────┴────────────┐
              │    Any gate fails?      │
              └────────────┬────────────┘
                    YES    │    NO
                    ▼      │      ▼
              NO_SIGNAL    │    BUY or SELL
                           │      │
              ┌────────────▼──────▼────────────┐
              │    Post-evaluate filters       │
              │    (scanner.py: 408-997)       │
              └────────────┬───────────────────┘
                    BLOCK? │    PASS
                    ▼      │      ▼
              return None  │    confidence_v2.compute()
                           │      │
                           │      ▼
                           │    risk_params.calculate()
                           │      │
                           │    ┌─┴─┐
                           │    │   │
                           │  weak  │
                           │  and   │
                           │  !trade│
                           │    ▼   │
                           │  BLOCK │
                           │        ▼
                           │    SAVE + SEND
                           ▼
                    (signal lost)
```

### Conflict Matrix

| Компонент A | Компонент B | Конфликт | Влияние |
|-------------|-------------|----------|---------|
| signal_engine.score (0-7) | confidence_v2.total_score (-100..100) | Разные метрики одного concept | Display: verdict label может не совпадать с score |
| signal_engine._confidence_v2 (7 factors) | confidence_v2.compute() (10 factors) | Второй перезаписывает первый | Production: первый никогда не используется |
| signal_engine.verdict (score-based fallback) | confidence_v2.quality (total_score-based) | Два алгоритма quality |verdict всегда =信心_v2.quality в production |
| signal_engine min_score (≥2) | confidence_v2 quality thresholds | Независимые пороги | Сигнал может пройти min_score но быть "weak" |
| context_scorer.verdict | confidence_v2.quality | Независимые системы | Контекст может заблокировать то, что信心_v2 одобрил |

### Source of Truth

**signal_engine.evaluate()** (strategy/signal_engine.py:185-742) является окончательным источником решения BUY/SELL/NO_SIGNAL. Он принимает единственное направленческое решение (line 661) и имеет 10 блокирующих gate. Все остальные компоненты (confidence_v2, context_scorer, dynamic_risk) работают ПОСЛЕ этого решения и могут только отменить (return None), но не изменить направление.

---

# SOURCE OF TRUTH

**"Какая система является окончательным источником решения BUY/SELL в текущем коде."**

**signal_engine.evaluate()** — единственная система, генерирующая BUY/SELL. Все остальные — фильтры (блокируют) или мета-данные (отображают/рассчитывают риск). Double scoring существует в formе дублирования quality labels и factor scoring, но НЕ в конфликте направлений, поскольку信心_v2 не может изменить direction.
