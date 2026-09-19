# Prompt for Senior Model Review

## Context

You are reviewing a crypto trading bot (Telegram + Binance Futures) that uses ICT methodology.
The bot scans 150 symbols on 1h/4h timeframes every 15 minutes and sends signals to a Telegram channel.

**Repository:** https://github.com/Andersan41/telebot
**Branch:** feat/htf-bias-v2-premium-discount
**Documentation:** See `fix/bot_fix_v1.2.md` in the repo for full context.

## What happened

The bot was blocking 100% of signals for over a week.
We identified and fixed 3 bugs (see section "Fixes applied" below), but the core question remains:
**Why does the bot produce zero signals despite 77,253 entries over 7 days?**

## Scan Engine — Funnel Statistics (7 days, live data)

| Metric | Value |
|--------|-------|
| Total Entries | 77,253 |
| Signals Sent | **0** |
| Config Version | 10 |

### Pipeline Funnel (all 0 sent, blocked at each gate):

| Gate | Blocked | % of Total |
|------|---------|-----------|
| Pattern Engine | 47,359 | 61.3% |
| Score Gate | 16,084 | 20.8% |
| Confirmation | 3,225 | 4.2% |
| Indicators | 1,988 | 2.6% |
| Displacement | 1,199 | 1.6% |
| Volatility | 983 | 1.3% |
| HTF Bias | 936 | 1.2% |
| Entry Trigger | 1,090 | 1.4% |
| Risk Engine | 153 | 0.2% |
| Portfolio Risk | 2 | 0.0% |

### Top Rejection Reasons (ranked):

| Reason | Count | % of Total |
|--------|-------|-----------|
| pattern_no_setup | 34,764 | 45.0% |
| score_too_low | 16,084 | 20.8% |
| mss_none | 12,179 | 15.8% |
| time_of_day_blocked | 4,003 | 5.2% |
| confirmation_low | 3,225 | 4.2% |
| data_integrity_fail | 2,141 | 2.8% |
| displacement_missing | 1,199 | 1.6% |
| entry_trigger_no | 1,090 | 1.4% |
| htf_short_in_bullish | 817 | 1.1% |
| volatility_too_low | 655 | 0.8% |

### Critical observations from these numbers:

1. **Pattern Engine kills 61%** — but `pattern_no_setup` (34,764) is only 73% of that.
   The remaining ~12,598 pattern_engine blocks are OTHER reasons (ranging, etc.)

2. **Score Gate kills 20.8%** — this is the SECOND biggest bottleneck. `score_too_low` = 16,084.
   This means ~16K setups DETECTED but with too few components (score < 2).

3. **MSS None = 12,179 (15.8%)** — sweep detected but no MSS classification.
   This is what P0-1 (reclaim_bars fix) should address.

4. **time_of_day_blocked = 4,003 (5.2%)** — THIS IS ACTIVE despite being "commented out"
   in the version we reviewed. Either: (a) the deployed code differs from repo, or
   (b) there's another code path we missed. **THIS NEEDS INVESTIGATION.**

5. **Confirmation low = 3,225 (4.2%)** — setup detected but confirmation_score < 2.

6. **Displacement missing = 1,199 (1.6%)** — sweep exists but no displacement candle.

7. **Zero signals through ALL gates** — not just one gate is the problem.
   The funnel is a cascade: even if we fix pattern_engine, score_gate blocks 16K more.

## What we already fixed (deployed 2026-09-19)

1. **P0-1 (reclaim_bars):** `classify_choch()` used wrong sweep for reclaim_bars.
   Should reduce `mss_none` from 12,179.

2. **P1-1 (SL dead zone):** 8% hard cap on dynamic_sl_max.
   Should reduce risk_engine blocks for wide-SL setups.

3. **P2-2 (block_neutral_htf):** Dead config field. Removed.

## What I need you to review

### 1. Why is score_too_low = 16,084 (20.8%)?

This is the BIGGEST surprise. Score gate should only block weak setups.
But 16K blocks means the score formula is too strict OR the components are not being detected.

Look at:
- `strategy/pattern_engine.py` — `_build_components()` method
- `strategy/pattern_engine.py` — `confirmation_score` property
- `scheduler/scanner.py:588-603` — score gate logic

Questions:
- What is the formula for confirmation_score?
- For reversal: what components contribute? (sweep=2, MSS=1, FVG=1, OB=1?)
- For continuation: what components contribute? (BOS=2, Trend=1, FVG=1, OB=1?)
- If a setup has score=1 (e.g., BOS-only continuation), it's blocked. Is this correct?
- Should we lower min_score_for_signal from 2 to 1?

### 2. Why is time_of_day_blocked = 4,003 if the code is "commented out"?

In `scanner.py:455-470` the time-of-day filter appears commented out.
But 4,003 blocks with this reason exist.

Possibilities:
- The deployed code on the server has a different version than the repo
- There's another code path that uses TIME_OF_DAY_BLOCKED
- The comment-out was not deployed

Action: Check if the bot running on the server matches the repo code.

### 3. Are the pattern_engine thresholds reasonable?

`pattern_no_setup` = 34,764 (45%) — nearly HALF of all entries.
This could mean:
- Markets genuinely don't have ICT patterns (unlikely for 150 symbols over 7 days)
- The detection is too strict (max_causal_bars, displacement_atr, etc.)

Look at:
- `strategy/pattern_engine.py` — `detect()` method
- What are the exact conditions for `no valid setup`?
- Is `max_causal_bars=10` too tight for 1h/4h?
- Is `displacement_atr >= 0.2` threshold reasonable?

### 4. The funnel cascade problem

Even if we fix ALL pattern_engine blocks (47,359), score_gate blocks 16,084 more.
Even if we fix score_gate, confirmation blocks 3,225 more.

The question is: **what is the realistic maximum number of signals?**

Assume:
- Pattern engine allows 30% instead of 0% → 23,176 pass
- Score gate allows 80% of those → 18,541 pass
- Confirmation allows 90% → 16,687 pass
- Other gates allow 95% → ~15,853 pass

Is this realistic? Or are the gates correlated (same setups blocked by multiple gates)?

### 5. What should we prioritize after the deployed fixes?

Given the 7-day data, rank these by expected impact:
- A: Lower min_score_for_signal from 2 to 1
- B: Tune pattern_engine (max_causal_bars, displacement_atr)
- C: Investigate time_of_day_blocked (4,003 blocks)
- D: Improve MSS detection (12,179 mss_none)
- E: Improve displacement detection (1,199 displacement_missing)
- F: Something else entirely

## How to review

1. Read `fix/bot_fix_v1.2.md` for full context on what was reviewed and fixed
2. Read `scheduler/scanner.py` — focus on `scan_symbol_v2()` (line 294+) and each gate
3. Read `strategy/pattern_engine.py` — focus on `detect()`, `_build_components()`, `confirmation_score`
4. Read `risk/engine.py` — focus on `evaluate()` method
5. Read `storage/audit_reasons.py` — all 40+ rejection codes
6. Read `config/settings.py` — all default thresholds

## Constraints

- Bot trades BTC/USDT and ETH/USDT primarily, 150 symbols total
- Timeframes: 1h and 4h
- Exchange: Binance Futures (via ccxt)
- Must NOT send false signals (risk management is priority)
- Currently 0 signals/week is unacceptable — need at least 2-5 quality signals/week
- Config version is 10 (latest: H-014 volatility_max_atr 5→8%, sweep_min_wick 0.02→0.01%)
