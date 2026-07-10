# 02 — Complete Factor Inventory

## A. Technical Indicators (indicators/engine.py)

| # | Factor | Period | Used In | Function | Weight (Signal) | Weight (Conf V2) | Gate/Score |
|---|--------|--------|---------|----------|-----------------|-------------------|------------|
| 1 | EMA Fast | 8 | Signal Engine, Conf V2 | `_strength_ema()` | 10 | — | Both |
| 2 | EMA Slow | 21 | Signal Engine, Conf V2 | `_strength_ema()` | 10 | — | Both |
| 3 | EMA Trend | 55 | Signal Engine | alignment gate | — | — | Gate |
| 4 | EMA Spread % | derived | Signal Engine | spread gate | — | — | Gate |
| 5 | EMA Slope | derived | Signal Engine | slope gate | — | — | Gate |
| 6 | RSI | 10 | Signal Engine, Conf V2 | `_strength_rsi()`, `score_rsi()` | 5 | 5 | Both |
| 7 | MACD Hist | 8,21,5 | Signal Engine, Conf V2 | `_strength_macd()`, `score_macd()` | 10 | 5 | Both |
| 8 | ADX | 14 | Signal Engine, Conf V2, Dynamic Risk | `_strength_adx()`, `score_adx()` | 5 | 5 | Both |
| 9 | DMI+ / DMI- | 14 | Signal Engine, Conf V2 | `_strength_dmi()`, `score_adx()` | 5 | (in ADX) | Both |
| 10 | ATR | 14 | SL/TP calc, Volatility, Risk | `_calculate_sl_tp()`, `classify_volatility()` | — | — | Score |
| 11 | Supertrend | 10, 2.5 | Signal Engine, Conf V2 | `_strength_supertrend()` | 5 | (in HTF) | Both |
| 12 | Volume | raw | Signal Engine, Conf V2 | `_strength_volume()`, `score_volume()` | 15 | 5 | Both |
| 13 | Volume SMA | 20 | Signal Engine | volume filter | — | — | Gate |
| 14 | Volume Delta | taker buy | Signal Engine | delta trigger + strength | — | — | Score |

## B. Market Structure (market_structure/)

| # | Factor | Used In | Function | Weight | Gate/Score |
|---|--------|---------|----------|--------|------------|
| 15 | BOS (Break of Structure) | Signal Engine (trigger), Conf V2 | `analyze_structure()` | — (trigger) | Gate+Score |
| 16 | CHoCH (Change of Character) | MTF Alignment (reversal detection) | `analyze_structure()` | — | Gate |
| 17 | Swing Points | S/R levels, distance filter | `find_swing_levels()`, `get_support_resistance()` | — | Gate |
| 18 | Structure Trend | Conf V2, No-Trade Zones | `score_structure()` | 15 (Conf V2) | Score |
| 19 | MTF Alignment | Conf V2, Momentum Entry | `check_mtf_alignment()` | 20 (Conf V2) | Both |

## C. Liquidity (liquidity/)

| # | Factor | Used In | Function | Weight (Conf V2) | Gate/Score |
|---|--------|---------|----------|-------------------|------------|
| 20 | Liquidity Sweeps | Signal Engine (trigger), Conf V2, SL/TP | `detect_sweeps()` | 20 | Both |
| 21 | Order Blocks | Signal Engine (trigger), Conf V2, SL/TP | `detect_order_blocks()` | (in liquidity) | Both |
| 22 | Fair Value Gaps (FVG) | TP recalculation, Conf V2 | `detect_fvg()` | (in liquidity) | Score |
| 23 | Candle Quality | Reasons, warnings | `analyze_last_candle()` | — | Score |

## D. Derivatives (derivatives/)

| # | Factor | Used In | Function | Weight (Conf V2) | Gate/Score |
|---|--------|---------|----------|-------------------|------------|
| 24 | BTC Price vs 4h EMA200 | BTC Correlation gate | `fetch_btc_context()` | 15 | Gate |
| 25 | BTC Structure | BTC Correlation gate | `_detect_structure()` | (in BTC) | Gate |
| 26 | BTC Breakout | BTC Correlation gate | `_detect_breakout()` | — | Gate |
| 27 | BTC Price vs Daily EMA200 | BTC Global Trend gate | inline | — | Gate |
| 28 | ETH Structure | ETH Correlation gate | `fetch_eth_context()` | — | Gate |
| 29 | ETH Momentum | ETH Correlation gate | `fetch_eth_context()` | — | Gate |
| 30 | Funding Rate | Context, Conf V2, No-Trade | `classify_funding()`, `score_funding_from_state()` | 5 | Both |
| 31 | Open Interest Delta | Context, Conf V2, No-Trade | `classify_oi()`, `score_oi_from_state()` | 5 | Both |
| 32 | Long/Short Ratio | Context (display only) | `fetch_long_short_ratio()` | — | Score |

## E. Context / Sentiment (context/)

| # | Factor | Used In | Function | Weight (Conf V2) | Gate/Score |
|---|--------|---------|----------|-------------------|------------|
| 33 | Fear & Greed Index | Context Scorer | `_score_fear_greed()` | — | Score |
| 34 | CoinGecko 24h/7d Change | Context Scorer | `_score_price_trend()` | — | Score |
| 35 | CryptoPanic Sentiment | Context Scorer | `_score_news()` | — | Score |
| 36 | RSS News Sentiment | Context Scorer | `_score_news()` | — | Score |
| 37 | Trending Status | Display only | `fetch_trending()` | — | None |

## F. Risk (risk/)

| # | Factor | Used In | Function | Weight | Gate/Score |
|---|--------|---------|----------|--------|------------|
| 38 | Market Regime | Signal Engine | `_detect_regime()` | — | Gate |
| 39 | Volatility Regime (ATR%) | Volatility gate, Dynamic Risk | `classify_volatility()` | — | Gate |
| 40 | Setup Quality (score_verdict) | Dynamic Risk | `calculate_risk()` | — | Gate |
| 41 | Historical Winrate | Conf V2 blend | `db.get_historical_winrate()` | — | Score |

## G. Composite / Derived

| # | Factor | Used In | Function | Gate/Score |
|---|--------|---------|----------|------------|
| 42 | Factor Fingerprint | Analytics, Conf V2 blend | `_build_factor_fingerprint()` | Score |
| 43 | Weighted Score | Signal Engine verdict | inline sum | Score |
| 44 | Supporting Reasons Count | Signal Engine score | `len(supporting_reasons)` | Score |
