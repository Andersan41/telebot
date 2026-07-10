# 06 — Dependency Graph

## Module Call Graph (who calls whom)

```
main.py
  └─ scheduler/tasks.py (APScheduler)
       └─ scanner.run_scan_cycle()
            ├─ circuit_breaker.check_recent_losses()
            │    └─ storage.database.get_outcomes_since()
            │
            └─ scanner.scan_symbol() [per symbol × TF]
                 │
                 ├─ [0] circuit_breaker.is_circuit_breaker_active()
                 │
                 ├─ [1] scanner._is_cooldown_active()
                 │    └─ database.get_cooldown()
                 │
                 ├─ [2] database.get_active_signals_count()
                 │    database.get_portfolio_risk_sum()
                 │
                 ├─ [3] exchange_client.fetch_ohlcv("BTC/USDT", "1d")
                 │    (BTC global trend — inline EMA200 calc)
                 │
                 ├─ [4] scanner._get_indicators(symbol, tf)
                 │    ├─ exchange_client.fetch_ohlcv(symbol, tf)
                 │    └─ indicators.engine.calculate(df)
                 │         ├─ pandas_ta.ema(), rsi(), macd(), adx(), atr()
                 │         ├─ pandas_ta.supertrend()
                 │         └─ volume SMA + delta calc
                 │
                 ├─ scanner._detect_regime(ind, df)
                 │    └─ risk.market_regime.RegimeDetector.detect()
                 │
                 ├─ [early] liquidity.sweep.detect_sweeps()
                 │    liquidity.order_blocks.detect_order_blocks()
                 │    market_structure.structure.analyze_structure()
                 │
                 ├─ [pre-MTF] market_structure.structure.check_mtf_alignment(req=1)
                 │    └─ exchange_client.fetch_ohlcv() × HTFs
                 │
                 ├─ [5] strategy.signal_engine.evaluate_confirm()
                 │    (simple: EMA aligned OR ST aligned on 15m)
                 │
                 ├─ [6] strategy.signal_engine.evaluate()
                 │    ├─ _strength_supertrend()
                 │    ├─ _strength_ema()
                 │    ├─ _strength_macd()
                 │    ├─ _strength_rsi()
                 │    ├─ _strength_volume()
                 │    ├─ _strength_adx()
                 │    ├─ _strength_dmi()
                 │    ├─ _calculate_sl_tp()
                 │    └─ ConfidenceResult (inline, 7 factors)
                 │
                 ├─ strategy.levels.get_support_resistance()
                 │    strategy.levels.validate_levels_vs_trade()
                 │    strategy.levels.find_swing_levels()
                 │
                 ├─ [7] market_structure.distance_filter.check_distance_filter()
                 │
                 ├─ [8] market_structure.tp_path.evaluate_tp_path()
                 │
                 ├─ [liquidity reanalysis]
                 │    liquidity.candle_quality.analyze_last_candle()
                 │    risk.dynamic_risk.calculate_structural_tp()
                 │    risk.dynamic_risk.calculate_structural_sl()
                 │    liquidity.fvg.detect_fvg()
                 │
                 ├─ [9] market_structure.structure.check_mtf_alignment()
                 │
                 ├─ [10] derivatives.btc_correlation.fetch_btc_context()
                 │
                 ├─ [11] derivatives.eth_correlation.fetch_eth_context()
                 │
                 ├─ [12] risk.volatility_regime.classify_volatility()
                 │
                 ├─ [13] context.analyzer.context_engine.get_snapshot()
                 │    ├─ context.fetcher.fetch_fear_greed()
                 │    ├─ context.fetcher.fetch_coingecko()
                 │    ├─ context.fetcher.fetch_trending()
                 │    ├─ context.fetcher.fetch_funding_rate()
                 │    ├─ context.fetcher.fetch_open_interest()
                 │    ├─ context.fetcher.fetch_long_short_ratio()
                 │    ├─ context.fetcher.fetch_cryptopanic()
                 │    └─ context.fetcher.fetch_rss_news()
                 │
                 ├─ [13] context.scorer.context_scorer.score()
                 │    ├─ _score_fear_greed()
                 │    ├─ _score_funding_rate()
                 │    ├─ _score_long_short()
                 │    ├─ _score_oi()
                 │    ├─ _score_news()
                 │    └─ _score_price_trend()
                 │
                 ├─ [14] risk.news_filter.check_news_block()
                 │
                 ├─ [17] risk.no_trade_zones.check_no_trade_zones()
                 │    (reuses: funding_state, atr_pct, structure, btc, tp, oi)
                 │
                 ├─ [18] risk.dynamic_risk.calculate_risk()
                 │
                 ├─ [confidence] scoring.confidence_v2.confidence_engine_v2.compute()
                 │    ├─ score_htf_trend()
                 │    ├─ score_structure()
                 │    ├─ score_liquidity()
                 │    ├─ score_volume()
                 │    ├─ score_btc_correlation()
                 │    ├─ score_funding_from_state()
                 │    ├─ score_oi_from_state()
                 │    ├─ score_rsi()
                 │    ├─ score_macd()
                 │    └─ score_adx()
                 │
                 ├─ [save] database.save_signal()
                 │    database.create_outcome()
                 │    database.save_context_snapshot()
                 │
                 ├─ [cooldown] scanner._set_cooldown()
                 │
                 └─ [notify] notify_callback(result, context_verdict)
                      └─ bot/notifier.py
```

## Key Data Flow

```
OHLCV (exchange)
  → IndicatorValues (pandas_ta)
    → SignalEngine.evaluate() → SignalResult (BUY/SELL/NO_SIGNAL + score + SL/TP)
      → scanner gates (distance, MTF, BTC, ETH, context, etc.)
        → confidence_v2.compute() → ConfidenceResult (display)
          → database.save_signal()
            → Telegram notification
```

## Shared State Between Modules

| Variable | Set By | Used By |
|----------|--------|---------|
| `_btc_ctx` | BTC Correlation gate | No-Trade Zones, Dynamic Risk, Conf V2 |
| `_eth_ctx` | ETH Correlation gate | No-Trade Zones, Dynamic Risk |
| `_pre_mtf_aligned` | Pre-MTF check | Signal Engine (momentum entry) |
| `_structure` | Early structure analysis | Signal Engine, SL/TP recalc, Conf V2 |
| `_sweeps` | Early sweep detection | Signal Engine, SL/TP recalc, Conf V2 |
| `_order_blocks` | Early OB detection | Signal Engine, SL/TP recalc, Conf V2 |
| `context_verdict` | Context enrichment | Context gates, No-Trade, Conf V2, DB |
| `vol_regime` | Volatility classification | Volatility gate, Dynamic Risk |
| `result._factor_strengths` | Signal Engine | Factor fingerprint |
| `result._confidence_v2` | Conf V2 | Telegram display |
