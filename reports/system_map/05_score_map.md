# 05 — Complete Score Map

## Score System 1: Signal Engine Score (strategy/signal_engine.py)

**Purpose**: Determine signal quality for sizing and dynamic risk gate.
**Range**: 0 to 7 (count of supporting reasons)
**Thresholds**: strong ≥ 6, moderate ≥ 4, weak ≥ 2 (signal required)

### Factor Strengths (internal, -1.0 to 1.0)

| Factor | Function | Calculation | Weight |
|--------|----------|-------------|--------|
| Supertrend | `_strength_supertrend()` | ±ADX_factor where ADX_factor = clamp((adx-20)/30, 0.3, 1.0) | 5 |
| EMA | `_strength_ema()` | ±min(1.0, spread%/1.0) | 10 |
| MACD | `_strength_macd()` | ±clamp((hist/close×100)×10, -1, 1), filtered by MIN_MACD_PCT=0.03% | 10 |
| RSI | `_strength_rsi()` | BUY: ≤28→1.0, <55→0.5, <72→0.0, ≥72→-1.0 | 5 |
| Volume | `_strength_volume()` | min(1.0, 0.3+0.4×(ratio-1)+0.3×delta_factor), below avg→-0.3 | 15 |
| ADX | `_strength_adx()` | (adx-20)/30, clamp -1..1 | 5 |
| DMI | `_strength_dmi()` | ±(dmi+-dmi-)/50×2, clamp -1..1 | 5 |

**Weighted Score** = Σ(strength × weight) / Σ(weights)
**Max Signal Score** = 115 (sum of all weights)

### Score Verdict

| Score | Verdict | Risk % | Should Trade |
|-------|---------|--------|-------------|
| ≥ 6 | strong | 1.0% | Yes |
| ≥ 4 | moderate | 0.5% | Yes |
| ≥ 2 | weak | 0.25% | No (RISK_WEAK_TRADE=false) |
| < 2 | weak | 0.25% | No |

## Score System 2: Context Score (context/scorer.py)

**Purpose**: Determine market context alignment with signal direction.
**Range**: -1.0 to 1.0
**Verdict Thresholds**: CONFIRMED ≥ 0.40, WEAK ≥ 0.05, CONFLICTED ≥ -0.10, BLOCKED < -0.10

### Factor Weights

| Factor | Weight | BUY Logic | SELL Logic |
|--------|--------|-----------|------------|
| Fear & Greed | 0.15 | <20→+0.8, <40→+0.1, <60→0, <80→-0.3, ≥80→-0.8 | Inverted |
| Funding Rate | 0.25 | Strong neg→+0.9, mod neg→+0.4, neutral→+0.1, mod pos→-0.4, strong pos→-0.9 | Inverted |
| Long/Short | 0.20 | <0.7→+0.7, 0.7-1.2→0, >1.2→-0.6 | Inverted |
| Open Interest | 0.15 | +delta→+0.5/+0.3/+0.2, -delta→-0.1/-0.2/-0.3 | Inverted |
| News | 0.05 | raw score forwarded | raw score forwarded |
| Price Trend 7d | 0.10 | >5%→+0.5, >0→+0.3, >-5%→0, <-5%→-0.5 | Inverted |

**Normalization**: final_score = weighted_sum / total_weight (only counts available factors)

## Score System 3: Confidence V2 (scoring/confidence_v2.py)

**Purpose**: 10-factor weighted quality assessment for display.
**Range**: -100 to 100 (abs = confidence_pct)
**Quality Thresholds**: strong ≥ 65, moderate ≥ 30, weak < 30

### Factor Weights

| Factor | Weight | Scoring Function | Range |
|--------|--------|-----------------|-------|
| HTF Trend | 20 | `score_htf_trend()`: aligned→0.8+0.2×min(cnt-req,1), not→-0.5 | -0.5 to 1.0 |
| Structure | 15 | `score_structure()`: trend+bos aligned→1.0, opposing→-0.8 | -0.8 to 1.0 |
| Liquidity | 20 | `score_liquidity()`: sweeps±0.3, OB±0.2, FVG±0.15 | -1.0 to 1.0 |
| Volume | 5 | `score_volume()`: above avg→0.3+0.5×(ratio-1), below→-0.15 | -0.15 to 0.8 |
| BTC Correlation | 15 | `score_btc_correlation()`: allows+strong→0.8, allows→0.4, blocks→-0.3 | -0.3 to 0.8 |
| Funding | 5 | `score_funding_from_state()`: strong aligned→0.8, opposed→-0.8 | -0.8 to 0.8 |
| OI | 5 | `score_oi_from_state()`: strong aligned→0.8, opposed→-0.8 | -0.8 to 0.8 |
| RSI | 5 | `score_rsi()`: oversold/overbought bounce→0.6, neutral→0, opposing→-0.8 | -0.8 to 0.6 |
| MACD | 5 | `score_macd()`: ±(hist/price×100)×10, noise filtered | -1.0 to 1.0 |
| ADX | 5 | `score_adx()`: strength×DMI_dir×2, soft threshold | -0.5 to ~1.0 |

**Historical Blend**: confidence = historical_wr × 0.4 + score_confidence × 0.6 (when available)

## Score System 4: Context Verdict Rank

```
BLOCKED (0) < CONFLICTED (1) < WEAK (2) < CONFIRMED (3)
```

CONTEXT_MIN_VERDICT default = "WEAK" (rank 2). Verdict must be ≥ WEAK to pass.

## Score System 5: Dynamic Risk Score

**Purpose**: Position sizing based on setup quality.
**Input**: score_verdict (from Signal Engine) + volatility_regime + btc/eth alignment

```
effective_risk = base_risk × vol_mult × corr_mult

base_risk: strong=1.0%, moderate=0.5%, weak=0.25%
vol_mult: high=0.5, medium/low=1.0
corr_mult: btc/eth misaligned=0.5, aligned=1.0
```
