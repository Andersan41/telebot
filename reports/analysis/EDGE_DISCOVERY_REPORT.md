# EDGE DISCOVERY REPORT

## Executive Summary

- **Total trades (full_new, min_score=2):** 306
- **Overall WR:** 52.3%
- **Overall PF:** 2.52
- **Overall Expectancy:** +1.0471%

## 1. Where is the main edge?

The primary edge is in **Score=5** trades:
- 107 trades, WR 68.2%, PF 5.06, Expectancy +1.9674%

Best regime: **expansion** — 107 trades, WR 61.7%, PF 3.68, Expectancy +1.5384%

Best combination: **Score=6, Regime=trend, SL=structural**
- 1 trades, WR 100.0%, PF 3.41, Expectancy +3.4055%

## 2. What is the optimal min_score?

| Config | Trades | WR | PF | Expectancy |
| --- | --- | --- | --- | --- |
| min_score=2 | 306 | 52.3% | 2.52 | +1.0471 |
| min_score=3 | 300 | 52.0% | 2.47 | +1.0246 |
| min_score=4 | 265 | 52.8% | 2.66 | +1.1183 |
| min_score=5 | 147 | 60.5% | 3.73 | +1.5459 |

## 3. Should min_score be raised to 5?

Score=5: 147 trades, WR 60.5%, PF 3.73, Expectancy +1.5459%
Score=4: 265 trades, WR 52.8%, PF 2.66, Expectancy +1.1183%
Delta: -118 trades, WR +7.7%, PF +1.07

## 4. Should compression be disabled?

| Config | Trades | WR | PF | Expectancy | MaxDD |
| --- | --- | --- | --- | --- | --- |
| compression=ON | 306 | 52.3% | 2.52 | +1.0471% | 8.59% |
| compression=OFF | 369 | 49.6% | 2.27 | +0.8798% | 13.05% |

Compression regime trades: 15 (WR 60.0%)

## 5. Best Score x Regime combination

| Regime | Score | Trades | WR | PF | Expectancy |
| --- | --- | --- | --- | --- | --- |
| expansion | 6 | 1 | 100.0% | 2.77 | +2.7677 |
| expansion | 5 | 51 | 70.6% | 5.94 | +2.2472 |
| expansion | 2 | 3 | 66.7% | 7.17 | +2.0561 |
| compression | 4 | 1 | 100.0% | 2.05 | +2.0473 |
| trend | 5 | 34 | 67.6% | 4.71 | +2.0149 |

## 6. What influences the result most?

### By Score

| Score | Trades | WR | PF | Expectancy |
| --- | --- | --- | --- | --- |
| 2 | 10 | 40.0% | 2.21 | +0.8173 |
| 3 | 59 | 49.2% | 1.94 | +0.7098 |
| 4 | 120 | 42.5% | 1.61 | +0.5014 |
| 5 | 107 | 68.2% | 5.06 | +1.9674 |
| 6 | 9 | 33.3% | 1.08 | +0.0752 |
| 7 | 1 | 0.0% | 0.0 | -1.0000 |

### By Regime

| Regime | Trades | WR | PF | Expectancy |
| --- | --- | --- | --- | --- |
| compression | 15 | 60.0% | 2.49 | +0.6734 |
| expansion | 107 | 61.7% | 3.68 | +1.5384 |
| range | 118 | 44.1% | 1.79 | +0.6156 |
| trend | 66 | 50.0% | 2.44 | +1.1068 |

### By SL Source

| SL Source | Trades | WR | PF | Expectancy |
| --- | --- | --- | --- | --- |
| atr | 230 | 53.0% | 2.44 | +1.0263 |
| bos | 34 | 47.1% | 1.9 | +0.6304 |
| structural | 42 | 52.4% | 3.75 | +1.4980 |

### Impact ranking (expectancy spread)

1. **Regime:** spread = +0.9228%
2. **Score:** spread = +2.9674%
3. **SL Source:** spread = +0.8676%

## 7. What should NOT be changed

- Keep the `full_new` preset pipeline flags as-is
- Keep the scoring system (7 factors, count-based)
- Keep the cooldown at 45 min
- Keep the ATR-based regime detection thresholds
- Do NOT add new indicators or filters at this stage