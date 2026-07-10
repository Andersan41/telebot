# Scenario Expectancy Report

Generated: 2026-07-08 20:49 UTC

Trades analyzed: 41

## Overall Performance

| Metric | Value |
|--------|-------|
| Total trades | 41 |
| Win rate | 4.9% |
| Profit factor | 0.24 |
| Expectancy (R) | -0.726 |
| Avg win (R) | +4.615 |
| Avg loss (R) | -1.000 |
| Avg PnL % | -2.006% |

## MAE/MFE Analysis — Entry vs Exit Quality

**Diagnosis: MIXED: both entry and exit contribute to losses**

| Metric | Winners | Losers |
|--------|---------|--------|
| Count | 2 | 39 |
| Avg MFE (R) | +8.021 | -0.044 |
| Avg MAE (R) | -3.566 | +0.414 |
| Avg PnL % | +5.749% | -2.403% |
| Avg hold bars | 22.0 | 5.4 |

### Loser Excursion Thresholds

| Threshold | % of losers reaching |
|-----------|---------------------|
| +0.5R | 5.1% |
| +1.0R | 0.0% |
| +1.5R | 0.0% |
| +2.0R | 0.0% |

## Time-To-Failure Analysis

**Diagnosis: PREMATURE_ENTRIES: >40% of losses occur within 2 bars — entries against immediate momentum**

- Average bars to SL: **5.4**
- Average bars to TP: **22.0**

### Holding Period Distribution (Losers)

| Bars | Count | % |
|------|-------|---|
| 0-1 | 0 | 0.0% |
| 1-2 | 12 | 30.8% |
| 2-3 | 6 | 15.4% |
| 3-5 | 6 | 15.4% |
| 5-10 | 8 | 20.5% |
| 10-20 | 6 | 15.4% |
| 20-50 | 1 | 2.6% |
| 50+ | 0 | 0.0% |

### Early Failure Rates

- within 1 bars: **12** trades (30.8%)
- within 2 bars: **18** trades (46.2%)
- within 3 bars: **21** trades (53.8%)

## Directional Analysis

**Diagnosis: SELL_BIAS: SELL trades significantly outperform BUY trades**

| Metric | BUY | SELL | Delta |
|--------|-----|------|-------|
| Trades | 40 | 1 | +39 |
| Win rate | 2.5% | 100.0% | -97.5% |
| PF | 0.19 | 999.99 | -999.80 |
| Expectancy (R) | -0.794 | +2.000 | -2.794 |
| Avg PnL % | -2.203% | +5.888% | -8.091% |
| Avg hold bars | 5.8 | 23.0 | |
| Avg MFE (R) | +0.296 | +2.472 | |
| Avg MAE (R) | +0.267 | -1.672 | |

## Scenario Type Ranking

| Scenario Type | Trades | WR | PF | Expectancy | Avg RR |
|---------------|--------|----|----|------------|--------|
| unknown | 41 | 4.9% | 0.24 | -0.726 | 4.61 |

## Feature Expectancy Analysis

### Adx

| Bin | Trades | WR | PF | Expectancy | Avg Win | Avg Loss |
|-----|--------|----|----|------------|---------|----------|
| adx_<18 | 7 | 0.0% | 0.0 | -1.000 | +0.000 | -1.000 |
| adx_18-25 | 10 | 10.0% | 0.22 | -0.700 | +2.000 | -1.000 |
| adx_25-30 | 8 | 12.5% | 1.03 | +0.029 | +7.229 | -1.000 |
| adx_>=30 | 16 | 0.0% | 0.0 | -1.000 | +0.000 | -1.000 |

### Bos Age

| Bin | Trades | WR | PF | Expectancy | Avg Win | Avg Loss |
|-----|--------|----|----|------------|---------|----------|

### Ob Distance

| Bin | Trades | WR | PF | Expectancy | Avg Win | Avg Loss |
|-----|--------|----|----|------------|---------|----------|
| ob_dist_<1atr | 36 | 5.6% | 0.27 | -0.688 | +4.615 | -1.000 |
| ob_dist_>2atr | 4 | 0.0% | 0.0 | -1.000 | +0.000 | -1.000 |

### Rr Ratio

| Bin | Trades | WR | PF | Expectancy | Avg Win | Avg Loss |
|-----|--------|----|----|------------|---------|----------|
| rr_1.5-2 | 10 | 0.0% | 0.0 | -1.000 | +0.000 | -1.000 |
| rr_2-3 | 15 | 6.7% | 0.14 | -0.800 | +2.000 | -1.000 |
| rr_>=3 | 16 | 6.2% | 0.48 | -0.486 | +7.229 | -1.000 |

### Regime

| Bin | Trades | WR | PF | Expectancy | Avg Win | Avg Loss |
|-----|--------|----|----|------------|---------|----------|
| expansion | 3 | 0.0% | 0.0 | -1.000 | +0.000 | -1.000 |
| range | 38 | 5.3% | 0.26 | -0.704 | +4.615 | -1.000 |

### Direction

| Bin | Trades | WR | PF | Expectancy | Avg Win | Avg Loss |
|-----|--------|----|----|------------|---------|----------|
| BUY | 40 | 2.5% | 0.19 | -0.794 | +7.229 | -1.000 |

### Structure Alignment

| Bin | Trades | WR | PF | Expectancy | Avg Win | Avg Loss |
|-----|--------|----|----|------------|---------|----------|
| counter_trend | 41 | 4.9% | 0.24 | -0.726 | +4.615 | -1.000 |

### Sweep

| Bin | Trades | WR | PF | Expectancy | Avg Win | Avg Loss |
|-----|--------|----|----|------------|---------|----------|
| sweep_present | 17 | 11.8% | 0.62 | -0.339 | +4.615 | -1.000 |
| no_sweep | 24 | 0.0% | 0.0 | -1.000 | +0.000 | -1.000 |

### Ob Present

| Bin | Trades | WR | PF | Expectancy | Avg Win | Avg Loss |
|-----|--------|----|----|------------|---------|----------|
| ob_present | 5 | 0.0% | 0.0 | -1.000 | +0.000 | -1.000 |
| no_ob | 36 | 5.6% | 0.27 | -0.688 | +4.615 | -1.000 |

### Fvg

| Bin | Trades | WR | PF | Expectancy | Avg Win | Avg Loss |
|-----|--------|----|----|------------|---------|----------|
| no_fvg | 41 | 4.9% | 0.24 | -0.726 | +4.615 | -1.000 |

### Scenario Confidence

| Bin | Trades | WR | PF | Expectancy | Avg Win | Avg Loss |
|-----|--------|----|----|------------|---------|----------|
| conf_<0.3 | 41 | 4.9% | 0.24 | -0.726 | +4.615 | -1.000 |

### Scenario Score

| Bin | Trades | WR | PF | Expectancy | Avg Win | Avg Loss |
|-----|--------|----|----|------------|---------|----------|
| score_<30 | 41 | 4.9% | 0.24 | -0.726 | +4.615 | -1.000 |

## Scenario Freshness Analysis

**Estimated half-life: None bars**

**Diagnosis: Insufficient data to estimate half-life**

### Bos Age

| Bin | Trades | WR | PF | Expectancy |
|-----|--------|----|----|------------|

### Stability

| Bin | Trades | WR | PF | Expectancy |
|-----|--------|----|----|------------|
| stability_<0.3 | 41 | 4.9% | 0.24 | -0.726 |

### Decay

| Bin | Trades | WR | PF | Expectancy |
|-----|--------|----|----|------------|
| decay_<0.3 | 41 | 4.9% | 0.24 | -0.726 |
