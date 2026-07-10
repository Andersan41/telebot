# 08 — Architectural Conflict Map

## Conflict 1: BTC Triple-Gating

```
BTC Global Trend Gate (daily EMA200)
  └─ Blocks BUY if BTC < 77K (daily)
       └─ BTC Correlation Gate (4h EMA200)
            └─ Blocks BUY if BTC < 62K (4h)
                 └─ Context Scorer
                      └─ BTC correlation factor (weight 0.15 in context)
                           └─ Confidence V2
                                └─ BTC correlation score (weight 15)
```

**Conflict**: Two separate BTC gates use different timeframes (daily vs 4h) and different EMAs. A signal can pass 4h BTC check but fail daily BTC check (or vice versa). The daily gate runs first (position 3 in funnel), so the 4h gate is redundant when daily blocks. When daily passes, the 4h gate provides additional filtering.

**Impact**: Medium. The gates are complementary but not synchronized. During trending markets they agree; during ranging they may disagree.

## Conflict 2: Signal Engine Score vs Confidence V2 Quality

```
Signal Engine:
  score = 6 → score_verdict = "strong" → risk = 1.0% → should_trade = True

Confidence V2:
  quality = "weak" (conf=25%) → displayed as "СЛАБЫЙ"
```

**Conflict**: A signal can be "strong" by technical score (passes dynamic risk) but "weak" by confidence (displayed as weak). The user sees "СЛАБЫЙ" in Telegram but the signal was traded at full risk.

**Root Cause**: Signal Engine counts supporting reasons (simple count). Confidence V2 uses 10-factor weighted scoring with different weights. They measure different things.

**Impact**: High. User may see conflicting quality labels in Telegram vs actual trade size.

## Conflict 3: Context Score_verdict vs Score_verdict

```
Signal Engine:
  score_verdict = "moderate" (score=4)
  → dynamic_risk: should_trade = True

Context:
  verdict = "CONFLICTED" (score=-0.05)
  → context_min_verdict: CONFLICTED < WEAK → BLOCKED
```

**Conflict**: Context can override a technically valid signal. The context verdict is based on external data (F&G, Funding, OI) that may disagree with technical analysis.

**Impact**: This is by design — context is a deliberate filter. But it means a strong technical signal can be killed by sentiment.

## Conflict 4: Regime Compression Breakout Mode

```
Signal Engine (compression regime):
  1. Regime gate: compression → deferred
  2. After direction determined:
     - Needs: strong trigger + ATR expansion + high volume + ST aligned
     - If NOT met → BLOCKED (ENGINE_REGIME_BLOCK)

Signal Engine (non-compression):
  - Normal trigger gate: any leading trigger
  - Much easier to pass
```

**Conflict**: The same market conditions (trending alts during BTC compression) produce different outcomes depending on regime detection. Compression mode is 3-4x stricter.

**Impact**: Low. This is intentional risk management.

## Conflict 5: SL Recalculation Chain

```
Calculate SL:
  1. BOS-based SL (signal_engine.py:919-932)
  2. Structural SL (scanner.py:718-780) — only if not BOS-based
  3. Stop hunt buffer (scanner.py:766-778) — only if structural SL accepted
  4. SL distance guard (scanner.py:1132-1159) — shift to min/max

Result: SL can be modified 3 times before final value
```

**Conflict**: Each recalculation can move SL further from entry, changing R:R. The R:R guard (gate 16) checks the FINAL SL, but the signal was scored with the ORIGINAL SL.

**Impact**: Medium. A signal with good original R:R can fail the R:R guard after structural SL adjustment.

## Conflict 6: MTF Pre-Check vs Full MTF Gate

```
Pre-MTF check (before Signal Engine):
  required_alignment=1 (hardcoded)
  Used for: momentum entry mode in Signal Engine

Full MTF gate (after Signal Engine):
  required_alignment=min(len(higher_tfs), config.mtf_required_alignment)
  Default: 2 for 1h, 1 for 4h
  Used for: blocking signal
```

**Conflict**: Pre-check uses relaxed requirement (1), full gate uses stricter requirement (2). A signal can pass pre-check (enabling momentum entry) but fail full MTF gate.

**Impact**: Low. Momentum entry mode is already rare (requires ST+EMA+ADX+volume all aligned).

## Conflict 7: Dynamic Risk vs Score_verdict

```
Dynamic Risk:
  setup_quality = result.score_verdict  # "strong"/"moderate"/"weak"
  If "weak" → should_trade = False (blocked)

BUT:
  score_verdict = "weak" if score < 4
  min_score_for_signal = 2
  Signal Engine blocks if score < 2
  So score can be 2 or 3 → "weak" → dynamic_risk blocks
```

**Conflict**: Signal Engine allows score ≥ 2, but Dynamic Risk blocks score < 4. Effective minimum score = 4 for trading.

**Impact**: Intentional but confusing. The signal engine produces signals with score 2-3 that are immediately killed by dynamic risk. These show as "signal_engine: PASS" then "dynamic_risk: BLOCKED" in funnel logs.
