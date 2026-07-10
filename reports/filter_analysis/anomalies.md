# Anomaly Log

**Date:** 2026-06-25 00:51 UTC

## Anomalies Found

1. SCORE5 BLOCKED: rr_filter blocks 12 Score=5 trades (14.3% of baseline Score=5)
2. SCORE5 BLOCKED: sl_distance_guard blocks 2 Score=5 trades (2.4% of baseline Score=5)

## Anomaly Categories

- DEAD CODE: Filter rejects 0 signals
- AGGRESSIVE: Filter rejects >50% of signals
- LOW N: Sample size < 30 trades
- SCORE5 BLOCKED: Filter blocks >30% of Score=5 trades
- CONTRADICTION: CI non-overlap but N < 30