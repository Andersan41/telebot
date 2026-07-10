# Factor Importance Analysis

**Dataset:** 1138 rows x 74 columns
**Win rate:** 48.8%

## Correlation with Win

| Factor | Correlation | Significance |
|--------|------------|---------------|
| rsi_strength | -0.1934 | *** |
| sweep_strength | -0.1133 | *** |
| has_sweep | -0.1046 | *** |
| ema_strength | -0.0797 | * |
| rsi_value | -0.0711 | * |
| supertrend_bullish | -0.0680 | * |
| ema_bullish_alignment | -0.0656 | * |
| macd_hist_normalized | -0.0590 | * |
| has_bos | -0.0489 |  |
| ema_bearish_cross | -0.0289 |  |
| ema_bullish_cross | -0.0282 |  |
| structure_breaks | -0.0179 |  |
| hours_in_trade | -0.0057 |  |
| trend_is_strong | +0.0165 |  |
| has_ob | +0.0318 |  |
| ob_valid | +0.0318 |  |
| macd_bullish_cross | +0.0457 |  |
| macd_bearish_cross | +0.0477 |  |
| volume_ratio | +0.0618 | * |
| ema_bearish_alignment | +0.0656 | * |
| supertrend_bearish | +0.0680 | * |
| signal_score | +0.1010 | *** |
| atr_percentile | +0.1087 | *** |
| supertrend_strength | +0.1143 | *** |
| adx_strength | +0.1211 | *** |
| adx_value | +0.1245 | *** |
| volume_above_avg | +0.1416 | *** |
| ema_spread_pct | +0.1486 | *** |
| regime_confidence | +0.1536 | *** |
| dmi_strength | +0.2028 | *** |
| rr | +0.7526 | *** |
| ema_slope_ok | +nan |  |

## Win Rate by Category

### regime

| regime      |   N |   WR |   avg_pnl |
|:------------|----:|-----:|----------:|
| expansion   | 334 | 62   |    2.1248 |
| trend       | 258 | 45.3 |    1.0139 |
| range       | 485 | 42.9 |    0.7697 |
| compression |  61 | 37.7 |    0.2704 |

### sl_source

| sl_source   |   N |   WR |   avg_pnl |
|:------------|----:|-----:|----------:|
| atr         | 810 | 49.8 |    1.1825 |
| bos         | 145 | 49.7 |    1.1008 |
| structural  | 183 | 43.7 |    1.3313 |

### score_verdict

| score_verdict   |   N |   WR |   avg_pnl |
|:----------------|----:|-----:|----------:|
| strong          | 215 | 54   |    1.2742 |
| moderate        | 874 | 47.6 |    1.1584 |
| weak            |  49 | 46.9 |    1.5238 |

### direction

| direction   |   N |   WR |   avg_pnl |
|:------------|----:|-----:|----------:|
| SELL        | 540 | 52.2 |    1.6218 |
| BUY         | 598 | 45.7 |    0.8115 |

### structure_trend

| structure_trend   |   N |   WR |   avg_pnl |
|:------------------|----:|-----:|----------:|
| ranging           | 380 | 50.3 |    1.5093 |
| bearish           | 426 | 49.5 |    1.1516 |
| bullish           | 332 | 46.1 |    0.8944 |

### ema_spread_trend

| ema_spread_trend   |   N |   WR |   avg_pnl |
|:-------------------|----:|-----:|----------:|
| rising             | 756 | 52   |    1.4155 |
| stable             | 117 | 47   |    1.0745 |
| falling            | 265 | 40.4 |    0.6234 |

## High Correlation Pairs (>0.5)

| Factor 1 | Factor 2 | Correlation |
|----------|----------|-------------|
| adx_value | adx_strength | +0.9763 |
| ema_strength | rsi_value | +0.9468 |
| adx_strength | supertrend_strength | +0.8930 |
| adx_value | supertrend_strength | +0.8857 |
| macd_hist_normalized | rsi_value | +0.7976 |
| rsi_strength | dmi_strength | -0.7118 |
| ema_strength | macd_hist_normalized | +0.7082 |
| ema_spread_pct | adx_value | +0.5523 |
| ema_spread_pct | adx_strength | +0.5353 |
| ema_spread_pct | supertrend_strength | +0.5215 |
