# Continuation Cascade Analysis — Альтернативный вариант

## Дата: 2026-09-20
## Статус: PENDING (ничего не меняем, только документация)

---

## Проблема

Continuation паттерны детектятся pattern_engine, но последовательно блокируются на каждом gate из-за структурной нехватки компонентов.

### Каскад блокировок

```
Pattern Engine: Trend + BOS → detected ✓
    ↓
Score Gate: components_count >= 2 → PASSES (barely)
    ↓
Confirmation Score: >= 2 → PASSES (BOS alone = 2)
    ↓
HTF Bias v2: continuation mismatch → HARD BLOCK ✗
    ↓ (если прошёл)
Probability Engine: components_count <= 2 → -10.0 winrate
                    no OB → -5.0 winrate
                    Total: -15.0 winrate penalty ✗
    ↓
Risk Engine: min_rr_ratio, SL limits
```

### Сравнение: Reversal vs Continuation

| Параметр | Reversal | Continuation |
|----------|----------|--------------|
| Макс. компонентов | 5 (Sweep+Disp+MSS+OB+FVG) | 4 (Trend+BOS+OB+FVG) |
| Типичных компонентов | 4-5 | 2-3 |
| HTF mismatch | Soft penalty (0.85x) | **Hard block** |
| Probability max edge | 16.0 | 9.0 (-44%) |
| Penalty за мало компонентов | -10.0 (если <=2) | **-10.0 (всегда)** |
| Penalty за нет OB | -5.0 | **-5.0** |

---

## Варианты решения

### A. Снизить min_score_for_signal с 2 до 1
- **Влияние:** пропустит continuation с одним BOS (score=1)
- **Риск:** false signals — BOS без подтверждения
- **Рекомендация:** НЕ стоит, BOS без FVG/OB слабый

### B. HTF Bias v2 continuation → soft penalty
- **Сейчас:** continuation mismatch → HARD BLOCK (return None)
- **Предложение:** continuation mismatch → penalty 0.85 (как reversal)
- **Влияние:** +HIGH — пропустит continuation которые сейчас убивает HTF
- **Риск:** continuation против HTF — ниже winrate, но не нулевой

**Доказательство:**
```python
# scanner.py:1000-1012 — СЕЙЧАС:
if setup.setup_type == "continuation":
    setup_bias = direction_map.get(setup.direction)
    if setup_bias != _bias_enum:
        return None  # ← HARD BLOCK

# ПРЕДЛОЖЕНИЕ:
if setup.setup_type == "continuation":
    setup_bias = direction_map.get(setup.direction)
    if setup_bias != _bias_enum:
        _htf_bias_penalty = 0.85  # soft penalty, как reversal
        reason = f"HTF soft penalty: continuation {setup.direction} vs HTF {htf_bias_str}"
        _current_funnel.log_gate(symbol, timeframe, "htf_bias", "PASS",
                                 f"penalty=0.85 {reason}")
        trace.passed("htf_bias", note=reason)
```

### C. Убрать penalty за components_count <= 2 для continuation
- **Сейчас:** probability_engine.py:342-348 — -10.0 winrate за <=2 компонентов
- **Предложение:** не применять этот penalty для continuation
- **Влияние:** +HIGH — continuation получит нормальный winrate

**Доказательство:**
```python
# probability_engine.py:342-348 — СЕЙЧАС:
if f.components_count <= 1:
    penalty -= 15.0
elif f.components_count <= 2:
    penalty -= 10.0

# ПРЕДЛОЖЕНИЕ:
if f.setup_type == "reversal":  # ← только для reversal
    if f.components_count <= 1:
        penalty -= 15.0
    elif f.components_count <= 2:
        penalty -= 10.0
```

### D. Добавить "trend_strength" как компонент для continuation
- **Предложение:** если тренд сильный (ADX > 25 или supertrend совпадает) → +1 компонент
- **Влияние:** +MEDIUM — continuation будет иметь 3 компонента вместо 2
- **Риск:** минимальный

**Доказательство:**
```python
# pattern_engine.py:617-638 — _build_components()
# Добавить после BOS:
if self.structure_trend in ("bullish", "bearish") and self.has_bos:
    # Strong trend confirmation for continuation
    if hasattr(self, '_trend_strength') and self._trend_strength > 0.7:
        components.append("TrendStrength")
```

### E. Снизить min_p_tp для continuation
- **Сейчас:** min_p_tp = 0.30 (для всех)
- **Предложение:** min_p_tp_continuation = 0.20
- **Влияние:** +MEDIUM — больше continuation пройдёт probability gate
- **Риск:** больше signals с низким P(TP)

### F. Комбинация B + C + D (рекомендуется)
- **Предложение:** сделать 3 фикса вместе
- **Влияние:** максимальный эффект
- **Риск:** нужен A/B тестирование
- **Оценка:** +HIGHEST impact

---

## Ожидаемый эффект (естimation)

Сейчас: 0 signals/week

После B + C + D:
- Pattern Engine: ~30% continuation pass (вместо 0%) → ~23K → ~7K
- Score Gate: 90% pass → ~6.3K
- Confirmation: 95% pass → ~6K
- HTF Bias (soft penalty): 80% pass → ~4.8K
- Probability Engine (no penalty): 70% pass → ~3.4K
- Risk Engine: 90% pass → ~3K

**Итого: ~3K signals/week** (2-3/day на 150 символов)

Это ОЧЕНЬ грубо. Реально будет меньше, потому что gates коррелированы (один и тот же setup блокируется на нескольких уровнях). Реалистичная оценка: **5-15 signals/week**.

---

## Приоритеты

| Приоритет | Фикс | Impact | Risk |
|-----------|------|--------|------|
| 1 | B: HTF Bias v2 continuation → soft penalty | +HIGH | Low |
| 2 | C: Убрать components_count penalty для continuation | +HIGH | Low |
| 3 | D: Добавить trend_strength компонент | +MEDIUM | Very Low |
| 4 | E: Снизить min_p_tp для continuation | +MEDIUM | Medium |

---

## Зависимости

- Фикс B можно делать независимо
- Фикс C можно делать независимо
- Фикс D можно делать независимо
- Фикс E зависит от C (если убрать penalty, min_p_tp становится менее критичным)

---

## A/B тестирование

После применения фиксов:
1. Запустить на 1-2 символах (BTC/USDT, ETH/USDT) на 4h
2. Сравнить количество signals до/после
3. Если signals > 5/week и winrate > 35% — масштабировать на все символы
4. Мониторить false positive rate ( signals которые ушли в SL)

---

## Примечание

Это альтернативный вариант. Основной анализ в `fix/bot_fix_v1.3.md`. Данный документ используется как справочный материал для potential future changes.
