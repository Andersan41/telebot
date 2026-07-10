# 09 — Dead Code & Unused Parameters Analysis

## Parameters That Exist But Don't Affect Decisions

### 1. Signal Engine Weight Constants (NOT USED as multipliers)

The config defines `w_bos=15`, `w_sweep=10`, `w_ob=10`, `w_btc=10`, `w_funding=5`, `w_oi=10` in `ScoringConfig`, but these are **NOT used in Signal Engine's weighted score calculation**. Signal Engine only uses:
- `w_supertrend`, `w_ema`, `w_macd`, `w_rsi`, `w_volume`, `w_adx`, `w_dmi`

The BOS/Sweep/OB/BTC/Funding/OI weights exist in config but are **only referenced by `max_signal_score` property** (which is never called in the live pipeline).

**Impact**: These weights are dead configuration. The `max_signal_score` property returns 115 but nothing uses it to gate or normalize.

### 2. Confidence V2 `confidence_strong_threshold` / `confidence_moderate_threshold`

These config values (`CONFIDENCE_STRONG_THRESHOLD=65`, `CONFIDENCE_MODERATE_THRESHOLD=40`) exist in `ScoringConfig` but are **never read**. The actual thresholds used are `quality_strong_threshold` and `quality_moderate_threshold`.

**Impact**: Confusing. Two sets of thresholds exist; only one pair is used.

### 3. `tech_confidence_blend` and `market_confidence_blend`

These config values (`TECH_CONFIDENCE_BLEND=0.6`, `MARKET_CONFIDENCE_BLEND=0.4`) are defined but **only used in the fallback path** of `SignalResult.confidence` property (when `_confidence_v2` is None). In production, `_confidence_v2` is always set, so these are dead.

**Impact**: Dead code in production path.

### 4. `SIGNAL_BLOCK_NOTIFY` config

The `signal_block_notify` config flag exists but is **never checked** before calling `_notify_blocked()`. Notifications for blocked signals are always sent (when `blocked_callback` is provided).

**Impact**: Config flag has no effect.

### 5. `coingecko_symbol_map` entries for non-CoinGecko symbols

The map only covers BTC/USDT and ETH/USDT. For all other symbols, `_fetch_coingecko()` returns early (no coin_id). CoinGecko data is only available for BTC and ETH.

**Impact**: Context enrichment for alts misses CoinGecko data (price_change_24h, 7d, market_cap_rank, trending).

### 6. `_score_price_trend()` in Context Scorer

The function uses `snapshot.price_change_7d` which comes from CoinGecko. Since CoinGecko only works for BTC/ETH, this factor is effectively dead for all alt signals.

**Impact**: 10% weight in context scorer is wasted for alts.

### 7. `NEWS_FILTER_ENABLED=false` by default

The news filter gate exists but is disabled by default. The entire `risk/news_filter.py` module is inactive unless explicitly enabled.

**Impact**: No impact unless enabled. Dead by default.

### 8. `TP_PATH_ENABLED=false` by default

The TP path quality gate exists but is disabled by default. The entire `market_structure/tp_path.py` evaluation is inactive unless explicitly enabled.

**Impact**: No impact unless enabled. Dead by default.

### 9. `EMA_SLOPE_CHECK=true` but `MACD_SLOPE_CHECK=false`

EMA slope check is enabled but MACD slope check is disabled. In `_strength_macd()`, the MACD slope check is gated by `config.trading.macd_slope_check` which defaults to false. The code path exists but never executes.

**Impact**: MACD slope filter is dead code.

### 10. `OB_RETEST_REQUIRED=false` by default

Order Block retest validation is disabled. OBs are accepted without retest confirmation.

**Impact**: OBs may trigger on false breakouts.

## Functions That Exist But Are Never Called in Live Pipeline

| Function | File | Purpose | Status |
|----------|------|---------|--------|
| `get_volatility_config()` | volatility_regime.py:64 | Returns thresholds for logging | Never called |
| `refresh_runtime_symbols()` | settings.py:792 | Reloads symbols from DB | Called only from admin commands |
| `_get_base_currency()` | analyzer.py:162 | Extracts base from symbol | Used for trending check |
| `FundingState.contributes_to()` | funding.py:17 | Score contribution | Used in scanner display |
| `OIState.contributes_to()` | open_interest.py:17 | Score contribution | Used in scanner display |

## Configuration Dead Ends

| Config | Defined At | Read By | Actually Used? |
|--------|-----------|---------|----------------|
| `W_BOS` | settings.py:414 | `max_signal_score` property | No (property unused) |
| `W_SWEEP` | settings.py:415 | `max_signal_score` property | No |
| `W_OB` | settings.py:416 | `max_signal_score` property | No |
| `W_BTC` | settings.py:418 | `max_signal_score` property | No |
| `W_FUNDING` | settings.py:419 | `max_signal_score` property | No |
| `W_OI` | settings.py:420 | `max_signal_score` property | No |
| `CONFIDENCE_STRONG_THRESHOLD` | settings.py:393 | Nowhere | No |
| `CONFIDENCE_MODERATE_THRESHOLD` | settings.py:395 | Nowhere | No |
| `TECH_CONFIDENCE_BLEND` | settings.py:436 | SignalResult.confidence (fallback only) | No in production |
| `MARKET_CONFIDENCE_BLEND` | settings.py:438 | SignalResult.confidence (fallback only) | No in production |
| `SIGNAL_BLOCK_NOTIFY` | settings.py:562 | Nowhere | No |
