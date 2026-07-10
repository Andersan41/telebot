# New Pipeline Backtest — 2026-07-11 01:00

**Symbols:** BTC/USDT, ETH/USDT, ZRO/USDT
**Timeframe:** 4h | **Days:** 90
**Commission:** 0.06% | **Slippage:** 0.02%

## Aggregate

| Metric | Value |
|---|---|
| Total trades | 156 |
| Winrate | 28.8% |
| Profit Factor | 1.40 |
| Sharpe Ratio | 12.11 |
| Total PnL (net) | +82.16% |

## Setup Type Breakdown (aggregate)

| Setup | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|
| MSS Reversal | 9 | 22.2% | 1.32 | -0.03 | +3.85% |
| BOS Continuation LONG | 108 | 27.8% | 1.43 | +0.37 | +68.68% |
| BOS Continuation SHORT | 39 | 33.3% | 1.28 | -0.08 | +9.63% |
| BOS Continuation ALL | 147 | 29.3% | 1.4 | +0.25 | +78.31% |

## Per-Symbol Overview

| Symbol | Trades | WR% | PF | PnL% | Sharpe | MaxDD | Rev | Cont |
|---|---|---|---|---|---|---|---|---|
| BTC/USDT | 90 | 28.9% | 1.45 | +40.76% | 13.16 | 23.58% | 7 | 83 |
| ETH/USDT | 66 | 28.8% | 1.36 | +41.40% | 11.75 | 52.43% | 2 | 64 |
| ZRO/USDT | 0 | 0% | 0 | +0.00% | 0 | 0.00% | 0 | 0 |

## Per-Symbol × Setup Type

| Symbol | Setup | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|---|
| BTC/USDT | MSS Reversal | 7 | 28.6% | 2.4 | +0.25 | +9.27% |
| BTC/USDT | BOS LONG | 46 | 23.9% | 1.32 | +0.09 | +17.80% |
| BTC/USDT | BOS SHORT | 37 | 35.1% | 1.45 | -0.03 | +13.68% |
| ETH/USDT | MSS Reversal | 2 | 0.0% | 0.0 | -1.00 | -5.43% |
| ETH/USDT | BOS LONG | 62 | 30.6% | 1.48 | +0.57 | +50.88% |
| ETH/USDT | BOS SHORT | 2 | 0.0% | 0.0 | -1.00 | -4.05% |

## MSS Score Bucket Attribution

| Bucket | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|
| 0-30 | 147 | 29.3% | 1.4 | +0.25 | +78.31% |
| 30-50 | 9 | 22.2% | 1.32 | -0.03 | +3.85% |

## Regime Attribution

| Regime | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|
| bullish | 112 | 26.8% | 1.35 | +0.32 | +59.39% |
| bearish | 44 | 34.1% | 1.62 | +0.02 | +22.76% |

## Regime × Setup Type

| Regime | Setup | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|---|
| bullish | MSS Reversal | 4 | 0.0% | 0.0 | -1.00 | -9.29% |
| bullish | BOS LONG | 108 | 27.8% | 1.43 | +0.37 | +68.68% |
| bearish | MSS Reversal | 5 | 40.0% | 5.72 | +0.75 | +13.13% |
| bearish | BOS SHORT | 39 | 33.3% | 1.28 | -0.08 | +9.63% |

## Asset Type Clustering

| Asset Type | Symbols | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|---|
| L1 | ZRO/USDT | 0 | 0.0% | 0.0 | +0.00 | +0.00% |
| major | BTC/USDT, ETH/USDT | 156 | 28.8% | 1.4 | +0.23 | +82.16% |

## MSS Reversal by Asset Type

| Asset Type | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|
| major | 9 | 22.2% | 1.32 | -0.03 | +3.85% |

## BOS Continuation by Asset Type × Direction

| Asset Type | Dir | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|---|
| major | LONG | 108 | 27.8% | 1.43 | +0.37 | +68.68% |
| major | SHORT | 39 | 33.3% | 1.28 | -0.08 | +9.63% |

## Rejection Reasons

| Reason | Count |
|---|---|
| reversal: no MSS (strong CHoCH) | 1350 |
| low_p_tp | 1140 |
| continuation: ranging market | 881 |
| continuation: no BOS | 293 |
| continuation: BOS bearish vs trend bullish | 16 |
| continuation: BOS bullish vs trend bearish | 9 |
| RR=1.08 < 1.5 | 4 |
| SL too wide: 6.51% > 5.0% | 2 |
| RR=1.27 < 1.5 | 2 |
| RR=1.45 < 1.5 | 2 |
| RR=1.14 < 1.5 | 1 |
| SL too wide: 5.58% > 5.0% | 1 |
| SL too wide: 5.19% > 5.0% | 1 |
| SL too wide: 5.30% > 5.0% | 1 |
| SL too wide: 5.09% > 5.0% | 1 |
| RR=1.42 < 1.5 | 1 |
| SL too tight: 0.23% < 0.25% | 1 |
| RR=1.29 < 1.5 | 1 |
| RR=1.20 < 1.5 | 1 |
| RR=1.28 < 1.5 | 1 |
| RR=0.95 < 1.5 | 1 |
| RR=0.41 < 1.5 | 1 |
| SL too wide: 7.31% > 5.0% | 1 |
| SL too wide: 7.47% > 5.0% | 1 |
| SL too wide: 7.70% > 5.0% | 1 |
| SL too wide: 7.52% > 5.0% | 1 |
| SL too wide: 7.06% > 5.0% | 1 |
| RR=0.70 < 1.5 | 1 |
| SL too wide: 5.75% > 5.0% | 1 |
| SL too wide: 7.01% > 5.0% | 1 |
| SL too wide: 7.17% > 5.0% | 1 |
| SL too wide: 7.34% > 5.0% | 1 |
| SL too wide: 7.37% > 5.0% | 1 |
| SL too wide: 5.65% > 5.0% | 1 |
| SL too wide: 5.47% > 5.0% | 1 |
| SL too wide: 7.27% > 5.0% | 1 |
| SL too wide: 6.70% > 5.0% | 1 |
| SL too wide: 6.61% > 5.0% | 1 |
| SL too wide: 7.09% > 5.0% | 1 |
| SL too wide: 7.03% > 5.0% | 1 |
| SL too wide: 5.57% > 5.0% | 1 |
| RR=1.06 < 1.5 | 1 |
| RR=0.78 < 1.5 | 1 |
| SL too wide: 6.25% > 5.0% | 1 |
| SL too wide: 6.12% > 5.0% | 1 |
| SL too wide: 5.97% > 5.0% | 1 |
| SL too wide: 6.36% > 5.0% | 1 |
| SL too wide: 5.83% > 5.0% | 1 |
| SL too wide: 5.87% > 5.0% | 1 |
| RR=1.21 < 1.5 | 1 |
| RR=1.24 < 1.5 | 1 |
| RR=1.17 < 1.5 | 1 |
| SL too wide: 5.86% > 5.0% | 1 |
| SL too wide: 5.78% > 5.0% | 1 |
| SL too wide: 5.73% > 5.0% | 1 |
| SL too wide: 6.02% > 5.0% | 1 |
| SL too wide: 5.72% > 5.0% | 1 |
| RR=1.03 < 1.5 | 1 |
| RR=1.22 < 1.5 | 1 |
| SL too wide: 6.00% > 5.0% | 1 |
| RR=1.31 < 1.5 | 1 |
| RR=1.43 < 1.5 | 1 |
| RR=1.38 < 1.5 | 1 |
| SL too wide: 5.98% > 5.0% | 1 |
| SL too wide: 6.01% > 5.0% | 1 |
| RR=1.10 < 1.5 | 1 |
| RR=1.05 < 1.5 | 1 |
