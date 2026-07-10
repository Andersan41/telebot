# Sweep SELL Conditional Attribution

Total trades: 1138 (BUY=598, SELL=540)

## Table 1: SELL -- regime x has_sweep

| regime | has_sweep | N | WR% | avg_pnl | ADX_mean |
|--------|-----------|---|-----|---------|----------|
| expansion | True | 44 | 40.9% | +0.592% | 32.3 |
| expansion | False | 147 | 71.4% | +3.054% | 37.4 |
| | **diff** | | **-30.5pp** | | |

| trend | True | 41 | 36.6% | +0.596% | 33.8 |
| trend | False | 95 | 60.0% | +2.135% | 39.6 |
| | **diff** | | **-23.4pp** | | |

| range | True | 107 | 40.2% | +0.860% | 24.7 |
| range | False | 70 | 45.7% | +1.156% | 32.7 |
| | **diff** | | **-5.5pp** | | |

## Table 2: SELL + expansion -- ADX quartile x has_sweep

ADX quartiles: Q1<=27.6, Q2<=33.7, Q3<=41.9

| ADX quartile | has_sweep | N | WR% | avg_pnl | ADX_mean |
|-------------|-----------|---|-----|---------|----------|
| Q1 | True | 26 | 30.8% | -0.148% | 23.1 |
| Q1 | False | 22 | 36.4% | +0.656% | 24.4 |
| | **diff** | | **-5.6pp** | | |

| Q2 | True | 8 | 37.5% | -0.301% | 30.8 |
| Q2 | False | 40 | 72.5% | +2.462% | 31.3 |
| | **diff** | | **-35.0pp** | | |

| Q3 | True | 2 | 100.0% | +4.664% | 38.6 |
| Q3 | False | 45 | 73.3% | +2.945% | 37.6 |
| | **diff** | | **+26.7pp** | | |

| Q4 | True | 8 | 62.5% | +2.871% | 61.9 |
| Q4 | False | 40 | 87.5% | +5.089% | 50.3 |
| | **diff** | | **-25.0pp** | | |

## Table 3: BUY -- regime x has_sweep (control group)

| regime | has_sweep | N | WR% | avg_pnl |
|--------|-----------|---|-----|---------|
| expansion | True | 44 | 56.8% | +1.200% |
| expansion | False | 99 | 59.6% | +1.837% |
| | **diff** | | **-2.8pp** | |
| trend | True | 55 | 40.0% | +0.309% |
| trend | False | 67 | 34.3% | +0.259% |
| | **diff** | | **+5.7pp** | |
| range | True | 111 | 44.1% | +0.542% |
| range | False | 197 | 42.6% | +0.711% |
| | **diff** | | **+1.5pp** | |

**BUY overall:** sweep N=210 WR=45.2% vs no_sweep N=363 WR=43.5% diff=+1.7pp (neutral-to-positive)

## Verdict

### 1. Direction-specific effect (confirmed)

Sweep is **direction-dependent**:
- **BUY**: neutral (+1.7pp overall, never worse than -2.8pp in any regime)
- **SELL**: harmful (-22.9pp overall, -30.5pp in expansion, -23.4pp in trend)

This is NOT a proxy effect. If sweep were merely proxying for "bad conditions," it would hurt both directions equally.

### 2. ADX does NOT eliminate sweep harm for SELL

At SELL + expansion + ADX>42 (top quartile): sweep WR=62.5% vs no_sweep WR=87.5% = **-25.0pp**

Even at the strongest trend conditions (high ADX + expansion regime), sweep still hurts SELL. This is **INDEPENDENT** of trend strength.

### 3. Caveats before code changes

- Q3 (ADX 34-42): N=2 sweep trades — too small to draw conclusions (the +26.7pp is noise)
- Q2 (ADX 28-34): -35.0pp with N=8 — large effect but small sample
- Q4 (ADX>42): -25.0pp with N=8 — concentrated in ARB/USDT (4), SUI/USDT (3), DOGE/USDT (1)
- All expansion+sweep SELL N=44 — adequate but not large

### 4. Recommended next step (analysis only, no code change yet)

Test whether **direction-specific sweep gating** for SELL only would improve metrics:
- Block sweep as trigger for SELL direction
- Keep sweep neutral for BUY direction
- This requires a targeted backtest comparing:
  - full_new (current) vs full_new + sello_sweep_block

The conditional attribution supports the hypothesis but N=44 is on the edge.
A targeted backtest with 1-2 specific symbols (e.g., BTC/USDT, ETH/USDT) could validate
before full 20-symbol run.

---

## 5. Targeted Backtest Results

**Presets**: full_new vs full_new_sell_no_sweep (sell_sweep_block=True)
**Symbols**: BTC/USDT, ETH/USDT, SOL/USDT, NEAR/USDT, ARB/USDT
**Period**: 3897 candles (~162 days), both presets re-run with current code

### Overall

| Metric          | full_new | sell_no_sweep | Delta    |
|-----------------|----------|---------------|----------|
| Trades          | 459      | 365           | -94      |
| WR %            | 52.9     | 51.2          | -1.7pp   |
| Avg PnL %       | +1.297   | +1.226        | -0.071pp |
| Total PnL %     | +595.3   | +447.5        | -147.8pp |
| Max DD %        | 12.3     | 12.2          | -0.1pp   |
| sell_sweep_rej  | 0        | 159           | +159     |

### By Direction (confirms change only affects SELL)

| Direction | Metric | full_new | sell_no_sweep | Delta |
|-----------|--------|----------|---------------|-------|
| BUY       | N      | 267      | 267           | 0     |
| BUY       | WR     | 46.8%    | 46.8%         | 0pp   |
| SELL      | N      | 192      | 98            | -94   |
| SELL      | WR     | 61.5%    | 63.3%         | +1.8pp|

### Per-Symbol

| Symbol    | full_new | sell_no_sweep | dWR     |
|-----------|----------|---------------|---------|
| BTC/USDT  | 99t/51.5%| 74t/48.6%     | -2.9%   |
| ETH/USDT  | 116t/51.7%| 81t/44.4%    | -7.3%   |
| SOL/USDT  | 85t/56.5%| 72t/54.2%     | -2.3%   |
| NEAR/USDT | 93t/50.5%| 79t/51.9%     | +1.4%   |
| ARB/USDT  | 66t/56.1%| 59t/59.3%     | +3.3%   |

### Analysis

1. **BUY metrics are identical** — confirms sell_sweep_block only affects SELL
2. **159 SELL signals rejected** (of ~240 SELL signals that had sweep in reasons)
3. **SELL WR improved +1.8pp** (61.5% -> 63.3%) but below 3pp threshold
4. **Total PnL dropped -147.8pp** — the 94 removed trades were net profitable (avg +0.93%)
5. **Rejected sweep trades were winners**: WR of rejected trades = (192*0.615 - 98*0.633) / 94 = ~57%

### Why total PnL dropped despite WR improvement

The sweep_penalty in signal_engine.py already reduces sweep's contribution to score.
Sweep SELL signals that still pass the score threshold (>=4) are the "better" sweep trades.
Blocking ALL sweep SELL signals removes both bad AND good sweep trades.

The 159 rejected trades included ~89 winners (57% WR) and ~70 losers.
Net effect: lost +89*avg_win vs saved 70*avg_loss = net negative.

### Verdict

**HYPOTHESIS NOT CONFIRMED at the 3pp threshold.**

- SELL WR delta = +1.8pp (< 3pp required)
- Total PnL decreased significantly (-147.8pp)
- sweep_penalty_enabled=True in signal_engine.py is already the better intervention
- A blanket sell_sweep_block is too aggressive — it removes profitable sweep trades too

**Recommendation**: Keep sweep_penalty_enabled=True (already in code). Do NOT add sell_sweep_block to production. The sweep penalty is the right level of intervention.