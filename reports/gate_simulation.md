# Gate Simulation Report

Generated: 2026-07-08 14:58 UTC

Trades analyzed: 39

Baseline: WR=5.1% | PF=0.25 | E=-0.712R | Avg PnL=-2.029%

## Single Filter Impact

Sorted by delta expectancy (best filters first).

| Filter | Trades | WR | PF | Expectancy | Delta E | Diagnosis |
|--------|--------|----|----|------------|---------|-----------|
| bos_age_3 | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| bos_age_5 | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| bos_age_10 | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| ob_dist_1atr | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| trend_regime | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| mtf_aligned | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| mtf_strong | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| structure_aligned | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| fvg_present | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| high_confidence | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| strong_scenario | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| fresh_scenario | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| btc_supportive | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| sweep_present | 16/39 | 0.1% | 0.66 | -0.298R | ++0.414R | IMPROVES_EDGE: filter adds positive expectancy |
| rr_3 | 14/39 | 0.1% | 0.56 | -0.412R | ++0.300R | IMPROVES_EDGE: filter adds positive expectancy |
| rr_2.5 | 15/39 | 0.1% | 0.52 | -0.451R | ++0.261R | IMPROVES_EDGE: filter adds positive expectancy |
| moderate_vol | 28/39 | 0.1% | 0.35 | -0.599R | ++0.113R | IMPROVES_EDGE: filter adds positive expectancy |
| rr_2 | 29/39 | 0.1% | 0.34 | -0.613R | ++0.099R | IMPROVES_EDGE: filter adds positive expectancy |
| adx_25 | 23/39 | 0.0% | 0.33 | -0.642R | ++0.070R | IMPROVES_EDGE: filter adds positive expectancy |
| adx_18 | 33/39 | 0.1% | 0.30 | -0.660R | ++0.052R | IMPROVES_EDGE: filter adds positive expectancy |
| no_extreme_vol | 38/39 | 0.1% | 0.26 | -0.704R | ++0.008R | IMPROVES_EDGE: filter adds positive expectancy |
| rr_1.5 | 39/39 | 0.1% | 0.25 | -0.712R | +0.000R | NEUTRAL: minor impact on expectancy |
| no_compression | 39/39 | 0.1% | 0.25 | -0.712R | +0.000R | NEUTRAL: minor impact on expectancy |
| counter_trend | 39/39 | 0.1% | 0.25 | -0.712R | +0.000R | NEUTRAL: minor impact on expectancy |
| volume_above_avg | 11/39 | 0.1% | 0.20 | -0.727R | -0.015R | OVER_FILTERED: removes >70% of trades |
| adx_30 | 16/39 | 0.0% | 0.00 | -1.000R | -0.288R | DESTROYS_EDGE: filter reduces expectancy |
| ob_dist_2atr | 1/39 | 0.0% | 0.00 | -1.000R | -0.288R | DESTROYS_EDGE: filter reduces expectancy |
| ob_dist_3atr | 1/39 | 0.0% | 0.00 | -1.000R | -0.288R | DESTROYS_EDGE: filter reduces expectancy |
| expansion_regime | 3/39 | 0.0% | 0.00 | -1.000R | -0.288R | DESTROYS_EDGE: filter reduces expectancy |
| no_range | 3/39 | 0.0% | 0.00 | -1.000R | -0.288R | DESTROYS_EDGE: filter reduces expectancy |
| ob_present | 5/39 | 0.0% | 0.00 | -1.000R | -0.288R | DESTROYS_EDGE: filter reduces expectancy |
| has_bos | 34/39 | 0.0% | 0.00 | -1.000R | -0.288R | DESTROYS_EDGE: filter reduces expectancy |
| volume_strong | 2/39 | 0.0% | 0.00 | -1.000R | -0.288R | DESTROYS_EDGE: filter reduces expectancy |

## DB Gate Columns (Pipeline Gates)

These are actual gates from the production pipeline.

| Gate | Trades | WR | PF | Expectancy | Delta E | Diagnosis |
|------|--------|----|----|------------|---------|-----------|
| db:cooldown | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:portfolio_risk | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:btc_global_trend | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:indicators | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:confirm_tf | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:signal_engine | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:distance_filter | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:tp_path | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:mtf_alignment | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:btc_correlation | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:eth_correlation | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:volatility | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:context_timeout | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:context_block | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:context_min_verdict | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:news | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:sl_distance | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:rr_guard | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:no_trade_zones | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:dynamic_risk | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:confidence_v2 | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:dedup | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |
| db:compression_block | 0/39 | 0.0% | 0.00 | +0.000R | ++0.712R | TOO_FEW_TRADES: positive but insufficient sample |

## Best Filter Combinations

Top combinations that improve expectancy with sufficient sample size.

| Filters | Trades | WR | PF | Expectancy | Delta E |
|---------|--------|----|----|------------|---------|
| sweep_present AND moderate_vol AND rr_2 | 10/39 | 0.2% | 1.15 | +0.123R | ++0.835R |
| sweep_present AND rr_2 | 12/39 | 0.2% | 0.92 | -0.064R | ++0.648R |
| rr_3 AND adx_18 | 10/39 | 0.1% | 0.80 | -0.177R | ++0.535R |
| sweep_present AND moderate_vol | 14/39 | 0.1% | 0.77 | -0.198R | ++0.514R |
| sweep_present AND adx_18 | 14/39 | 0.1% | 0.77 | -0.198R | ++0.514R |
| sweep_present AND no_extreme_vol | 15/39 | 0.1% | 0.71 | -0.251R | ++0.461R |
| rr_2.5 AND adx_18 | 11/39 | 0.1% | 0.72 | -0.252R | ++0.460R |
| sweep_present | 16/39 | 0.1% | 0.66 | -0.298R | ++0.414R |
| moderate_vol AND rr_2 | 18/39 | 0.1% | 0.58 | -0.376R | ++0.336R |
| rr_3 | 14/39 | 0.1% | 0.56 | -0.412R | ++0.300R |
| rr_3 AND rr_2.5 | 14/39 | 0.1% | 0.56 | -0.412R | ++0.300R |
| rr_3 AND rr_2 | 14/39 | 0.1% | 0.56 | -0.412R | ++0.300R |
| rr_3 AND no_extreme_vol | 14/39 | 0.1% | 0.56 | -0.412R | ++0.300R |
| rr_3 AND rr_2.5 AND rr_2 | 14/39 | 0.1% | 0.56 | -0.412R | ++0.300R |
| rr_2.5 | 15/39 | 0.1% | 0.52 | -0.451R | ++0.261R |
| rr_2.5 AND rr_2 | 15/39 | 0.1% | 0.52 | -0.451R | ++0.261R |
| rr_2.5 AND no_extreme_vol | 15/39 | 0.1% | 0.52 | -0.451R | ++0.261R |
| rr_2 AND adx_25 | 16/39 | 0.1% | 0.48 | -0.486R | ++0.226R |
| rr_2 AND adx_18 | 23/39 | 0.1% | 0.44 | -0.512R | ++0.200R |
| moderate_vol AND adx_25 | 17/39 | 0.1% | 0.45 | -0.516R | ++0.196R |

## Summary

### Filters that IMPROVE expectancy (8):

- **sweep_present**: +0.414R (16 trades, WR 0.1%)
- **rr_3**: +0.300R (14 trades, WR 0.1%)
- **rr_2.5**: +0.261R (15 trades, WR 0.1%)
- **moderate_vol**: +0.113R (28 trades, WR 0.1%)
- **rr_2**: +0.099R (29 trades, WR 0.1%)
- **adx_25**: +0.070R (23 trades, WR 0.0%)
- **adx_18**: +0.052R (33 trades, WR 0.1%)
- **no_extreme_vol**: +0.008R (38 trades, WR 0.1%)

### Filters that DESTROY expectancy (8):

- **adx_30**: -0.288R (16 trades, WR 0.0%)
- **ob_dist_2atr**: -0.288R (1 trades, WR 0.0%)
- **ob_dist_3atr**: -0.288R (1 trades, WR 0.0%)
- **expansion_regime**: -0.288R (3 trades, WR 0.0%)
- **no_range**: -0.288R (3 trades, WR 0.0%)
- **ob_present**: -0.288R (5 trades, WR 0.0%)
- **has_bos**: -0.288R (34 trades, WR 0.0%)
- **volume_strong**: -0.288R (2 trades, WR 0.0%)

### Recommendation

Best single filter: **sweep_present** (++0.414R, 16 trades)

Best combination: **sweep_present AND moderate_vol AND rr_2** (++0.835R, 10 trades)
