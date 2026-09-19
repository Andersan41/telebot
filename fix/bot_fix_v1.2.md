# bot_fix_v1.2.md — Independent review + fix plan

## I. Review of v1.1 findings

### P0-1 — reclaim_bars from wrong sweep — CONFIRMED

`scanner.py:531-534` takes reclaim from first valid sweep (oldest):
```python
_valid_sw = [s for s in sweeps if s.is_valid]
if _valid_sw:
    _reclaim = _valid_sw[0].reclaim_candles   # oldest sweep
```

`structure.py:141` saves it as external param:
```python
choch.reclaim_bars = reclaim_bars   # from _valid_sw[0], NOT matching_sweep
```

`structure.py:164-166` finds matching_sweep internally (correct direction, causal window).

`structure.py:204-208` final MSS check uses EXTERNAL reclaim_bars:
```python
is_mss = (
    choch.has_sweep_reference
    and displacement_atr >= 0.2
    and reclaim_bars <= 2      # from _valid_sw[0], NOT matching_sweep!
)
```

Verdict: Real bug. Systematically prevents MSS classification.

---

### P0-2 — Score Gate — CONFIRMED (other model could not find it)

The code EXISTS at `scanner.py:588-603`:
```python
_min_score = getattr(config.trading, 'min_score_for_signal', 2)
if setup.components_count < _min_score:
    reason = f"score={setup.components_count} < min {_min_score}"
    # ... SCORE_TOO_LOW
```

`storage/audit_reasons.py:19`: SCORE_TOO_LOW = "score_too_low"

Why it blocks: sweep-only setup = 1 component < min 2 = BLOCKED.

---

### P0-3 — time_of_day_blocked — REFUTED

The code is COMMENTED OUT at `scanner.py:455-470`:
```python
# try:
#     _current_hour = datetime.now(timezone.utc).hour
#     ...
#     return None
# except Exception:
#     pass
```

TIME_OF_DAY_BLOCKED is imported but never called. The 4,003 blocks come from elsewhere.

---

### P1-1 — SL dead zone — CONFIRMED

ATR=4.5%: dynamic_sl_max=8.0% (cap), min_sl_from_atr=9.0% -> after relax=8.0%.
floor = ceiling = 8.0%, only one valid point.

---

### P1-2 — EV gate only in Kelly — REFUTED

EV check is at `risk/engine.py:246-255`, BEFORE risk_mode branching at line 257:
```python
# Line 246: EV gate — applies to BOTH fixed and Kelly modes
_ev = _p * _b - (1 - _p)
if _ev <= 0:
    return RiskDecision(should_trade=False, ...)

_risk_mode = getattr(config, 'risk_mode', 'fixed')   # line 257, AFTER EV
```

EV gate works in both modes. Other model was wrong.

---

### P1-3 — Documentation mismatch — PARTIALLY CONFIRMED

MSS is NOT a hard gate. In `pattern_engine.py:380-396`:
```python
if not has_mss:
    return ICTSetup(
        detected=True,    # detected=True, NOT False!
        rejection_reason="reversal: sweep only (no MSS)",
    )
```

MSS = soft gate (setup passes but marked weak).

---

### P2-1 — min_rr_threshold dead — REFUTED

Other model claimed it is unused. Grep shows 15+ usages:
- `strategy/trade_engine.py:297` — R:R validation
- `scheduler/core_v2.py:198` — R:R gate
- `backtest/engine.py:702`, `backtest/funnel.py:425`, etc.

---

### P2-2 — block_neutral_htf dead — CONFIRMED

Declared in config, never read in scanner.py.

---

## II. Summary table

| Item | v1.1 status | Verdict |
|------|-------------|---------|
| P0-1 reclaim_bars | CONFIRMED | CONFIRMED |
| P0-2 Score Gate | "not found" | CODE EXISTS (other model missed it) |
| P0-3 time_of_day | "not found" | REFUTED (commented out) |
| P1-1 SL dead zone | CONFIRMED | CONFIRMED |
| P1-2 EV gate only Kelly | CONFIRMED | REFUTED (works in both modes) |
| P1-3 Docs mismatch | CONFIRMED | PARTIAL (MSS is soft) |
| P2-1 min_rr_threshold dead | CONFIRMED | REFUTED (15+ usages) |
| P2-2 block_neutral_htf dead | CONFIRMED | CONFIRMED |

---

## III. Fix plan (ordered by impact)

### Fix 1: reclaim_bars from matching_sweep (P0-1)

**File:** `market_structure/structure.py`

In `classify_choch()`, after finding matching_sweep, overwrite reclaim_bars:

```python
# Line ~168, AFTER finding matching_sweep:
if matching_sweep is not None:
    choch.has_sweep_reference = True
    choch.causality_score = calc_causality(bars_since)
    reclaim_bars = matching_sweep.reclaim_candles   # FIX
    choch.reclaim_bars = reclaim_bars
```

**File:** `scheduler/scanner.py`

Remove pre-computation of _reclaim (lines 526-534):

```python
# BEFORE:
_disp_atr = 0.0
_reclaim = 0
if candle_quality and ind.atr and ind.atr > 0:
    _disp_atr = candle_quality.body_atr_ratio if hasattr(candle_quality, 'body_atr_ratio') else 0.0
if sweeps:
    _valid_sw = [s for s in sweeps if s.is_valid]
    if _valid_sw:
        _reclaim = _valid_sw[0].reclaim_candles

# AFTER:
_disp_atr = 0.0
if candle_quality and ind.atr and ind.atr > 0:
    _disp_atr = candle_quality.body_atr_ratio if hasattr(candle_quality, 'body_atr_ratio') else 0.0
```

And remove reclaim_bars from analyze_structure() call:

```python
# BEFORE:
structure = analyze_structure(
    _df_clean, lookback=50, sweeps=sweeps,
    displacement_atr=_disp_atr, reclaim_bars=_reclaim,
    atr_value=ind.atr if ind.atr else 0.0,
)

# AFTER:
structure = analyze_structure(
    _df_clean, lookback=50, sweeps=sweeps,
    displacement_atr=_disp_atr,
    atr_value=ind.atr if ind.atr else 0.0,
)
```

And remove reclaim_bars from analyze_structure() signature and classify_choch() call
inside structure.py. classify_choch() will compute it internally.

---

### Fix 2: SL dead zone (P1-1)

**File:** `risk/engine.py`

Remove the 8.0% hard cap:

```python
# BEFORE (line ~216):
dynamic_sl_max = max(self.sl_absolute_max_pct, atr_pct * 2.2)
dynamic_sl_max = min(dynamic_sl_max, 8.0)  # hard cap

# AFTER:
dynamic_sl_max = max(self.sl_absolute_max_pct, atr_pct * 2.2)
# No cap — 2.2 multiplier > 2.0 multiplier guarantees floor < ceiling
```

---

### Fix 3: block_neutral_htf cleanup (P2-2)

**File:** `config/settings.py`

Remove dead flag:

```python
# DELETE this line:
block_neutral_htf: bool = os.getenv("BLOCK_NEUTRAL_HTF", "true").lower() == "true"
```

---

## IV. Verification plan

After each fix, run:
```
pytest -v
```

After Fix 1 specifically, monitor audit logs for:
- `mss_none` count should drop significantly
- `pattern_no_setup` count should drop (more setups detected with valid MSS)
- `Signals Sent` should become > 0
