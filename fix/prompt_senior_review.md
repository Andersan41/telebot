# Prompt for Senior Model Review

## Context

You are reviewing a crypto trading bot (Telegram + Binance Futures) that uses ICT methodology.
The bot scans symbols on 1h/4h timeframes every 15 minutes and sends signals to a Telegram channel.

**Repository:** https://github.com/Andersan41/telebot
**Branch:** feat/htf-bias-v2-premium-discount
**Prior audits:** `fix/bot_fix_v1.1.md`, `fix/bot_fix_v1.2.md`, `fix/bot_fix_v1.3.md`
**Modernization baseline:** `bot_fix_v2.0.md` (sibling project `E:\Projects\tgbot-claude`) — B-001…B-012
**Current audit:** `fix/bot_fix_v2.1.md` — B-013…B-027 (this cycle)

## What happened (2026-09-24)

v2.0 fixes were **not ported** to this repo. Live DB (`data/signals.db`) shows a mature
funnel with **zero decision traces** and a large false-fail class (`data_integrity_fail`
with sl/tp=0). A `note=` crash was fixed in the working tree this session but the live
process has not been restarted.

User claim "бот модернизирован по bot_fix_v2.0.md" does **not** match this working tree:
`save_signal_with_risk`, `entry_mode`, `max_sl_atr`, `poi_entry`, `BEGIN IMMEDIATE`,
`select_causal_sweep`, `closed_htf_history`, `first_touch`, `load_outcome_window` are absent.

## Scan Engine — Live DB stats (cumulative, not 7-day window)

| Metric | Value |
|--------|-------|
| signal_audit_log | 229,972 (pass 173,424 / fail 56,548) |
| decision_traces | **0** (migration bug) |
| signal_candidates | 0 |
| signals | 4 |
| signal_outcomes | 4 × HIT_TP |
| Config version | 11 (`_CONFIG_VERSION`) |
| App VERSION | 2.5.0 |

### Fail by reason (top)

| Reason | Count |
|--------|------:|
| mss_none | 35,405 |
| entry_trigger_no | 7,446 |
| htf_short_in_bullish | 5,919 |
| data_integrity_fail | 5,822 |
| ob_retest_failed | 651 |
| min_p_tp | 372 |
| volatility_too_low | 301 |
| htf_long_in_bearish | 227 |
| rr_too_low | 153 |

### Fail by stage

| Stage | Count |
|-------|------:|
| pattern_engine | 35,413 |
| entry_trigger | 7,446 |
| htf_bias | 6,156 |
| risk_engine | 5,881 |
| ob_retest | 651 |
| volatility_filter | 379 |
| min_p_tp | 372 |
| indicators | 195 |
| dedup | 55 |

### Critical observations

1. **decision_traces = 0** — `hypothesis_snapshot` missing from `trace_migrations`;
   every `trace.save()` fails with OperationalError, swallowed at DEBUG.
2. **data_integrity_fail** — meta `hyp_sl=0.0000,hyp_tp=0.0000`: scanner never checks
   `trade_plan.is_valid`; TradePlan defaults sl/tp=0.0.
3. **htf_short_in_bullish (5,919)** — uncommitted soft-penalty path writes audit
   `passed=False` while pipeline **continues**; funnel "PENALTY" not counted; config
   flags `block_short/long_*_htf` are dead (never read in scanner).
4. **ML logs** `P(TP)=65% | RR=1.00 | PF=1.86` — `rr_ratio=0` → `expected_rr=1.0`
   fallback + p_tp clamp 0.65. Floor 0.05 → min_p_tp blocks on some symbols.
5. **mss_none still dominant** at pattern_engine (35k) — B-006 same-type fix only
   partial (`structure.py:150`); no shared causal sweep selector.

## v2.0 port status (summary)

| v2.0 | Status |
|------|--------|
| B-001 MAX_SL_ATR | NOT ported |
| B-002 isfinite/directed geo | PARTIAL (U10 yes, isfinite no) |
| B-003 atomic save | NOT ported |
| B-004 FVG entry price | not verified |
| B-005 FVG causality | PARTIAL (ts off-by-one) |
| B-006 MSS same-type sweep | PARTIAL |
| B-007 HTF causal history | NOT ported |
| B-008/B-009 outcome window / EXPIRED | NOT ported |
| B-010 WR by pnl | NOT ported |
| B-011 trace features | BROKEN (migration) |
| B-012 lookback parity | PARTIAL (engine tail(100) ≠ live 50/100/50) |

## Pipeline architecture (current)

Pattern Engine → Feature Builder → Probability Engine → Risk Engine
(`scan_symbol_v2`). Audit reason codes in `storage/audit_reasons.py`.
HTF Bias V2 ON; premium/discount OFF; breakout quality soft gate.

## Uncommitted / operational state

- Working tree: `note=` crash fix (scanner 1024/1109); HTF soft-penalty diff;
  web/dashboard; bot `/report`; .env.example HTF flags flipped.
- Live process: **old code** — restart required after deploy of B-013/B-015.
- Tests: `pytest --co` = 1301; focused subset ~14 fails (MockSweep, wave_label str);
  full suite hangs without pytest-timeout.

## What I need you to review

### 1. Confirm or refute B-013…B-017 root causes

- Is the `trade_plan.is_valid` gap the full explanation for 5,822 data_integrity_fail?
- Is missing `hypothesis_snapshot` migration the full explanation for 0 traces?
- Any second path that could write traces to a different DB?
- Should HTF soft-penalty audit be `passed=True` + penalty meta, or a new reason code?

### 2. ML probability integrity

- After blocking invalid plans, is `_predict_rules` fallback on `rr_ratio<=0` correct,
  or should probability be skipped entirely?
- Is `p_tp` clamp [0.05, 0.65] still appropriate for expected_return+isotonic?
- When to retrain `models/probability_model.pkl` (features will shift)?

### 3. Gate/path schema

- Canonical GATE_ORDER list for gate_path JSON?
- How to represent PENALTY vs BLOCK in funnel counters and get_trace_stats?

### 4. v2.0 rebase vs cherry-pick

- Recommend full rebase of bot_fix_v2.0.md onto this branch, or cherry-pick only
  B-003, B-007–B-012?

### 5. Signal volume reality check

Given pattern_engine still kills 35k and entry_trigger 7.4k, what is the realistic
ceiling for 2–5 quality signals/week after B-013/B-015 (without loosening thresholds)?

## How to review

1. Read `fix/bot_fix_v2.1.md` for findings B-013…B-027 (machine-actionable fixes)
2. Read `fix/bot_fix_v1.3.md` for historical findings lineage
3. Read `scheduler/scanner.py` — `scan_symbol_v2()` gates, especially 940–1210 (HTF),
   1158–1181 (trade_plan), 2192/2264/2275 (save)
4. Read `storage/database.py` — `trace_migrations` (~407), `save_decision_trace` (~801)
5. Read `storage/trace.py` — GATE_ORDER, build_gate_path, save
6. Read `strategy/trade_plan.py`, `strategy/trade_engine.py`, `strategy/probability_engine.py`
7. Read `risk/engine.py` — evaluate()
8. Read `config/settings.py` — VERSION, min_p_tp, risk, HTF flags
9. Optional: sibling `E:\Projects\tgbot-claude\bot_fix_v2.0.md` for port diffs

## Constraints

- Must NOT send false signals (risk first)
- 2–5 quality signals/week target; 0/week unacceptable
- Config version 11; VERSION 2.5.0
- Do not loosen min_p_tp / min_rr until B-013/B-014 land and baseline remeasured
- Premium/discount stays OFF
- Telegram HTML requires `html.escape()` on dynamic substrings

---

## Output: create file fix/bot_fix_v2.2.md (or update bot_fix_v2.1.md)

After completing your review, save findings using the template below.
This file will be given to a junior AI (mimo) that will implement every fix.
Instructions must be **precise, unambiguous, and machine-actionable**.

### Template:

```markdown
# bot_fix_vX.Y.md — Senior model audit

## Date: [YYYY-MM-DD]
## Auditor: [model name]
## Branch: feat/htf-bias-v2-premium-discount
## Config version: 11

---

## I. Executive summary

[2-3 paragraphs: overall health, top 3 critical issues, expected impact of fixing them]

---

## II. Findings

For EACH finding use this EXACT format:

### [ID] — [Short title] — [Severity: CRITICAL/HIGH/MEDIUM/LOW]

**File:** `path/to/file.py`
**Lines:** XX-YY (or "class Foo, method bar")
**Current behavior:** [what the code does now]
**Expected behavior:** [what it should do]
**Why it matters:** [impact on signals, false positives, or risk]

**Evidence:**
```python
# exact code snippet that demonstrates the issue
```

**Fix:**
```python
# exact replacement code (copy-paste ready)
```

**Verification:** [how to confirm — specific test or log output]

---

## III. Summary table

| ID | Title | Severity | File | Status |
|----|-------|----------|------|--------|

---

## IV. Priority order

Ranked by (signal_volume_impact × confidence):

1. B-XXX — [title] — [why first]

---

## V. Config recommendations

| Param | Current | Recommended | Reason |
|-------|---------|-------------|--------|

---

## VI. Questions for the team

---

## VII. Implementation notes for mimo

- Which fixes are safe to apply immediately
- Which fixes need A/B testing
- Which fixes require server config changes
- Dependencies between fixes ("fix B-003 before B-004")
- Test files that need updating
```

### Rules for findings:

1. **Every finding MUST have a code snippet.** No vague statements.
2. **Every fix MUST be syntactically correct Python.** mimo will copy-paste directly.
3. **Do not report issues already fixed** — check bot_fix_v1.3 "Fixes applied" and
   bot_fix_v2.1 "Status" column.
4. **Number findings sequentially** continuing the open series (next free: B-028
   after v2.1, or restart B-001 only if starting a clean series and say so).
5. **Severity:** CRITICAL = crashes/wrong signals/dead telemetry, HIGH = >5% signal
   loss or decision integrity, MEDIUM = suboptimal, LOW = code quality.
6. **Mark uncertain findings** with "(UNCERTAIN)" in the title.
7. **Port-gap findings** must cite the v2.0 ID (B-001…B-012) they correspond to.
