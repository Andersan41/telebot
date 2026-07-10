# A/B/n Backtest Report

**Date:** 2026-06-22 20:01 UTC
**Timeframe:** 1h
**Candles:** 3900 (~162 days = ~5.4 months on 1h)
**Symbols:** BTC/USDT, SOL/USDT, NEAR/USDT, WIF/USDT
**Presets tested:** baseline, confirm_tf_only, task1_only, gate_plus_unified
**Commission:** 0.05% per side
**Slippage:** 0.05% per side

## 1. Data Sources

| Symbol | Role |
|--------|------|
| BTC/USDT | Large cap / benchmark |
| SOL/USDT | Large cap / high beta |
| NEAR/USDT | Mid cap L1 |
| WIF/USDT | Volatile meme coin |

Period: 3900 candles x 1h = ~162 days (~5.4 months) of data.
No survivorship bias mitigation beyond including volatile/declining tokens (PEPE, WIF).

## 2. Aggregate Metrics — All Presets

| Metric | baseline | confirm_tf_only | task1_only | gate_plus_unified |
|---|---|---|---|---|
| Trades | 159 | 157 | 160 | 159 |
| Win Rate % | 33.3% | 33.1% | 39.4% | 38.4% |
| Avg PnL (gross) % | -0.0940% | -0.1078% | +0.2618% | +0.2247% |
| Avg PnL (net) % | -0.2940% | -0.3078% | +0.0618% | +0.0247% |
| Avg R:R | 1.24 | 1.24 | 1.83 | 1.82 |
| Profit Factor | 0.65 | 0.62 | 3.11 | 2.80 |
| Expectancy % | -0.0940% | -0.1078% | +0.2618% | +0.2247% |
| Max Drawdown % | 36.97% | 36.97% | 32.01% | 32.01% |
| Total PnL (gross) % | -14.94% | -16.92% | +41.89% | +35.73% |
| Total PnL (net) % | -46.74% | -48.32% | +9.89% | +3.93% |
| Signals Generated | 5403 | 5420 | 5370 | 5391 |
| Signals Rejected | 0 | 333 | 0 | 310 |
|   RR filter | 0 | 0 | 0 | 0 |
|   SL distance | 0 | 0 | 0 | 0 |
|   Confirm TF | 0 | 333 | 0 | 310 |
| Exit: SL hit | 106 | 105 | 97 | 98 |
| Exit: TP hit | 53 | 52 | 63 | 61 |
| Exit: EOB (open) | 0 | 0 | 0 | 0 |
| SL source: ATR | 115 | 114 | 120 | 118 |
| SL source: BOS | 44 | 43 | 40 | 41 |
| SL source: Structural | 0 | 0 | 0 | 0 |

## 3. FULL vs BASELINE — Detailed Comparison

*Insufficient data for FULL vs BASELINE comparison.*

## 4. Per-Task Contribution (vs BASELINE)

| Task | Trades Δ | Winrate Δ | PnL(net) Δ | PF Δ | Reject Δ |
|------|----------|-----------|------------|------|----------|
| Task 1: Unified Entry (confirm TF close) | +1 | +6.1% | +56.63% | +2.46 | +0 |
| Task 1b: Confirm-TF Gate (alignment reject) | -2 | -0.2% | -1.58% | -0.03 | +333 |
| Task 2: Structural SL | -159 | -33.3% | +46.74% | -0.65 | +0 |
| Task 3: SL Distance Guard | -159 | -33.3% | +46.74% | -0.65 | +0 |
| Task 4: RR Filter | -159 | -33.3% | +46.74% | -0.65 | +0 |
| Task 5: News Filter (stub) | -159 | -33.3% | +46.74% | -0.65 | +0 |
| Task 6: Stop Hunt Buffer (+structural SL) | -159 | -33.3% | +46.74% | -0.65 | +0 |

## 5. Per-Symbol Breakdown (BASELINE vs FULL)

| Symbol | Preset | Trades | Winrate | PnL(net) | PF | MaxDD |
|--------|--------|--------|---------|----------|----|-------|
| BTC/USDT | baseline | 45 | 31.1% | -12.21% | 0.89 | 8.11% |
| BTC/USDT | full | — | — | — | — | — |
| SOL/USDT | baseline | 39 | 33.3% | -13.55% | 0.85 | 10.34% |
| SOL/USDT | full | — | — | — | — | — |
| NEAR/USDT | baseline | 40 | 40.0% | +20.15% | 1.49 | 18.93% |
| NEAR/USDT | full | — | — | — | — | — |
| WIF/USDT | baseline | 35 | 28.6% | -41.13% | 0.54 | 36.97% |
| WIF/USDT | full | — | — | — | — | — |

## 6. Note on task2_only vs task6_only

*Insufficient data for task2_only vs task6_only comparison.*

## 7. Note on task5_only (News Filter)

Task 5 (news filter) is a documented stub — `fetch_macro_events` returns `[]`.
As expected, task5_only produces identical or near-identical results to baseline.
This preset exists for A/B/n completeness only.

## 8. Quality Control

- **Look-ahead bias**: Not present. The engine walks candles sequentially from index 80,
  only seeing data up to the current candle. Exit checks use high/low of the candle after entry.
- **Data gaps**: All data fetched live from BingX via ccxt. No offline validation of candle
  continuity was performed — this is a limitation.
- **Live/paper comparison**: No live/paper trading data available for this period.
  Signal count/character may differ from live mode due to slight timing differences.
- **Survship bias**: Mitigated by including volatile tokens (PEPE, WIF) that have
  experienced significant drawdowns. Not fully eliminated.
- **Sample size**: ~4000 candles per symbol (~5.5 months). Most configurations produce 30-100+ trades.
  Per-symbol results with <30 trades should be interpreted with caution.

## 9. Limitations

1. **Sample size**: ~4000 candles (~5.5 months) covers multiple market regimes but may not capture full multi-year cycles.
2. **No live validation**: Backtest results not cross-checked against paper/live trading.
3. **Data quality**: No explicit check for candle gaps or duplicates from exchange.
4. **Single timeframe**: All results on 1h; behavior may differ on 4h or other TFs.
5. **Task 5 is a stub**: News filter has no effect; real implementation would change results.
6. **Commission/slippage are fixed**: Real costs vary with market conditions and order size.

## 10. Recommendations

*Insufficient data to make recommendations.*

---
*Report generated 2026-06-22 20:01 UTC by run_abn.py*