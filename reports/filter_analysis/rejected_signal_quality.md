# Quality of Rejected Signals

**Date:** 2026-06-25 00:51 UTC
**Baseline WR:** 50.0% | **Baseline Exp:** +0.9856%

## Main Table

| Filter | Rejected N | WR | Avg PnL | WR CI | Verdict |
|--------|-----------|-----|---------|-------|---------|
| rr_filter | 32 | 59.4% | +0.2093% | [+0.42%, +0.74%] | **KILLER** (CI overlaps 50%) |
| sl_distance_guard | 13 | 38.5% | -0.0426% | [+0.18%, +0.64%] | **GUARDIAN** — Insufficient data (CI overlaps 50%) |
| confirm_tf_gate | 31 | 41.9% | +0.5098% | [+0.26%, +0.59%] | **NEUTRAL** (CI overlaps 50%) |

## Score=5 Deep Attribution

| Filter | Blocked Score5 N | WR Score5 | AvgPnL Score5 | Flag |
|--------|-----------------|-----------|---------------|------|
| rr_filter | 14 | 57.1% | -0.0571% | HIGH VALUE SIGNAL LOSS |
| sl_distance_guard | 2 | 50.0% | +0.3541% |  |
| confirm_tf_gate | 1 | 0.0% | -1.0000% |  |

## Verdict Definitions

- **GUARDIAN**: WR rejected < 40% (filter blocks bad trades)
- **KILLER**: WR rejected > 50% (filter blocks good trades)
- **NEUTRAL**: WR rejected 40-50%
- **HIGH VALUE SIGNAL LOSS**: Blocks Score=5 trades with WR > 55%

## Interpretation

- **rr_filter**: HIGH VALUE SIGNAL LOSS — prioritize for relaxation