# Live-Only Filter Architecture

**Date:** 2026-06-25 00:51 UTC

These filters exist ONLY in the live pipeline (`scheduler/scanner.py`).
Backtest attribution is unavailable. Do NOT extrapolate backtest results to these filters.

## Filter Table

| Filter | File | Lines | Blocks Signal | Affects TG Output | Potential Bottleneck |
|--------|------|-------|---------------|-------------------|---------------------|
| Cooldown Gate | `scheduler/scanner.py` | 215-222, 261-263 | YES | No | POTENTIAL BOTTLENECK |
| Portfolio Risk Gate | `scheduler/scanner.py` | 265-279 | YES | No | POTENTIAL BOTTLENECK |
| Distance Filter | `scheduler/scanner.py` | 424-442 | YES | Yes | POTENTIAL BOTTLENECK |
| TP Path Quality | `scheduler/scanner.py` | 444-466, 630-651 | YES | Yes | POTENTIAL BOTTLENECK |
| MTF Alignment Gate | `scheduler/scanner.py` | 658-693 | YES | Yes | POTENTIAL BOTTLENECK |
| BTC Correlation Gate | `scheduler/scanner.py` | 695-729 | YES | Yes | POTENTIAL BOTTLENECK |
| ETH Correlation Gate | `scheduler/scanner.py` | 731-764 | YES | Yes | POTENTIAL BOTTLENECK |
| Volatility Regime Filter | `scheduler/scanner.py` | 767-782 | YES | No | POTENTIAL BOTTLENECK |
| Context BLOCKED Gate | `scheduler/scanner.py` | 840-850 | YES | Yes | POTENTIAL BOTTLENECK |
| Context MIN_VERDICT Gate | `scheduler/scanner.py` | 852-863 | YES | Yes | POTENTIAL BOTTLENECK |
| News Filter (live) | `scheduler/scanner.py` | 893-912 | YES | Yes | POTENTIAL BOTTLENECK |
| No-Trade Zones | `scheduler/scanner.py` | 958-1013 | YES | No | POTENTIAL BOTTLENECK |
| Dynamic Risk Filter | `scheduler/scanner.py` | 1015-1039 | YES | Yes | POTENTIAL BOTTLENECK |
| Deduplication | `scheduler/scanner.py` | 1119-1144 | YES | No | POTENTIAL BOTTLENECK |
| Circuit Breaker | `scheduler/circuit_breaker.py` | — | YES | No | POTENTIAL BOTTLENECK |

## Notes

- All live-only filters block signals (return None) — they are POTENTIAL BOTTLENECKS.
- Quantitative attribution requires live/paper trading comparison.
- These filters are candidates for separate live/paper testing.
- **Do not** change these filters based on backtest data alone.