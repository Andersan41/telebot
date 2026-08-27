# New Pipeline Backtest — 2026-07-27 23:48

**Symbols:** BTC/USDT, ETH/USDT, SOL/USDT
**Timeframe:** 4h | **Days:** 90
**Commission:** 0.06% | **Slippage:** 0.02%

## Aggregate

| Metric | Value |
|---|---|
| Total trades | 218 |
| Winrate | 35.3% |
| Profit Factor | 1.29 |
| Sharpe Ratio | 10.02 |
| Total PnL (net) | +102.48% |

## Setup Type Breakdown (aggregate)

| Setup | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|
| MSS Reversal | 15 | 0.0% | 0.0 | -0.94 | -24.81% |
| BOS Continuation LONG | 105 | 50.5% | 2.09 | +0.80 | +171.49% |
| BOS Continuation SHORT | 98 | 24.5% | 0.74 | -0.26 | -44.21% |
| BOS Continuation ALL | 203 | 37.9% | 1.39 | +0.29 | +127.28% |

## Per-Symbol Overview

| Symbol | Trades | WR% | PF | PnL% | Sharpe | MaxDD | Rev | Cont |
|---|---|---|---|---|---|---|---|---|
| BTC/USDT | 98 | 37.8% | 1.4 | +51.90% | 13.44 | 32.76% | 7 | 91 |
| ETH/USDT | 86 | 33.7% | 1.29 | +43.47% | 9.82 | 39.30% | 7 | 79 |
| SOL/USDT | 34 | 32.4% | 1.1 | +7.10% | 3.87 | 28.91% | 1 | 33 |

## Per-Symbol × Setup Type

| Symbol | Setup | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|---|
| BTC/USDT | MSS Reversal | 7 | 0.0% | 0.0 | -0.86 | -8.77% |
| BTC/USDT | BOS LONG | 42 | 54.8% | 2.2 | +0.83 | +61.91% |
| BTC/USDT | BOS SHORT | 49 | 28.6% | 0.98 | -0.13 | -1.23% |
| ETH/USDT | MSS Reversal | 7 | 0.0% | 0.0 | -1.00 | -14.60% |
| ETH/USDT | BOS LONG | 30 | 63.3% | 3.87 | +1.27 | +101.05% |
| ETH/USDT | BOS SHORT | 49 | 20.4% | 0.57 | -0.39 | -42.97% |
| SOL/USDT | MSS Reversal | 1 | 0.0% | 0.0 | -1.00 | -1.43% |
| SOL/USDT | BOS LONG | 33 | 33.3% | 1.12 | +0.32 | +8.53% |

## MSS Score Bucket Attribution

| Bucket | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|
| 0-30 | 203 | 37.9% | 1.39 | +0.29 | +127.28% |
| 30-50 | 14 | 0.0% | 0.0 | -1.00 | -24.52% |
| 50-70 | 1 | 0.0% | 0.0 | -0.03 | -0.29% |

## Regime Attribution

| Regime | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|
| bullish | 108 | 49.1% | 2.0 | +0.75 | +163.91% |
| bearish | 110 | 21.8% | 0.67 | -0.33 | -61.44% |

## Regime × Setup Type

| Regime | Setup | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|---|
| bullish | MSS Reversal | 3 | 0.0% | 0.0 | -1.00 | -7.58% |
| bullish | BOS LONG | 105 | 50.5% | 2.09 | +0.80 | +171.49% |
| bearish | MSS Reversal | 12 | 0.0% | 0.0 | -0.92 | -17.23% |
| bearish | BOS SHORT | 98 | 24.5% | 0.74 | -0.26 | -44.21% |

## Asset Type Clustering

| Asset Type | Symbols | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|---|
| L1 | SOL/USDT | 34 | 32.4% | 1.1 | +0.28 | +7.10% |
| major | BTC/USDT, ETH/USDT | 184 | 35.9% | 1.34 | +0.19 | +95.38% |

## MSS Reversal by Asset Type

| Asset Type | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|
| L1 | 1 | 0.0% | 0.0 | -1.00 | -1.43% |
| major | 14 | 0.0% | 0.0 | -0.93 | -23.38% |

## BOS Continuation by Asset Type × Direction

| Asset Type | Dir | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|---|
| L1 | LONG | 33 | 33.3% | 1.12 | +0.32 | +8.53% |
| major | LONG | 72 | 58.3% | 2.88 | +1.01 | +162.96% |
| major | SHORT | 98 | 24.5% | 0.74 | -0.26 | -44.21% |

## Rejection Reasons

| Reason | Count |
|---|---|
| reversal: no MSS (strong CHoCH) | 1616 |
| continuation: ranging market | 1391 |
| low_p_tp | 1080 |
| continuation: no BOS | 590 |
| l1_short_blocked | 461 |
| continuation: BOS bearish vs trend bullish | 76 |
| continuation: BOS bullish vs trend bearish | 34 |
| RR=0.84 < 1.5 | 8 |
| RR=0.74 < 1.5 | 8 |
| RR=1.31 < 1.5 | 8 |
| RR=1.08 < 1.5 | 7 |
| RR=0.86 < 1.5 | 6 |
| RR=0.79 < 1.5 | 6 |
| RR=1.27 < 1.5 | 6 |
| RR=0.78 < 1.5 | 6 |
| RR=1.03 < 1.5 | 6 |
| RR=0.85 < 1.5 | 6 |
| RR=1.00 < 1.5 | 6 |
| RR=0.88 < 1.5 | 6 |
| RR=1.20 < 1.5 | 6 |
| RR=1.06 < 1.5 | 6 |
| RR=0.99 < 1.5 | 5 |
| RR=1.24 < 1.5 | 5 |
| RR=1.44 < 1.5 | 5 |
| RR=0.70 < 1.5 | 5 |
| RR=1.05 < 1.5 | 5 |
| RR=1.28 < 1.5 | 5 |
| RR=1.26 < 1.5 | 5 |
| RR=1.33 < 1.5 | 5 |
| RR=1.11 < 1.5 | 4 |
| RR=0.52 < 1.5 | 4 |
| RR=0.46 < 1.5 | 4 |
| RR=0.98 < 1.5 | 4 |
| RR=0.61 < 1.5 | 4 |
| RR=1.09 < 1.5 | 4 |
| RR=1.10 < 1.5 | 4 |
| RR=1.36 < 1.5 | 4 |
| RR=1.14 < 1.5 | 4 |
| RR=1.17 < 1.5 | 4 |
| RR=0.96 < 1.5 | 4 |
| RR=1.02 < 1.5 | 4 |
| RR=1.45 < 1.5 | 4 |
| RR=1.15 < 1.5 | 3 |
| RR=1.25 < 1.5 | 3 |
| RR=0.50 < 1.5 | 3 |
| RR=0.59 < 1.5 | 3 |
| RR=0.55 < 1.5 | 3 |
| RR=0.77 < 1.5 | 3 |
| RR=0.75 < 1.5 | 3 |
| RR=0.81 < 1.5 | 3 |
| RR=0.83 < 1.5 | 3 |
| RR=1.49 < 1.5 | 3 |
| RR=0.95 < 1.5 | 3 |
| RR=1.13 < 1.5 | 3 |
| RR=1.37 < 1.5 | 3 |
| RR=1.35 < 1.5 | 3 |
| RR=1.21 < 1.5 | 3 |
| RR=0.41 < 1.5 | 3 |
| RR=1.22 < 1.5 | 3 |
| RR=1.29 < 1.5 | 3 |
| RR=0.93 < 1.5 | 3 |
| RR=0.31 < 1.5 | 3 |
| RR=1.18 < 1.5 | 3 |
| RR=0.90 < 1.5 | 3 |
| RR=0.72 < 1.5 | 3 |
| RR=1.07 < 1.5 | 3 |
| RR=0.91 < 1.5 | 3 |
| RR=0.92 < 1.5 | 3 |
| RR=0.51 < 1.5 | 2 |
| RR=0.62 < 1.5 | 2 |
| RR=0.56 < 1.5 | 2 |
| RR=0.47 < 1.5 | 2 |
| RR=0.48 < 1.5 | 2 |
| RR=0.45 < 1.5 | 2 |
| RR=0.24 < 1.5 | 2 |
| RR=0.66 < 1.5 | 2 |
| RR=1.19 < 1.5 | 2 |
| SL too wide: 5.58% > 5.0% | 2 |
| SL too wide: 6.28% > 5.0% | 2 |
| RR=1.43 < 1.5 | 2 |
| RR=0.87 < 1.5 | 2 |
| RR=0.35 < 1.5 | 2 |
| RR=1.34 < 1.5 | 2 |
| RR=0.64 < 1.5 | 2 |
| RR=1.01 < 1.5 | 2 |
| SL too wide: 7.47% > 5.0% | 2 |
| RR=0.73 < 1.5 | 2 |
| SL too wide: 6.11% > 5.0% | 2 |
| RR=0.69 < 1.5 | 2 |
| RR=0.39 < 1.5 | 2 |
| RR=0.29 < 1.5 | 2 |
| SL too wide: 5.78% > 5.0% | 2 |
| SL too wide: 8.44% > 5.0% | 2 |
| RR=1.40 < 1.5 | 2 |
| SL too wide: 7.03% > 5.0% | 2 |
| SL too wide: 6.51% > 5.0% | 2 |
| RR=0.67 < 1.5 | 2 |
| RR=0.82 < 1.5 | 2 |
| RR=0.60 < 1.5 | 2 |
| RR=1.41 < 1.5 | 2 |
| RR=0.97 < 1.5 | 2 |
| RR=1.04 < 1.5 | 2 |
| RR=1.42 < 1.5 | 2 |
| SL too wide: 5.90% > 5.0% | 2 |
| RR=1.32 < 1.5 | 2 |
| RR=1.46 < 1.5 | 1 |
| RR=0.63 < 1.5 | 1 |
| RR=0.94 < 1.5 | 1 |
| RR=0.43 < 1.5 | 1 |
| SL too wide: 5.33% > 5.0% | 1 |
| RR=1.12 < 1.5 | 1 |
| RR=0.30 < 1.5 | 1 |
| RR=0.38 < 1.5 | 1 |
| RR=0.42 < 1.5 | 1 |
| SL too wide: 5.19% > 5.0% | 1 |
| SL too wide: 5.30% > 5.0% | 1 |
| SL too wide: 5.09% > 5.0% | 1 |
| SL too wide: 5.28% > 5.0% | 1 |
| SL too wide: 5.13% > 5.0% | 1 |
| RR=1.48 < 1.5 | 1 |
| SL too wide: 5.24% > 5.0% | 1 |
| SL too tight: 0.23% < 0.25% | 1 |
| RR=1.39 < 1.5 | 1 |
| RR=0.65 < 1.5 | 1 |
| RR=1.38 < 1.5 | 1 |
| RR=0.89 < 1.5 | 1 |
| SL too wide: 9.36% > 5.0% | 1 |
| SL too wide: 9.48% > 5.0% | 1 |
| SL too wide: 9.37% > 5.0% | 1 |
| SL too wide: 6.60% > 5.0% | 1 |
| SL too wide: 7.39% > 5.0% | 1 |
| SL too wide: 7.52% > 5.0% | 1 |
| SL too wide: 7.06% > 5.0% | 1 |
| RR=0.53 < 1.5 | 1 |
| RR=0.71 < 1.5 | 1 |
| RR=0.33 < 1.5 | 1 |
| RR=0.36 < 1.5 | 1 |
| SL too wide: 5.75% > 5.0% | 1 |
| SL too wide: 7.01% > 5.0% | 1 |
| SL too wide: 7.17% > 5.0% | 1 |
| SL too wide: 7.34% > 5.0% | 1 |
| SL too wide: 7.37% > 5.0% | 1 |
| SL too wide: 6.27% > 5.0% | 1 |
| SL too wide: 7.28% > 5.0% | 1 |
| SL too wide: 6.42% > 5.0% | 1 |
| SL too wide: 5.51% > 5.0% | 1 |
| SL too wide: 8.65% > 5.0% | 1 |
| SL too wide: 8.21% > 5.0% | 1 |
| SL too wide: 9.20% > 5.0% | 1 |
| SL too wide: 10.37% > 5.0% | 1 |
| SL too wide: 9.69% > 5.0% | 1 |
| SL too wide: 9.12% > 5.0% | 1 |
| RR=0.54 < 1.5 | 1 |
| SL too wide: 5.40% > 5.0% | 1 |
| SL too wide: 8.34% > 5.0% | 1 |
| SL too wide: 5.80% > 5.0% | 1 |
| SL too wide: 8.05% > 5.0% | 1 |
| SL too wide: 7.27% > 5.0% | 1 |
| SL too wide: 6.70% > 5.0% | 1 |
| SL too wide: 6.61% > 5.0% | 1 |
| SL too wide: 7.09% > 5.0% | 1 |
| SL too wide: 6.25% > 5.0% | 1 |
| SL too wide: 6.12% > 5.0% | 1 |
| SL too wide: 6.36% > 5.0% | 1 |
| SL too wide: 5.87% > 5.0% | 1 |
| SL too wide: 5.76% > 5.0% | 1 |
| SL too wide: 6.80% > 5.0% | 1 |
| SL too wide: 5.94% > 5.0% | 1 |
| SL too wide: 5.86% > 5.0% | 1 |
| SL too wide: 5.73% > 5.0% | 1 |
| SL too wide: 6.02% > 5.0% | 1 |
| SL too wide: 5.72% > 5.0% | 1 |
| RR=0.27 < 1.5 | 1 |
| RR=0.44 < 1.5 | 1 |
| SL too wide: 6.00% > 5.0% | 1 |
| SL too wide: 5.98% > 5.0% | 1 |
| SL too wide: 6.34% > 5.0% | 1 |
| RR=0.40 < 1.5 | 1 |
| RR=0.32 < 1.5 | 1 |
| RR=0.37 < 1.5 | 1 |
| RR=1.50 < 1.5 | 1 |
| RR=1.47 < 1.5 | 1 |
| RR=0.20 < 1.5 | 1 |
| SL too wide: 5.66% > 5.0% | 1 |
| SL too wide: 6.13% > 5.0% | 1 |
| SL too wide: 6.32% > 5.0% | 1 |
| SL too wide: 7.49% > 5.0% | 1 |
| SL too wide: 9.14% > 5.0% | 1 |
| SL too wide: 8.12% > 5.0% | 1 |
| SL too wide: 6.58% > 5.0% | 1 |
| SL too wide: 8.89% > 5.0% | 1 |
| SL too wide: 8.26% > 5.0% | 1 |
| SL too wide: 6.29% > 5.0% | 1 |
| SL too wide: 6.62% > 5.0% | 1 |
| SL too wide: 6.35% > 5.0% | 1 |
| RR=0.68 < 1.5 | 1 |
| RR=0.80 < 1.5 | 1 |
| SL too wide: 6.53% > 5.0% | 1 |
| SL too wide: 7.04% > 5.0% | 1 |
| SL too wide: 8.84% > 5.0% | 1 |
| SL too wide: 9.10% > 5.0% | 1 |
| SL too wide: 6.01% > 5.0% | 1 |
| SL too wide: 7.72% > 5.0% | 1 |
| SL too wide: 8.71% > 5.0% | 1 |
| RR=0.76 < 1.5 | 1 |
| SL too wide: 10.17% > 5.0% | 1 |
| SL too wide: 6.91% > 5.0% | 1 |
| SL too wide: 7.44% > 5.0% | 1 |
| SL too wide: 8.19% > 5.0% | 1 |
| RR=1.23 < 1.5 | 1 |
| SL too wide: 6.24% > 5.0% | 1 |
| SL too wide: 6.07% > 5.0% | 1 |
| SL too wide: 6.48% > 5.0% | 1 |
| SL too wide: 6.50% > 5.0% | 1 |
| SL too wide: 5.92% > 5.0% | 1 |
| SL too wide: 5.39% > 5.0% | 1 |
| SL too wide: 5.15% > 5.0% | 1 |
