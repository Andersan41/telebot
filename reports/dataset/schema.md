# Dataset Schema — Feature Dataset for Factor Importance

**Version:** 1.0  
**Date:** 2026-06-27

## Column Definitions

### IDENTIFIERS
| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `signal_id` | str | computed | `{symbol}_{entry_timestamp_hash8}` |
| `symbol` | str | raw_results | Trading pair |
| `timeframe` | str | raw_results | Always "1h" for current data |
| `direction` | str | raw_results | "BUY" / "SELL" |
| `created_at` | str | raw_results | Entry timestamp (ISO) |
| `source` | str | hardcoded | "backtest" (all current data) |

### TARGET (Outcome)
| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `result` | str | raw_results | "TP" / "SL" / "EOB" |
| `pnl_pct` | float | raw_results | Gross PnL % |
| `net_pnl_pct` | float | raw_results | Net PnL % |
| `win` | bool | computed | `pnl_pct > 0` |
| `hours_in_trade` | float | computed | exit_time - entry_time |

### SIGNAL ENGINE FACTORS (from snapshot → recomputed)
| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `ema_strength` | float | recomputed | [-1.0, 1.0] via `_strength_ema()` |
| `ema_spread_pct` | float | recomputed | EMA spread as % of slow EMA |
| `ema_slope_ok` | bool | recomputed | Spread widening (5% tolerance) |
| `adx_value` | float | snapshot | Raw ADX value |
| `adx_strength` | float | recomputed | [0.0, 1.0] via `_strength_adx()` |
| `supertrend_strength` | float | recomputed | [-1.0, 1.0] via `_strength_supertrend()` |
| `macd_hist_normalized` | float | computed | `macd_hist / close * 100` |
| `rsi_value` | float | snapshot | Raw RSI value |
| `rsi_strength` | float | recomputed | [-1.0, 1.0] via `_strength_rsi()` |
| `volume_ratio` | float | computed | `volume / volume_sma` |
| `volume_delta` | float | snapshot | `volume_delta_pct` (may be None) |
| `dmi_strength` | float | recomputed | [-1.0, 1.0] via `_strength_dmi()` |

### STRUCTURE & LIQUIDITY FACTORS (from snapshot)
| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `has_bos` | bool | snapshot | BOS present in structure |
| `bos_type` | str | snapshot | "bullish" / "bearish" / None |
| `has_sweep` | bool | snapshot | Valid sweep present |
| `sweep_strength` | float | snapshot | Max sweep strength [0.0, 1.0] |
| `has_ob` | bool | snapshot | Order block present |
| `ob_valid` | bool | snapshot | At least one valid OB |
| `structure_trend` | str | snapshot | "bullish" / "bearish" / "ranging" |
| `structure_breaks` | int | snapshot | Number of structure breaks |

### MARKET CONTEXT (from snapshot → MarketRegime)
| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `regime` | str | snapshot | "trend" / "range" / "compression" / "expansion" |
| `regime_confidence` | float | snapshot | [0.0, 1.0] |
| `atr_percentile` | float | snapshot | ATR percentile rank |
| `ema_spread_trend` | str | snapshot | "rising" / "falling" / "stable" |

### SIGNAL QUALITY (from raw_results)
| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `signal_score` | int | computed | Count of factors with strength > 0 (0-7) |
| `score_verdict` | str | computed | "strong" (>=6) / "moderate" (>=4) / "weak" (<4) |

### TRADE MECHANICS (from raw_results)
| Column | Type | Source | Description |
|--------|------|--------|-------------|
| `sl_source` | str | raw_results | "atr" / "bos" / "structural" |
| `entry_price` | float | raw_results | Entry price |
| `exit_price` | float | raw_results | Exit price |
| `rr` | float | raw_results | Actual R/R at exit |

### NOT AVAILABLE (NaN for all rows)
- `btc_above_ema200_daily`, `btc_above_ema200_4h` — not computed in backtest
- `funding_rate`, `funding_class` — live-only context fetcher
- `oi_delta_pct` — live-only context fetcher
- `context_score`, `context_verdict` — live-only context fetcher
- `confidence_v2_score`, `confidence_v2_quality` — not saved
- `sl_distance_pct` — sl not saved in raw_results
- `theoretical_rr` — sl/tp not saved in raw_results
