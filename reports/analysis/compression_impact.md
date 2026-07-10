# Compression Impact Analysis

A: `allow_compression = true` (default)

B: `allow_compression = false`

| Config | Trades | WR | AvgPnL | PF | Expectancy | MaxDD |
| --- | --- | --- | --- | --- | --- | --- |
| A: compression=ON | 306 | 52.3% | +1.0471% | 2.52 | +1.0471% | 8.59% |
| B: compression=OFF | 369 | 49.6% | +0.8798% | 2.27 | +0.8798% | 13.05% |

## Delta (OFF vs ON)

| Metric | ON | OFF | Delta |
| --- | --- | --- | --- |
| Trades | 306 | 369 | +63 |
| WR | 52.3% | 49.6% | -2.7% |
| PF | 2.52 | 2.27 | -0.25 |
| Expectancy | +1.0471 | +0.8798 | -0.1673 |
| MaxDD | 8.59% | 13.05% | +4.46% |

## Compression Regime Trades (from ON)

| Metric | Value |
| --- | --- |
| Trades | 15 |
| WR | 60.0% |
| AvgPnL | +0.6734% |
| PF | 2.49 |
| Expectancy | +0.6734 |
| MaxDD | 2.12% |