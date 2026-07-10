# 01 — Complete Decision Pipeline

## Entry Point

```
main.py
  → scheduler/tasks.py (APScheduler CronTrigger :02, :17, :32, :47)
    → scanner.run_scan_cycle()
      → scanner.scan_symbol(symbol, timeframe, notify_callback, blocked_callback)
```

## scan_symbol() — Full Decision Tree

Every gate runs sequentially. First BLOCKED = signal dies. File: `scheduler/scanner.py:334-1444`.

```
scan_symbol(symbol, timeframe)
│
├─ [GATE 0] Circuit Breaker
│  File: scheduler/circuit_breaker.py
│  Func: is_circuit_breaker_active()
│  Check: 3+ consecutive losses in 60min window → pause 30min
│  Input: DB outcomes table
│  Output: bool
│  Fail: OPEN (exception = no block)
│  Blocks: ALL signals for ALL symbols
│
├─ [GATE 1] Cooldown
│  File: scheduler/scanner.py:342-348
│  Func: _is_cooldown_active(symbol, timeframe)
│  Check: last signal sent < max(45min, TF_min × 2.0)
│  Input: DB cooldowns table
│  Output: (bool, minutes)
│  Fail: OPEN (exception = no block)
│
├─ [GATE 2] Portfolio Risk
│  File: scheduler/scanner.py:350-367
│  Func: inline
│  Check: active_count < 3 AND portfolio_risk_sum < 3.0%
│  Input: DB signals table (active)
│  Output: bool
│  Fail: OPEN
│
├─ [GATE 3] BTC Global Trend
│  File: scheduler/scanner.py:369-433
│  Func: inline with cache
│  Check: BUY blocked if BTC < daily EMA200; SELL blocked if above
│  Input: exchange BTC/USDT 1d candles
│  Output: bool
│  Fail: OPEN (exception = skip gate)
│  Cache: 3600s, global tuple
│  Config: BTC_GLOBAL_TREND_FILTER=true, BTC_GLOBAL_EMA_PERIOD=200
│
├─ [GATE 4] Indicators
│  File: scheduler/scanner.py:435-441
│  Func: _get_indicators(symbol, timeframe)
│  Check: OHLCV fetchable + indicator calculation succeeds
│  Input: exchange fetch_ohlcv + indicators/engine.py calculate()
│  Output: (IndicatorValues, DataFrame) or None
│  Fail: CLOSED (None = blocked)
│
│  ┌─────────────────────────────────────────────────────┐
│  │ IndicatorValues computed (indicators/engine.py)     │
│  │ EMA(8,21,55), RSI(10), MACD(8,21,5),              │
│  │ ADX(14)+DMI, ATR(14), Supertrend(10,2.5),         │
│  │ Volume SMA(20), Volume Delta (taker buy)           │
│  └─────────────────────────────────────────────────────┘
│
├─ Regime Detection
│  File: scheduler/scanner.py:245-284
│  Func: _detect_regime(ind, df)
│  Uses: risk/market_regime.py RegimeDetector
│  Output: MarketRegime (trend/range/compression/expansion/reversal)
│  Does NOT block — passes to signal_engine
│
├─ Early Liquidity/Structure Analysis
│  File: scheduler/scanner.py:446-458
│  Functions: detect_sweeps(), detect_order_blocks(), analyze_structure()
│  Reused later in pipeline (not a gate)
│
├─ Preliminary MTF Check (for momentum entry)
│  File: scheduler/scanner.py:460-477
│  Func: check_mtf_alignment(required=1)
│  Output: _pre_mtf_aligned, _pre_mtf_direction
│  Used by: signal_engine momentum entry mode
│
├─ [GATE 5] Confirmation TF (15m)
│  File: scheduler/scanner.py:479-508
│  Func: signal_engine.evaluate_confirm()
│  Check: EMA aligned OR Supertrend aligned on 15m
│  Input: 15m indicators
│  Output: bool + entry_price
│  Fail: OPEN (exception = use primary close)
│
├─ [GATE 6] Signal Engine
│  File: strategy/signal_engine.py:174-733
│  Func: signal_engine.evaluate()
│  INTERNAL SUB-GATES (see signal_engine section):
│    a. None/NaN guard → NO_SIGNAL
│    b. ADX flat (ADX < 18 compression / < 24 otherwise) → NO_SIGNAL
│    c. Supertrend alignment (st_str < -0.3) → NO_SIGNAL
│    d. Compression breakout check → NO_SIGNAL
│    e. Trigger gate (leading trigger required) → NO_SIGNAL
│    f. EMA alignment (fast > slow > trend) → NO_SIGNAL
│    g. EMA spread (≥ 0.20%) → NO_SIGNAL
│    h. EMA slope (not narrowing > 5%) → NO_SIGNAL
│    i. Min score (≥ 2 supporting reasons) → NO_SIGNAL
│    j. Candle close confirmation (upper/lower 40%) → NO_SIGNAL
│  Input: IndicatorValues + regime + sweeps + OB + structure
│  Output: SignalResult (BUY/SELL/NO_SIGNAL)
│  Score: count of supporting reasons
│
├─ S/R Levels
│  File: scheduler/scanner.py:538-582
│  Func: get_support_resistance() on 1h + 4h
│  Does NOT block — populates sr_levels for downstream gates
│
├─ [GATE 7] Distance Filter
│  File: scheduler/scanner.py:584-604
│  Func: check_distance_filter()
│  Check: entry too close to S/R level (< 1.2%)
│  Input: sr_levels + entry_price
│  Output: DistanceResult (blocked + reasons)
│  Fail: OPEN
│  Config: DISTANCE_FILTER_ENABLED=true
│
├─ [GATE 8] TP Path Quality
│  File: scheduler/scanner.py:606-627
│  Func: evaluate_tp_path()
│  Check: obstacles between entry and TP (OB, S/R)
│  Input: sr_levels + entry + tp
│  Output: TpPathResult (blocked + score)
│  Fail: OPEN
│  Config: TP_PATH_ENABLED=false (disabled by default)
│
├─ Liquidity Analysis + SL/TP Recalculation
│  File: scheduler/scanner.py:647-819
│  Functions: analyze_last_candle(), calculate_structural_tp(), calculate_structural_sl()
│  Modifies: result.sl, result.tp, result.reasons
│  Does NOT block — enhances SL/TP quality
│
├─ [GATE 9] MTF Alignment
│  File: scheduler/scanner.py:821-863
│  Func: check_mtf_alignment()
│  Check: ≥N higher TFs aligned with signal direction
│  Input: HTF OHLCV (1d, 4h for 1h primary; 1d for 4h primary)
│  Output: MTFAlignmentResult (aligned + states)
│  Fail: OPEN (exception = skip gate)
│  Required: min(len(higher_tfs), config.mtf_required_alignment)
│  Config: MTF_REQUIRED_ALIGNMENT=2, MTF_TIMEFRAMES="1d,4h,1h"
│
├─ [GATE 10] BTC Correlation (4h EMA200)
│  File: scheduler/scanner.py:865-902
│  Func: fetch_btc_context()
│  Check: BUY blocked if BTC below 4h EMA200 or bearish structure
│  Input: BTC/USDT 4h candles
│  Output: BTCContext (above_ema200, structure, is_breakout)
│  Fail: OPEN
│  Cache: 3600s
│  Config: BTC_CORRELATION_ENABLED=true
│
├─ [GATE 11] ETH Correlation
│  File: scheduler/scanner.py:904-940
│  Func: fetch_eth_context()
│  Check: BUY blocked if ETH bearish structure; SELL blocked if impulsive up
│  Input: ETH/USDT + correlated alts
│  Output: ETHContext
│  Fail: OPEN
│  Config: ETH_CORRELATION_ENABLED=true
│
├─ [GATE 12] Volatility
│  File: scheduler/scanner.py:942-960
│  Func: classify_volatility()
│  Check: ATR% < low_threshold → block (no breakout in low vol)
│  Input: ATR + close
│  Output: VolatilityRegime
│  Fail: OPEN
│  Config: VOLATILITY_FILTER_ENABLED=true, VOLATILITY_LOW_THRESHOLD=0.8%
│
├─ [GATE 13] Context Enrichment
│  File: scheduler/scanner.py:962-1088
│  Func: context_engine.get_snapshot() + context_scorer.score()
│  Check: 10s timeout; on timeout → use cache (1800s TTL); no cache → BLOCKED
│  Input: 8+ external APIs (F&G, CoinGecko, Funding, OI, L/S, CryptoPanic, RSS)
│  Output: ContextVerdict (verdict, confidence, score)
│  Fail: CLOSED (timeout + no cache = BLOCKED)
│  Sub-gates:
│    ├─ context_timeout: None verdict → BLOCKED
│    ├─ context_block: verdict=BLOCKED + CONTEXT_BLOCK_ON_BLOCKED=true → BLOCKED
│    └─ context_min_verdict: verdict < CONTEXT_MIN_VERDICT → BLOCKED
│  Config: CONTEXT_ENABLED=true, CONTEXT_MIN_VERDICT="WEAK"
│
├─ [GATE 14] News Filter
│  File: scheduler/scanner.py:1109-1130
│  Func: check_news_block()
│  Check: high-impact event within ±60/30 min window
│  Input: external news API
│  Output: NewsBlock (blocked + reason)
│  Fail: OPEN
│  Config: NEWS_FILTER_ENABLED=false (disabled by default)
│
├─ [GATE 15] SL Distance
│  File: scheduler/scanner.py:1132-1159
│  Func: inline
│  Check: SL distance < min (1%) → shift SL; SL distance > max (10%) → block
│  Input: entry_price + result.sl
│  Output: adjusts SL or blocks
│  Fail: OPEN
│
├─ [GATE 16] R:R Guard
│  File: scheduler/scanner.py:1161-1178
│  Func: inline
│  Check: reward/risk < 1.5 → block
│  Input: entry + sl + tp
│  Output: bool
│  Fail: OPEN
│
├─ [GATE 17] No-Trade Zones
│  File: scheduler/scanner.py:1180-1237
│  Func: check_no_trade_zones()
│  Check: ATR too low, ranging, BTC unclear, TP blocked, OI extreme
│  Input: funding_state + atr_pct + structure + btc + tp_blocked + oi
│  Output: NoTradeCheck (blocked + reasons)
│  Fail: OPEN
│  Config: NO_TRADE_ZONES_ENABLED=true
│
├─ [GATE 18] Dynamic Risk
│  File: scheduler/scanner.py:1239-1265
│  Func: calculate_risk()
│  Check: setup_quality=weak + risk_weak_trade=false → block
│  Input: score_verdict + volatility_regime + btc_aligned + eth_aligned
│  Output: RiskParams (should_trade, effective_risk_pct)
│  Fail: OPEN
│  Config: DYNAMIC_RISK_ENABLED=true, RISK_WEAK_TRADE=false
│
├─ Confidence V2 (NO GATE — display only)
│  File: scheduler/scanner.py:1267-1342
│  Func: confidence_engine_v2.compute()
│  10-factor weighted scoring
│  Output: ConfidenceResult (quality, confidence_pct)
│  Used for: Telegram display + analytics only
│
├─ [GATE 19] Dedup
│  File: scheduler/scanner.py:1344-1381
│  Func: inline
│  Check: same direction + within cooldown → block
│  Check: cross-direction + within half cooldown → block
│  Input: DB signals table (last signal)
│  Output: bool
│  Fail: OPEN
│
├─ [SAVE] Signal saved to DB
│  File: scheduler/scanner.py:1383-1403
│
├─ [COOLDOWN SET]
│  File: scheduler/scanner.py:1424-1425
│
└─ [NOTIFY] Telegram message sent
   File: scheduler/scanner.py:1427-1435
```

## Gate Execution Order (FUNNEL GATES)

```python
_FUNNEL_GATES = [
    "cooldown", "portfolio_risk", "btc_global_trend", "indicators",
    "confirm_tf", "signal_engine",
    "distance_filter", "tp_path", "mtf_alignment", "btc_correlation",
    "eth_correlation", "volatility", "context_timeout", "context_block",
    "context_min_verdict",
    "news", "sl_distance", "rr_guard", "no_trade_zones", "dynamic_risk",
    "confidence_v2", "dedup",
]
```

## Key Insight

Signal Engine (gate 6) has **10 internal sub-gates**. By the time a signal exits the Signal Engine, it has already passed ~16 total checks (6 scanner gates + 10 internal). The remaining 13 scanner gates are post-engine filters.
