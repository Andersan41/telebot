"""
storage/audit_reasons.py — Structured reason codes for signal_audit_log.

Every BLOCKED/PASS point in scan_symbol_v2 maps to one of these codes.
The code is stable (never changes wording) so audit queries remain valid.
"""


# ── Phase 0: Hard Gates ────────────────────────────────────────────
COOLDOWN_ACTIVE = "cooldown_active"
PORTFOLIO_MAX_ACTIVE = "portfolio_max_active"
PORTFOLIO_MAX_RISK = "portfolio_max_risk"
DAILY_LIMIT_HIT = "daily_limit_hit"
POSITION_LIMIT_HIT = "position_limit_hit"
DATA_INTEGRITY_FAIL = "data_integrity_fail"
VOLATILITY_TOO_LOW = "volatility_too_low"
VOLATILITY_TOO_HIGH = "volatility_too_high"
REGIME_BLOCKED = "regime_blocked"
SCORE_TOO_LOW = "score_too_low"
SWEEP_CONTINUATION_MISMATCH = "sweep_continuation_mismatch"
BOS_NO_RETEST = "bos_no_retest"
SL_STRUCTURAL_TIGHT = "sl_structural_tight"
TIME_OF_DAY_BLOCKED = "time_of_day_blocked"

# ── Phase 1: Pattern Engine ────────────────────────────────────────
PATTERN_NO_SETUP = "pattern_no_setup"
SWEEP_NONE = "sweep_none"
SWEEP_FALSE_FILTERED = "sweep_false_filtered"
DISPLACEMENT_MISSING = "displacement_missing"
MSS_NONE = "mss_none"
MSS_DIRECTION_UNCLEAR = "mss_direction_unclear"
CONTINUATION_RANGING = "continuation_ranging"
CONTINUATION_NO_BOS = "continuation_no_bos"
CONTINUATION_BOS_NOT_BREAKING = "continuation_bos_not_breaking"
CONTINUATION_BOS_VS_TREND = "continuation_bos_vs_trend"

# ── Phase 1.4: Setup-Type Gates ───────────────────────────────────
ENTRY_ZONE_BLOCKED = "entry_zone_blocked"

# ── Phase 1.41: Breakout Quality ──────────────────────────────────
BREAKOUT_FAKE = "breakout_fake"

# ── Phase 1.42: Confirmation + OB Retest ──────────────────────────
CONFIRMATION_LOW = "confirmation_low"
OB_RETEST_FAILED = "ob_retest_failed"
OB_TOO_OLD = "ob_too_old"
OB_BROKEN = "ob_broken"
OB_MITIGATED = "ob_mitigated"
OB_TOO_FAR = "ob_too_far"
OB_NOT_RETESTED = "ob_not_retested"
OB_NO_CONFIRMATION = "ob_no_confirmation"

# ── Phase 1.43: Session ───────────────────────────────────────────
SESSION_BLOCKED = "session_blocked"

# ── Phase 1.45: HTF Bias ─────────────────────────────────────────
HTF_SHORT_IN_BULLISH = "htf_short_in_bullish"
HTF_LONG_IN_BEARISH = "htf_long_in_bearish"
HTF_CONTINUATION_MISMATCH = "htf_continuation_mismatch"
HTF_REVERSAL_MISMATCH = "htf_reversal_mismatch"

# ── Phase 1.5: SL/TP ─────────────────────────────────────────────
SL_TP_FAILED = "sl_tp_failed"

# ── Phase 1.7: LTF Confirmation ──────────────────────────────────
LTF_NO_CONFIRMATION = "ltf_no_confirmation"
LTF_DATA_UNAVAILABLE = "ltf_data_unavailable"

# ── Phase 3: Probability ──────────────────────────────────────────
MIN_P_TP = "min_p_tp"

# ── Phase 4: Risk Engine ──────────────────────────────────────────
RR_TOO_LOW = "rr_too_low"
SL_TOO_TIGHT = "sl_too_tight"
SL_TOO_WIDE = "sl_too_wide"
SL_ATR_CONFLICT = "sl_atr_conflict"
POSITION_SIZE_BELOW_MIN = "position_size_below_min"
NEGATIVE_EV = "negative_ev"

# ── Phase 4.5: Entry Trigger ──────────────────────────────────────
ENTRY_TRIGGER_NO = "entry_trigger_no"

# ── Phase 6: Dedup ────────────────────────────────────────────────
DEDUP_OB = "dedup_ob"
DEDUP_SAME_DIR = "dedup_same_dir"
DEDUP_CROSS_DIR = "dedup_cross_dir"

# ── Phase 7: Execution ────────────────────────────────────────────
SPREAD_TOO_WIDE = "spread_too_wide"
DEPTH_TOO_LOW = "depth_too_low"
CORRELATION_BLOCKED = "correlation_blocked"

# ── Pass ──────────────────────────────────────────────────────────
OK = "ok"
