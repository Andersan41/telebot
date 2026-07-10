# Survivor Analysis

Generated: 2026-07-08 20:49 UTC

## Top Discriminating Features

Features that most differentiate winners from losers:

| Feature | Value | Winners % | Losers % | Delta |
|---------|-------|-----------|----------|-------|
| sweep_present | False | 0.0% | 61.5% | -61.5% |
| sweep_present | True | 100.0% | 38.5% | +61.5% |
| direction | SELL | 50.0% | 0.0% | +50.0% |
| direction | BUY | 50.0% | 100.0% | -50.0% |
| ob_present | False | 100.0% | 87.2% | +12.8% |
| ob_present | True | 0.0% | 12.8% | -12.8% |
| regime | expansion | 0.0% | 7.7% | -7.7% |
| regime | range | 100.0% | 92.3% | +7.7% |
| structure_trend | ranging | 100.0% | 100.0% | +0.0% |
| fvg_present | False | 100.0% | 100.0% | +0.0% |
| structure_alignment | False | 100.0% | 100.0% | +0.0% |
| choch_present | False | 100.0% | 100.0% | +0.0% |

## Top Winner Fingerprints

Most common feature combinations among winning trades:

- `range_SELL_False_True_False` — 1 trades
- `range_BUY_False_True_False` — 1 trades

## Negative Indicators

Features that appear significantly more in losers than winners:

- **sweep_present=False**: 61.5% of losers vs 0.0% of winners (delta: -61.5%)
- **ob_present=True**: 12.8% of losers vs 0.0% of winners (delta: -12.8%)
