# Data Inventory — Feature Dataset for Factor Importance

**Date:** 2026-06-27  
**Purpose:** Factor importance analysis for signal quality

## 1. raw_results_r6.json — Backtest Results

**Structure:** JSON array of 200 records (20 symbols × 10 presets)  
**Total trades:** 11,220 across all presets; **full_new preset: 1,138 trades** (20 symbols)

### Per-record (aggregate) fields:
- `symbol`, `preset`, `total_trades`, `wins`, `losses`, `winrate`
- `avg_pnl`, `avg_net_pnl`, `avg_rr`, `profit_factor`, `expectancy`, `sharpe_ratio`
- `max_drawdown`, `total_pnl_pct`, `total_net_pnl_pct`
- `signals_generated`, `signals_rejected`, `exposure_time_pct`, `avg_trade_duration`
- `reject_rr`, `reject_sl_dist`, `reject_confirm_tf`, `reject_news`
- `exit_sl`, `exit_tp`, `exit_eob`, `src_atr`, `src_bos`, `src_structural`
- `trades`: list of per-trade dicts

### Per-trade fields (saved):
| Field | Type | Description |
|-------|------|-------------|
| `symbol` | str | e.g. "BTC/USDT" |
| `direction` | str | "BUY" / "SELL" |
| `entry_price` | float | Entry price |
| `exit_price` | float | Exit price (may be None for open) |
| `exit_reason` | str | "sl" / "tp" / "eob" |
| `pnl_pct` | float | Gross PnL % |
| `net_pnl_pct` | float | Net PnL % (after fees) |
| `rr` | float | Risk/Reward ratio at exit |
| `sl_source` | str | "atr" / "bos" / "structural" |
| `regime` | str | "trend" / "range" / "expansion" / "compression" |
| `entry_timestamp` | str | ISO datetime |
| `exit_timestamp` | str | ISO datetime |

### What's MISSING in saved trades:
- ❌ Factor strengths (ema_strength, adx_strength, etc.)
- ❌ Signal score (score field exists in BacktestTrade but NOT saved to JSON)
- ❌ Confidence / confidence_v2
- ❌ Indicator values (RSI, MACD, ADX at entry)
- ❌ Context data (funding_rate, OI, fear_greed)
- ❌ Structure data (BOS level, trend)
- ❌ Sweep / OB data
- ❌ SL/TP prices

**Note:** `signal_score` and `confidence` are computed in BacktestTrade but dropped in `result_to_record()`.

## 2. snapshot_cache/ — Precomputed Indicators

**Files:** 20 `.pkl` files, one per symbol  
**Format:** Python list of 3,798 snapshot dicts per symbol  
**Time range:** 2026-01-15 to 2026-06-22 (1h candles)

### Snapshot dict keys:
| Key | Type | Content |
|-----|------|---------|
| `i` | int | Candle index in DataFrame |
| `ind` | IndicatorValues | Full indicator values |
| `regime_obj` | MarketRegime | Regime classification |
| `structure` | StructureState | Market structure (BOS/CHOCH) |
| `all_sweeps` | list[SweepEvent] | All detected sweeps |
| `all_obs` | list[OrderBlock] | All detected order blocks |
| `valid_sweeps` | list[SweepEvent] | Validated sweeps |
| `valid_obs` | list[OrderBlock] | Validated order blocks |
| `fvgs` | list | Fair Value Gaps |
| `entry_price_base` | float | Entry price used |
| `confirm_entry_price` | float | Confirmation entry price |
| `confirm_ok` | bool | Confirmation passed |
| `df_index_i` | str | Candle timestamp (ISO) — **MATCH KEY** |

### IndicatorValues fields (33 attributes):
**Raw values:** `close`, `high`, `low`, `volume`, `ema_fast`, `ema_slow`, `ema_trend`, `ema_fast_prev`, `ema_slow_prev`, `rsi`, `macd`, `macd_signal`, `macd_hist`, `macd_hist_prev`, `adx`, `dmi_plus`, `dmi_minus`, `atr`, `supertrend`, `supertrend_direction`, `volume_sma`, `volume_delta_pct`

**Computed booleans:** `ema_bullish_cross`, `ema_bearish_cross`, `ema_bullish_alignment`, `ema_bearish_alignment`, `macd_bullish_cross`, `macd_bearish_cross`, `volume_above_avg`, `supertrend_bullish`, `supertrend_bearish`, `trend_is_strong`

### MarketRegime fields:
- `regime` (trend/range/compression/expansion/reversal)
- `confidence` (0-1)
- `adx` (float)
- `atr_percentile` (float)
- `ema_spread_trend` (rising/falling/stable)

### StructureState fields:
- `trend` (bullish/bearish/ranging)
- `last_bos` → BOS(type, level, timestamp, candle_index)
- `last_choch` → CHoCH(type, level, timestamp, candle_index)
- `swing_points`, `structure_breaks`, `recent_highs`, `recent_lows`

### SweepEvent fields:
- `type` (bullish/bearish), `swept_level`, `sweep_low`, `sweep_high`
- `reclaim_candles`, `volume_ratio`, `timestamp`
- `wick_body_ratio`, `displacement_after`, `delta_aligned`
- **`strength` property:** 0.0-1.0 score

### OrderBlock fields:
- `type` (bullish/bearish), `high`, `low`, `timestamp`
- `mitigated`, `displacement_atr`, `volume_ratio`, `has_bos`, `retested`
- **`is_valid` property:** validation check
- **`midpoint` property:** (high+low)/2

### Matching quality:
- **100% exact match** between trade entry_timestamp and snapshot df_index_i
- All 10 test trades matched within 0.0h diff

## 3. signals.db — Live Database

**Status: EMPTY** (0 bytes, no tables)  
**Expected tables:** `signals`, `signal_outcomes`  
**Live trades:** 0

## Available Factors Summary

### Can be extracted from snapshot_cache (recomputable):
| Factor | Source | How |
|--------|--------|-----|
| `ema_strength` | IndicatorValues | `_strength_ema()` from signal_engine.py |
| `ema_spread_pct` | IndicatorValues | `(ema_fast - ema_slow) / ema_slow * 100` |
| `ema_slope_ok` | IndicatorValues | Compare current vs prev spread |
| `adx_value` | IndicatorValues | Direct `.adx` |
| `adx_strength` | IndicatorValues | `_strength_adx()` |
| `supertrend_strength` | IndicatorValues | `_strength_supertrend()` |
| `macd_hist_normalized` | IndicatorValues | `macd_hist / close * 100` |
| `rsi_value` | IndicatorValues | Direct `.rsi` |
| `rsi_strength` | IndicatorValues | `_strength_rsi()` |
| `volume_ratio` | IndicatorValues | `volume / volume_sma` |
| `volume_delta` | IndicatorValues | `.volume_delta_pct` |
| `dmi_strength` | IndicatorValues | `_strength_dmi()` |
| `regime` | MarketRegime | Direct `.regime` |
| `regime_confidence` | MarketRegime | Direct `.confidence` |
| `atr_percentile` | MarketRegime | Direct `.atr_percentile` |
| `ema_spread_trend` | MarketRegime | Direct `.ema_spread_trend` |
| `structure_trend` | StructureState | Direct `.trend` |
| `has_bos` | StructureState | `last_bos is not None` |
| `bos_type` | StructureState | `.last_bos.type` if present |
| `has_sweep` | snapshots | `len(valid_sweeps) > 0` |
| `sweep_strength` | SweepEvent | `.strength` (max of valid sweeps) |
| `has_ob` | snapshots | `len(valid_obs) > 0` |
| `ob_valid` | snapshots | `any(ob.is_valid for ob in valid_obs)` |

### Available from raw_results_r6.json directly:
- `symbol`, `direction`, `entry_price`, `exit_price`, `exit_reason`
- `pnl_pct`, `net_pnl_pct`, `rr`, `sl_source`, `regime`
- `entry_timestamp`, `exit_timestamp`
- `signal_score` (in BacktestTrade but NOT saved → **needs re-extraction**)

### NOT available (require re-run or new data collection):
- ❌ `context_score`, `context_verdict` (live-only context fetcher)
- ❌ `funding_rate`, `funding_class` (live-only)
- ❌ `oi_delta_pct` (live-only)
- ❌ `btc_above_ema200_daily`, `btc_above_ema200_4h` (not computed in backtest)
- ❌ `confidence_v2_score`, `confidence_v2_quality` (not saved)
- ❌ `sl_distance_pct` (can be computed from entry_price + sl, but sl not saved)
- ❌ `theoretical_rr` (can be computed from entry + sl + tp, but not saved)
- ❌ `entry_price` at exact signal moment (snap.i gives candle index, entry_price_base available)
