# Отчёт: Расчёт SL и TP в Trading Signal Bot

## 1. ФАЙЛЫ И ФУНКЦИИ

### Основной расчёт SL/TP

**Файл:** `strategy/signal_engine.py` → `_calculate_sl_tp()` (строки 915–938)

Это **единственная функция**, которая устанавливает SL и TP при генерации сигнала. Полный код:

```python
def _calculate_sl_tp(
    ind: IndicatorValues, signal: SignalType, structure: Optional[Any] = None
):
    cfg = config.trading
    atr = ind.atr if ind.atr > 0 else ind.close * cfg.atr_fallback_pct / 100

    if structure and structure.last_bos:
        bos = structure.last_bos
        if signal == SignalType.BUY and bos.type == "bullish":
            sl = round(bos.level * 0.995, 8)
            tp = round(ind.close + atr * cfg.atr_multiplier_tp, 8)
            return sl, tp
        if signal == SignalType.SELL and bos.type == "bearish":
            sl = round(bos.level * 1.005, 8)
            tp = round(ind.close - atr * cfg.atr_multiplier_tp, 8)
            return sl, tp

    if signal == SignalType.BUY:
        sl = round(ind.close - atr * cfg.atr_multiplier_sl, 8)
        tp = round(ind.close + atr * cfg.atr_multiplier_tp, 8)
    else:
        sl = round(ind.close + atr * cfg.atr_multiplier_sl, 8)
        tp = round(ind.close - atr * cfg.atr_multiplier_tp, 8)
    return sl, tp
```

### Пересчёт TP с учётом FVG

**Файл:** `risk/dynamic_risk.py` → `calculate_structural_tp()` (строки 200–298)

Вызывается из `scheduler/scanner.py:504–531`, заменяет TP если найдены FVG с RR ≥ 2.0. Полный код:

```python
def calculate_structural_tp(
    direction: Literal["BUY", "SELL"],
    entry: float,
    sl: float,
    sweeps: list["SweepEvent"],
    order_blocks: list["OrderBlock"],
    structure: Optional["StructureState"] = None,
    fvgs: Optional[list["FairValueGap"]] = None,
    atr: float = 0.0,
    close: float = 0.0,
) -> list[TPTarget]:
    risk = abs(entry - sl)
    if risk <= 0:
        risk = entry * (settings.config.trading.atr_fallback_pct / 100.0)

    candidate_levels: list[tuple[float, str]] = []

    if direction == "BUY":
        for s in sweeps:
            if s.sweep_high > entry:
                candidate_levels.append((s.sweep_high, f"sweep high {s.sweep_high:.4f}"))
        for ob in order_blocks:
            if ob.high > entry:
                candidate_levels.append((ob.high, f"OB high {ob.high:.4f}"))
        if structure:
            for high in structure.recent_highs:
                if high > entry:
                    candidate_levels.append((high, f"structure high {high:.4f}"))
        if fvgs:
            for fvg in fvgs:
                if fvg.is_active and fvg.type == "bearish":
                    fvg_fill = (fvg.top + fvg.bottom) / 2
                    if fvg_fill > entry:
                        candidate_levels.append((fvg_fill, f"FVG fill {fvg_fill:.4f}"))

        candidate_levels.sort(key=lambda x: x[0])
    else:
        for s in sweeps:
            if s.sweep_low < entry:
                candidate_levels.append((s.sweep_low, f"sweep low {s.sweep_low:.4f}"))
        for ob in order_blocks:
            if ob.low < entry:
                candidate_levels.append((ob.low, f"OB low {ob.low:.4f}"))
        if structure:
            for low in structure.recent_lows:
                if low < entry:
                    candidate_levels.append((low, f"structure low {low:.4f}"))
        if fvgs:
            for fvg in fvgs:
                if fvg.is_active and fvg.type == "bullish":
                    fvg_fill = (fvg.top + fvg.bottom) / 2
                    if fvg_fill < entry:
                        candidate_levels.append((fvg_fill, f"FVG fill {fvg_fill:.4f}"))

        candidate_levels.sort(key=lambda x: x[0], reverse=True)

    targets: list[TPTarget] = []
    for price, label in candidate_levels:
        reward = abs(price - entry)
        rr = reward / risk if risk > 0 else 0
        if rr >= 2.0:
            targets.append(TPTarget(price=round(price, 8), label=label, rr=round(rr, 2)))

    if not targets:
        cfg = settings.config.trading
        if atr <= 0:
            atr = close * 0.02
        if direction == "BUY":
            tp_price = round(entry + atr * cfg.atr_multiplier_tp, 8)
        else:
            tp_price = round(entry - atr * cfg.atr_multiplier_tp, 8)
        reward = abs(tp_price - entry)
        rr = reward / risk if risk > 0 else 0
        targets.append(TPTarget(price=tp_price, label=f"ATR fallback ({cfg.atr_multiplier_tp}x)", rr=round(rr, 2)))

    return targets
```

### Структурный SL (определён, но НЕ используется в пайплайне)

**Файл:** `risk/dynamic_risk.py` → `calculate_structural_sl()` (строки 129–197)

Функция написана и протестирована, но **не вызывается** из scanner.py. SL один раз задаётся `_calculate_sl_tp` и больше не пересчитывается. Полный код:

```python
def calculate_structural_sl(
    direction: Literal["BUY", "SELL"],
    entry: float,
    sweeps: list["SweepEvent"],
    order_blocks: list["OrderBlock"],
    structure: Optional["StructureState"] = None,
    atr: float = 0.0,
    close: float = 0.0,
) -> float:
    candidate_levels: list[float] = []

    if direction == "BUY":
        for s in sweeps:
            if s.type == "bullish" and s.sweep_low < entry:
                candidate_levels.append(s.sweep_low)
        for ob in order_blocks:
            if ob.low < entry:
                candidate_levels.append(ob.low)
        if structure:
            for low in structure.recent_lows:
                if low < entry:
                    candidate_levels.append(low)

        sl_level = _find_nearest_below(candidate_levels, entry)
        if sl_level is not None:
            return round(sl_level, 8)
    else:
        for s in sweeps:
            if s.type == "bearish" and s.sweep_high > entry:
                candidate_levels.append(s.sweep_high)
        for ob in order_blocks:
            if ob.high > entry:
                candidate_levels.append(ob.high)
        if structure:
            for high in structure.recent_highs:
                if high > entry:
                    candidate_levels.append(high)

        sl_level = _find_nearest_above(candidate_levels, entry)
        if sl_level is not None:
            return round(sl_level, 8)

    # Fallback: ATR-based
    cfg = settings.config.trading
    if atr <= 0:
        atr = close * (cfg.atr_fallback_pct / 100.0)
    if direction == "BUY":
        return round(entry - atr * cfg.atr_multiplier_sl, 8)
    return round(entry + atr * cfg.atr_multiplier_sl, 8)
```

---

## 2. ВХОДНЫЕ ДАННЫЕ

| Параметр | Источник | Значение по умолчанию |
|---|---|---|
| `atr_period` | env `ATR_PERIOD` | **14** |
| `atr_multiplier_sl` | env `ATR_MULTIPLIER_SL` | **1.5** |
| `atr_multiplier_tp` | env `ATR_MULTIPLIER_TP` | **3.0** |
| `atr_fallback_pct` | env `ATR_FALLBACK_PCT` | **2.0** (процент от close) |

ATR рассчитывается в `indicators/engine.py:165`:
```python
df["atr"] = ta.atr(df["high"], df["low"], df["close"], length=cfg.atr_period)
```
Библиотека `pandas-ta`, период 14 свечей текущего таймфрейма.

**Если ATR ≤ 0** — fallback: `close * 2.0 / 100` (2% от цены).

---

## 3. ТОЧКА ВХОДА (Entry Price)

**Файл:** `scheduler/scanner.py:324–355`

```python
if config.trading.confirm_tf_enabled and confirm_tf != timeframe:
    # подтверждение на 15m
    entry_price = ind_confirm.close   # close свечи 15m
else:
    entry_price = result.close        # close основного TF (1h/4h)
```

**Правило:**
- Если есть подтверждение на `CONFIRM_TIMEFRAME` (по умолчанию `15m`) — entry = **close свечи 15m**.
- Если нет — entry = **close свечи основного таймфрейма** (1h или 4h).

SL и TP считаются **от ind.close** (в `_calculate_sl_tp`), а entry_price присваивается отдельно. Это значит, что SL/TP считаются от close **основного TF**, а entry_price может быть от close **15m** — они могут отличаться.

---

## 4. ФОРМУЛЫ

### Базовый путь (без BOS):

```
BUY:
  SL = close - ATR(14) × 1.5
  TP = close + ATR(14) × 3.0

SELL:
  SL = close + ATR(14) × 1.5
  TP = close - ATR(14) × 3.0
```

### С BOS (Break of Structure):

```
BUY + bullish BOS:
  SL = bos_level × 0.995          (на 0.5% ниже уровня BOS)
  TP = close + ATR(14) × 3.0

SELL + bearish BOS:
  SL = bos_level × 1.005          (на 0.5% выше уровня BOS)
  TP = close - ATR(14) × 3.0
```

### Fallback при ATR = 0:

```
ATR_fallback = close × 2.0 / 100
```
Далее подставляется в формулы выше вместо ATR.

---

## 5. RISK/REWARD

### Минимальный R:R

**В `_calculate_sl_tp` — НЕТ проверки R:R.** SL и TP ставятся чисто по формуле ATR, R:R = 1:2 за счёт соотношения множителей (1.5 vs 3.0).

**В `calculate_structural_tp` (FVG-пересчёт) — ЕСТЬ проверка:**
```python
if rr >= 2.0:    # строка 283
    targets.append(...)
```
Если ни один структурный уровень не даёт RR ≥ 2.0, используется ATR-fallback.

**Вывод:** Базовый R:R **1:2** (задаётся множителями 1.5/3.0). Структурные TP фильтруются по **минимум 1:2**.

### Расчёт R:R для отображения

В `signal_engine.py:121–129`:
```python
rr = abs(self.tp - entry) / abs(entry - self.sl)
```

---

## 6. УЧЁТ СТРУКТУРЫ РЫНКА

### SL — частично

- **С BOS:** SL привязывается к уровню BOS (× 0.995 или × 1.005) — это **единственный случай**, когда SL зависит от структуры рынка.
- **Без BOS:** SL = чисто математический (ATR × множитель).
- `calculate_structural_sl` (сweep/OB/structure) **не вызывается** в продакшене.

### TP — после FVG-пересчёта

Если найдены FVG, TP пересчитывается через `calculate_structural_tp`, которая собирает кандидатов:
1. Sweep high/low
2. Order Block high/low
3. Structure recent high/low
4. FVG fill (midpoint)

Ближайший уровень с RR ≥ 2.0 становится TP. Если таких нет — ATR-fallback.

### Уровни S/R

`strategy/levels.py` → `get_support_resistance()` находит swing high/low, но они используются **только для фильтрации** (distance filter, TP path quality), **не для расчёта SL/TP**.

---

## 7. ОСОБЫЕ СЛУЧАИ

### ATR = 0 или очень мал

```python
atr = ind.atr if ind.atr > 0 else ind.close * cfg.atr_fallback_pct / 100
```

Fallback = **2% от close**. В `calculate_structural_tp` fallback жёстко `close * 0.02`.

### Защита от слишком узкого SL

**Нет.** Если ATR маленький, SL будет очень близко к entry. Нет минимального порога расстояния SL от entry.

### Защита от слишком широкого SL

**Нет.** Нет максимального порога. При резком скачке ATR SL может уйти на десятки процентов.

### TP path blocked

`market_structure/tp_path.py` → `evaluate_tp_path()` проверяет препятствия между entry и TP (resistance для BUY, support для SELL). Если путь заблокирован — `tp_blocked`, сигнал может быть отклонён через `check_no_trade_zones`.

---

## ИТОГОВАЯ СХЕМА

```
entry_price = close(15m) или close(primary TF)

SL (задаётся ОДИН раз):
  ├─ Есть BOS → bos_level × 0.995/1.005
  └─ Нет BOS  → close ± ATR(14) × 1.5

TP (может быть пересчитан):
  ├─ Начально → close ± ATR(14) × 3.0
  └─ Если FVG  → ближайший структурный уровень с RR ≥ 2.0
                  (sweep/OB/structure/FVG fill)
                  иначе → ATR-fallback
```
