# New Pipeline Backtest — 2026-07-11 01:54

**Symbols:** BTC/USDT, ETH/USDT, ZRO/USDT
**Timeframe:** 4h | **Days:** 90
**Commission:** 0.06% | **Slippage:** 0.02%

## Aggregate

| Metric | Value |
|---|---|
| Total trades | 134 |
| Winrate | 24.6% |
| Profit Factor | 1.14 |
| Sharpe Ratio | 4.58 |
| Total PnL (net) | +26.84% |

## Setup Type Breakdown (aggregate)

| Setup | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|
| MSS Reversal | 9 | 22.2% | 1.59 | -0.03 | +5.93% |
| BOS Continuation LONG | 85 | 25.9% | 1.36 | +0.33 | +45.06% |
| BOS Continuation SHORT | 40 | 22.5% | 0.6 | -0.31 | -24.15% |
| BOS Continuation ALL | 125 | 24.8% | 1.11 | +0.12 | +20.91% |

## Per-Symbol Overview

| Symbol | Trades | WR% | PF | PnL% | Sharpe | MaxDD | Rev | Cont |
|---|---|---|---|---|---|---|---|---|
| BTC/USDT | 65 | 27.7% | 1.45 | +29.71% | 13.12 | 20.45% | 7 | 58 |
| ETH/USDT | 53 | 26.4% | 1.32 | +28.81% | 10.33 | 34.98% | 1 | 52 |
| ZRO/USDT | 16 | 6.2% | 0.25 | -31.69% | -54.73 | 35.07% | 1 | 15 |

## Per-Symbol × Setup Type

| Symbol | Setup | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|---|
| BTC/USDT | MSS Reversal | 7 | 28.6% | 2.4 | +0.25 | +9.27% |
| BTC/USDT | BOS LONG | 33 | 24.2% | 1.38 | +0.15 | +14.79% |
| BTC/USDT | BOS SHORT | 25 | 32.0% | 1.28 | -0.03 | +5.65% |
| ETH/USDT | MSS Reversal | 1 | 0.0% | 0.0 | -1.00 | -1.46% |
| ETH/USDT | BOS LONG | 52 | 26.9% | 1.35 | +0.44 | +30.28% |
| ZRO/USDT | MSS Reversal | 1 | 0.0% | 0.0 | -1.00 | -1.89% |
| ZRO/USDT | BOS SHORT | 15 | 6.7% | 0.26 | -0.78 | -29.80% |

## MSS Score Bucket Attribution

| Bucket | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|
| 0-30 | 125 | 24.8% | 1.11 | +0.12 | +20.91% |
| 30-50 | 8 | 25.0% | 1.96 | +0.09 | +7.81% |
| 50-70 | 1 | 0.0% | 0.0 | -1.00 | -1.89% |

## Regime Attribution

| Regime | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|
| bullish | 88 | 25.0% | 1.3 | +0.28 | +39.74% |
| bearish | 46 | 23.9% | 0.8 | -0.21 | -12.90% |

## Regime × Setup Type

| Regime | Setup | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|---|
| bullish | MSS Reversal | 3 | 0.0% | 0.0 | -1.00 | -5.32% |
| bullish | BOS LONG | 85 | 25.9% | 1.36 | +0.33 | +45.06% |
| bearish | MSS Reversal | 6 | 33.3% | 3.41 | +0.46 | +11.24% |
| bearish | BOS SHORT | 40 | 22.5% | 0.6 | -0.31 | -24.15% |

## Asset Type Clustering

| Asset Type | Symbols | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|---|
| L1 | ZRO/USDT | 16 | 6.2% | 0.25 | -0.80 | -31.69% |
| major | BTC/USDT, ETH/USDT | 118 | 27.1% | 1.38 | +0.24 | +58.53% |

## MSS Reversal by Asset Type

| Asset Type | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|
| L1 | 1 | 0.0% | 0.0 | -1.00 | -1.89% |
| major | 8 | 25.0% | 1.96 | +0.09 | +7.81% |

## BOS Continuation by Asset Type × Direction

| Asset Type | Dir | Trades | WR% | PF | Avg R | PnL% |
|---|---|---|---|---|---|---|
| L1 | SHORT | 15 | 6.7% | 0.26 | -0.78 | -29.80% |
| major | LONG | 85 | 25.9% | 1.36 | +0.33 | +45.06% |
| major | SHORT | 25 | 32.0% | 1.28 | -0.03 | +5.65% |

## Rejection Reasons

| Reason | Count |
|---|---|
| low_p_tp | 2139 |
| reversal: no MSS (strong CHoCH) | 1588 |
| continuation: ranging market | 1554 |
| continuation: no BOS | 641 |
| continuation: BOS bearish vs trend bullish | 67 |
| continuation: BOS bullish vs trend bearish | 13 |
| SL too wide: 6.51% > 5.0% | 2 |
| SL too wide: 7.16% > 5.0% | 2 |
| SL too wide: 5.58% > 5.0% | 1 |
| SL too wide: 5.19% > 5.0% | 1 |
| SL too wide: 5.30% > 5.0% | 1 |
| SL too wide: 5.09% > 5.0% | 1 |
| SL too wide: 5.75% > 5.0% | 1 |
| SL too wide: 7.01% > 5.0% | 1 |
| SL too wide: 7.17% > 5.0% | 1 |
| RR=0.78 < 1.5 | 1 |
| SL too wide: 6.25% > 5.0% | 1 |
| SL too wide: 6.12% > 5.0% | 1 |
| SL too wide: 5.97% > 5.0% | 1 |
| SL too wide: 6.36% > 5.0% | 1 |
| SL too wide: 5.83% > 5.0% | 1 |
| SL too wide: 5.87% > 5.0% | 1 |
| SL too wide: 6.00% > 5.0% | 1 |
| SL too wide: 5.98% > 5.0% | 1 |
| SL too wide: 6.01% > 5.0% | 1 |
| SL too wide: 19.88% > 5.0% | 1 |
| SL too wide: 6.17% > 5.0% | 1 |
| SL too wide: 8.14% > 5.0% | 1 |
| SL too wide: 11.04% > 5.0% | 1 |
| SL too wide: 9.35% > 5.0% | 1 |
| SL too wide: 6.71% > 5.0% | 1 |
| SL too wide: 7.13% > 5.0% | 1 |
| SL too wide: 5.84% > 5.0% | 1 |
| SL too wide: 7.72% > 5.0% | 1 |
| RR=1.21 < 1.5 | 1 |
