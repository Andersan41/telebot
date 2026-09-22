# logic_bot_1.2.md — Аудит стратегии v2.5.0

> **Дата:** 2026-09-08
> **Источники:** `logic_bot_v1.0.md`, `logic_bot_1.1.md`, 4 независимых анализа (Claude, Gemini, GPT, Kimi) + полная верификация в реальном коде
> **Фокус:** ТОЛЬКО торговая логика — паттерны, вероятности, размер позиции, входы, выходы
> **Статус:** все находки `[VERIFIED]` с указанием файл:строка

---

## СОДЕРЖАНИЕ

1. [Резюме](#1-резюме)
2. [Критические находки (P0)](#2-p0--критические)
3. [Существенные находки (P1)](#3-p1--существенные)
4. [Сомнительные параметры (P2)](#4-p2--сомнительные)
5. [Точечные улучшения (P3)](#5-p3--точечные)
6. [Что не трогать](#6-что-не-трогать)
7. [План доработки стратегии](#7-план-доработки)
8. [Правила изменений](#8-правила-изменений)

---

## 1. Резюме

### Матрица стратегических модулей

| Модуль | Оценка | Главная проблема |
|--------|--------|------------------|
| Pattern Engine (ICT Setup) | 7/10 | Концептуально чистый (sweep→MSS / trend→BOS), но confirmation score не учитывает reversal-ядро |
| Confirmation Score | 3/10 | Reversal без OB/FVG = score 0 → блок; continuation с BOS = score 2 → всегда проходит. Гейт не гейтит |
| Probability Engine | 4/10 | Аддитивный скор 50+бонусы ≠ вероятность; начисления за обязательные компоненты → min_p_tp вакуумный |
| Risk Engine | 6/10 | Kelly caps at 1% (бессмысленно); overlays 0.42x–1.38x без доказательств; fees занижены |
| Trade Engine (SL/TP) | 7/10 | Liquidity-first хорошо; SL buffer 0.35 ATR может быть тесным; HTF POI override слабо проверяется |
| Position Management | 8/10 | ExitPlan, partial close, trailing, breakeven — зрелая система |
| Cooldown/Dedup | 5/10 | OB-aware без OB = fallback на strict (молча); 4h скан 4 раза в час |
| Entry Trigger | 6/10 | entry_armed (location) ≠ entry_trigger (timing) — разделение правильное, но proximity 2% не нормализован |

**Главный вывод:** стратегия построена правильно на ICT-структуре (sweep→MSS→OB/FVG), но в трёх местах логика «есть гейт, который не гейтит» или «два гейта противоречат друг другу» — это искажает воронку и обучающую выборку для ML.

---

## 2. P0 — Критические

### S1 [CRITICAL] — Confirmation Score ломает reversal и не фильтрует continuation

**Файл:** `strategy/pattern_engine.py:103-113` `[VERIFIED]`

**Код:**
```python
@property
def confirmation_score(self) -> int:
    score = 0
    if self.has_bos:    score += 2   # BOS = +2
    if self.has_fvg:    score += 1   # FVG = +1
    if self.has_ob:     score += 1   # OB  = +1
    return score
```

**Две проблемы:**

**A) Reversal结构性 deficit:**
Reversal по определению НЕ имеет BOS (BOS = компонент continuation). MSS/Sweep/Displacement в confirmation score НЕ начисляются. Результат:
- Reversal sweep+MSS+displacement без OB и FVG → score = 0 → **BLOCKED** (`CONFIRMATION_LOW`)
- Reversal с OB, но без FVG → score = 1 → **BLOCKED**
- Reversal с FVG, но без OB → score = 1 → **BLOCKED**
- Reversal с OB + FVG → score = 2 → **проходит** (едва, на минимуме)

При этом Probability Engine начисляет MSS +4.0, sweep +3.0, displacement +3.0 —总价 +10 за reversal-ядро. Confirmation Score игнорирует все эти +10. **Противоречие внутри одной системы.**

**B) Continuation结构性 pass-through:**
BOS обязателен для continuation (гейт `CONTINUATION_NO_BOS`). BOS = +2 очка. Min = 2. Therefore: **любой continuation автоматически получает score ≥ 2** и проходит confirmation gate. Гейт бессмыслен для continuation — заглушка.

**Что сделать:**

Вариант А (рекомендуемый): начислять за reversal-ядро + разделить пороги:
```python
@property
def confirmation_score(self) -> int:
    score = 0
    if self.has_bos:    score += 2
    if self.has_fvg:    score += 1
    if self.has_ob:     score += 1
    if self.has_mss:    score += 2   # MSS — ядро reversal
    if self.has_sweep:  score += 1   # sweep — триггер reversal
    return score

def passes_confirmation(self, setup_type: str) -> bool:
    if setup_type == "continuation":
        return self.confirmation_score >= 3  # BOS + минимум 1 компонент
    else:  # reversal
        return self.confirmation_score >= 2  # MSS/Sweep дают базу
```

**Критерий приёмки:**
- Reversal sweep+MSS+displacement без OB/FVG → проходит (score=3: MSS(2)+sweep(1))
- Continuation BOS-only → блок (score=2 < 3)
- Continuation BOS+FVG → проход (score=3)
- Continuation BOS+OB → проход (score=3)

---

### S2 [CRITICAL] — Probability Engine: начисления за обязательные компоненты делают min_p_tp вакуумным

**Файл:** `strategy/probability_engine.py:219-340` `[VERIFIED]`

**Проблема:** Базовый winrate = 50%. Reversal-сигнал, прошедший все гейты (sweep + displacement + MSS), получает:
- sweep: +3.0
- displacement: +3.0
- MSS: +4.0
- MSS quality >70: +2.0
**Суммарно: +12.0** → winrate ≥ 62%

Плюс OB(+1.5) + FVG(+1.0) + entry_armed(+1.5) + volume/MTF/session → winrate 70-77%.

Пороги `min_p_tp`: buy=0.30, sell=0.40, **reversal=0.50**. Любой reversal с MSS/ob и минимальным сопровождением получает ≥62% → порог 0.50 **никогда не срабатывает**.

**Это означает:** min_p_tp — мёртвый гейт. Реально ограничивает только EV gate (который учитывает RR), но min_p_tp как ранний фильтр не работает.

**Что сделать:**

1. Убрать бонусы за обязательные компоненты (sweep/displacement/MSS для reversal, BOS для continuation) из rules-based scoring — они уже гарантированы гейтами
2. Оставить бонусы за необязательные улучшатели: volume, MTF, session, ATR regime, context
3. Переименовать `p_tp` → `setup_score` в rules-режиме (не смешивать с калиброванной вероятностью)
4. Пороги `min_p_tp` пересмотреть после калибровки

**До этого:** не менять пороги min_p_tp — они и так не срабатывают, их изменение бесполезно без пересмотра scoring.

---

### S3 [CRITICAL] — Kelly не увеличивает риск: `min(kelly*100, base_risk_pct)`

**Файл:** `risk/engine.py:244-264` `[VERIFIED]`

**Код:**
```python
kelly = (p * b - q) / b
if kelly <= 0: return RiskDecision(should_trade=False, ...)
kelly = min(kelly, 0.20)          # cap at 20%
kelly *= probability.confidence   # ×0.4-1.0
risk_pct = min(kelly * 100, self.base_risk_pct)  # base_risk_pct = 1.0%
```

**Математика:** при p=0.6, b=2.0 → Kelly=0.4 → min(40, 1.0) = 1.0%. Kelly **всегда** упирается в `base_risk_pct` (1.0%) и никогда не может превысить его. Режим `risk_mode=kelly` фактически работает как `fixed_with_penalty` — только снижает размер для слабых сетапов.

**Это может быть осознанным** (консервативный risk ceiling), но:
- Название `kelly` вводит в заблуждение
- Если задумывался как усилитель сильных сетапов — баг
- Kelly от некалиброванного p (из S2) — опасен

**Что сделать (выбрать одно):**
- **A (честный Kelly):** `risk_pct = min(0.5 * kelly * 100, max_risk_pct)` — half-Kelly с потолком 2.0%
- **B (оставить как есть):** переименовать в `fixed_with_penalty`, убрать из документации слово Kelly

**Предусловие:** Kelly-режим включать ТОЛЬКО после калибровки P(TP) (решение S2).

---

## 3. P1 — Существенные

### S4 [HIGH] — Overlays влияют на sizing без доказательной базы

**Файл:** `risk/engine.py:269-305` `[VERIFIED]`

**Код:**
```python
scenario_adj = 0.6 + (scenario_score / 100.0) * 0.6    # [0.6, 1.2]
stability_adj = 0.7 + scenario_stability * 0.45         # [0.7, 1.15]
```

**Суммарный диапазон:** 0.42x–1.38x к риску. Это **больше, чем эффект многих гейтов**. При этом overlays (MarketThesis, Scenario) — самые сложные и наименее проверяемые компоненты без подтверждённой предиктивной силы.

**Что сделать:**
1. Добавить флаг `OVERLAYS_AFFECT_SIZING` (default `false`)
2. При `false` — overlays пишутся в trace/analytics, но `scenario_adj = stability_adj = 1.0`
3. Включать только после бэктеста: PF с/без overlays на одной выборке

---

### S5 [HIGH] — Fees/slippage занижены: 0.1% round trip vs реалистичные 0.12–0.18%

**Файл:** `risk/engine.py:186-189` `[VERIFIED]`

**Текущие значения:** `exchange_fee_pct=0.05%`, `slippage_pct=0.05%` → round trip = 2×(0.05+0.05) = **0.1%**

**Реальность:** taker ~0.05%×2 = 0.1% + slippage на входе + slippage на стопе (стоп = маркет в момент волатильности, slippage 0.02–0.1%) → реалистично **0.12–0.18%**

**Влияние:** Занижение costs **завышает** RR → пропускаются сделки, которые на деле EV<0. Занижение cost — ошибка в опасную сторону, противоположная консервативной.

**Что сделать:** `FEE_PCT=0.05`, `SLIPPAGE_PCT=0.07` → round trip ≈ 0.24%. После накопления исходов — калибровать по фактическим ценам входа/выхода.

---

### S6 [HIGH] — SL_atr_min (2.0×ATR) конфликтует с structural SL

**Файл:** `risk/engine.py:207-223`, `strategy/trade_engine.py:133` `[VERIFIED]`

**Trade Engine** строит SL liquidity-first: `SL = invalidation_level − 0.35×ATR` (sweep low / OB low / swing / BOS).

**Risk Engine** требует: `sl_distance ≥ atr × 2.0` (reason `SL_ATR_CONFLICT`).

**Конфликт:** ATR=1.0%, sweep low в 0.9% от входа → корректный structural SL = 0.9% + 0.35% = 1.25% ATR-экв. Гейт требует ≥ 2.0% → **reject**. При этом сделка уже прошла все фазы 1.5–4 (HTF-запросы, overlays, 53 фичи) — растраченные ресурсы.

**A1 fix работает:** relaxed механизм срабатывает при ATR 4.0–5.0% (floor clammpается к cap 8%). Но для ATR 1.0–3.0% конфликт остаётся: structural SL часто < 2.0×ATR.

**Что сделать:** понизить `sl_min_atr_multiplier` до 1.25–1.5, либо сделать ATR-гейт lower guard (расширять SL, не reject):
```python
min_sl_from_atr = atr_pct * 1.25
if sl_distance_pct < min_sl_from_atr:
    sl = entry - min_sl_from_atr   # расширить SL, не reject
    tp = entry + (entry - sl) * min_rr  # пересчитать TP
    if tp_beyond_structure:         # path clarity check
        return reject(SL_ATR_CONFLICT)
```

---

### S7 [HIGH] — `block_neutral_htf` мёртвый флаг

**Файл:** `config/settings.py:719`, `scheduler/scanner.py` `[VERIFIED]`

Флаг объявлен `block_neutral_htf=True`, но **нигде** в pipeline-коде не проверяется. NEUTRAL всегда проходит. При 4-TF голосовании (W1/D1/H4) NEUTRAL — частый исход.

**Что сделать:** реализовать или удалить. Рекомендация — реализовать для continuation:
```python
if htf_bias == NEUTRAL and config.block_neutral_htf and setup_type == "continuation":
    return reject(HTF_NEUTRAL_BLOCKED)
```

---

### S8 [HIGH] — Два конфликтующих порога R:R

**Файл:** `config/settings.py:154` (`min_rr_threshold=1.5`) + `config/settings.py:655` (`min_rr_ratio=2.0`) `[VERIFIED]`

`min_rr_threshold` (1.5) используется в `trade_engine.py:242` только как информационная строка — **не блокирует**. Реальный hard gate — `min_rr_ratio` (2.0) в `risk/engine.py`.

**Что сделать:** переименовать для ясности: `min_rr_threshold` → `tp_target_rr` (цель построения TP) или удалить.

---

### S9 [HIGH] — OB-aware cooldown молча fallback-ит на strict

**Файл:** `scheduler/scanner.py:1856-1922` `[VERIFIED]`

В `ob_aware` режиме Phase 0.1 **всегда пропускается**; реальная проверка — в Phase 6. Если у нового сигнала нет OB (`_nearest_ob is None`) ИЛИ у последнего сигнала нет `ob_midpoint` — else-ветка применяет **полный strict cooldown** (`DEDUP_SAME_DIR`).

**Проблема:** fallback не логируется как смена режима. Сигнал молча блокируется stricter rules, чем ожидалось.

**Что сделать:** добавить явный fallback + логирование:
```python
else:
    # No OB data → strict cooldown fallback
    _current_funnel.log_gate(symbol, timeframe, "cooldown", "PASS",
        "ob_aware fallback: no OB data, applying strict rules")
    effective = max(base=45, tf_minutes * 2.0)
    if same_direction and delta < effective:
        block(DEDUP_SAME_DIR)
```

---

### S10 [HIGH] — HTF voting: 3 TF, но описано для 4

**Файл:** `market_structure/htf_bias_v2.py:103-111` `[VERIFIED]`

Фактически голосуют **W1, D1, H4** (3 TF). H1 вычисляется, но **не участвует** в voting (используется только для zone classification). В документации описано 4-TF голосование — неточность.

**Что сделать:** исправить документацию; убедиться, что H1 не вносит self-confirmation при скане 1h.

---

## 4. P2 — Сомнительные параметры

| # | Параметр | Default | Проблема | Рекомендация |
|---|---|---|---|---|
| P2-01 | `ob_proximity_pct` (entry_armed) | 2.0% | Абсолютный %; на BTC 1h ≈ $1.3k — entry_armed почти всегда true → мёртвый флаг | Нормализовать через ATR: `distance / ATR < 1.0` |
| P2-02 | `sweep_min_body_size` | 0.05% | Практически пропускает любую свечу — false-sweep фильтр слабый | Поднять до `0.2×ATR` |
| P2-03 | `sweep_max_pool_age_bars` | 100 (1h ≈ 4 дня) | Недельные экстремумы отсекаются на 1h | Per-TF: 1h=200, 4h=100 |
| P2-04 | `SIGNAL_COOLDOWN_MINUTES` | 45 | Не используется: effective = max(45, tf×2) ≥ 120 для 1h | Удалить или дать отдельную семантику |
| P2-05 | `MIN_DEPTH_0_5_PERCENT` | $10k | Для BTC/ETH очень мелко, фильтр никогда не сработает | Per-symbol: BTC=$250k, ETH=$100k |
| P2-06 | Trading sessions (UTC) | фикс. границы | DST-сдвиг Лондона/Нью-Йорка ±1ч | IANA-tz: `Europe/London`, `America/New_York` |
| P2-07 | `risk_strong_pct` / `risk_moderate_pct` | 1.0/0.5 | Не видно в sizing-цепочке | Применять (quality label → risk) или удалить |
| P2-08 | `sl_distance < 1% → ×1.1` | — | Рост риска при узком SL → экстремальные размеры | Убрать; добавить cap на notional |
| P2-09 | Fees | 0.1% round trip | Занижено (см. S5) | 0.2% round trip |
| P2-10 | `min_rr_threshold` | 1.5 | Мёртвый для live (см. S8) | Удалить или переименовать |
| P2-11 | Volatility band | [0.3, 5.0]% | 5% для 4h BTC недостижима; 0.3% для 4h — всегда true | Per-TF: 1h [0.3, 5.0], 4h [0.5, 7.0] |
| P2-12 | Elliott Wave | enabled, min_confidence=0.4 | Нестабильность разметки; вероятный шум | Ablation-тест; при деградации — удалить |
| P2-13 | `premium_discount` | false | A/B показал PF 1.28→0.91 | Включать после 500+ live trades; использовать как soft multiplier, не hard gate |
| P2-14 | 4h scan frequency | 4 раза в час | 3/4 циклов видят ту же закрытую 4h свечу | Per-TF расписание или throttle |
| P2-15 | `max_trades_per_day` = `max_positions_total` | 5/5 | Дневной лимит сгорает за первые часы | Развести или скользящее окно 24ч |

---

## 5. P3 — Точечные улучшения

### Входы

1. **entry_armed (location) ≠ entry_trigger (timing)** — разделение правильное. Не превращать entry_armed в hard gate без статистики.

2. **Path clarity check** для TP:反对 OB/FVG с strength > 0.5 между entry и target — хорошо. Проверить, что strength > 0.5 — обоснованный порог.

3. **SL buffer 0.35 ATR** — может быть тесным для market makers (сносят 0.5–0.75 ATR за свингом). Замерить MAE в ATR; возможно adaptive buffer от volatility regime.

### Выходы

4. **TP win в ambiguous candle** (TP и SL в одной свече → `HIT_TP`) — консервативнее было бы `HIT_SL` или `0.5R`. Для ML-калибровки это завышает winrate.

5. **Partial close:** `0.25*2R + 0.35*3R + 0.40*4R = 3.15R` gross. Хорошая структура. Проверить, что доли % относятся к **начальному** размеру (так и есть в коде).

### Вероятности

6. **Rules-based scoring ≠ calibrated probability.** Значения 0.55/0.65 не соответствуют реальной частоте TP. До калибровки treat как ranking score, не вероятность.

7. **RR исключён из probability scoring** — правильно. RR в economics после probability, не в probability.

8. **Elliott Wave:** confidence ≥ 0.4 → bonus; конфликт → ×0.85. Ablation-тест обязателен.

### Портфель

9. **Корреляция BTC/ETH/SOL** (0.8–0.95): при открытом BTC long, ETH/SOL long почти всегда блокируется. `max_long_positions=3` фактически недостижим. Сделать корреляционный порог явным параметром.

10. **Correlation block vs direction limits:** дублирование. correlation-block **или** direction limits, не оба.

---

## 6. Что не трогать

1. **ICT pipeline (sweep→MSS→OB/FVG / trend→BOS)** — концептуально чистый
2. **fetch_ohlcv отбрасывает последнюю свечу** — предотвращает сигналы по незакрытому бару
3. **Индикаторы не участвуют в hard gates** — чистое разделение ICT и ML-признаков
4. **EV gate в обоих risk modes** (A09)
5. **Min-notional dimension fix** (A10)
6. **RR feedback loop устранён** — RR не повышает P(TP)
7. **Liquidity-first Trade Engine** — хороший концепт
8. **ExitPlan + partial close + trailing** — зрелая система
9. **Audit trail с 50 reason codes** — отличная observability
10. **OB retest gate** — требовать retest = требовать подтверждение; не ослаблять без данных

---

## 7. План доработки стратегии

### Этап 1 — Quick wins (1–2 дня): конфиг, без смены поведения гейтов

- S7: реализовать `block_neutral_htf` для continuation (новый reason code)
- S8: удалить/переименовать `min_rr_threshold`
- P2-04: удалить `SIGNAL_COOLDOWN_MINUTES` или дать отдельную семантику
- P2-07:清理 `risk_strong_pct`/`risk_moderate_pct`

**Приёмка:** funnel summary не меняется на исторических данных; bump `_CONFIG_VERSION`.

### Этап 2 — Confirmation Score + Probability (2–4 дня)

- S1: реформа confirmation score (MSS+2, sweep+1, разделение порогов)
- S2: убрать бонусы за обязательные компоненты из probability scoring
- S9: fallback cooldown с логированием

**Приёмка:** юнит-тесты на 4 комбинации (reversal/continuation × score=2/3); funnel до/после на 7 днях истории.

### Этап 3 — Risk Engine (3–5 дней)

- S5: fees до 0.2% round trip
- S6: SL_atr_min_multiplier до 1.25 или auto-expand
- S4: флаг `OVERLAYS_AFFECT_SIZING` (default false)
- S3: решение по Kelly (после калибровки P(TP))

**Приёмка:** backtest на сохранённых OHLCV; dry-run 1 неделя с counterfactual trace.

### Этап 4 — Параметрическая оптимизация (после 100+ исходов)

- P2-01: entry_armed через ATR normalization
- P2-02: sweep_min_body_size до 0.2×ATR
- P2-05: depth per-symbol
- P2-11: per-TF volatility bands
- P2-14: per-TF scan schedule
- P2-15: развести max_trades и max_positions
- S10: HTF voting documentation fix

**Приёмка:** counterfactual outcome data; MAE/MFE analysis; calibration curve.

---

## 8. Правила изменений

1. **Каждое изменение = гипотеза** с hypothesis id в `docs/hypotheses.md`
2. **Bump `_CONFIG_VERSION`** при любом изменении порогов
3. **Не менять несколько независимых групп параметров** одним коммитом
4. **Не удалять reason codes** — write-only
5. **Не переводить soft feature в hard gate** без counterfactual evidence
6. **Не включать Premium/Discount** без 500+ live trades
7. **Не превращать индикаторы в hard gates** без OOS evidence
8. **Kelly-режим включать ТОЛЬКО после калибровки P(TP)**
9. **Любой ML experiment** — temporal/OOS, без random train/test split
10. **Не оптимизировать параметры** по одной серии wins/losses
