# bot_fix_v1.2.md — Independent review, fixes applied, baseline snapshot

## Status: FIXES DEPLOYED, AWAITING LIVE MEASUREMENTS

Date: 2026-09-19
Branch: feat/htf-bias-v2-premium-discount
Config version: 10

---

## I. Review of v1.1 findings

### P0-1 — reclaim_bars from wrong sweep — CONFIRMED → FIXED ✓

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

### P0-2 — Score Gate — CONFIRMED

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

### P1-1 — SL dead zone — CONFIRMED → FIXED ✓

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

### P2-2 — block_neutral_htf dead — CONFIRMED → FIXED ✓

Declared in config, never read in scanner.py.

---

### P(-1) — scanner.py imports 6 non-existent names — REFUTED

Other model claimed REGIME_BLOCKED, SCORE_TOO_LOW, SWEEP_CONTINUATION_MISMATCH,
BOS_NO_RETEST, SL_STRUCTURAL_TIGHT, TIME_OF_DAY_BLOCKED don't exist in audit_reasons.py.

ALL 6 EXIST at `storage/audit_reasons.py:18-23`:
```python
REGIME_BLOCKED = "regime_blocked"          # line 18
SCORE_TOO_LOW = "score_too_low"            # line 19
SWEEP_CONTINUATION_MISMATCH = "sweep_continuation_mismatch"  # line 20
BOS_NO_RETEST = "bos_no_retest"            # line 21
SL_STRUCTURAL_TIGHT = "sl_structural_tight" # line 22
TIME_OF_DAY_BLOCKED = "time_of_day_blocked" # line 23
```

No ImportError. Module loads fine.

---

## II. Summary table

| Item | v1.1 status | Verdict | Action |
|------|-------------|---------|--------|
| P0-1 reclaim_bars | CONFIRMED | CONFIRMED | FIXED ✓ |
| P0-2 Score Gate | "not found" | CODE EXISTS | No action needed |
| P0-3 time_of_day | "not found" | REFUTED (commented out) | No action needed |
| P1-1 SL dead zone | CONFIRMED | CONFIRMED | FIXED ✓ |
| P1-2 EV gate only Kelly | CONFIRMED | REFUTED (works in both modes) | No action needed |
| P1-3 Docs mismatch | CONFIRMED | PARTIAL (MSS is soft) | No action needed |
| P2-1 min_rr_threshold dead | CONFIRMED | REFUTED (15+ usages) | No action needed |
| P2-2 block_neutral_htf dead | CONFIRMED | CONFIRMED | FIXED ✓ |
| P(-1) ImportError | CONFIRMED | REFUTED (all 6 exist) | No action needed |

---

## III. Fixes applied (2026-09-19)

### Fix 1: reclaim_bars from matching_sweep (P0-1) ✓

**Files changed:**
- `market_structure/structure.py` — `classify_choch()` and `analyze_structure()`
- `scheduler/scanner.py` — removed `_reclaim` pre-computation
- `backtest/run_breakout_quality.py` — removed `reclaim_bars=_reclaim`
- `backtest/run_new_pipeline.py` — removed `reclaim_bars=_reclaim`
- `scripts/analyze_mss_failures.py` — removed `reclaim_bars=_reclaim`
- `scripts/analyze_alt_mss.py` — removed `reclaim_bars=_reclaim`
- `scripts/ab_test_htf_v2.py` — removed `reclaim_bars=_reclaim`
- `tests/test_new_pipeline.py` — updated MockSweep.reclaim_candles

**What changed:**
- Removed `reclaim_bars` param from `classify_choch()` signature
- Removed `reclaim_bars` param from `analyze_structure()` signature
- `classify_choch()` now gets reclaim_bars from `matching_sweep.reclaim_candles`
- Scanner no longer pre-computes `_reclaim` from first valid sweep

---

### Fix 2: SL dead zone (P1-1) ✓

**File changed:** `risk/engine.py`

**What changed:**
- Removed `dynamic_sl_max = min(dynamic_sl_max, 8.0)` hard cap
- Dynamic SL max now = `max(sl_absolute_max_pct, ATR × 2.2)` without ceiling

---

### Fix 3: block_neutral_htf cleanup (P2-2) ✓

**File changed:** `config/settings.py`

**What changed:**
- Removed dead `block_neutral_htf` field (never referenced anywhere)

---

## IV. Pre-fix baseline (7-day live data + local log snapshot)

### Live funnel statistics (7 days, config v10):

| Metric | Value |
|--------|-------|
| Total Entries | 77,253 |
| Signals Sent | **0** |
| Config Version | 10 |

### Pipeline Funnel (all 0 sent):

| Gate | Blocked | % |
|------|---------|---|
| Pattern Engine | 47,359 | 61.3% |
| Score Gate | 16,084 | 20.8% |
| Confirmation | 3,225 | 4.2% |
| Indicators | 1,988 | 2.6% |
| Displacement | 1,199 | 1.6% |
| Volatility | 983 | 1.3% |
| HTF Bias | 936 | 1.2% |
| Entry Trigger | 1,090 | 1.4% |
| Risk Engine | 153 | 0.2% |
| Portfolio Risk | 2 | 0.0% |

### Top Rejection Reasons:

| Reason | Count | % |
|--------|-------|---|
| pattern_no_setup | 34,764 | 45.0% |
| score_too_low | 16,084 | 20.8% |
| mss_none | 12,179 | 15.8% |
| time_of_day_blocked | 4,003 | 5.2% |
| confirmation_low | 3,225 | 4.2% |
| data_integrity_fail | 2,141 | 2.8% |
| displacement_missing | 1,199 | 1.6% |
| entry_trigger_no | 1,090 | 1.4% |
| htf_short_in_bullish | 817 | 1.1% |
| volatility_too_low | 655 | 0.8% |

### Key observations:
1. **Pattern Engine** kills 61% — `pattern_no_setup` (34,764) is 73% of that
2. **Score Gate** kills 20.8% — `score_too_low` = 16,084 (BIGGEST surprise)
3. **MSS None** = 12,179 — what Fix 1 (reclaim_bars) should address
4. **time_of_day_blocked** = 4,003 — should be commented out, needs investigation
5. **Zero signals through ALL gates** — cascade problem

---

## V. Post-fix expectations

### Fix 1: reclaim_bars (P0-1) — targets mss_none (12,179)
- `mss_none` should drop from 12,179 to ~3,000-5,000 (50-75% reduction)
- Some of those will convert to `pattern_no_setup` reduction
- Expected pattern_engine blocks: 47,359 → ~40,000-42,000

### Fix 2: SL dead zone (P1-1) — targets risk_engine (153)
- Risk engine blocks should decrease (already small at 153)
- More impact on individual signal quality than volume

### Remaining bottlenecks after fixes:
- **score_too_low (16,084)** — 2nd biggest, needs config change (min_score 2→1) or more components
- **pattern_no_setup (34,764)** — still dominant, needs pattern_engine tuning
- **time_of_day_blocked (4,003)** — needs investigation (should be inactive)

### Measurement plan:
1. **Immediately after deploy:** `python scripts/measure_rejection_rate.py` — compare with H-006 baselines
2. **24 hours:** Check live funnel stats — compare rejection reasons with pre-fix baseline
3. **3 days:** If score_too_low still > 10%, consider lowering min_score_for_signal
4. **1 week:** Full analysis — are signals being sent? What's the winrate?

---

## VI. Files in this repository relevant to the pipeline

### Core pipeline:
- `scheduler/scanner.py` — main pipeline `scan_symbol_v2()` at line 294
- `strategy/pattern_engine.py` — ICT setup detection, confirmation_score
- `strategy/feature_builder.py` — ~35 raw features into flat vector
- `strategy/probability_engine.py` — P(TP), expected RR, profit factor
- `risk/engine.py` — capital protection, Kelly, hard gates

### Market structure:
- `market_structure/structure.py` — `classify_choch()`, `analyze_structure()`
- `market_structure/htf_bias_v2.py` — HTF bias (W1 removed from majority vote)

### Liquidity:
- `liquidity/sweep.py` — sweep detection and false-filter
- `liquidity/order_blocks.py` — OB detection
- `liquidity/fvg.py` — FVG detection
- `liquidity/candle_quality.py` — displacement, candle analysis

### Config:
- `config/settings.py` — all config defaults
- `storage/audit_reasons.py` — 40+ rejection reason codes

### Tests:
- `tests/test_new_pipeline.py` — pipeline unit tests
- `tests/test_market_structure.py` — structure tests
- `tests/test_risk.py` — risk engine tests
- `tests/test_htf_bias_v2.py` — HTF bias tests

---

## VII. Known issues (not fixed, lower priority)

1. **Confirmation score < 2** — still blocks some setups, but H-013 already fixed the worst case (reversal without BOS)
2. **OB detection extremely low** (0-5.8%) — order_blocks.py may need tuning
3. **Displacement rate low** (0.6-4.8%) — H-003 fix (body→range) helped but not enough
4. **Scheduler runs both scanner.py and core_v2.py** — need to verify which one is active
5. **Tests in test_new_pipeline.py** — 21 pre-existing failures (MockSweep missing `passes_false_sweep_filters`, risk engine `entry` NameError)
