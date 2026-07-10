# Sweep Inventory — All Usage Points

## Overview

Liquidity sweep is used in 3 main modules: `strategy/signal_engine.py`, `backtest/engine.py`, `backtest/run_r6_batch.py`.

---

## 1. strategy/signal_engine.py

### 1.1 Leading Trigger (lines 265–281)

**Role: TRIGGER** (when penalty disabled) / **FILTER** (when penalty enabled)

```python
if sweeps:
    if config.trading.sweep_penalty_enabled:
        # PENALTY MODE — sweep is NOT a trigger, logged as negative signal
        for sw in sweeps:
            if getattr(sw, "is_valid", False):
                leading_reasons.append(
                    f"Sweep {sw.type} present (PENALTY — not a trigger) уровень {sw.swept_level}"
                )
                break
    else:
        # NON-PENALTY MODE — sweep IS a leading trigger
        for sw in sweeps:
            if getattr(sw, "is_valid", False):
                has_leading_trigger = True
                leading_trigger_direction = sw.type
                leading_reasons.append(f"Sweep {sw.type} (leading trigger) уровень {sw.swept_level}")
                break
```

- **Current state**: `sweep_penalty_enabled = True` (default)
- **Effect**: Sweep does NOT set `has_leading_trigger`. Logged as penalty reason.
- **Impact on BUY/SELL**: Symmetric — affects both directions equally.

### 1.2 Compression Breakout Check (lines 418–422)

**Role: TRIGGER** (contributor to breakout detection)

```python
if sweeps:
    for sw in sweeps:
        if getattr(sw, "is_valid", False):
            has_strong_trigger = True
            break
```

- **Context**: Only active when `regime == "compression"` AND `compression_enabled = True`
- **Effect**: Sweep presence contributes to `has_strong_trigger` for breakout mode.
- **Impact on BUY/SELL**: Symmetric.

### 1.3 Candle Close Confirmation Bypass (lines 634–645)

**Role: FILTER** (skips candle close check)

```python
is_sweep_setup = False
if sweeps:
    for sw in sweeps:
        if getattr(sw, "is_valid", False) and (
            (direction == "buy" and getattr(sw, "type", "").lower() == "bullish") or
            (direction == "sell" and getattr(sw, "type", "").lower() == "bearish")
        ):
            is_sweep_setup = True
            break

if cfg.candle_close_enabled and not is_sweep_setup:
    # ... candle close confirmation logic
```

- **Effect**: Sweep setups skip candle close confirmation filter.
- **Impact on BUY/SELL**: Directional — bullish sweep for BUY, bearish sweep for SELL.

---

## 2. backtest/engine.py

### 2.1 BacktestConfig flag (line 231)

**Role: CONFIG**

```python
sell_sweep_block: bool = False  # TEMP: reject SELL signals with sweep trigger
```

### 2.2 Preset "full_new_sell_no_sweep" (line 120–125 in run_r6_batch.py)

**Role: PRESET**

```python
"full_new_sell_no_sweep": {
    ...
    "sell_sweep_block": True,
}
```

### 2.3 Post-signal rejection (lines 504–510 in run_r6_batch.py)

**Role: FILTER** (hard block)

```python
if cfg.sell_sweep_block and result.signal == SignalType.SELL:
    sweep_in_reasons = any("sweep" in r.lower() for r in (result.reasons or []))
    if sweep_in_reasons:
        state.reject_stats.sell_sweep_rejected += 1
        state.reject_stats.total_rejected += 1
        continue
```

- **Effect**: Any SELL signal with "sweep" in reasons is completely rejected.
- **Limitation**: Also rejects SELL signals where sweep is only a penalty (not a trigger).

---

## 3. config/settings.py

### 3.1 sweep_penalty_enabled (line 76)

**Role: CONFIG**

```python
sweep_penalty_enabled: bool = os.getenv("SWEEP_PENALTY_ENABLED", "true").lower() == "true"
```

- **Default**: `True` — sweep is logged as penalty, not used as trigger.

### 3.2 Sweep strength weights (lines 212–215)

**Role: SCORING PARAMS**

```python
sweep_strength_fast_reclaim: float = 0.3
sweep_strength_high_volume: float = 0.3
sweep_strength_delta_aligned: float = 0.2
sweep_strength_displacement: float = 0.2
```

### 3.3 w_sweep weight (line 419)

**Role: SCORING WEIGHT**

```python
w_sweep: int = int(os.getenv("W_SWEEP", "10"))
```

- Used in `max_signal_score` calculation but NOT in signal_engine scoring logic.
- Sweep strength is NOT directly used in the signal_engine score.

---

## 4. liquidity/sweep.py

### 4.1 SweepEvent dataclass (line 34)

**Role: DATA MODEL**

```python
@dataclass
class SweepEvent:
    type: Literal["bullish", "bearish"]
    swept_level: float
    sweep_low: float
    sweep_high: float
    reclaim_candles: int
    volume_ratio: float
    timestamp: datetime
    ...
```

### 4.2 detect_sweeps function (line 73)

**Role: DETECTION**

```python
def detect_sweeps(df, lookback=50, swing_window=5) -> list[SweepEvent]:
```

### 4.3 strength property (line 54)

**Role: SCORING**

```python
@property
def strength(self) -> float:
    score = 0.0
    if self.reclaim_candles <= fast_reclaim: score += 0.3
    if self.volume_ratio > high_vol: score += 0.3
    if self.delta_aligned: score += 0.2
    if self.displacement_after > 0: score += 0.2
    return min(score, 1.0)
```

- **Note**: `sweep_strength` is computed but NOT used in signal_engine.evaluate().
- It IS used in `calculate_structural_sl` and `calculate_structural_tp` for SL/TP placement.

---

## 5. scoring/confidence_v2.py

### 5.1 score_liquidity function (line 168)

**Role: SCORING** (confidence V2, not signal_engine)

```python
def score_liquidity(
    bullish_sweeps: int = 0,
    bearish_sweeps: int = 0,
    ...
) -> float:
    score = 0.0
    score += 0.3 * min(bullish_sweeps, 2)
    score -= 0.3 * min(bearish_sweeps, 2)
    ...
```

- **Note**: This is in confidence_v2, NOT in signal_engine.
- Sweep affects confidence scoring but NOT the signal_engine score.

---

## Summary: Sweep Role Matrix

| Location | Role | BUY Impact | SELL Impact | Current State |
|----------|------|-----------|------------|---------------|
| signal_engine:265-281 | Trigger/Filter | Yes | Yes | Penalty mode (not trigger) |
| signal_engine:418-422 | Trigger (compression) | Yes | Yes | Active |
| signal_engine:634-645 | Filter (candle close) | Yes | Yes | Active |
| run_r6_batch:504-510 | Hard block | No | Yes | Only in sell_sweep_block preset |
| confidence_v2:168 | Scoring | Yes | Yes | Not called from signal_engine |
| structural_sl/tp | SL/TP calc | Yes | Yes | Always active |

---

## Key Finding

**Sweep is NOT used as a score contributor in signal_engine.** It affects:
1. Trigger gate (penalty mode: no trigger; non-penalty: yes trigger)
2. Compression breakout detection
3. Candle close confirmation bypass
4. Structural SL/TP calculation (via detect_sweeps in backtest)

**Sweep IS used in confidence_v2 scoring** but this module is NOT called from signal_engine.evaluate() for the main signal decision.
