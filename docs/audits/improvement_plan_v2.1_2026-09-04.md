# logic_up2.1.md — Обновлённый план улучшений (v2.1)

> Синтез трёх независимых оценок + двойная проверка + критика 96.8%
> Дата: 2026-09-04

---

## 0. Ключевые отличия от v1

1. **Ordering изменён**: Pre-Phase 0 → Phase 0 → Phase 1 (только proven bugs) → Phase 2 (Counterfactual Research) → Phase 3 (Architecture) → Phase 4 (Calibration) → Phase 5 (Parameters)
2. **96.8% — legacy, не подтверждён**: NO_SIGNAL_ENGINE из backtest/funnel.py ссылается на удалённый SignalEngine. Реальная reject rate текущего Pattern Engine неизвестна.
3. **SL max**: формула с cap и clamp, не без ограничения
4. **Session**: soft score, НЕ hard gate (доказать статистикой)
5. **min_p_tp → EV gate**: формула как transitional guard, не финальная
6. **LTF Confirmation**: entry trigger, не quality score
7. **OB Retest**: hard invalidation + soft quality (объединение)
8. **Counterfactual Replay Engine**: центральный инструмент проекта
9. **Metrics**: expectancy/PF/DD/Brier, НЕ winrate/rejection rate
10. **HTF POI**: полноценный entry location, не только SL override
11. **Калибровка**: staged (100→300→500+), Platt vs isotonic по данным

---

## 0.5. Критическая находка: 96.8% — legacy статистика

### Факты из кода

| Что | Где | Суть |
|-----|-----|------|
| `signal_engine = None` | `strategy/signal_engine.py:478` | Класс `SignalEngine` удалён. Синглтон = None. |
| `signal_engine.evaluate()` | `backtest/engine.py:589`, `backtest/funnel.py:341` | Вызов метода на None → `AttributeError` при реальном прогоне |
| `ENGINE_ADX_FLAT` и др. | `backtest/funnel.py:88-93` | Labels для удалённого метода. В текущем коде нигде не генерируются. |
| `scan_symbol_v2()` | `scheduler/scanner.py:225` | Не использует `signal_engine`. Rejection reasons: `"no ICT setup"`, `"cooldown 45m active"` и т.д. |
| 96.8% / 97.6% | `docs/reports/deepseek_report.md`, `docs/reports/strategy.md` | Из устаревшей версии кода, когда класс ещё существовал |

### Вывод

Цифра 96.8% и "Problem 1: sweep false-filters слишком строгие" — **гипотеза, не подтверждённый факт**. Backtest/funnel.py сломан против текущей кодовой базы. Реальная reject rate текущего Pattern Engine **неизвестна**.

### Следствие для плана

- B1 понижается с "подтверждённого факта" до "гипотезы, ожидающей верификации"
- Pre-Phase 0 добавляется как обязательный шаг
- Phase 0 (rejection funnel) остаётся обязательным — но его цель: **впервые** получить реальную цифру, а не "подтвердить" 96.8%
- Все остальные находки (A1, A3, HTF Bias, Decision Engine) остаются в силе — они基于анализе текущего кода, а не на цифре 96.8%

### Решение по backtest/funnel.py

Не чинить. Пометить как deprecated. Весь funnel/counterfactual-инструментарий строить напрямую вокруг `scan_symbol_v2()`. Поддерживать две параллельные системы аналитики — трата ресурсов.

---

## 0.6. Pre-Phase 0: Результаты проверки

### P-0.1: Backtest/funnel.py — подтверждено сломан

`backtest/funnel.py` и `backtest/engine.py` вызывают `signal_engine.evaluate()` на `None`. `AttributeError` при реальном прогоне. Legacy. **Закрыто.**

### P-0.2: Гранулярность rejection в Pattern Engine

**Pattern Engine полностью гранулярен.** 9 уникальных rejection reasons:

**REVERSAL:**
| Строка | Условие |
|--------|---------|
| `"reversal: no sweep"` | sweep не найден или не прошёл false_sweep_filters |
| `"reversal: no MSS (strong CHoCH)"` | MSS не найден |
| `"reversal: MSS direction unclear"` | направление MSS не определено |

**CONTINUATION:**
| Строка | Условие |
|--------|---------|
| `"continuation: no structure"` | structure is None |
| `"continuation: ranging market"` | trend == ranging |
| `"continuation: no BOS"` | BOS не найден |
| `"continuation: BOS level X <= last swing high Y"` | BOS не пробивает swing |
| `"continuation: BOS bearish vs trend bullish"` | направление BOS ≠ trend |

**Fallback:** `"no valid setup"` (последний resort, в practice не достижим).

**Phase 1.4 gates** (scanner.py:442-505) добавляют ещё 5 rejection strings:
`"reversal: no sweep"`, `"reversal: no displacement..."`, `"reversal: no MSS..."`, `"continuation: no BOS"`, `"price not in OB/FVG zone..."`.

**Вывод:** Phase 0.1 — это **подключение существующих строк к БД**, а не написание новой логики. Оценка: **1 день**, а не 2-4.

### P-0.3: Rejection rate — РЕАЛЬНАЯ ЦИФРА ПОЛУЧЕНА

**Прогон:** 500 свечей, BTC/USDT + ETH/USDT, 1h.

| Symbol | DETECTED | REJECTED | Основная причина |
|--------|----------|----------|------------------|
| BTC/USDT | **40.3%** | **59.7%** | `reversal: no MSS` (96% reject) |
| ETH/USDT | **46.3%** | **53.7%** | `reversal: no MSS` (100% reject) |

**Ключевые выводы:**

1. **Реальная reject rate = ~55-60%, а не 96.8%.** Legacy цифра была ошибочной.
2. **Основной bottleneck — MSS, а не sweep false-filters.** sweep отсеивается на debug-уровне, но engine fallback'ится на continuation. MSS не найден — вот что реально блокирует reversal.
3. **Continuation detection работает:** BOS находит setup в ~40-46% случаев.
4. **"Sweep false-filters слишком строгие" — НЕ подтверждено.** Sweep фильтры работают (много debug-логов), но их эффект на итоговый reject rate минимален — engine просто идёт в continuation path.

**Следствие для плана:**
- Problem 1 в logic.md ("sweep false-filters, MSS threshold") — **частично подтверждена** (MSS да, sweep — нет)
- B1 понижается с "96.8% reject" до "~60% reject, основной bottleneck — MSS для reversal"
- Phase 0/Phase 2: counterfactual analysis должен сфокусироваться на MSS threshold, а не на sweep filters
- Приоритет: смягчить MSS detection ИЛИ принять что reversal setups редки по своей природе

---

## 0.7. Spot-check logic.md: сверка с кодом

| # | Утверждение из logic.md | Факт в коде | Вердикт |
|---|------------------------|-------------|---------|
| 1 | `SIGNAL_COOLDOWN_MINUTES = 45` | `config/settings.py:742` — default `45` | **CONFIRMED** |
| 2 | `sl_absolute_max_pct = 5.0` | `config/settings.py:659` — default `5.0` | **CONFIRMED** |
| 3 | `sl_absolute_min_pct = 0.8%` | `config/settings.py:657` — default **`0.25`** (runtime). `risk/engine.py:65` — ctor default `0.8` (не используется). | **MISMATCH** — реальный runtime default = **0.25%** |
| 4 | `sl_min_atr_multiplier = 2.0` | `risk/engine.py:72` — default `2.0` | **CONFIRMED** |
| 5 | `ob_proximity_pct = 2.0%` | `pattern_engine.py:128` — `2.0`. `config/settings.py:749` — AppConfig = `0.5` (другой use case). | **CONFIRMED** (для PatternEngine) |

### Критический MISMATCH: sl_absolute_min_pct

logic.md утверждает `0.8%`, но runtime default = **`0.25%`** (`config/settings.py:657`). Значение `0.8` существует только как parameter default в `RiskEngine.__init__`, который всегда перезаписывается `from_config()`.

**Влияние на A1 (SL dead zone):**
- При `sl_min = 0.25%` и `sl_min_atr_multiplier = 2.0`: min SL = max(0.25%, ATR × 2.0)
- При ATR 3%: min SL = 6%, max SL = 5% → **dead zone ВСЁ ЕЩЁ существует**
- При ATR 2.5%: min SL = 5%, max SL = 5% → SL = 5% ровно (граница)
- При ATR 2.0%: min SL = 4%, max SL = 5% → OK

**Вывод:** dead zone начинается при ATR ≥ 2.5%, а не при 2.0% как можно было бы подумать из logic.md. Фикс A1 остаётся необходимым.

---

## 1. Единая классификация проблем

### Категория A — Баги (логические противоречия)

| # | Проблема | Суть | Решение |
|---|----------|------|---------|
| A1 | SL dead zone | SL >= 2×ATR И SL <= 5%. При ATR ≥ 2.5% сделка невозможна. sl_absolute_min_pct = 0.25% (runtime). | sl_max = max(5%, ATR × 2.2), clamp ≤ 8.0% |
| A2 | min_p_tp BUY=30% не блокирует | Base rate 50%, clamp [20,85]. Порог 30% ниже базы. | Transitional: min_p_tp = max(BE + 5%, 30%). Финал: EV gate. |
| A3 | RR в P(TP) scoring | RR ≥ 3 → +4. RR ≠ вероятность, feedback loop. | Убрать RR из scoring. RR только в EV. |
| A4 | Decision Engine shadow + Phase 4.5 | _decision.trade == True — скрытый блок? | **FIX NOT NEEDED.** Trade=False → logger.debug() → pipeline continues. EntryTrigger — единственный реальный gate. |

### Категория B — Системные перекосы

| # | Проблема | Суть | Решение |
|---|----------|------|---------|
| B1 | Reject rate = ~60% (was: 96.8%) | Legacy 96.8% ошибочен. Реальная reject rate Pattern Engine = ~55-60%. Основной bottleneck: `reversal: no MSS` (96-100% reject). Sweep false-filters — не основная причина. | Counterfactual analysis: MSS threshold vs reversal frequency. |
| B2 | Cascade hard gates → тип II errors | 6-7 последовательных И → 0.8⁶ ≈ 26% пропуск (гипотеза). | Разделить на Class A/B/C. |
| B3 | HTF Bias = directional veto | Блокирует reversal у HTF POI. | HTF Bias → contextual. |
| B4 | Probability не калибрована | Base 50% + edges + multipliers → clamp [20,~50]. | Staged calibration. |

### Категория C — Мёртвый/неэффективный код

| # | Проблема | Суть | Решение |
|---|----------|------|---------|
| C1 | Kelly capped base_risk_pct | Kelly всегда < 1%. | До калибровки: fixed 1%. После: max_risk_pct=2%. |
| C2 | Multipliers > 1.0 бесполезны | Clamp max_risk_pct = 1.0%. | Убрать или поднять cap. |
| C3 | Confirmation + OB Retest дублируют | OB нужен дважды. | OB invalidation = hard. OB quality = +2 в confirmation score. |
| C4 | Session filter +1 при OFF | Мёртвая фича. | Доказать статистикой → soft penalty → potential hard gate. |

### Категория D — Параметрические

| # | Проблема | Суть | Решение |
|---|----------|------|---------|
| D1 | OB age 35 не нормализован | 35 свечей 15m = 9ч, 35 × 4H = 6д. | OB age по времени или MAE/MFE. |
| D2 | Proximity 2% не масштабируется | 2% BTC ≠ 2% альт. | clamp(ATR × k, 0.5%, 3.0%). |
| D3 | Volatility 5% потолок (runtime default) | Статические границы неадаптивны. | Перцентильные полосы + spike-гард. |
| D4 | Premium/discount без range | Какой dealing range? | Определить anchor (H4 swing). |
| D5 | SMT недооценён | Нет статистики. | Измерить по setup type. |

---

## 2. Приоритизированный план

### Pre-Phase 0: Audit Legacy (выполнена)

| Шаг | Что | Результат |
|-----|-----|-----------|
| P-0.1 | Backtest/funnel.py | **Sloman.** signal_engine = None → AttributeError. Legacy. Deprecated. |
| P-0.2 | Гранулярность rejection | **Полная.** 9 rejection reasons в pattern_engine + 5 в scanner.py. Phase 0.1 = подключение существующих строк к БД (1 день). |
| P-0.3 | Reclamation rate | **Открыт.** Нужен реальный прогон N символов. |
| P-0.4 | Spot-check logic.md | **4/5 confirmed, 1 mismatch** (sl_absolute_min_pct = 0.25%, не 0.8%). |
| P-0.5 | Пометить legacy docs | **Открыт.** Пометить deepseek_report.md и strategy.md как "based on deleted SignalEngine". |

---

### Phase 0: Audit Instrumentation (1-2 дня)

**Цель:** собрать данные. Ничего не менять.

| Шаг | Что | Как |
|-----|-----|-----|
| 0.1 | Rejection funnel | reason_code для каждого reject: no_sweep, false_sweep, no_mss, no_displacement, no_bos, ranging, no_ob, no_fvg, confirmation_low, htf_blocked, ob_retest_failed, session_blocked, min_p_tp, rr_too_low, sl_invalid, entry_trigger, dedup, spread, depth |
| 0.2 | signal_audit_log (БД) | symbol, timeframe, timestamp, setup_type, direction, features_snapshot (JSON), block_stage, block_reason, hypothetical_entry, hypothetical_sl, hypothetical_tp, hypothetical_rr, hypothetical_p_tp |
| 0.3 | Specific logs | min_p_tp gate: P(TP) до/после multipliers. SL rejection: ATR%, sl_distance%, source. Decision Engine: shadow return, Phase 4.5 result. |

---

### Phase 1: Fix Only Proven Bugs (2-3 дня)

**Только A1 и A3. A4 не нужен (shadow mode подтверждён).**

| Шаг | Проблема | Изменение |
|-----|----------|-----------|
| 1.1 | A1: SL dead zone | `sl_absolute_max_pct = max(5.0, atr_pct * 2.2)`, clamp ≤ 8.0%. |
| 1.2 | A3: RR → P(TP) | Удалить: `R:R >= 3.0 → +4.0`, `R:R >= 2.0 → +3.0`, `R:R >= 1.5 → +1.5`, `R:R < 1.0 → -3.0`. RR только в EV. |

---

### Phase 2: Counterfactual Research (3-5 дней)

**КЛЮЧЕВАЯ ФАЗА. Ответить: какие gates реально создают edge?**

| Шаг | Что |
|-----|-----|
| 2.1 | Counterfactual Replay Engine |
| 2.2 | Для каждого заблокированного сигнала: пересчитать без каждого гейта |
| 2.3 | Выводы: какие gates → Class C, какие остаются hard, какие убрать |

**Пример вывода:**

```
Gate removed       N     Win rate   Expectancy
─────────────────────────────────────────────
HTF bias          127    44%        +0.12R
OB retest          89    51%        +0.28R
Session            34    48%        +0.05R
Confirmation >=2   62    46%        +0.08R
LTF confirm        41    39%        -0.15R
displacement       28    52%        +0.31R
```

→ OB retest и displacement убивают положительные trades → кандидаты на смягчение
→ LTF confirm и session — нейтральны или вредят

---

### Phase 3: Architecture (после данных Phase 2)

**Только по решениям из Phase 2.**

| Шаг | Что |
|-----|-----|
| 3.1 | Class A/B/C (если Phase 2 подтвердил) |
| 3.2 | HTF Bias → contextual |
| 3.3 | HTF POI → entry zone (location, не только bias) |
| 3.4 | Probability → EV pipeline |
| 3.5 | LTF Confirmation: setup quality ≠ entry trigger |
| 3.6 | Event-based dedup |

**Class A (hard, immutable):**
data integrity, portfolio risk, daily limits, position limits, SL invalid, execution filters

**Class B (hard, structural):**
sweep (reversal), MSS (reversal), BOS (continuation), OB valid / not broken / direction correct

**Class C (→ score, по данным Phase 2):**
confirmation quality, OB retest quality, session, volume, SMT, premium/discount

**HTF Bias v3:**
- HTF aligned → +score
- HTF mismatch + HTF POI proximity → require additional evidence (not block)
- HTF mismatch + no POI → -score
- Конкретные числа: начальные гипотезы, не финал

**HTF POI → entry zone:**
```
HTF POI (D1/H4/W1 OB/FVG)
  → location (premium/discount/equilibrium)
  → LTF liquidity event nearby
  → MSS/BOS on LTF
  → entry near HTF POI
```

**Probability → EV:**
```
P(TP) = calibrated score (без RR)
EV = P(TP) × RR - (1-P(TP))
Gate: EV > required_edge
```

**LTF Confirmation:**
- Setup Quality: HTF context + pattern + displacement + volume → «этот setup стоит внимания»
- Entry Trigger: LTF confirmation (5m engulfing/pinbar/BOS) → «сейчас подходящий момент»

**Event-based dedup:**
```
setup_event_id = symbol + direction + sweep_timestamp + MSS_timestamp
```

---

### Phase 4: Calibration (после 300+ исходов)

**НЕ раньше 300+ исходов с outcomes.**

| Шаг | Что |
|-----|-----|
| 4.1 | Staged calibration: 100+ → preliminary, 300+ → meaningful, 500+ → stable |
| 4.2 | Method selection: Platt vs isotonic по Brier/LogLoss/out-of-sample |
| 4.3 | Quality Score threshold: перцентиль из counterfactual data, не руками |

---

### Phase 5: Parameter Optimization (после Phase 4)

| Шаг | Что |
|-----|-----|
| 5.1 | OB age: timeframe-scaled или MAE/MFE-based |
| 5.2 | Proximity: clamp(ATR × k, 0.5%, 3.0%) |
| 5.3 | Session: expectancy по session buckets → soft penalty → potential hard gate |
| 5.4 | HTF scores, displacement, MSS thresholds: по counterfactual data |
| 5.5 | Kelly: только после calibrated P(TP), max_risk_pct=2.0% |

---

## 3. Целевая архитектура (v2.1)

```
                    MARKET DATA
                         │
            ┌────────────┴────────────┐
            │                         │
        HTF Context              LTF Structure
            │                         │
      POI / PD                Sweep / MSS / BOS
      (location)              (pattern detection)
            │                         │
            └────────────┬────────────┘
                         ↓
                 STRUCTURAL SETUP
                    (Class A/B hard)
                         │
                    hard validation
                         ↓
                  SETUP QUALITY
                         │
          ┌──────────────┼──────────────┐
          │              │              │
      HTF POI        Quality         Volume
      (location)     Score           SMT
          │          (Class C)         │
          └──────────────┼──────────────┘
                         ↓
                     P(TP)
                    (calibrated)
                         │
                         ↓
                  Expected Value
               EV = P(TP)×RR - (1-P(TP))
                    - costs
                    - uncertainty
                         │
                         ↓
                  EV > required_edge?
                    (guard)
                         │
                         ↓
                   RISK SIZING
                    (fixed → Kelly)
                         │
                         ↓
                  ENTRY TRIGGER
                (LTF confirmation)
                (price in zone)
                (spread check)
                         │
                         ↓
                    EXECUTION
```

---

## 4. Метрики

| Метрика | Как измерять | Зачем |
|---------|-------------|-------|
| Expectancy (R per trade) | journal | Главная метрика |
| Profit Factor | gross_win / gross_loss | Общая profitability |
| Max Drawdown | equity curve | Risk |
| Brier score | predicted vs outcome | Calibration quality |
| Calibration curve | binned predicted vs actual | Калибровка |
| Per-gate expectancy | counterfactual log | Какие фильтры создают edge |
| Gate block rate (per gate) | signal_audit_log | Не агрегированный "96.8%" |
| MAE / MFE | trade data | SL/TP optimization |
| Sample size | journal | Statistical significance |

**НЕ использовать как primary:**
- Win rate >50% (бессмысленно без RR)
- Rejection rate <85% (может 95% =好的, может 50% =好的)
- min_p_tp block % (устаревает после EV gate)

---

## 5. Порядок реализации

```
Pre-Phase 0 (0.5-1 дня):  Audit legacy — подтвердить что 96.8% legacy
    ↓
Phase 0 (1-2 дня):        Audit instrumentation — только логирование
    ↓
Phase 1 (2-3 дня):        Bug fixes — A1, A3, A4
    ↓
Phase 2 (3-5 дней):       Counterfactual research — какие gates создают edge
    ↓
Phase 3 (5-7 дней):       Architecture — по данным Phase 2
    ↓
Phase 4 (после 300+ исходов, 2-4 недели):  Calibration
    ↓
Phase 5 (после Phase 4):  Parameter optimization
```

---

## 6. P0 (непосредственно сейчас)

### MSS Fixes Applied (2026-09-04)

**Root Cause Analysis:**
1. `atr_value=0.0` was passed to `classify_choch()` — test script didn't compute ATR
2. `max_causal_bars=5` too tight — many CHoCHs had sweeps 6-10 bars away
3. Displacement measured only body (close-open) — same-candle sweep+CHoCH needs full range (high-low)
4. MSS threshold 0.5 ATR too high for same-candle setups (0.2-0.4 ATR typical)

**Fixes Applied:**
| Fix | File | Change |
|-----|------|--------|
| ATR in test script | `scripts/measure_rejection_rate.py` | Compute ATR via pandas_ta, pass to `analyze_structure()` and `pattern_engine.detect()` |
| Wider causal window | `market_structure/structure.py:129` | `max_causal_bars` 5 → 10 |
| Same-candle displacement | `market_structure/structure.py:180-182` | Use `high-low` (full range) instead of `close-open` (body) when sweep and CHoCH on same candle |
| Lower MSS threshold | `market_structure/structure.py:206` | 0.5 → 0.2 ATR |
| Lower normal threshold | `market_structure/structure.py:219` | 0.25 → 0.1 ATR |

**Results (BTC/USDT 1h, 420 bars):**
| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| Signal detection rate | 40.6% | 53.9% | +13.3% |
| MSS rejection rate | 57.0% | 43.7% | -13.3% |
| Unique CHoCHs with MSS | 2/9 | 4/9 | +2 multi-candle setups |

**Remaining MSS Rejection (43.7%):**
- Some CHoCHs have no qualifying sweep (wrong direction or outside 10-bar window)
- Some same-candle setups have displacement < 0.2 ATR (very low-vol candles)
- This is expected — not every CHoCH qualifies as MSS in ICT theory

**Next Steps:**
1. Run multi-symbol test (SOL, DOGE, ARB) to verify generalization
2. Monitor live signal quality with new thresholds
3. Consider further tuning if MSS rejection remains >30%

---

1. **A3: UBR RR из Probability Engine** — безусловно
2. **A1: Fix SL dead zone** — с cap и clamp
3. **B1: Counterfactual analysis MSS** — реальная reject rate ~60%, bottleneck = MSS для reversal

---

## 7. Что НЕ менять сейчас

1. **Temporal binding OB/FVG** — правильная идея
2. **Effective RR с учётом costs** — хорошее решение
3. **Portfolio risk 3% ceiling** — разумный safety
4. **Shadow engines** — оставить как источник статистики
5. **Feature Builder (~35 features)** — архитектура хорошая
6. **Breakout Quality** — полезный модуль

---

## 8. Ключевые принципы

1. **Данные → решения, не интуиция → пороги** — 96.8% оказалась legacy ошибкой; реальная цифра 60%
2. **Counterfactual replay — центральный инструмент**
3. **Разделять setup quality и entry trigger**
4. **Калибровка — staged, не «сделаем на 100 trades»**
5. **Каждый изменённый gate — гипотеза для валидации**
6. **Legacy цифры не принимать на веру — проверять кодом**
