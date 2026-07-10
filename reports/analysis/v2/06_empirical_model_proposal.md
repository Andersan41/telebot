# Factor Analysis V2 — Empirical Scoring Model

## Key Findings

### Logistic Regression
- Significant features (p<0.05): 5
- Significant features (p<0.01): 0
- High VIF features (>5): 9 — multicollinearity detected

### Composite Ranking (Top 10)
1. **dmi_strength** — LR coef: +0.2452, SHAP: 0.3023, Cluster: 7
1. **atr_percentile** — LR coef: +0.1769, SHAP: 0.2483, Cluster: 4
1. **rsi_value** — LR coef: -0.0680, SHAP: 0.3563, Cluster: 1
1. **supertrend_direction** — LR coef: -0.2650, SHAP: 0.0755, Cluster: 1
1. **adx_strength** — LR coef: -0.0885, SHAP: 0.1614, Cluster: 7
1. **rsi_strength** — LR coef: -0.2155, SHAP: 0.0361, Cluster: 7
1. **ema_spread_pct** — LR coef: +0.0258, SHAP: 0.1617, Cluster: 7
1. **regime_confidence** — LR coef: +0.0095, SHAP: 0.1655, Cluster: 6
1. **structure_breaks** — LR coef: +0.3256, SHAP: 0.0233, Cluster: 5
1. **macd_bullish_cross** — LR coef: +0.1277, SHAP: 0.0517, Cluster: 4

### Feature Clusters
- Cluster 1: macd_hist_normalized, rsi_value, ema_bearish_alignment, supertrend_bearish, supertrend_bullish, ema_bullish_alignment, supertrend_direction
- Cluster 2: ob_valid, has_ob
- Cluster 3: has_sweep, sweep_strength
- Cluster 4: ema_bullish_cross, atr_percentile, ema_bearish_cross, macd_bullish_cross, trend_is_strong, macd_bearish_cross
- Cluster 5: structure_trend, has_bos, structure_breaks
- Cluster 6: volume_above_avg, regime, volume_ratio, regime_confidence
- Cluster 7: supertrend_strength, adx_strength, rsi_strength, ema_spread_pct, dmi_strength, ema_spread_trend

### Proposed Scoring Model
Based on cluster representatives (one per cluster, highest composite rank):
- **dmi_strength** (Cluster 7): weight=5, supports TP (OR=0.245)
- **atr_percentile** (Cluster 4): weight=4, supports TP (OR=0.177)
- **rsi_value** (Cluster 1): weight=1, penalizes TP (OR=-0.068)
- **structure_breaks** (Cluster 5): weight=7, supports TP (OR=0.326)
- **regime_confidence** (Cluster 6): weight=0, supports TP (OR=0.010)
- **has_sweep** (Cluster 3): weight=3, penalizes TP (OR=-0.126)
- **has_ob** (Cluster 2): weight=1, supports TP (OR=0.071)