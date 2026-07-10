# DATASET_REPORT.md — Feature Dataset for Factor Importance

**Date:** 2026-06-27  
**Dataset:** `reports/dataset/features_combined.parquet` + `.csv`

---

## 1. Dataset Size

| Metric | Value |
|--------|-------|
| Total rows | **1,138** |
| Total columns | **73** |
| Source | backtest only (signals.db empty) |
| Preset | `full_new` |
| Symbols | 20 (ADA, APT, ARB, AVAX, BTC, DOGE, DOT, ETH, FIL, FLOKI, GRT, INJ, LINK, NEAR, OP, SOL, SUI, UNI, WIF, XRP) |
| Timeframe | 1h |
| Match rate | **100%** (all 1,138 trades matched to snapshots) |
| Win rate | **48.8%** |
| Avg PnL | **+1.196%** |
| Avg Net PnL | **+0.996%** |

---

## 2. Columns with NaN > 30%

| Column | NaN Count | NaN % | Status |
|--------|-----------|-------|--------|
| `volume_delta` | 1,138 | **100%** | Expected — backtest doesn't use taker_buy_volume. **Drop column.** |
| `volume_delta_pct` | 1,138 | **100%** | Same raw indicator field as above. **Drop column.** |
| `bos_type` | 636 | **55.9%** | Expected — NaN means no BOS present. Keep as categorical (None = "none"). |

**Decision:** Drop `volume_delta` and `volume_delta_pct` from analysis. Encode `bos_type` NaN as `"none"`.

---

## 3. Top-5 Factors by Correlation with Win

| Rank | Factor | Correlation | Direction | Interpretation |
|------|--------|------------|-----------|----------------|
| 1 | `rr` | **+0.753** | Positive | Higher R/R at exit = more likely win. **Leakage** — rr is computed from exit_price. |
| 2 | `dmi_strength` | **+0.203** | Positive | Strong DMI alignment = higher WR |
| 3 | `rsi_strength` | **-0.193** | Negative | Counter-intuitive: high RSI strength for BUY = overbought = bad |
| 4 | `regime_confidence` | **+0.154** | Positive | Higher regime confidence = higher WR |
| 5 | `ema_spread_pct` | **+0.149** | Positive | Wider EMA spread = higher WR |

**⚠️ Note on `rr`:** This is a data leakage artifact. `rr` = `(exit_price - entry_price) / (entry_price - sl)`, which is directly determined by whether the trade won. For真正的 factor importance, **exclude `rr` from the model** — it's a target proxy, not a predictive factor.

### Excluding `rr`, the true top-5 predictive factors:

| Rank | Factor | Correlation | RF Importance |
|------|--------|------------|---------------|
| 1 | `dmi_strength` | +0.203 | 2.7% |
| 2 | `regime_confidence` | +0.154 | 1.3% |
| 3 | `ema_spread_pct` | +0.149 | 2.0% |
| 4 | `volume_above_avg` | +0.142 | 0.3% |
| 5 | `adx_value` | +0.125 | 1.0% |

---

## 4. Factor Pairs with Correlation > 0.8 (Duplication)

| Factor 1 | Factor 2 | Correlation | Action |
|----------|----------|-------------|--------|
| `adx_value` | `adx_strength` | **+0.976** | Drop `adx_strength` (linear transform of adx_value) |
| `ema_strength` | `rsi_value` | **+0.947** | Drop `rsi_value` (redundant with ema_strength) |
| `adx_strength` | `supertrend_strength` | **+0.893** | Drop `supertrend_strength` (captured by adx + ema) |
| `adx_value` | `supertrend_strength` | **+0.886** | Same as above |

**Recommended deduplication set (keep 5 of 8):**
- Keep: `adx_value`, `ema_strength`, `dmi_strength`, `rsi_strength`, `ema_spread_pct`
- Drop: `adx_strength`, `supertrend_strength`, `rsi_value`

---

## 5. Factors with Correlation Near 0 (Candidates for Removal)

| Factor | Correlation | RF Importance | Verdict |
|--------|------------|---------------|---------|
| `ema_slope_ok` | NaN | 0.00% | **Remove** — constant or near-constant |
| `trend_is_strong` | +0.017 | 0.00% | **Remove** — almost all True (1128/1138) |
| `ema_bullish_cross` | -0.028 | 0.00% | **Remove** — only 4 occurrences |
| `ema_bearish_cross` | -0.029 | 0.00% | **Remove** — only 1 occurrence |
| `macd_bullish_cross` | +0.046 | 0.01% | Keep — 58 occurrences, WR=58.6% |
| `macd_bearish_cross` | +0.048 | 0.00% | Keep — 82 occurrences, WR=57.3% |
| `hours_in_trade` | -0.006 | 3.6% | Keep — low correlation but RF finds it useful |
| `has_ob` / `ob_valid` | +0.032 | 0.02% | Keep — 110 occurrences, WR=53.6% |

---

## 6. What's Needed for Missing Factor Strengths

### Currently NaN (100%):
- **`volume_delta` / `volume_delta_pct`**: Requires backtest to pass OHLCV with `taker_buy_volume` column. Currently the backtest uses Binance spot-style OHLCV without taker data. **Fix:** Use ` exchange.fetch_ohlcv()` with futures market type, or synthetic taker buy volume estimation.

### Not computed in backtest:
- **Context factors** (`funding_rate`, `oi_delta_pct`, `context_score`, `context_verdict`, `btc_above_ema200_*`): These are live-only fetchers. **Fix:** Add context snapshot caching to backtest (requires historical funding/OI data from Binance).
- **`confidence_v2_score` / `confidence_v2_quality`**: Computed by `scoring/confidence_v2.py` but not saved in `BacktestTrade`. **Fix:** Add `confidence_v2` field to `BacktestTrade` dataclass and save in `result_to_record()`.
- **`sl_distance_pct` / `theoretical_rr`**: SL/TP not saved in raw_results. **Fix:** Add `sl`, `tp` fields to the trade dict in `result_to_record()`.

### Recommended minimal patch for future backtest runs:
```python
# In BacktestTrade dataclass, add:
factor_strengths: dict = field(default_factory=dict)
confidence_v2_quality: str = ""
sl: float = 0.0
tp: float = 0.0

# In result_to_record(), save them:
"sl": t.sl, "tp": t.tp,
"factor_strengths": t.factor_strengths,
"confidence_v2_quality": t.confidence_v2_quality,
```

---

## Key Insights

1. **Regime is the strongest non-leakage predictor**: Expansion regime has 62% WR vs 37.7% for compression. This single factor explains ~24% of WR variance.

2. **Volume confirmation matters**: Above-average volume = 55% WR vs 40.7% without. This is a strong binary filter.

3. **SELL signals outperform BUY**: 52.2% WR vs 45.7%. The system is slightly better at shorting.

4. **DMI strength is the strongest technical indicator**: +0.20 correlation with win. DMI captures the directional momentum that supertrend/EMA also reflect (high duplication).

5. **Sweeps hurt performance**: Signals with sweeps have 42.2% WR vs 53% without. This contradicts the "sweep as leading trigger" hypothesis — sweeps may be noise.

6. **RSI strength is negatively correlated with win**: Counter-intuitive but explained by the scoring logic — high RSI strength for BUY means overbought conditions.

7. **MACD crossovers are weak but positive**: Both bullish and bearish MACD crosses show ~57% WR, but sample sizes are small (58 and 82).

---

## Files Generated

| File | Description |
|------|-------------|
| `reports/dataset/data_inventory.md` | Data source inventory |
| `reports/dataset/schema.md` | Target dataset schema |
| `reports/dataset/backtest_features.parquet` | Backtest features (1138 x 73) |
| `reports/dataset/backtest_features.csv` | CSV copy |
| `reports/dataset/features_combined.parquet` | Combined dataset (= backtest, signals.db empty) |
| `reports/dataset/features_combined.csv` | CSV copy |
| `reports/dataset/factor_importance.md` | Factor importance analysis |
| `reports/dataset/DATASET_REPORT.md` | This report |
