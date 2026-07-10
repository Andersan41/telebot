# Plan 16 — Decision Intelligence Layer (v2)

**Status:** Draft  
**Date:** 2026-06-30 (revised)  
**Depends on:** Decision Traces (implemented), Candidate Dataset (implemented)

## Goal

Maximize data quality and completeness of telemetry. Every decision the bot makes must be fully reconstructable from the stored data — parameters, indicators, factor contributions, gate path, regime context.

No new analytical entities until we have 200+ live candidates and 50+ closed trades through the new trace system.

---

## What NOT to do now

- **❌ FactorContributions table** — `signal_candidates` already stores all 7 factor strengths (st/ema/macd/rsi/vol/adx/dmi) + weighted_score. `signals.confidence_v2_factors` stores the 10 confidence V2 factors as JSON. Adding a 4th entity = join hell in 2 months. If analysis later shows the existing fields are insufficient, extend `decision_traces` with new columns — don't create new tables.
- **❌ Version comparison** — v2.4.0 just started collecting data. Comparing 3 trades vs 8 trades is meaningless. Defer until 50+ closed trades exist.
- **❌ ema_slope as single noisy metric** — replacing with ema_slope_3 and ema_slope_5 (percentage change over 3 and 5 bars).

---

## Phase A — Critical telemetry (DO FIRST)

### A1. config_snapshot — Auto-populate Strategy Parameters

**Problem:** `config_snapshot` column exists (database.py:236) but is **always None**.  
`trace.set_version(VERSION)` at scanner.py:1681 has no config_snapshot argument.

**Solution:** New function in `config/settings.py`:

```python
def build_config_snapshot() -> str:
    """Serialize key strategy parameters to JSON for decision trace."""
    s = config.scoring
    t = config.trading
    r = config.risk
    m = config.market_structure
    d = config.derivatives
    
    snapshot = {
        # Signal engine weights
        "w_supertrend": s.w_supertrend, "w_ema": s.w_ema,
        "w_macd": s.w_macd, "w_rsi": s.w_rsi,
        "w_volume": s.w_volume, "w_adx": s.w_adx, "w_dmi": s.w_dmi,
        "w_bos": s.w_bos, "w_sweep": s.w_sweep, "w_ob": s.w_ob,
        "w_btc": s.w_btc, "w_funding": s.w_funding, "w_oi": s.w_oi,
        # EMA
        "ema_fast": t.ema_fast, "ema_slow": t.ema_slow, "ema_trend": t.ema_trend,
        "min_ema_spread_pct": t.min_ema_spread_pct,
        # ADX / RSI / MACD
        "adx_min": t.adx_min, "adx_strong": t.adx_strong,
        "rsi_period": t.rsi_period, "rsi_overbought": t.rsi_overbought, "rsi_oversold": t.rsi_oversold,
        "macd_fast": t.macd_fast, "macd_slow": t.macd_slow, "macd_signal": t.macd_signal,
        # Score / SL/TP
        "min_score_for_signal": s.min_score_for_signal,
        "atr_multiplier_sl": t.atr_multiplier_sl, "atr_multiplier_tp": t.atr_multiplier_tp,
        "min_rr_threshold": t.min_rr_threshold,
        # Filter toggles
        "adx_filter_enabled": t.adx_filter_enabled,
        "ema_alignment_enabled": t.ema_alignment_enabled,
        "trigger_required": t.trigger_required,
        "compression_enabled": t.compression_enabled,
        "block_compression_regime": t.block_compression_regime,
        "confirm_tf_enabled": t.confirm_tf_enabled,
        "confirm_timeframe": t.confirm_timeframe,
        # Risk
        "risk_strong_pct": r.risk_strong_pct, "risk_moderate_pct": r.risk_moderate_pct,
        "volatility_filter_enabled": r.volatility_filter_enabled,
        "no_trade_zones_enabled": r.no_trade_zones_enabled,
        "dynamic_risk_enabled": r.dynamic_risk_enabled,
        # Context
        "context_min_verdict": config.context_min_verdict,
        "context_fetch_timeout": config.context_fetch_timeout,
        # MTF
        "mtf_required_alignment": m.mtf_required_alignment, "mtf_enabled": m.mtf_enabled,
        # Derivatives
        "btc_correlation_enabled": d.btc_correlation_enabled,
        "btc_global_trend_filter": d.btc_global_trend_filter,
        "eth_correlation_enabled": d.eth_correlation_enabled,
    }
    return json.dumps(snapshot, sort_keys=True)
```

**Changes in scanner.py** — at every `trace.set_version(VERSION)` call, add config_snapshot:
- Line 575 (compression_block)
- Line 684 (signal_engine blocked)
- Line 1681 (signal generated)
- All other early exits

### A2. atr_pct — Normalized Volatility

**New column in `decision_traces`:** `atr_pct` (Float)

**Computation in scanner.py** (after line 563):
```python
if ind.atr and ind.close and ind.close > 0:
    _trace_features["atr_pct"] = round(ind.atr / ind.close * 100, 4)
```

### A3. nearest_support_pct / nearest_resistance_pct

**New columns in `decision_traces`:** `nearest_support_pct` (Float), `nearest_resistance_pct` (Float)

**Computation in scanner.py** (after sr_levels computed, ~line 734):
```python
current_price = entry_price or result.close
if sr_levels and current_price:
    all_supports, all_resistances = [], []
    for tf_levels in sr_levels.values():
        all_supports.extend(tf_levels.get('support', []))
        all_resistances.extend(tf_levels.get('resistance', []))
    
    below = [s for s in all_supports if s < current_price]
    if below:
        nearest = max(below)
        _trace_features["nearest_support_pct"] = round(
            (current_price - nearest) / current_price * 100, 4
        )
    above = [r for r in all_resistances if r > current_price]
    if above:
        nearest = min(above)
        _trace_features["nearest_resistance_pct"] = round(
            (nearest - current_price) / current_price * 100, 4
        )
```

---

## Phase B — Rich telemetry (DO AFTER A)

### B1. ema_slope_3 + ema_slope_5

**New columns in `decision_traces`:** `ema_slope_3` (Float), `ema_slope_5` (Float)

**Formula:**
```
ema_slope_N = (ema_fast[now] - ema_fast[N bars ago]) / ema_fast[N bars ago] * 100
```

**Computation in scanner.py** — use the OHLCV dataframe to compute EMA at different lookbacks:
```python
if df is not None and len(df) >= 6:
    _ema_series = df['close'].ewm(span=cfg.ema_fast, adjust=False).mean()
    _ema_now = _ema_series.iloc[-1]
    if len(_ema_series) >= 4 and _ema_series.iloc[-3] > 0:
        _trace_features["ema_slope_3"] = round(
            (_ema_now - _ema_series.iloc[-3]) / _ema_series.iloc[-3] * 100, 4
        )
    if len(_ema_series) >= 6 and _ema_series.iloc[-5] > 0:
        _trace_features["ema_slope_5"] = round(
            (_ema_now - _ema_series.iloc[-5]) / _ema_series.iloc[-5] * 100, 4
        )
```

### B2. regime_confidence

**Already exists in `signal_candidates`** (database.py:130) but **missing from `decision_traces`**.

**New column in `decision_traces`:** `regime_confidence` (Float)

**Computation in scanner.py** (after line 669):
```python
_trace_features["regime_confidence"] = regime.confidence if regime else None
```

### B3. gate_path_json

**New column in `decision_traces`:** `gate_path` (Text, nullable) — JSON array

Stores the ordered sequence of gate outcomes for each candidate. Enables transition matrix analysis.

**Format:**
```json
[
  "cooldown:PASS",
  "portfolio_risk:PASS",
  "btc_global_trend:PASS",
  "indicators:PASS",
  "confirm_tf:PASS",
  "signal_engine:BLOCK:not_actionable:ENGINE_ADX_FLAT"
]
```

**Implementation in `trace.py`:**

```python
# In DecisionTraceBuilder:
def build_gate_path(self) -> str:
    """Serialize gate outcomes as ordered JSON array."""
    path = []
    for gate in GATE_ORDER:
        result = self._gates.get(gate)
        if result is None:
            continue
        status = "PASS" if result else "BLOCK"
        entry = f"{gate}:{status}"
        if not result and self._final_stage == gate and self._blocked_reason:
            entry += f":{self._blocked_reason[:80]}"
        path.append(entry)
    # Also add compression_block if recorded
    if "compression_block" in self._gates:
        status = "PASS" if self._gates["compression_block"] else "BLOCK"
        path.append(f"compression_block:{status}")
    return json.dumps(path)
```

**In `save()` method**, pass `gate_path=self.build_gate_path()` to `db.save_decision_trace()`.

---

## Phase C — Analytics (LATER, after 50+ trades)

### C1. Extend get_trace_stats()

Add to the return dict:
- `avg_pnl_downstream`: average PnL of downstream signals
- `expectancy_downstream`: `(wr/100 * avg_win) - ((1-wr/100) * avg_loss)`
- `total_pnl_downstream`: sum of all PnL downstream

### C2. Weekly audit

Script that runs weekly and outputs:
- Funnel summary (entered → passed → sent → closed)
- Top/bottom factors by WR contribution
- Gate efficiency ranking
- Config version distribution

---

## Phase D — Deferred (after 200+ candidates, 50+ trades)

- Version comparison (automated diff between strategy versions)
- Factor contribution analysis per factor (using existing signal_candidates data)
- Walk-forward validation on live data

---

## Files to modify

| File | Changes |
|------|---------|
| `config/settings.py` | Add `build_config_snapshot()` |
| `storage/trace.py` | Add new keys to FEATURE_KEYS, add `build_gate_path()`, pass gate_path in save() |
| `storage/database.py` | Add columns: atr_pct, ema_slope_3, ema_slope_5, nearest_support_pct, nearest_resistance_pct, regime_confidence, gate_path to DecisionTrace; migration in `_migrate()` |
| `scheduler/scanner.py` | Pass config_snapshot at all set_version() calls; compute new features (atr_pct, ema slopes, S/R distances, regime_confidence) |

## Implementation Order

| Step | Task | Complexity |
|------|------|------------|
| 1 | `build_config_snapshot()` in settings.py | Low |
| 2 | Pass config_snapshot at all trace.set_version() calls in scanner.py | Low (mechanical) |
| 3 | Add 7 new columns to DecisionTrace + migration | Low |
| 4 | Add FEATURE_KEYS: atr_pct, ema_slope_3, ema_slope_5, nearest_support_pct, nearest_resistance_pct, regime_confidence | Low |
| 5 | Compute atr_pct in scanner.py | Low |
| 6 | Compute ema_slope_3, ema_slope_5 in scanner.py | Medium |
| 7 | Compute nearest_support_pct, nearest_resistance_pct in scanner.py | Medium |
| 8 | Add regime_confidence to _trace_features | Low |
| 9 | Add gate_path column + build_gate_path() in trace.py | Medium |
| 10 | Wire gate_path into trace.save() | Low |

## Verification

1. `python main.py` — no import errors
2. Trigger scan cycle — config_snapshot populated in all decision_traces rows
3. Verify atr_pct, ema_slope_3/5, S/R distances, regime_confidence are populated
4. Verify gate_path is a valid JSON array with gate outcomes
5. `pytest -v` — existing tests pass
