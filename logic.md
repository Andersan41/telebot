# Logic.md — Полная логика сканирования рынка и генерации сигналов

> Дата: 2026-09-03
> Pipeline: `scan_symbol_v2()` в `scheduler/scanner.py`

---

## 0. Обзор архитектуры

```
Phase 0: Hard Gates (capital protection)
Phase 1: Pattern Engine (ICT setup detection)
Phase 1.4: Setup-Type-Specific Gates
Phase 1.41: Breakout Quality
Phase 1.42: Confirmation Score + OB Retest
Phase 1.43: Session Filter
Phase 1.44: SMT Divergence (soft)
Phase 1.45: HTF Bias + Premium/Discount
Phase 1.5: HTF POI Detection + Trade Engine
Phase 1.55: Market Phase Detection (shadow)
Phase 1.6: Market Thesis Engine (shadow)
Phase 1.65: Scenario Engine (shadow)
Phase 1.7: Hypothesis Engine + Decision Engine (shadow)
Phase 1.7b: LTF Confirmation (multi_tf mode)
Phase 2: Feature Builder
Phase 3: Probability Engine
Phase 3.1: min_p_tp gate
Phase 4: Risk Engine
Phase 4.5: Entry Trigger Check
Phase 5: Build SignalResult
Phase 6: Dedup
Phase 7: Execution Filters (spread, depth, correlation)
Phase 8: Save to DB + Notify
```

---

## 1. Phase 0: Hard Gates (Capital Protection)

Все这些 гейты блокируют сигнал НЕЗАВИСИМО от его качества.

### 1.1 Cooldown
- **Где:** `scanner.py:244`
- **Условие:** был ли сигнал для этого symbol+timeframe за последние N минут
- **Значение по умолчанию:** `SIGNAL_COOLDOWN_MINUTES = 45` (в памяти, сбрасывается при рестарте)
- **Блокировка:** `BLOCKED`

### 1.2 Portfolio Risk
- **Где:** `scanner.py:254-272`
- **Условия:**
  - Активных сигналов >= `max_active_signals` (default 3)
  - Суммарный риск >= `max_portfolio_risk_pct` (default 3%)
- **Блокировка:** `BLOCKED`

### 1.3 Daily Limits
- **Где:** `scanner.py:274-286`
- **Условие:** `daily_limits.can_open_trade()` — лимиты по дню/неделе
- **Блокировка:** `BLOCKED`

### 1.4 Position Limits
- **Где:** `scanner.py:288-309`
- **Условие:** всего открытых позиций >= `max_positions_total`
- **Блокировка:** `BLOCKED`

### 1.5 Data Integrity
- **Где:** `scanner.py:311-320`
- **Условие:** OHLCV + индикаторы недоступны
- **Блокировка:** `BLOCKED`

### 1.6 Volatility Filter
- **Где:** `scanner.py:322-334`
- **Условие:** ATR% (ATR/close*100) вне диапазона `[volatility_min_atr_percent, volatility_max_atr_percent]`
- **Значения:** min=0.3%, max=5.0% (config: `volatility_max_atr_percent`)
- **Блокировка:** `BLOCKED`

---

## 2. Phase 1: Pattern Engine (ICT Setup Detection)

**Модуль:** `strategy/pattern_engine.py`
**Вход:** sweeps, order_blocks, structure, fvgs, candle_quality, current_price, atr
**Выход:** `ICTSetup` dataclass

### Два пайплайна:

#### REVERSAL: Sweep → Displacement → MSS → [OB/FVG]
```
1. Sweep найден? → нет = BLOCKED "reversal: no sweep"
2. Sweep passes false_sweep_filters? (atr, pool_age)
3. Displacement? (информационно, НЕ гейт)
4. MSS (Market Structure Shift) найден? → нет = BLOCKED "reversal: no MSS"
5. Direction из MSS: bullish→buy, bearish→sell
```

#### CONTINUATION: Trend → BOS → [OB/FVG]
```
1. Structure trend != ranging? → нет = BLOCKED "continuation: ranging"
2. BOS найден? → нет = BLOCKED "continuation: no BOS"
3. BOS breaks last swing (TZ §6.3)?
4. Trend aligned? (buy+bullish, sell+bearish) → нет = BLOCKED
```

### Entry Zones (НЕ гейты, только логирование):
- **OB:** directional, temporal binding (ob.timestamp >= sweep.timestamp)
- **FVG:** directional, temporal binding
- **Entry Armed:** price within `ob_proximity_pct` (2.0%) от OB/FVG midpoint

### Confirmation Score (гейт):
- BOS = +2, FVG = +1, OB = +1
- **Минимум:** 2 для entry

---

## 3. Phase 1.4: Setup-Type-Specific Gates

### Reversal Gates (все ОБЯЗАТЕЛЬНЫ):
| Gate | Условие | Дефолт |
|------|---------|--------|
| `sweep_required` | `setup.has_sweep == True` | mandatory |
| `displacement_gate` | `config.reversal_require_displacement == False` OR `setup.has_displacement == True` | `true` |
| `mss_gate` | `setup.has_mss == True` | mandatory |

### Continuation Gates:
| Gate | Условие | Дефолт |
|------|---------|--------|
| `bos_gate` | `setup.has_bos == True` | mandatory |

### Entry Zone (мягкий/жёсткий):
- `config.require_entry_zone = false` → мягкий, логирует но не блокирует
- `config.require_entry_zone = true` → жёсткий, блокирует если price не в OB/FVG

---

## 4. Phase 1.41: Breakout Quality

- **Где:** `scanner.py:534-595`
- **Модуль:** `liquidity/breakout_quality.py`
- **Условие:** `config.breakout_quality_enabled` AND `config.breakout_quality_hard_gate`
- **Вход:** df, direction, atr, OI change, lookback
- **Логика:** AMD stop-hunt vs real breakout
  - body > 50% of range → real
  - wick past boundary but close retraced → fake
- **Блокировка:** только `verdict == "fake"` (очень строгое)

---

## 5. Phase 1.42: Confirmation Score + OB Retest

### Confirmation Score (гейт):
- BOS = 2, FVG = 1, OB = 1
- **Минимум:** 2

### OB Retest + Mitigation Gate:
- **Где:** `scanner.py:597-688`
- **Условие:** `config.require_ob_retest == true` AND `setup.has_ob`
- **Логика:**
  1. Find active OB for direction
  2. Check OB age (max_age_candles = 35)
  3. Check OB state (BROKEN → block, MITIGATED → block)
  4. Check price touched OB zone
  5. Check confirmation candle (engulfing or pin-bar)
- **Блокировка:** если любой шаг не пройден

---

## 6. Phase 1.43: Session Filter (Kill Zones)

- **Где:** `scanner.py:692-706`
- **Условие:** `config.session_hard_gate = false` (default OFF)
- **Сессии:** asian (0-7), london (7-12), overlap (12-16), new_york (16-21), off_hours
- **Блокировка:** если текущая сессия не в `config.trading_sessions`

---

## 7. Phase 1.44: SMT Divergence (soft)

- **Где:** `scanner.py:522-532`
- **Модуль:** `derivatives/smt_divergence.py`
- **Условие:** `config.derivatives.smt_enabled`
- **Вход:** fetches SMT data for symbol
- **Выход:** detail string, score (soft feature)
- **Блокировка:** НЕТ (только логирование)

---

## 8. Phase 1.45: HTF Bias V2

- **Где:** `scanner.py:730-808`
- **Модуль:** `strategy/htf_bias_v2.py`
- **Условие:** `config.htf_bias_v2 = True` (default ON)

### Логика:
```
W1 → D1 → H4 → H1 EMA alignment
```
- EMA21/EMA53 на каждом TF
- BOS после последнего low на HTF → bullish bias

### Direction Filter (hard gate):
| HTF Bias | Blocked Direction | Config |
|----------|-------------------|--------|
| bullish | SELL | `block_short_in_bullish_htf = true` |
| bearish | BUY | `block_long_in_bearish_htf = true` |
| neutral | none | — |

### Continuation + Reversal alignment:
- Если HTF bias не совпадает с направлением setup → `BLOCKED`

---

## 9. Phase 1.5: HTF POI Detection + Trade Engine

### HTF POI (Multi-Timeframe Points of Interest):
- **Модуль:** `strategy/htf_poi.py`
- **Детекция:** OB/FVG на D1, H4, W1
- **Проксимити:** current price within 2% от midpoint
- **Фильтр по направлению:** bullish POI для BUY, bearish POI для SELL

### Trade Engine:
- **Модуль:** `strategy/trade_engine.py`
- **Вход:** ind, direction, structure, order_blocks, sweeps, fvgs, df, timeframe, htf_poi_result
- **Выход:** `TradePlan` (entry, sl, tp, sl_source)

#### SL Calculation:
1. Find invalidation level (sweep lows/highs, OB lows/highs, swing points, BOS level)
2. SL = invalidation ± ATR * 0.35 buffer
3. SL safety: ensure SL beyond current candle wick
4. **HTF POI override:** если цена рядом с HTF POI → SL за HTF уровень

#### TP Calculation:
1. Find targets (external liquidity, opposing OB, active FVG, swing levels)
2. Best target by score (distance, liquidity strength)
3. Fallback: ATR * atr_multiplier_tp

---

## 10. Phase 1.55-1.7: Shadow Systems

Все these работают в SHADOW MODE — не блокируют, только логируют.

### Market Phase Detection:
- **Модуль:** `strategy/market_phase_engine.py`
- **Фазы:** compression, expansion, trend, range, high_vol, low_vol
- **Вход:** ADX, ATR, EMA, BOS, displacement

### Market Thesis Engine:
- **Модуль:** `strategy/market_thesis_engine.py`
- **Логика:** LiquidityGraph → DynamicTradeThesis → BUY/SELL scenarios
- **Output:** scenario_score, scenario_stability

### Scenario Engine:
- **Модуль:** `strategy/scenario_engine.py`
- **Логика:** detect_scenarios() → probability_engine.estimate_scenario() → weight_manager.adjust()

### Hypothesis Engine + Decision Engine:
- **Модуль:** `strategy/hypothesis.py`, `strategy/decision_engine.py`
- **Логика:** HypothesisSet → MarketState → DecisionEngine.decide() → utility-based selection

---

## 11. Phase 1.7b: LTF Confirmation

- **Где:** `scanner.py:937-1001`
- **Условие:** `scan_mode == "multi_tf"` AND `confirm_tf_enabled`
- **Модуль:** `strategy/confirmation_engine.py`
- **Вход:** 5m OHLCV, direction, entry_zone, sl_price, atr_5m
- **Логика:** ищет trigger на LTF (engulfing, pin-bar, BOS)
- **Блокировка:** если нет подтверждения на 5m

---

## 12. Phase 2: Feature Builder

- **Модуль:** `strategy/feature_builder.py`
- **Вход:** ICTSetup, IndicatorValues, StructureState, MarketRegime, VolatilityRegime, MTF, Context, Risk
- **Выход:** `SetupFeatures` dataclass (~35 raw features)

### Категории фич:

| Категория | Фичи | Вес в ML |
|-----------|-------|----------|
| ICT Pattern | has_bos, has_sweep, has_ob, has_fvg, has_displacement, components_count | высокий |
| Reversal | has_mss, mss_score, mss_causality, displacement_atr_ratio, sweep_to_mss_bars | высокий |
| Pattern Metrics | ob_distance_pct, fvg_size_pct, sweep_reclaim_speed, sweep_strength | средний |
| Market Structure | structure_trend, structure_bos_aligned | средний |
| Volume | volume_ratio, volume_delta_pct | средний |
| Volatility | atr_pct, regime | средний |
| Indicators | rsi, adx, ema_spread_pct, dmi_diff, macd_hist_pct | низкий (ML only) |
| MTF | mtf_aligned, mtf_htf_count, is_4h_aligned | средний |
| Context | fear_greed, funding_rate, context_score | низкий |
| Risk | rr_ratio, sl_distance_pct, tp_distance_pct | средний |
| Execution | session, candle_close_pct, is_reversal, entry_armed | низкий |
| Soft Multipliers | htf_alignment_score, premium_discount_score, htf_bias_penalty, ob_state_multiplier, smt_divergence_score | средний |
| Elliott Wave | wave_confidence, wave_direction, wave_conflict | низкий |

---

## 13. Phase 3: Probability Engine

- **Модуль:** `strategy/probability_engine.py`
- **Вход:** SetupFeatures
- **Выход:** `TradeProbability` (p_tp, expected_rr, profit_factor, confidence, model_type)

### Два режима:

#### Rules-based fallback (когда нет ML модели):

**Base rate:** 50% (или из scenario_memory если > 10 trades)

**Reversal scoring (в порядке приоритета):**

| Factor | Edge |
|--------|------|
| sweep | +3.0 |
| displacement | +3.0 |
| MSS | +4.0 |
| MSS quality > 70 | +2.0 |
| MSS quality 50-70 | +1.0 |
| OB | +1.5 |
| FVG | +1.0 |
| entry_armed | +1.5 |

**Continuation scoring:**

| Factor | Edge |
|--------|------|
| BOS | +3.0 |
| structure_bos_aligned | +2.0 |
| OB | +1.5 |
| FVG | +1.0 |
| entry_armed | +1.5 |

**Common scoring:**

| Factor | Edge |
|--------|------|
| structure_bos_aligned | +2.0 |
| volume_ratio > 2.0 | +3.0 |
| volume_ratio > 1.5 | +2.0 |
| volume_ratio > 1.2 | +1.0 |
| ~~R:R >= 3.0~~ | ~~+4.0~~ **REMOVED (A3)** |
| ~~R:R >= 2.0~~ | ~~+3.0~~ **REMOVED (A3)** |
| ~~R:R >= 1.5~~ | ~~+1.5~~ **REMOVED (A3)** |
| ~~R:R < 1.0~~ | ~~-3.0~~ **REMOVED (A3)** |
| MTF aligned | +2.0 |
| Session (london/overlap/ny) | +1.0 |
| ATR 1-3% | +1.5 |
| ATR > 5% | -2.0 |
| ATR < 0.5% | -1.5 |
| context_score > 0.3 | +1.0 |
| context_score < -0.3 | -1.5 |

**Regime-adaptive:**

| Regime | Continuation Edge | Reversal Edge |
|--------|-------------------|---------------|
| expansion | +2.0 | -1.5 |
| compression | +1.5 (if BOS) | -1.0 |
| trend | +2.5 (if aligned) | -2.0 |
| range | -1.0 | +1.5 |
| high_vol | -1.0 | -1.0 |
| low_vol | +1.0 (if BOS) | — |

**Soft multipliers:**
- `htf_alignment_score` [0, 1] → mult = 0.5 + 0.5 * score
- `premium_discount_score` [0, 1] → mult = 0.5 + 0.5 * score
- `htf_bias_penalty` → mult *= penalty (0.8 if reversal mismatch)
- `ob_state_multiplier` → mult *= multiplier (0.0 = broken)
- Elliott Wave: `conf * weight` (config.wave.weight), or `conflict_penalty` if conflict

**Clamp:** `max(20, min(85, winrate))`

#### ML-based (когда есть модель):
- Legacy: classifier → P(TP), regressor → expected RR
- Expected return: regressor → expected return, isotonic → P(TP)
- Confidence: 0.80 (vs 0.40 for rules)

### Quality labels:
- P(TP) >= 0.65 → "strong"
- P(TP) >= 0.50 → "moderate"
- P(TP) < 0.50 → "weak"

---

## 14. Phase 3.1: min_p_tp Gate

- **Где:** `scanner.py:1484-1501`
- **Значения по умолчанию:**
  - BUY: `min_p_tp = 0.30` (30%)
  - SELL: `min_p_tp_short = 0.40` (40%)
  - REVERSAL: `min_p_tp_reversal = 0.50` (50%)
- **Логика:** берётся максимум из всех применимых порогов
- **Блокировка:** если P(TP) < порог

---

## 15. Phase 4: Risk Engine

- **Модуль:** `risk/engine.py`
- **Вход:** features, probability, portfolio, entry_price, sl, tp
- **Выход:** `RiskDecision` (should_trade, risk_pct, rr_ratio)

### Hard Gates:

| Gate | Условие | Дефолт |
|------|---------|--------|
| Portfolio limits | active_count >= max, total_risk >= max | 3 / 3% |
| Data integrity | entry/sl/tp <= 0 | — |
| Zero risk | risk_dist <= 0 | — |
| R:R minimum | effective_rr < min_rr_ratio | 2.0 |
| SL too tight | sl_distance% < sl_absolute_min_pct | 0.8% |
| SL too wide | sl_distance% > sl_absolute_max_pct | 5.0% |
| SL vs ATR | sl_distance% < ATR * sl_min_atr_multiplier | 2.0x |

**Effective R:R calculation:**
```
round_trip_cost = (exchange_fee + slippage) * 2
effective_risk = risk_dist + cost_dist
effective_reward = max(0, reward_dist - cost_dist)
rr = effective_reward / effective_risk
```

### Position Sizing:

**Fixed mode** (default):
```
risk_pct = base_risk_pct (1.0%)
```

**Kelly mode:**
```
kelly = (p * b - q) / b
kelly = max(0, min(kelly, 0.20))  # half-Kelly cap
kelly *= probability.confidence
risk_pct = min(kelly * 100, base_risk_pct)
```

**Soft adjustments:**
| Factor | Multiplier |
|--------|------------|
| scenario_score [0, 100] | [0.6, 1.2] |
| scenario_stability [0, 1] | [0.7, 1.15] |
| atr_pct > 4.0 | 0.5 |
| atr_pct > 2.5 | 0.75 |
| mss_quality [0, 100] | [0.8, 1.1] |
| sl_distance < 1.0% | 1.1 (bonus) |
| sl_distance > 3.0% | 0.8 (penalty) |

**Clamp:** `[min_risk_pct, max_risk_pct]` = `[0.1%, 1.0%]`

---

## 16. Phase 4.5: Entry Trigger Check

- **Где:** `scanner.py:1544-1575`
- **Модуль:** `strategy/entry_trigger.py`
- **Условие:** `_decision.trade == True` (Decision Engine одобрил)
- **Проверки:** price in entry zone, spread check
- **Блокировка:** если trigger не сработал

---

## 17. Phase 5-8: SignalResult, Dedup, Execution, Notify

### SignalResult:
- score = components_count (количество компонентов setup)
- confidence = P(TP) * 100 (capped at 85)
- verdict = "СИЛЬНЫЙ" / "УМЕРЕННЫЙ" / "СЛАБЫЙ" / "ЗАБЛОКИРОВАН"

### Dedup:
- OB-aware mode: если OB разный → пропуска cooldown
- Same OB: reduced cooldown (1/3)
- Cross-direction: half cooldown

### Execution Filters:
- Spread < max_spread_percent
- Depth > min_depth_0_5_percent
- No correlated entries

---

## 18. Итоговая последовательность фильтров

```
START
  │
  ├─ Cooldown ────────────────── BLOCKED
  ├─ Portfolio Risk ──────────── BLOCKED
  ├─ Daily Limits ────────────── BLOCKED
  ├─ Position Limits ─────────── BLOCKED
  ├─ Data Integrity ──────────── BLOCKED
  ├─ Volatility Filter ───────── BLOCKED
  │
  ├─ Pattern Engine ──────────── BLOCKED (no setup)
  │   ├─ Reversal: sweep + MSS
  │   └─ Continuation: trend + BOS
  │
  ├─ Setup-Type Gates ────────── BLOCKED
  │   ├─ Reversal: sweep + displacement + MSS
  │   └─ Continuation: BOS
  │
  ├─ Confirmation Score ──────── BLOCKED (< 2)
  ├─ Breakout Quality ────────── BLOCKED (fake only)
  ├─ OB Retest ───────────────── BLOCKED (if require_ob_retest)
  ├─ Session Filter ──────────── BLOCKED (if session_hard_gate)
  │
  ├─ HTF Bias ────────────────── BLOCKED
  │   ├─ Block SHORT in bullish HTF
  │   ├─ Block LONG in bearish HTF
  │   └─ Continuation/Reversal alignment
  │
  ├─ Trade Engine ────────────── BLOCKED (no SL/TP)
  ├─ LTF Confirmation ────────── BLOCKED (if multi_tf)
  │
  ├─ Feature Builder ─────────── (сбор данных)
  ├─ Probability Engine ──────── BLOCKED (P(TP) < min)
  ├─ Risk Engine ─────────────── BLOCKED (R:R, SL limits)
  ├─ Entry Trigger ───────────── BLOCKED (if Decision Engine)
  │
  ├─ Dedup ───────────────────── BLOCKED
  ├─ Execution Filters ───────── BLOCKED (spread, depth)
  │
  └─ SIGNAL ✓ → Save + Notify
```

---

## 19. Веса и приоритеты (сводка)

| Компонент | Приоритет | Тип |
|-----------|-----------|-----|
| Sweep | 3.0 | trigger |
| Displacement | 3.0 | confirmation |
| MSS | 4.0 | trigger (strongest) |
| BOS | 3.0 | trigger |
| Structure aligned | 2.0 | confirmation |
| OB | 1.5 | entry zone |
| FVG | 1.0 | entry zone |
| Entry armed | 1.5 | entry readiness |
| Volume > 1.5x | 2.0 | confirmation |
| R:R >= 3.0 | 4.0 | quality |
| MTF aligned | 2.0 | context |
| Session | 1.0 | context |
| ATR 1-3% | 1.5 | volatility |
| Context score | ±1.5 | soft |
| HTF alignment | 0.5-1.0x | multiplier |
| OB state | 0.0-1.2x | multiplier |
| Elliott Wave | config.wave.weight | soft |

---

## 20. Известные проблемы и потенциальные улучшения

### Проблема 1: Pattern Engine reject rate = 96.8%
- 2910 / 3005 signals заблокированы на `NO_SIGNAL_ENGINE`
- Причина: sweep false-filters слишком строгие, MSS displacement threshold высокий

### Проблема 2: HTF Bias блокирует контр-трендовые входы
- Профи торгуют reversals в зонах HTF POI, наш бот блокирует все контр-трендовые сигналы

### Проблема 3: HTF POI как зона входа (не реализовано)
- Профи используют D1/W1 OB как зону входа → entry на LTF рядом с HTF POI
- Наш бот: HTF только для направления, не для зон

### Проблема 4:OB Retest gate слишком строгий
- Требует confirmation candle (engulfing/pin-bar) + proximity + age check
- Убивает сигналы которые прошли pattern engine

### Проблема 5: min_p_tp разные пороги для BUY/SELL/REVERSAL
- SELL: 40%, REVERSAL: 50% — значительно выше чем BUY: 30%
- Это может блокировать валидные reversals
