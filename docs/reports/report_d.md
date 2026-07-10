# Report 6 — Final A/B/n Backtest

## 1. Configuration Confirmation

### 10 Presets x 7 Flags

| Flag | true_baseline | unified_only | structural_sl_only | sl_guard_only | rr_filter_only | gate_only | buffer_only | full_old | full_new | unified_plus_filters |
|---|---|---|---|---|---|---|---|---|---|---|
| unified_entry | False | **True** | False | False | False | False | False | True | **True** | **True** |
| confirm_tf_gate | False | False | False | False | False | **True** | False | True | False | False |
| structural_sl | False | False | **True** | False | False | False | False | True | **True** | **True** |
| sl_distance_guard | False | False | False | **True** | False | False | False | True | **True** | **True** |
| rr_filter | False | False | False | False | **True** | False | False | True | **True** | **True** |
| news_filter | False | False | False | False | False | False | False | True | **True** | False |
| stop_hunt_buffer | False | False | False | False | False | False | **True** | True | False | False |

### Key Differences

- **full_old** vs **full_new**: `confirm_tf_gate` and `stop_hunt_buffer` disabled
- **unified_plus_filters**: clean combo — all useful filters, no gate/buffer/news-stub
- **gate_only** and **buffer_only**: for documenting that they are counterproductive

## 2. Results Table

> To be filled after backtest run.

## 3. Key Comparison: true_baseline | full_new | unified_plus_filters

> To be filled after backtest run.

## 4. full_old vs full_new

> To be filled after backtest run.

## 5. Per-Symbol Breakdown

> To be filled after backtest run.

## 6. Final Conclusions and Limitations

> To be filled after backtest run.

## 7. Recommended Next Steps

> To be filled after backtest run.
