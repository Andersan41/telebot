# 10 — Edge Source Map

## Edge Assessment by Component

| Component | Edge Source | Edge Type | Confidence | Notes |
|-----------|------------|-----------|------------|-------|
| **Supertrend** | Trend following | Directional | Medium | Simple but effective in trending markets. Weak in ranges. |
| **EMA Alignment** | Trend confirmation | Directional | Medium | Requires 3 EMAs aligned — late entry but higher accuracy. |
| **MACD** | Momentum | Directional | Low-Medium | Normalized by price, noise-filtered. Slope check disabled. |
| **RSI** | Mean reversion zones | Contrarian | Medium | Strong in ranging, weak in strong trends. |
| **Volume** | Participation | Confirmation | Medium | Delta (taker buy) is the real edge; volume alone is weak. |
| **ADX** | Trend strength | Filter | High | Effective flat filter. Prevents range-trading losses. |
| **DMI** | Directional momentum | Directional | Low | Redundant with EMA alignment. |
| **BOS/Sweep** | Market structure | Leading | High | Best edge source — institutional order flow footprint. |
| **Order Blocks** | Institutional zones | Confirmation | Medium | Requires validation (retest). Currently no retest required. |
| **FVG** | Price inefficiency | TP target | Medium | Good for TP optimization, not for entry. |
| **MTF Alignment** | Multi-timeframe | Filter | High | Strong filter — prevents counter-trend trades. |
| **BTC Correlation** | Market regime | Filter | High | BTC direction dominates alt behavior. |
| **BTC Global Trend** | Macro regime | Filter | Very High | Daily EMA200 is the strongest macro filter. |
| **ETH Correlation** | Alt correlation | Filter | Medium | ETH momentum affects alts but less than BTC. |
| **Funding Rate** | Derivatives sentiment | Contrarian | High | Extreme funding = overcrowded = reversal likely. |
| **Open Interest** | Participation | Confirmation | Medium | OI+price pattern detection is useful but noisy. |
| **Fear & Greed** | Sentiment | Contrarian | Medium | Extreme values are useful; middle range is noise. |
| **News** | Event risk | Filter | Low | Currently disabled. CryptoPanic data quality varies. |
| **Context Scorer** | Multi-factor | Directional | Medium | 6-factor weighted model. Good concept, some factors dead for alts. |
| **Confidence V2** | Quality assessment | Display | Low | 10-factor model is sophisticated but doesn't gate. |
| **Dynamic Risk** | Position sizing | Risk mgmt | High | Effective at reducing size in bad conditions. |
| **Circuit Breaker** | Loss protection | Risk mgmt | High | Simple but prevents catastrophic drawdowns. |
| **Cooldown/Dedup** | Overtrading prevention | Risk mgmt | High | Prevents signal spam. |
| **Distance Filter** | S/R proximity | Filter | Medium | Prevents entries too close to resistance/support. |
| **No-Trade Zones** | Multi-factor | Filter | Medium | Composite filter; some conditions overlap with other gates. |

## Highest Edge Components

1. **BOS/Sweep Leading Triggers** — Institutional order flow detection. This is the primary alpha source.
2. **BTC Global Trend (Daily EMA200)** — Macro regime filter. Blocks counter-trend trades in strong BTC moves.
3. **MTF Alignment** — Multi-timeframe confirmation. Prevents fighting higher timeframe trends.
4. **Funding Rate Extremes** — Contrarian signal at market extremes. High winrate when funding is extreme.
5. **ADX Flat Filter** — Prevents range-trading losses. Simple but effective.

## Lowest Edge / Noise Components

1. **DMI** — Redundant with EMA alignment. Adds noise to scoring.
2. **Fear & Greed (middle range)** — Values 20-80 provide no useful signal.
3. **CoinGecko Data** — Only works for BTC/ETH; dead for all alts.
4. **News Filter** — Disabled by default. Data quality issues.
5. **EMA Slope Check** — Too aggressive; catches normal pullbacks.

## Edge Degradation Points

| Where | How Edge Is Lost |
|-------|-----------------|
| Signal Engine → Confidence V2 | Score "strong" can display as "weak" confidence |
| Context Scorer → Context Gates | Good technical signal killed by bad sentiment data |
| Dynamic Risk → Weak signals | Score 2-3 signals blocked even though they passed Signal Engine |
| BTC Global Trend → All alts | BTC downtrend blocks ALL alt BUY signals, even strong ones |
| MTF Alignment → 4h primary | Only 1 HTF (1d) available — less filtering power than 1h primary |
