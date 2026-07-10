# SYSTEM ARCHITECTURE — Trading Signal Bot

> **Reverse Engineering Document** — No code changes. Pure analysis.
> Generated: 2026-06-27

## Quick Start: How a Signal Reaches Telegram

A signal must pass **~26 sequential checks** across 5 scoring layers. First BLOCKED = signal dies.

```
Scheduler (cron :02,:17,:32,:47)
  → Scanner (per symbol × timeframe)
    → 6 pre-engine gates
      → Signal Engine (10 internal sub-gates)
        → 13 post-engine gates
          → Save to DB
            → Telegram
```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    SCHEDULER LAYER                       │
│  APScheduler CronTrigger → :02, :17, :32, :47          │
│  Circuit Breaker (3 consecutive losses → 30min pause)   │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                    SCANNER LAYER                         │
│  22 gates in sequential funnel                          │
│  Parallel: symbols × timeframes via asyncio.gather      │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                 SIGNAL ENGINE LAYER                      │
│  Weighted Factor Model (7 factors)                      │
│  Trigger → Confirmation → Verdict pipeline              │
│  10 internal sub-gates                                  │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                  SCORING LAYER                           │
│  Context Scorer (6 factors, -1.0 to 1.0)               │
│  Confidence V2 (10 factors, -100 to 100)               │
│  Dynamic Risk (position sizing)                         │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                  OUTPUT LAYER                            │
│  Database (signals.db)                                  │
│  Telegram Channel                                       │
│  Outcome Tracker (SL/TP monitoring)                     │
└─────────────────────────────────────────────────────────┘
```

## The 5 Scoring Systems

| # | System | Range | Purpose | Gates? |
|---|--------|-------|---------|--------|
| 1 | Signal Engine Score | 0-7 | Technical quality → sizing | Yes (min_score=2) |
| 2 | Score Verdict | strong/moderate/weak | Dynamic risk gate | Yes (weak→blocked) |
| 3 | Context Verdict | CONFIRMED/WEAK/CONFLICTED/BLOCKED | Market context filter | Yes (3 sub-gates) |
| 4 | Confidence V2 | -100 to 100 | Quality display | **NO** (display only) |
| 5 | Dynamic Risk | effective_risk_pct | Position sizing | Yes (weak→blocked) |

**Critical Insight**: Confidence V2 does NOT gate signals. A signal with confidence=10% ("weak") can still be traded at full risk if score_verdict="strong".

## Factor Reuse Map (Double Counting)

Factors used in multiple scoring systems:

| Factor | Signal Engine | Context | Conf V2 | Risk | Gates | Total |
|--------|:---:|:---:|:---:|:---:|:---:|:---:|
| BTC EMA200 | — | — | ✔ | ✔ | ✔ (2 gates) | 4 |
| ADX | ✔ | — | ✔ | — | ✔ | 3 |
| Funding | — | ✔ | ✔ | — | ✔ | 3 |
| Volume | ✔ | — | ✔ | — | — | 2 |
| Structure/BOS | ✔ | — | ✔ | — | ✔ | 3 |
| MTF | — | — | ✔ | — | ✔ | 2 |
| EMA | ✔ | — | — | — | ✔ | 2 |
| RSI | ✔ | — | ✔ | — | — | 2 |
| MACD | ✔ | — | ✔ | — | — | 2 |
| ETH | — | — | — | ✔ | ✔ | 2 |

## Gate Execution Order

| # | Gate | Fail Mode | Can Skip? |
|---|------|-----------|-----------|
| 0 | Circuit Breaker | OPEN | Yes (exception = pass) |
| 1 | Cooldown | OPEN | Yes |
| 2 | Portfolio Risk | OPEN | Yes |
| 3 | BTC Global Trend | OPEN | Yes (no data = pass) |
| 4 | Indicators | **CLOSED** | No (None = blocked) |
| 5 | Confirm TF | OPEN | Yes |
| 6 | Signal Engine | **CLOSED** | No (NO_SIGNAL = blocked) |
| 7 | Distance Filter | OPEN | Yes |
| 8 | TP Path | OPEN | Yes (disabled default) |
| 9 | MTF Alignment | OPEN | Yes |
| 10 | BTC Correlation | OPEN | Yes |
| 11 | ETH Correlation | OPEN | Yes |
| 12 | Volatility | OPEN | Yes |
| 13a | Context Timeout | **CLOSED** | No (fail closed) |
| 13b | Context Block | OPEN | Yes |
| 13c | Context Min Verdict | OPEN | Yes |
| 14 | News Filter | OPEN | Yes (disabled default) |
| 15 | SL Distance | OPEN | Yes |
| 16 | R:R Guard | OPEN | Yes |
| 17 | No-Trade Zones | OPEN | Yes |
| 18 | Dynamic Risk | OPEN | Yes |
| 19 | Dedup | OPEN | Yes |

## Key Numbers

- **Max Signal Score**: 115 (sum of all Signal Engine weights)
- **Effective Min Score for Trading**: 4 (Signal Engine allows 2, but Dynamic Risk blocks < 4)
- **Context Timeout**: 10s (fail closed)
- **Context Cache TTL**: 1800s (30min)
- **BTC Global Trend Cache**: 3600s (1h)
- **BTC Correlation Cache**: 3600s (1h)
- **Cooldown**: max(45min, TF_min × 2.0)
- **Circuit Breaker**: 3 consecutive losses → 30min pause

## Known Architectural Issues

1. **Score Disagreement**: Signal Engine "strong" ≠ Confidence V2 "strong". They use different factors and weights.
2. **BTC Triple-Gating**: Daily EMA200 + 4h EMA200 + Context BTC factor = 3 BTC filters.
3. **Dead Config**: 10+ config parameters exist but are never used in production.
4. **Alt Context Blindness**: CoinGecko data only works for BTC/ETH. Alts get no price_change_7d, no trending status.
5. **Score 2-3 Limbo**: Signal Engine produces signals with score 2-3 that are immediately killed by Dynamic Risk.

## Files Index

| File | Lines | Purpose |
|------|-------|---------|
| scheduler/scanner.py | 1485 | Main pipeline — 22 gates |
| strategy/signal_engine.py | 943 | Signal decision — 10 sub-gates |
| indicators/engine.py | 240 | Technical indicators |
| config/settings.py | 816 | All parameters |
| scoring/confidence_v2.py | 303 | 10-factor confidence |
| context/scorer.py | 312 | 6-factor context scoring |
| context/analyzer.py | 167 | Context data collection |
| risk/dynamic_risk.py | 298 | Position sizing + structural SL/TP |
| risk/volatility_regime.py | 70 | Volatility classification |
| risk/market_regime.py | 229 | Regime detection |
| risk/no_trade_zones.py | 98 | No-trade conditions |
| market_structure/structure.py | 324 | BOS/CHoCH + MTF alignment |
| market_structure/distance_filter.py | ~100 | S/R distance check |
| market_structure/tp_path.py | ~100 | TP path quality |
| derivatives/btc_correlation.py | 131 | BTC 4h EMA200 + structure |
| derivatives/eth_correlation.py | ~120 | ETH structure + momentum |
| derivatives/funding.py | 74 | Funding classification |
| derivatives/open_interest.py | 83 | OI pattern detection |
| liquidity/sweep.py | ~200 | Liquidity sweep detection |
| liquidity/order_blocks.py | ~200 | Order block detection |
| liquidity/fvg.py | ~100 | Fair value gap detection |
| scheduler/circuit_breaker.py | 87 | Loss circuit breaker |
| storage/database.py | ~400 | SQLite persistence |
| bot/notifier.py | ~150 | Telegram formatting |
