# MIN_SCORE Sensitivity Analysis

All runs use `full_new` preset. Only `min_score` changes.

| Config | Trades | WR | AvgPnL | PF | Expectancy | MaxDD |
| --- | --- | --- | --- | --- | --- | --- |
| min_score=2 (default) | 306 | 52.3% | +1.0471% | 2.52 | +1.0471% | 8.59% |
| min_score=3 | 300 | 52.0% | +1.0246% | 2.47 | +1.0246% | 8.59% |
| min_score=4 | 265 | 52.8% | +1.1183% | 2.66 | +1.1183% | 12.11% |
| min_score=5 | 147 | 60.5% | +1.5459% | 3.73 | +1.5459% | 9.24% |

## Delta vs min_score=2

| Config | dTrades | dWR | dAvgPnL | dPF | dExpectancy |
| --- | --- | --- | --- | --- | --- |
| min_score=3 | -6 | -0.3% | -0.0225% | -0.05 | -0.0225 |
| min_score=4 | -41 | +0.5% | +0.0712% | +0.14 | +0.0712 |
| min_score=5 | -159 | +8.2% | +0.4988% | +1.21 | +0.4988 |