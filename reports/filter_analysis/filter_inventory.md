# Filter Inventory

**Date:** 2026-06-25 00:51 UTC

## Category A — Backtest-visible

Filters actively called in `backtest/engine.py` pipeline. These are subject to:
removal tests, contribution analysis, relaxation.

| # | Filter | Config Flag | Type | Pipeline Step |
|---|--------|-------------|------|---------------|
| 1 | Unified Entry Price | `enable_unified_entry` | Modify entry | Confirm TF (L548-569) |
| 2 | Confirm TF Gate | `enable_confirm_tf_gate` | Block signal | Confirm TF (L547-577) |
| 3 | Structural SL | `enable_structural_sl` | Modify SL | Post-signal (L632-666) |
| 4 | Stop Hunt Buffer | `enable_stop_hunt_buffer` | Modify SL | Post-signal (L658-664, coupled #3) |
| 5 | SL Distance Guard (Min) | `enable_sl_distance_guard` | Modify SL | Post-signal (L669-678) |
| 6 | SL Distance Guard (Max) | `enable_sl_distance_guard` | Block signal | Post-signal (L681-686) |
| 7 | RR Filter | `enable_rr_filter` | Block signal | Post-signal (L688-699) |
| 8 | News Filter (stub) | `enable_news_filter` | No-op | Post-signal (L701-704) |

**Notes:**
- #4 (Stop Hunt Buffer) is physically coupled with #3 (Structural SL) — it lives inside the structural SL block.
- #1 (Unified Entry) only modifies entry_price, never rejects signals.
- #8 (News Filter) is a stub — `fetch_macro_events()` returns `[]`, so it never blocks.
- Confirmed REMOVED by data: `confirm_tf_gate` (−27.82% vs baseline), `stop_hunt_buffer` (−74.94% vs baseline).

## Category B — Live-only (NOT simulated in backtest)

These filters only run in `scheduler/scanner.py` live pipeline.
Backtest attribution unavailable. NOT subject to removal/relaxation tests.

| # | Filter | File | Lines | Blocks Signal | Affects TG Output |
|---|--------|------|-------|---------------|-------------------|
| 1 | Cooldown Gate | scanner.py | 215-222, 261-263 | YES | No |
| 2 | Portfolio Risk Gate | scanner.py | 265-279 | YES | No |
| 3 | Distance Filter | scanner.py | 424-442 | YES | Yes (reject reason) |
| 4 | TP Path Quality | scanner.py | 444-466, 630-651 | YES | Yes (reject reason) |
| 5 | MTF Alignment Gate | scanner.py | 658-693 | YES | Yes (reject reason) |
| 6 | BTC Correlation Gate | scanner.py | 695-729 | YES | Yes (reject reason) |
| 7 | ETH Correlation Gate | scanner.py | 731-764 | YES | Yes (reject reason) |
| 8 | Volatility Regime Filter | scanner.py | 767-782 | YES | No |
| 9 | Context BLOCKED Gate | scanner.py | 840-850 | YES | Yes (verdict) |
| 10 | Context MIN_VERDICT Gate | scanner.py | 852-863 | YES | Yes (verdict) |
| 11 | News Filter (live) | scanner.py | 893-912 | YES | Yes (when enabled) |
| 12 | No-Trade Zones | scanner.py | 958-1013 | YES | No |
| 13 | Dynamic Risk Filter | scanner.py | 1015-1039 | YES | Yes (sizing) |
| 14 | Deduplication | scanner.py | 1119-1144 | YES | No |
| 15 | Circuit Breaker | circuit_breaker.py | — | YES (pauses scanning) | No |

## Summary

- **Category A (testable):** 8 filters (6 unique flags, 2 coupled)
- **Category B (live-only):** 15 filters
- **Confirmed REMOVED:** confirm_tf_gate, stop_hunt_buffer
- **Confirmed KEEP:** unified_entry (+1203% vs baseline)