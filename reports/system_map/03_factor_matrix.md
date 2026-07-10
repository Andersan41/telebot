# 03 — Factor Reuse & Double Counting Matrix

## Factor × Module Usage Matrix

| Factor | Signal Engine | Context Scorer | Conf V2 | Dynamic Risk | Scanner Gates | MTF | BTC Gate |
|--------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| EMA (8/21/55) | ✔ alignment + spread + slope | — | — | — | ✔ confirm_tf | — | — |
| RSI | ✔ strength + reasons | — | ✔ `score_rsi()` | — | — | — | — |
| MACD | ✔ strength + trigger | — | ✔ `score_macd()` | — | — | — | — |
| ADX | ✔ flat filter + strength | — | ✔ `score_adx()` | — | — | — | — |
| DMI | ✔ strength | — | (in `score_adx()`) | — | — | — | — |
| Supertrend | ✔ alignment gate + strength | — | — | — | — | — | — |
| Volume | ✔ above_avg + delta trigger + strength | — | ✔ `score_volume()` | — | — | — | — |
| ATR | — | — | — | ✔ volatility_mult | ✔ volatility gate | — | — |
| BOS | ✔ leading trigger | — | ✔ `score_structure()` | — | — | — | — |
| Sweep | ✔ leading trigger | — | ✔ `score_liquidity()` | ✔ structural SL | — | — | — |
| Order Block | ✔ trigger confirm | — | ✔ `score_liquidity()` | ✔ structural SL/TP | — | — | — |
| FVG | — | — | ✔ `score_liquidity()` | ✔ structural TP | — | — | — |
| Structure Trend | ✔ `._structure_trend` | — | ✔ `score_structure()` | — | ✔ no_trade_zones | — | — |
| MTF Alignment | ✔ momentum entry | — | ✔ `score_htf_trend()` | — | ✔ mtf gate | ✔ | — |
| BTC 4h EMA200 | — | — | ✔ `score_btc_correlation()` | ✔ btc_aligned | ✔ btc_correlation gate | — | ✔ |
| BTC Daily EMA200 | — | — | — | — | ✔ btc_global_trend | — | — |
| BTC Structure | — | — | (in btc_corr) | — | ✔ btc_correlation gate | — | ✔ |
| ETH Structure | — | — | — | ✔ eth_aligned | ✔ eth_correlation gate | — | — |
| Funding | — | ✔ `_score_funding_rate()` | ✔ `score_funding_from_state()` | — | ✔ no_trade_zones | — | — |
| OI | — | ✔ `_score_oi()` | ✔ `score_oi_from_state()` | — | ✔ no_trade_zones | — | — |
| Fear & Greed | — | ✔ `_score_fear_greed()` | — | — | — | — | — |
| L/S Ratio | — | ✔ (display only) | — | — | — | — | — |
| News | — | ✔ `_score_news()` | — | — | ✔ news_filter | — | — |
| Price Trend (7d) | — | ✔ `_score_price_trend()` | — | — | — | — | — |

## Double Counting Analysis

### Factors Used 3+ Times

| Factor | Count | Where | Issue |
|--------|-------|-------|-------|
| **BTC EMA200** | 3 | Signal Engine (via corr context), BTC Correlation Gate, BTC Global Trend Gate | Triple-gated: two gates (global daily + correlation 4h) + confidence scoring |
| **ADX** | 3 | Signal Engine (flat filter + strength), Confidence V2 (`score_adx()`), Dynamic Risk (indirectly via score_verdict) | Flat filter blocks, then strength scores, then conf V2 re-scores |
| **Funding** | 3 | Context Scorer (`_score_funding_rate()`), Confidence V2 (`score_funding_from_state()`), No-Trade Zones | Scorer provides verdict gate, conf V2 provides display score, no-trade checks neutral state |
| **Volume** | 3 | Signal Engine (trigger + strength), Confidence V2 (`score_volume()`), Volume SMA filter | Trigger uses delta, strength uses ratio+delta, conf V2 uses ratio |
| **Structure/BOS** | 3 | Signal Engine (leading trigger), Confidence V2 (`score_structure()`), No-Trade Zones (range detection) | Trigger gates signal, conf V2 scores alignment, no-trade blocks ranging |

### Factors Used 2 Times

| Factor | Count | Where |
|--------|-------|-------|
| EMA | 2 | Signal Engine (alignment + spread gates), Confirmation TF |
| RSI | 2 | Signal Engine (strength), Confidence V2 (`score_rsi()`) |
| MACD | 2 | Signal Engine (strength + trigger), Confidence V2 (`score_macd()`) |
| Supertrend | 2 | Signal Engine (gate + strength), Signal Engine (momentum entry) |
| Sweep | 2 | Signal Engine (trigger), Confidence V2 (`score_liquidity()`) |
| Order Block | 2 | Signal Engine (trigger confirm), Confidence V2 (`score_liquidity()`) |
| MTF | 2 | Scanner (gate), Confidence V2 (`score_htf_trend()`) |
| OI | 2 | Context Scorer, Confidence V2 |
| ETH | 2 | ETH Correlation Gate, Dynamic Risk (eth_aligned) |

### Architecture Note on Double Counting

The system has **three distinct scoring layers**:
1. **Signal Engine Score** (0-7): count of supporting reasons → determines `score_verdict` (strong/moderate/weak) → **controls sizing and dynamic risk gate**
2. **Context Score** (-1.0 to 1.0): weighted sum from 6 factors → determines verdict (CONFIRMED/WEAK/CONFLICTED/BLOCKED) → **controls context gates**
3. **Confidence V2** (-100 to 100): 10-factor weighted → determines quality (strong/moderate/weak) → **display only, does NOT gate**

**Critical**: Signal Engine score_verdict and Confidence V2 quality can DISAGREE. A signal can be "moderate" by score (passes dynamic risk) but "weak" by confidence (displayed as weak). This is by design — score_verdict = technical gate, confidence = blended quality assessment.
