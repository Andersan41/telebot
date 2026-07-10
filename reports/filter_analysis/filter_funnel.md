# Filter Funnel

**Date:** 2026-06-25 00:51 UTC
**Baseline:** full_new | **Total signals processed:** 12240

## Pipeline Funnel (backtest order)

| Stage | Filter | Candidates In | Passed | Drop % |
|-------|--------|---------------|--------|--------|
| Signal Engine evaluate() | — | 12240 | 298 | 97.6% |
| Confirm TF Gate | — | 298 | 298 | 0.0% |
| SL Distance Guard (max) | — | 298 | 295 | 1.0% |
| RR Filter | — | 295 | 246 | 16.6% |
| PASSED | — | 246 | 246 | 0.0% |

## Bottleneck Analysis

- Signal Engine is the primary bottleneck: 11942/12240 signals rejected (97.6%)
- RR Filter rejects 49 signals (0.4% of stream)
- 246 signals passed all filters → 2.0% pipeline throughput