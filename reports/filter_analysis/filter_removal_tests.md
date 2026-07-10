# Filter Removal Tests

**Date:** 2026-06-25 00:51 UTC
**Baseline:** full_new (WR=50.0%, Exp=+0.9856%, PF=2.3)
**Method:** For each Category A filter, disable it while keeping all others as baseline.
**Significance:** CI non-overlap at 95% level.

## Results

| Filter | ΔTrades | ΔWR (pp) | ΔExp (%) | PF | Verdict | WR CI | Exp CI | Notes |
|--------|---------|----------|----------|----|---------|-------|--------|-------|
| unified_entry | -16 | -18.7 | -0.9900 | 0.92 | **NOT SIGNIFICANT** | [+0.26%, +0.38%] | [+0.00%, +0.00%] |  |
| structural_sl | -2 | +2.0 | +0.0721 | 2.37 | **NOT SIGNIFICANT** | [+0.46%, +0.58%] | [+0.00%, +0.00%] |  |
| sl_distance_guard | +13 | -0.6 | -0.0159 | 2.36 | **NOT SIGNIFICANT** | [+0.43%, +0.55%] | [+0.00%, +0.00%] |  |
| rr_filter | +24 | +1.9 | -0.0441 | 2.18 | **NOT SIGNIFICANT** | [+0.46%, +0.58%] | [+0.00%, +0.00%] |  |
| confirm_tf_gate | -12 | -1.3 | -0.0595 | 2.20 | **REMOVED (confirmed)** | [+0.42%, +0.55%] | [+0.00%, +0.00%] |  |

## Interpretation

- **POSITIVE**: Disabling this filter worsened performance → filter is useful
- **NEGATIVE**: Disabling this filter improved performance → filter is harmful
- **NEUTRAL**: ΔWR < 2pp AND ΔPF < 0.1 simultaneously
- **NOT SIGNIFICANT**: CIs overlap → no reliable conclusion

## Fixed Decisions (from prior runs, not re-tested)

- `confirm_tf_gate`: **REMOVED** (gate_only −27.82% vs baseline, 20 symbols)
- `stop_hunt_buffer`: **REMOVED** (buffer_only −74.94% vs baseline, 20 symbols)
- `unified_entry`: **KEEP** (unified_only +1203% vs baseline, 20 symbols)