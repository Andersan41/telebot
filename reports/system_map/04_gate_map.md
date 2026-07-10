# 04 — Complete Gate Map

## Gate Properties

| # | Gate | File:Line | Condition | Blocks | Data Source | Timeout | Fail Mode | Cache |
|---|------|-----------|-----------|--------|-------------|---------|-----------|-------|
| 0 | Circuit Breaker | circuit_breaker.py:25 | 3+ consecutive losses in 60min | ALL signals | DB outcomes | — | Fail OPEN | In-memory |
| 1 | Cooldown | scanner.py:342 | elapsed < max(45, TF×2) min | Same symbol+TF | DB cooldowns | — | Fail OPEN | — |
| 2 | Portfolio Risk | scanner.py:350 | active<3 AND risk<3% | All symbols | DB signals | — | Fail OPEN | — |
| 3 | BTC Global Trend | scanner.py:369 | BUY: BTC>daily_EMA200; SELL: BTC<daily_EMA200 | Direction | BTC/USDT 1d | — | Fail OPEN | 3600s |
| 4 | Indicators | scanner.py:435 | OHLCV+calc succeeds | Symbol+TF | exchange + pandas_ta | — | Fail CLOSED | — |
| 5 | Confirm TF | scanner.py:479 | EMA or ST aligned on 15m | Symbol | 15m OHLCV | — | Fail OPEN | — |
| 6 | Signal Engine | signal_engine.py:174 | 10 internal sub-gates (see below) | Symbol+TF | indicators | — | Fail CLOSED | — |
| 7 | Distance Filter | scanner.py:584 | entry > 1.2% from S/R | Symbol+TF | S/R levels | — | Fail OPEN | — |
| 8 | TP Path | scanner.py:606 | No obstacles to TP | Symbol+TF | S/R + OB | — | Fail OPEN | — |
| 9 | MTF Alignment | scanner.py:821 | ≥N HTFs aligned | Symbol+TF | HTF OHLCV | — | Fail OPEN | — |
| 10 | BTC Correlation | scanner.py:865 | BTC 4h above EMA200 + not bearish | Symbol | BTC/USDT 4h | — | Fail OPEN | 3600s |
| 11 | ETH Correlation | scanner.py:904 | ETH not bearish (BUY) / not impulsive (SELL) | Symbol | ETH/USDT + alts | — | Fail OPEN | — |
| 12 | Volatility | scanner.py:942 | ATR% ≥ 0.8% | Symbol+TF | ATR | — | Fail OPEN | — |
| 13a | Context Timeout | scanner.py:1042 | context_verdict is not None | Symbol | 8+ APIs | 10s | Fail CLOSED | 1800s |
| 13b | Context Block | scanner.py:1057 | verdict ≠ BLOCKED | Symbol | context | — | Fail OPEN | — |
| 13c | Context Min Verdict | scanner.py:1071 | verdict ≥ WEAK | Symbol | context | — | Fail OPEN | — |
| 14 | News Filter | scanner.py:1109 | No high-impact event ±60/30min | Symbol | news API | — | Fail OPEN | — |
| 15 | SL Distance | scanner.py:1132 | 1% ≤ SL_dist ≤ 10% | Symbol+TF | entry+SL | — | Fail OPEN | — |
| 16 | R:R Guard | scanner.py:1161 | RR ≥ 1.5 | Symbol+TF | entry+SL+TP | — | Fail OPEN | — |
| 17 | No-Trade Zones | scanner.py:1180 | ATR OK + not ranging + BTC OK + TP OK + OI OK | Symbol+TF | multiple | — | Fail OPEN | — |
| 18 | Dynamic Risk | scanner.py:1239 | quality≠"weak" OR risk_weak_trade=true | Symbol+TF | score_verdict | — | Fail OPEN | — |
| 19 | Dedup | scanner.py:1344 | Not same-dir within cooldown | Symbol+TF | DB signals | — | Fail OPEN | — |

## Signal Engine Internal Sub-Gates (strategy/signal_engine.py)

| # | Sub-Gate | Line | Condition | Reject Reason |
|---|----------|------|-----------|---------------|
| 6a | Data Valid | 196-218 | No None/NaN in critical fields | ENGINE_DATA_INVALID |
| 6b | ADX Flat | 237-247 | ADX ≥ 18 (compression) or ≥ 24 | ENGINE_ADX_FLAT |
| 6c | Supertrend Alignment | 388-400 | st_str ≥ -0.3 | ENGINE_SUPERTREND |
| 6d | Compression Breakout | 402-443 | If compression: strong trigger + ATR exp + vol + ST aligned | ENGINE_REGIME_BLOCK |
| 6e | Trigger Required | 485-497 | Leading trigger OR momentum entry | ENGINE_NO_TRIGGER |
| 6f | EMA Alignment | 499-531 | fast > slow > trend (BUY) | ENGINE_EMA_ALIGNMENT |
| 6g | EMA Spread | 533-547 | spread ≥ 0.20% | ENGINE_EMA_SPREAD |
| 6h | EMA Slope | 549-581 | spread not narrowing > 5% | ENGINE_EMA_SLOPE |
| 6i | Min Score | 638-650 | supporting_reasons ≥ 2 | ENGINE_MIN_SCORE |
| 6j | Candle Close | 654-694 | Close in upper/lower 40% of range | ENGINE_CANDLE_CLOSE |

## Fail Mode Summary

| Fail Mode | Count | Behavior |
|-----------|-------|----------|
| **Fail OPEN** | 17 gates | Exception = gate skipped = signal passes |
| **Fail CLOSED** | 4 gates | Indicators, Context Timeout, Context Block, Context Min Verdict |

**Key Insight**: The system is **mostly fail-open**. Only 4 gates are fail-closed. If the exchange API is down (gate 4) or context enrichment fails (gate 13), signals are blocked. But if BTC correlation, ETH correlation, news filter, etc. fail, signals pass through.
