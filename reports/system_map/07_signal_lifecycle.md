# 07 — Signal Lifecycle: BUY and SELL Traces

## Trace 1: BUY Signal (e.g., AAVE/USDT on 2026-06-26)

### Stage 1: Scheduler triggers scan
```
APScheduler → :02 cron → run_scan_cycle()
  symbols = ["BTC/USDT","ETH/USDT","SOL/USDT","AAVE/USDT",...]
  timeframes = ["1h","4h"]
  Task: scan_symbol("AAVE/USDT", "1h", notify_callback)
```

### Stage 2: Early Gates
```
Circuit Breaker: check_recent_losses() → 0 consecutive losses → PASS
Cooldown: _is_cooldown_active("AAVE/USDT", "1h") → no last signal → PASS
Portfolio Risk: active_count=1 < 3, risk=0.5% < 3% → PASS
```

### Stage 3: BTC Global Trend
```
BTC/USDT 1d candles fetched
BTC price = 60054, EMA200 = 77261
BTC above EMA200 = False
direction = BUY (determined later, but gate checks is_buy)
→ is_buy=True AND btc_above=False → BLOCKED
```

**This signal never reaches the Signal Engine.** The BTC global trend gate kills all BUY signals when BTC < daily EMA200.

### What would happen if BTC were above EMA200:

```
Stage 4: Indicators
  fetch_ohlcv("AAVE/USDT", "1h", limit=200)
  indicator_engine.calculate() → IndicatorValues:
    ema_fast=88.5, ema_slow=87.2, ema_trend=85.0
    rsi=52.3, adx=28.5, macd_hist=+0.15
    atr=1.2, supertrend_direction=1 (up)
    volume=150000, volume_sma=120000
    volume_delta_pct=+22%

Stage 5: Confirmation TF
  fetch_ohlcv("AAVE/USDT", "15m")
  evaluate_confirm() → EMA fast > slow → True → PASS
  entry_price = 15m close = 88.3

Stage 6: Signal Engine
  Data valid: all fields non-None → PASS
  ADX flat: 28.5 > 24 → PASS
  Direction: leading trigger from BOS bullish → direction="buy"
  Supertrend: aligned, st_str=+0.7 → PASS
  Trigger: BOS bullish → has_trigger=True → PASS
  EMA alignment: fast(88.5) > slow(87.2) > trend(85.0) → PASS
  EMA spread: 1.49% ≥ 0.20% → PASS
  EMA slope: spread not narrowing → PASS
  Supporting reasons:
    1. BOS бычий (leading trigger)
    2. Supertrend aligned
    3. MACD бычий (norm=0.17%)
    4. RSI=52.3 — бычья зона
    5. ADX=28.5 (strong trend ≥ 22)
    6. Delta: +22% (покупки доминируют)
  score = 6 → score_verdict = "strong"
  Candle close: close in upper 60% → PASS
  SL: BOS-based SL = bos_level × 0.995 = 86.5
  TP: entry + ATR × 3.0 = 92.0
  → SignalResult(BUY, score=6, sl=86.5, tp=92.0)

Stage 7: Post-Engine Gates
  S/R levels: 1h + 4h levels calculated
  Distance filter: entry 88.3 > 1.2% from nearest resistance → PASS
  TP path: (disabled by default) → PASS
  MTF alignment: 1d=bullish, 4h=bullish → aligned=2/2, required=2 → PASS
  BTC correlation: BTC 4h above EMA200 + bullish structure → PASS
  ETH correlation: ETH not bearish → PASS
  Volatility: ATR%=1.36% ≥ 0.8% → PASS

Stage 8: Context Enrichment
  context_engine.get_snapshot("AAVE/USDT"):
    Fear & Greed = 45 (Neutral)
    Funding = +0.01% (neutral zone)
    OI delta = +1.5% (bullish_cont)
    L/S ratio = 0.95
    News = +0.1
  context_scorer.score("BUY", snapshot):
    F&G: 45 → 0.0 (neutral)
    Funding: +0.01% → neutral → +0.1
    L/S: 0.95 → 0.0 (neutral zone)
    OI: +1.5% → bullish_cont → +0.3
    News: +0.1 → +0.1
    Price 7d: +3% → +0.3
    total = (0×0.15 + 0.1×0.25 + 0×0.20 + 0.3×0.15 + 0.1×0.05 + 0.3×0.10) / total_weight
    score ≈ +0.15 → verdict = WEAK
  context_block: verdict=WEAK ≠ BLOCKED → PASS
  context_min_verdict: WEAK ≥ WEAK → PASS

Stage 9: Final Gates
  News filter: disabled → PASS
  SL distance: |88.3-86.5|/88.3 = 2.0% → 1% ≤ 2% ≤ 10% → PASS
  R:R: reward=3.7, risk=1.8, RR=2.06 ≥ 1.5 → PASS
  No-trade zones: ATR OK, structure=bullish, BTC OK, TP clear, OI moderate → PASS
  Dynamic risk: quality=strong → should_trade=True, risk=1.0% → PASS
  Confidence V2: 10 factors → quality=moderate, conf=35% (display only)
  Dedup: no recent AAVE/USDT BUY → PASS

Stage 10: Save & Notify
  db.save_signal() → signal_id=22
  db.create_outcome(risk_pct=1.0%)
  db.save_context_snapshot()
  _set_cooldown("AAVE/USDT", "1h")
  notify_callback(result, context_verdict)
    → Telegram message sent
```

## Trace 2: SELL Signal (e.g., INJ/USDT on 2026-06-23)

### Key Differences from BUY

```
Direction: SELL
BTC Global Trend: SELL blocked if BTC > daily EMA200
  → If BTC above EMA200: BLOCKED (can't short in uptrend)
  → If BTC below EMA200: PASS

Signal Engine:
  direction = "sell" (from BOS bearish or EMA alignment)
  EMA alignment: fast < slow < trend
  Supertrend: direction=-1 aligned
  Supporting reasons: BOS bearish + ST aligned + MACD bearish + RSI bearish + DMI- > DMI+

SL/TP: 
  SELL SL = entry + ATR × 1.5 (or BOS × 1.005)
  SELL TP = entry - ATR × 3.0

Context Scorer:
  Funding +0.05% (positive) → SELL: longs paying shorts → bearish → +0.9
  This STRONGLY supports SELL direction
```

## Key Decision Points Summary

| Stage | BUY Critical Check | SELL Critical Check |
|-------|-------------------|---------------------|
| BTC Global | BTC > daily EMA200 | BTC < daily EMA200 |
| BTC Corr | BTC 4h above EMA200 + not bearish | Not in bullish breakout |
| ETH Corr | ETH not bearish | ETH not impulsive up |
| Signal Engine | EMA fast > slow > trend | EMA fast < slow < trend |
| Context | Funding negative (shorts pay longs) | Funding positive (longs pay shorts) |
| Dynamic Risk | quality=strong → 1.0% risk | quality=strong → 1.0% risk |
