# Sweep Conditional Analysis

**Dataset:** 1138 trades from `features_combined.parquet`
**Method:** Wilson CI 95% (WR), Bootstrap CI 95% (diffs), 30 sample threshold

---

## Part A: Conditional Analysis

### Level 1: Direction × has_sweep

| Direction | has_sweep | N | WR% | Avg PnL | WR CI 95% | Verdict |
|-----------|-----------|---|-----|---------|-----------|---------|
| SELL | YES | 224 | 38.8% | +0.6419% | [32.7%, 45.4%] | SIGNIFICANT |
| SELL | NO | 316 | 61.7% | +2.3164% | [56.2%, 66.9%] | SIGNIFICANT |
| BUY | YES | 221 | 45.7% | +0.6215% | [39.3%, 52.3%] | SIGNIFICANT |
| BUY | NO | 377 | 45.6% | +0.9228% | [40.7%, 50.7%] | SIGNIFICANT |

**Differences (sweep YES vs NO):**

- **SELL:** ΔWR = -22.9pp, CI = [-0.3pp, -0.1pp]
  ΔPnL = -1.6745%, CI = [-2.2414%, -1.0781%]
- **BUY:** ΔWR = +0.1pp, CI = [-0.1pp, +0.1pp]
  ΔPnL = -0.3013%, CI = [-0.7983%, +0.1835%]

### Level 2: SELL × Regime × has_sweep

| Regime | has_sweep | N | WR% | Avg PnL | WR CI 95% | Verdict |
|--------|-----------|---|-----|---------|-----------|---------|
| compression | YES | 32 | 34.4% | +0.0400% | [20.4%, 51.7%] | SIGNIFICANT |
| compression | NO | 4 | 25.0% | -0.1919% | [4.6%, 69.9%] | LOW SAMPLE |
| expansion | YES | 44 | 40.9% | +0.5916% | [27.7%, 55.6%] | SIGNIFICANT |
| expansion | NO | 147 | 71.4% | +3.0541% | [63.7%, 78.1%] | SIGNIFICANT |
| range | YES | 107 | 40.2% | +0.8604% | [31.4%, 49.7%] | SIGNIFICANT |
| range | NO | 70 | 45.7% | +1.1564% | [34.6%, 57.3%] | SIGNIFICANT |
| trend | YES | 41 | 36.6% | +0.5956% | [23.6%, 51.9%] | SIGNIFICANT |
| trend | NO | 95 | 60.0% | +2.1352% | [49.9%, 69.3%] | SIGNIFICANT |

**Regime differences (sweep YES vs NO, ΔWR):**

- **compression:** ΔWR = +9.4pp, CI = [-0.4pp, +0.5pp]
- **expansion:** ΔWR = -30.5pp, CI = [-0.5pp, -0.1pp]
- **range:** ΔWR = -5.5pp, CI = [-0.2pp, +0.1pp]
- **trend:** ΔWR = -23.4pp, CI = [-0.4pp, -0.1pp]

### Level 3: SELL × ADX Quartile × has_sweep

| ADX Quartile | has_sweep | N | WR% | Avg PnL | WR CI 95% | Verdict |
|-------------|-----------|---|-----|---------|-----------|---------|
| Q1 | YES | 105 | 40.0% | +0.5907% | [31.1%, 49.6%] | SIGNIFICANT |
| Q1 | NO | 30 | 40.0% | +0.6469% | [24.6%, 57.7%] | SIGNIFICANT |
| Q2 | YES | 64 | 31.2% | -0.0344% | [21.2%, 43.4%] | SIGNIFICANT |
| Q2 | NO | 71 | 52.1% | +1.5913% | [40.7%, 63.3%] | SIGNIFICANT |
| Q3 | YES | 30 | 43.3% | +1.1592% | [27.4%, 60.8%] | SIGNIFICANT |
| Q3 | NO | 105 | 61.9% | +2.1733% | [52.4%, 70.6%] | SIGNIFICANT |
| Q4 | YES | 25 | 48.0% | +1.9678% | [30.0%, 66.5%] | LOW SAMPLE |
| Q4 | NO | 110 | 73.6% | +3.3763% | [64.7%, 81.0%] | SIGNIFICANT |

**ADX quartile differences (sweep YES vs NO, ΔWR):**

- **Q1:** ΔWR = +0.0pp, CI = [-0.2pp, +0.2pp]
- **Q2:** ΔWR = -20.9pp, CI = [-0.4pp, -0.0pp]
- **Q3:** ΔWR = -18.6pp, CI = [-0.4pp, +0.0pp]
- **Q4:** ΔWR = -25.6pp, CI = [-0.5pp, -0.0pp]

### Level 4: SELL × Score Verdict × has_sweep

| Score Verdict | has_sweep | N | WR% | Avg PnL | WR CI 95% | Verdict |
|---------------|-----------|---|-----|---------|-----------|---------|
| strong | YES | 1 | 0.0% | -1.2481% | [0.0%, 79.3%] | LOW SAMPLE |
| strong | NO | 0 | 0.0% | +0.0000% | [0.0%, 100.0%] | NO DATA |
| moderate | YES | 191 | 39.3% | +0.5520% | [32.6%, 46.3%] | SIGNIFICANT |
| moderate | NO | 304 | 61.8% | +2.3338% | [56.3%, 67.1%] | SIGNIFICANT |
| weak | YES | 32 | 37.5% | +1.2375% | [22.9%, 54.7%] | SIGNIFICANT |
| weak | NO | 12 | 58.3% | +1.8767% | [32.0%, 80.7%] | LOW SAMPLE |

**Score verdict differences (sweep YES vs NO, ΔWR):**

- **strong:** insufficient data (N=1+0)
- **moderate:** ΔWR = -22.6pp, CI = [-0.3pp, -0.1pp]
- **weak:** ΔWR = -20.8pp, CI = [-0.5pp, +0.1pp]

---

## Part B: Permutation Random Forest Importance

Rows for RF (after dropna): 1138 / 1138

### RF №1: All Trades (Permutation Importance)

RF Accuracy: 68.8%

| Rank | Feature | Permutation Importance |
|------|---------|----------------------|
| 1 | rsi_value | 0.0364 ########## |
| 2 | ema_strength | 0.0289 ######## |
| 3 | adx_value | 0.0272 ######## |
| 4 | macd_hist_normalized | 0.0242 ####### |
| 5 | volume_ratio | 0.0161 #### |
| 6 | has_sweep | 0.0130 ### |
| 7 | regime_confidence | 0.0122 ### |
| 8 | has_bos | 0.0100 ## |
| 9 | signal_score | 0.0088 ## |
| 10 | regime_range | 0.0042 # |
| 11 | regime_trend | 0.0032 # |
| 12 | has_ob | 0.0001 # |
| 13 | regime_compression | -0.0007 # |
| 14 | regime_expansion | -0.0009 # |

### RF №2: SELL Trades Only (Permutation Importance)

SELL trades: 540 | RF Accuracy: 68.7%

| Rank | Feature | Permutation Importance |
|------|---------|----------------------|
| 1 | adx_value | 0.0274 ######## |
| 2 | regime_confidence | 0.0149 #### |
| 3 | macd_hist_normalized | 0.0132 ### |
| 4 | signal_score | 0.0105 ### |
| 5 | ema_strength | 0.0093 ## |
| 6 | rsi_value | 0.0078 ## |
| 7 | regime_expansion | 0.0052 # |
| 8 | volume_ratio | 0.0048 # |
| 9 | has_sweep | 0.0012 # **<-- has_sweep** |
| 10 | regime_trend | 0.0011 # |
| 11 | regime_range | 0.0007 # |
| 12 | regime_compression | 0.0001 # |
| 13 | has_bos | -0.0004 # |
| 14 | has_ob | -0.0019 # |

**has_sweep rank in SELL model:** #9 (importance: 0.0012)
**Top-5 check:** NO — sweep is not top-5, effect likely explained by other factors

---

## Part C: Logistic Regression — Independent Effect of has_sweep

Model accuracy: 58.3% | N = 1138 | Features = 9

| Feature | Coef | Odds Ratio | 95% CI (OR) | p-value | Sig |
|---------|------|-----------|-------------|---------|-----|
| has_sweep_int | -0.1249 | 0.8826 | [0.7775, 1.0019] | 0.0536 | NO **<-- TARGET** |
| adx_value | +0.1779 | 1.1947 | [1.0510, 1.3580] | 0.0065 | YES |
| signal_score | +0.3153 | 1.3707 | [1.1703, 1.6055] | 0.0001 | YES |
| has_bos | +0.0929 | 1.0973 | [0.9540, 1.2621] | 0.1932 | NO |
| has_ob | +0.0885 | 1.0926 | [0.9682, 1.2330] | 0.1510 | NO |
| volume_ratio | -0.0537 | 0.9477 | [0.8272, 1.0858] | 0.4389 | NO |
| rsi_value | +0.1346 | 1.1441 | [0.7309, 1.7909] | 0.5561 | NO |
| macd_hist_normalized | -0.0182 | 0.9820 | [0.7973, 1.2095] | 0.8644 | NO |
| ema_strength | -0.4120 | 0.6623 | [0.4472, 0.9809] | 0.0397 | YES |

### Interpretation

- **has_sweep Odds Ratio:** 0.8826 (95% CI: [0.7775, 1.0019])
- **p-value:** 0.0536
- **Statistically significant:** NO
- Sweep REDUCES odds of winning by 11.7% (after controlling for ADX, regime, score, BOS, OB)

---

## Part D: Verdict Table

| # | Гипотеза | Статус | Основание |
|---|----------|--------|-----------|
| 1 | Sweep ухудшает SELL | **CONFIRMED** | ΔWR=-22.9pp, bootstrap CI not crossing 0, logistic p=0.0536 |
| 2 | Sweep влияет независимо от ADX/regime/score | **NO** | Logistic OR=0.883, p=0.0536, sig=NO |
| 3 | Sweep зависит от режима | **YES** | ΔWR range across regimes: 25.0pp |
| 4 | Sweep зависит от Score | **NO** | ΔWR range across scores: 1.7pp |
| 5 | Sweep в Top-5 RF факторов (SELL) | **NO** | RF permutation rank: #9 |

### Key evidence

- SELL overall: sweep WR=38.8% vs no_sweep WR=61.7% (Δ=-22.9pp)
- Logistic: OR=0.883, p=0.0536 → marker of bad conditions, not independent
- RF rank of has_sweep in SELL: #9
- Regime variation: 25.0pp range → sweep effect varies by regime