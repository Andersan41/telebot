# Filter Attribution Report

**Date:** 2026-06-25 00:51 UTC
**Symbols:** BTC/USDT, ETH/USDT, SOL/USDT, APT/USDT
**Timeframe:** 1h | **Candles:** 3900 (~162 days)

---

## Key Findings

**1. Most useful Category A filter:** No SIGNIFICANT positive filter found in this 4-symbol subset
**2. Most harmful Category A filter:** No SIGNIFICANT negative filter found
**3. HIGH VALUE SIGNAL LOSS:** `rr_filter` — blocks 14 Score=5 trades with WR 57.1%
**4. Confirmed conflicts between top-3:** Interaction tests require separate runs (see filter_interactions.md)
**5. Relaxation candidates:** None (no NEGATIVE SIGNIFICANT filters)
**6. Live-only POTENTIAL BOTTLENECKS:** Distance Filter, TP Path, MTF Alignment, BTC/ETH Correlation, Context Gates, No-Trade Zones, Dynamic Risk (all block signals in live pipeline)
**7. Best combinations:** Not yet tested — requires interaction test runs
**8. Don't touch without paper data:** unified_entry (KEEP), all Category B filters
**9. Edge source ranking:** Score > Regime > Unified Entry > Filter Stack > SL Source
**10. Recommended config for next A/B/n:** Current full_new is the best known configuration. Focus on Score=5 hit rate and regime-aware sizing.

---

## Statistical Summary

| Metric | Count |
|--------|-------|
| Total runs executed | 5 |
| SIGNIFICANT results | 0 |
| NOT SIGNIFICANT results | 4 |
| Low statistical confidence (N<30) | 0 |
| Unknown (?) verdicts | 0 |

### Minimum N to resolve '?' verdicts

Based on current observed effect sizes:
- For RR filter (ΔExp ~0.04%): need ~500+ trades per test for CI to separate
- For SL guard (ΔExp ~0.08%): need ~300+ trades per test
- Current N per symbol: 40-89 trades → total 253 for 4 symbols
- **Recommendation:** Run on full 20-symbol set to resolve remaining '?' verdicts

---

## Next Cycle Priorities

**P1 (highest impact): Score=5 signal enrichment**
- Score=5 trades: WR 60.6%, Avg PnL +1.95% — this is where 80% of edge lives
- Increasing Score=5 hit rate from ~30% to ~40% of signals → estimated +40% expectancy

**P2: Regime-aware position sizing**
- Expansion: WR 62.0%, Compression: WR 37.7%
- Skip compression trades entirely, increase size in expansion

**P3: Unified entry refinement**
- Already the dominant contributor (+1203% vs baseline)
- Fine-tune confirm TF entry timing

### What NOT to do next cycle

- **Don't re-test confirm_tf_gate or stop_hunt_buffer** — data is conclusive (20 symbols, large N)
- **Don't touch Category B filters** — backtest cannot validate live-only logic
- **Don't relaxation-test without NEGATIVE SIGNIFICANT verdict** — current data shows no negative filters in 4-symbol subset