# Plan 15: Candidate Dataset + Walk-Forward + Calibration

## Goal
Build a complete dataset of every signal evaluation (passed AND rejected) to enable
feature analysis, walk-forward validation, and probability calibration.

## Current State
- Only **passed** signals are saved to `signals` table (scanner.py:1394)
- `_gate_log` in signal_engine.py tracks gates but only logs to file, not DB
- `_FunnelCounter` tracks per-cycle stats but doesn't persist individual candidates
- `factor_fingerprint` exists for historical winrate lookups on passed signals only

## What Changes

### 1. New table: `signal_candidates`

Every call to `signal_engine.evaluate()` logs a row — pass OR fail.

```sql
CREATE TABLE signal_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp DATETIME NOT NULL,

    -- Outcome tracking (filled later by outcome_tracker)
    outcome TEXT,          -- HIT_TP / HIT_SL / EXPIRED / null (still open)
    pnl_pct REAL,

    -- What the engine decided
    signal_type TEXT,      -- BUY / SELL / null (NO_SIGNAL)
    rejection_reason TEXT, -- ENGINE_ADX_FLAT / ENGINE_NO_TRIGGER / null (passed)
    score INTEGER,

    -- All 7 factor strengths (raw, -1.0 to 1.0)
    st_strength REAL,
    ema_strength REAL,
    macd_strength REAL,
    rsi_strength REAL,
    vol_strength REAL,
    adx_strength REAL,
    dmi_strength REAL,

    -- Weighted composite
    weighted_score REAL,

    -- Raw indicator values (for re-analysis)
    adx REAL,
    rsi REAL,
    ema_fast REAL,
    ema_slow REAL,
    ema_trend REAL,
    macd_hist REAL,
    dmi_plus REAL,
    dmi_minus REAL,
    atr REAL,
    close REAL,
    volume REAL,
    volume_sma REAL,
    supertrend_direction INTEGER,

    -- Regime context
    regime TEXT,           -- trend / range / compression / expansion
    regime_confidence REAL,

    -- Gate that stopped the candidate (null = passed all gates)
    blocked_gate TEXT,     -- adx / trigger / ema_alignment / min_score / ...

    -- Metadata
    factor_fingerprint TEXT,
    confidence_v2_pct REAL,
    has_trigger BOOLEAN,
    has_leading_trigger BOOLEAN,
    mtf_aligned BOOLEAN
);
```

### 2. Log point: `signal_engine.evaluate()` return

Every `return SignalResult(...)` in `signal_engine.py` already has `_rejection_reason`
set for rejected candidates. We add a call to log the candidate at the END of evaluate(),
**before** the return, capturing all factor strengths and raw values.

New function: `_log_candidate(ind, result, regime, gates, ...)` called at every exit point.

### 3. Walk-Forward Validation Script

`scripts/walk_forward.py`:
- Reads `signal_candidates` table with outcomes (HIT_TP / HIT_SL)
- Uses `TimeSeriesSplit` for temporal splitting (no future leakage)
- For each fold:
  - Train `RandomForestClassifier` (n_estimators=200, max_depth=5) on factor strengths
  - Calibrate with `CalibratedClassifierCV(isotonic)` on train fold
  - Predict probability on test fold
- Outputs: per-fold accuracy, Brier score, ROC-AUC, calibration curve data

Feature vector (12 features):
```
st_strength, ema_strength, macd_strength, rsi_strength, vol_strength,
adx_strength, dmi_strength, weighted_score, adx, rsi, regime_encoded, has_trigger
```

Target: `1` if outcome == HIT_TP, `0` if outcome == HIT_SL
(Exclude EXPIRED and null outcomes from training)

### 4. Probability Calibration

`scripts/calibration.py`:
- Reads walk-forward predictions
- Groups by probability bucket (50-55%, 55-60%, ..., 95-100%)
- Computes actual win rate per bucket
- Fits isotonic regression (already done via CalibratedClassifierCV)
- Outputs: reliability diagram data, Expected Calibration Error (ECE), Brier score

## Files to Change

| File | Change |
|------|--------|
| `storage/database.py` | Add `SignalCandidate` model + `save_candidate()` method |
| `strategy/signal_engine.py` | Add `_log_candidate()` call at every exit point |
| `scheduler/scanner.py` | Pass extra context to `_log_candidate` (regime, mtf, etc.) |
| `scripts/walk_forward.py` | New file — RF + isotonic + TimeSeriesSplit |
| `scripts/calibration.py` | New file — calibration analysis + ECE |

## Model Choice
- **Classifier**: `RandomForestClassifier(n_estimators=200, max_depth=5, class_weight="balanced")`
- **Calibration**: `CalibratedClassifierCV(rf, method="isotonic", cv=3)`
- **Splitting**: `TimeSeriesSplit(n_splits=5)` — no future leakage
- **Why RF over LR**: LR AUC ≈ 0.52, RF AUC ≈ 0.56 on current data. RF captures non-linear factor interactions.

## Migration
- `signal_candidates` table created via `Base.metadata.create_all` in `Database.init()`
- No existing tables modified

## Risks
- **Performance**: logging every evaluation adds DB writes. Mitigate with async batch writes
  or write-behind queue if needed. Initially, single async write per evaluation should be fine
  (SQLite handles ~1000 writes/sec).
- **Disk size**: ~50-200 candidates per scan cycle × 96 cycles/day = ~5000-20000 rows/day.
  At ~500 bytes/row = ~10MB/day = ~300MB/month. Acceptable.
