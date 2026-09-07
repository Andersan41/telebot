# logic_3.md — Текущий аудит бота (v3)

> Дата: 2026-09-04
> Статус: Phase 0-1 выполнены, Phase 2 (partial), live data collection

---

## 0. Executive Summary

### Что сделано

| Phase | Что | Коммит | Результат |
|-------|-----|--------|-----------|
| Pre-Phase 0 | Audit legacy | — | 96.8% — legacy ошибка, реальная ~55-60% |
| Phase 1.1 | MSS fixes | `fa8cfee` | MSS rejection: 57% → 45% (BTC) |
| Phase 1.2 | A3: Remove RR | `06289c6` | Feedback loop устранён |
| Phase 1.3 | A1: Dynamic SL max | `72180b4` | Dead zone устранён при ATR ≥ 2.5% |
| Phase 2 | Counterfactual audit | `12777f6` | Confirmation >= 2 блокирует 27-30% detected |

### Текущие метрики (4 symbols × 419 bars × 1h)

| Symbol | Detection Rate | MSS Rejection | Confirmation Rej | Other |
|--------|---------------|---------------|------------------|-------|
| BTC/USDT | 52% | 45% | 14% | 2% ranging |
| ETH/USDT | 57% | 43% | 17% | — |
| SOL/USDT | 40% | 60% | — | — |
| DOGE/USDT | 42% | 57% | — | 1% no BOS |

### Следующий шаг

Ждать 2-4 недели live data. Собрать 100+ trades с исходами. Потом counterfactual replay.

---

## 1. Текущая архитектура pipeline

```
scan_symbol_v2() → 38 gates → Telegram signal
```

### Gate Map (по исполнению)

| # | Gate | Category | Hard/Soft | Blocked % |
|---|------|----------|-----------|-----------|
| 0-2 | Pre-scan (lock, circuit breaker, disabled) | Capital protection | Hard | ~0% |
| 3 | Cooldown 45m | Capital protection | Hard | varies |
| 4-5 | Portfolio risk (count, total %) | Capital protection | Hard | ~0% |
| 6 | Daily limits (5 sub-gates) | Capital protection | Hard | varies |
| 7 | Position limits | Capital protection | Hard | ~0% |
| 8 | Indicators availability | Data | Hard | ~0% |
| 9 | Volatility filter | Data | Hard | ~5% |
| **10** | **Pattern Engine: reversal** | **ICT setup** | **Hard** | **43-60%** |
| 11 | Pattern Engine: continuation | ICT setup | Hard | 1-2% |
| 12-16 | Setup-type specific (sweep, MSS, BOS, etc.) | ICT setup | Hard | — |
| **17** | **Entry zone (OB/FVG nearby)** | **Entry quality** | **Soft** | **87-93%** |
| **18** | **Confirmation score >= 2** | **Entry quality** | **Hard** | **27-30%** |
| 19 | Breakout quality | Quality | Soft (default) | — |
| 20 | OB retest | Quality | Hard (config) | — |
| 21 | Session filter | Timing | Hard (config) | — |
| 22-23 | HTF bias | Directional | Hard | — |
| 24 | SL/TP calculation | Trade plan | Hard | ~0% |
| 25 | LTF confirmation | Timing | Hard (multi_tf) | — |
| 26-27 | Probability Engine (OB state, min P(TP)) | Probability | Hard | — |
| 28-33 | Risk Engine (6 sub-gates) | Risk | Hard | — |
| 34 | Entry trigger | Execution | Hard | — |
| 35-36 | Dedup | Deduplication | Hard | — |
| 37-39 | Execution (spread, depth, correlated) | Execution | Hard | — |

**Итого:** ~38 gate checkpoints, 6 conditional gates

---

## 2. Pattern Engine: Rejection Breakdown

### Reversal path (9 rejection reasons)

| Rejection Reason | Описание | % of rejections |
|------------------|----------|-----------------|
| `reversal: no sweep` | Sweep не найден | <1% |
| `reversal: no MSS (strong CHoCH)` | MSS не найден | **96-100%** |
| `reversal: MSS direction unclear` | Направление MSS не определено | <1% |

### Continuation path (5 rejection reasons)

| Rejection Reason | Описание | % of rejections |
|------------------|----------|-----------------|
| `continuation: no structure` | Structure is None | ~0% |
| `continuation: ranging market` | trend == ranging | 2-5% |
| `continuation: no BOS` | BOS не найден | ~0% |
| `continuation: BOS level <= swing` | BOS не пробивает swing | ~0% |
| `continuation: BOS vs trend` | Направление BOS ≠ trend | ~0% |

### Phase 1.4 additional gates

| Rejection Reason | Описание |
|------------------|----------|
| `reversal: no displacement (config=true)` | config.reversal_require_displacement=True |
| `confirmation_score=X < min 2` | Confirmation score < 2 |
| `price not in OB/FVG zone` | config.require_entry_zone=True |

---

## 3. MSS Detection — Что исправлено

### Проблема

Сweep и CHoCH часто на одной свече. Displacement = body/ATR ≈ 0.1-0.4. Порог 0.5 ATR → все rejection.

### Исправления

| Параметр | Было | Стало | Файл:строка |
|----------|------|-------|-------------|
| `max_causal_bars` | 5 | **10** | `structure.py:129` |
| Same-candle displacement | `close-open` (body) | **`high-low` (full range)** | `structure.py:180-182` |
| MSS threshold | 0.5 ATR | **0.2 ATR** | `structure.py:206` |
| Normal threshold | 0.25 ATR | **0.1 ATR** | `structure.py:219` |
| `analyze_last_candle` body_atr_ratio | missing | **computed** | `candle_quality.py:320-323` |

### Результаты

| Metric | До | После |
|--------|-----|-------|
| BTC detection rate | 40.6% | 52.3% |
| BTC MSS rejection | 57.0% | 45.3% |
| ETH detection rate | 49.9% | 56.8% |
| ETH MSS rejection | 50.1% | 43.2% |

### Оставшийся MSS rejection (43-60%)

- CHoCH без квалифицированного sweep (направление не совпадает или окно 10 баров не хватает)
- SOL: все sweeps bearish, все CHoCH bearish → sweep_dir == choch_dir → skip
- Это **structural limitation**, не баг

---

## 4. Probability Engine — Что исправлено

### A3: RR feedback loop

**Проблема:** RR ≥ 3 → +4 к P(TP). RR уже используется для расчёта SL/TP → feedback loop.

**Исправление:** Убрано полностью.

| Что | Где | Было | Стало |
|-----|-----|------|-------|
| `rr_edge` | `probability_engine.py:270-279` | +4.0 за RR ≥ 3.0 | **removed** |
| `rr_edge` в total | `probability_engine.py:308-312` | `+ rr_edge` | **removed** |
| `base_p *=` | `probability_engine.py:520-525` | `*= 1.10` за RR ≥ 3.0 | **removed** |

---

## 5. Risk Engine — Что исправлено

### A1: SL dead zone

**Проблема:** SL >= 2×ATR И SL <= dynamic_sl_max. При высоком ATR min > max → dead zone.

**Исправление:** Dynamic SL max + ATR-min relaxation.

```python
dynamic_sl_max = max(sl_absolute_max_pct, atr_pct * 2.2)
dynamic_sl_max = min(dynamic_sl_max, 8.0)  # hard cap
min_sl_from_atr = atr_pct * sl_min_atr_multiplier  # 2.0×ATR
if min_sl_from_atr > dynamic_sl_max:
    min_sl_from_atr = dynamic_sl_max  # relaxed (logged)
```

| ATR% | min SL (2×ATR) | dynamic_sl_max | Range valid? | Status |
|------|----------------|----------------|--------------|--------|
| 1.0% | 2.0% | 5.0% | 3.0% wide | OK |
| 2.0% | 4.0% | 5.0% | 1.0% wide | OK |
| 2.5% | 5.0% | 5.5% | 0.5% wide | OK (was dead) |
| 3.0% | 6.0% | 6.6% | 0.6% wide | OK (was dead) |
| 4.0% | 8.0% | 8.0% | 0.0% (boundary) | OK (min relaxed to 8.0%) |
| 5.0% | 10.0% | 8.0% (cap) | min > max | **Relaxed** to 8.0% |
| 8.0% | 16.0% | 8.0% (cap) | min > max | **Relaxed** to 8.0%; volatility gate blocks (max=5%) |

**After A1 fix:** min SL is relaxed to `dynamic_sl_max` when it exceeds the cap. Signal still enters with wider SL (smaller position size keeps risk constant). Logged as `sl_atr_min_relaxed`.

---

## 6. Counterfactual Audit — Phase 2 (partial)

### Данные

4 символа × 419 баров × 1h. Script: `scripts/counterfactual_audit.py`

### Gate Impact (BTC/USDT)

| Gate | Would Block Detected | % |
|------|---------------------|---|
| MSS (reversal) | — | 45.8% total |
| **Confirmation >= 2** | **59** | **27% of detected** |
| Entry armed (OB/FVG nearby) | 201 | 93% (soft) |
| Displacement | 215 | 99% (soft) |

### Detected Signal Characteristics

| Feature | BTC | ETH |
|---------|-----|-----|
| Continuation (BOS) | 73% | 70% |
| Reversal (MSS) | 27% | 30% |
| has OB | 0.5% | 0% |
| has FVG | 30% | 21% |
| has Displacement | 1% | 0.4% |
| entry_armed | 7% | 13% |
| Confirmation score avg | 1.8 | 1.6 |

### Confirmation Score Distribution

| Score | BTC | ETH |
|-------|-----|-----|
| 0 | 13% | 24% |
| 1 | 14% | 7% |
| **2** | **56%** | **56%** |
| 3 | 16% | 14% |
| 4 | 0.5% | 0% |

**Blocked by >= 2:** BTC 27%, ETH 30%

### Key Insight

**Confirmation >= 2 — второй по величине bottleneck.** Большинство detected signals имеют BOS only (score 0-1). Только 56% имеют score >= 2.

**Вопрос для counterfactual:** Создаёт ли confirmation >= 2 edge? Или блокирует хорошие сигналы?

---

## 7. Известные проблемы

### Текущие

| # | Проблема | Severity | Статус |
|---|----------|----------|--------|
| 1 | MSS rejection 43-60% (structural) | Medium | Accepted — data limitation |
| 2 | Confirmation >= 2 blocks 27-30% | High | Needs outcome data |
| 3 | OB presence < 1% in detected signals | Medium | Architecture issue |
| 4 | entry_armed = 7-13% | Low | Soft gate, not blocking |
| 5 | Pre-existing test failures (MockSweep) | Low | 14 tests, not related to changes |

### Исправлено

| # | Проблема | Коммит | Статус |
|---|----------|--------|--------|
| 1 | MSS threshold too high | `fa8cfee` | ✅ Done |
| 2 | Causal window too tight | `fa8cfee` | ✅ Done |
| 3 | Same-candle displacement wrong | `fa8cfee` | ✅ Done |
| 4 | RR feedback loop | `06289c6` | ✅ Done |
| 5 | SL dead zone | `72180b4` | ✅ Done |
| 6 | analyze_last_candle missing body_atr_ratio | `fa8cfee` | ✅ Done |
| 7 | measure_rejection_rate.py no ATR | `fa8cfee` | ✅ Done |

---

## 8. Следующие шаги

### Immediate (1-2 недели)

1. **Live data collection** — запустить бота с текущими фиксами
2. **Собрать 100+ trades** с исходами (HIT_TP / HIT_SL / EXPIRED)
3. **Мониторить confirmation score** — какой win rate у score 0, 1, 2, 3?

### Short-term (2-4 недели)

4. **Counterfactual replay** — что если confirmation >= 2 убран?
5. **OB/FVG analysis** — почему <1% detected mają OB?
6. **SOL/DOGE deep dive** — MSS rejection 57-60% vs BTC/ETH 43-45%

### Medium-term (1-2 месяца)

7. **Phase 3: Architecture** — по данным counterfactual
8. **Class A/B/C gates** — разделить hard/soft по данным
9. **Calibration** — Platt scaling после 300+ trades

---

## 9. Gate Classification (текущая, до Phase 3)

### Class A (Hard, immutable) — не трогать

- Data integrity (entry/sl/tp > 0)
- Portfolio risk (3% ceiling)
- Daily limits
- Position limits
- SL invalid (min/max/ATR)

### Class B (Hard, structural) — potentially Class C

- MSS (reversal) — **threshold relaxed, quality unverified** (needs outcome data)
- BOS (continuation)
- Sweep required (reversal)
- Confirmation >= 2 — **needs counterfactual validation**

### Class C (→ score, по данным) —候補

- HTF bias — directional veto
- Session filter — timing
- OB retest — quality
- Entry zone — proximity

### Soft (never block)

- Displacement
- entry_armed
- SMT divergence
- Context score
- Regime

---

## 10. Config Summary (текущие runtime defaults)

| Parameter | Value | Source |
|-----------|-------|--------|
| `sl_absolute_min_pct` | 0.25% | `config/settings.py:657` |
| `sl_absolute_max_pct` | dynamic: max(5%, ATR×2.2), cap 8% | `risk/engine.py:194-203` |
| `sl_min_atr_multiplier` | 2.0 (relaxed if > dynamic_sl_max) | `risk/engine.py:205-213` |
| `min_rr_ratio` | 2.0 | `risk/engine.py:64` |
| `max_causal_bars` | 10 | `structure.py:129` |
| `MSS threshold` | 0.2 ATR | `structure.py:206` |
| `Normal threshold` | 0.1 ATR | `structure.py:219` |
| `confirmation_min` | 2 | `scanner.py:507-520` |
| `SIGNAL_COOLDOWN_MINUTES` | 45 | `config/settings.py:742` |
| `sl_max_atr_multiplier` | 2.2 | `risk/engine.py:197` |
| `sl_max_cap` | 8.0% | `risk/engine.py:198` |
| `volatility_min_atr_percent` | 0.3% | `config/settings.py:216` |
| `volatility_max_atr_percent` | **5.0%** | `config/settings.py:218` |

---

## 11. File Reference

| File | Purpose |
|------|---------|
| `strategy/pattern_engine.py` | ICT setup detection (reversal/continuation) |
| `strategy/probability_engine.py` | P(TP) estimation |
| `risk/engine.py` | Risk evaluation, position sizing |
| `market_structure/structure.py` | CHoCH/BOS/MSS classification |
| `liquidity/sweep.py` | Liquidity sweep detection |
| `liquidity/order_blocks.py` | Order block detection |
| `liquidity/fvg.py` | Fair value gap detection |
| `liquidity/candle_quality.py` | Candle quality analysis |
| `scheduler/scanner.py` | Pipeline orchestration (38 gates) |
| `scripts/measure_rejection_rate.py` | Rejection rate measurement |
| `scripts/counterfactual_audit.py` | Counterfactual gate analysis |
| `config/settings.py` | All runtime defaults |

---

## 12. Key Principles

1. **Данные → решения, не интуиция → пороги** — 96.8% была legacy ошибкой
2. **Counterfactual replay — центральный инструмент** — нужен outcome data
3. **Разделять setup quality и entry trigger** — MSS ≠ confirmation ≠ entry
4. **Калибровка — staged** — 100→300→500+ trades
5. **Каждый изменённый gate — гипотеза для валидации**
6. **Legacy цифры не принимать на веру** — проверять кодом
