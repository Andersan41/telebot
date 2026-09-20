"""
scheduler/scanner.py — Основной сканер рынка.

ICT Core pipeline: Pattern Engine → Feature Builder → Probability Engine → Risk Engine
"""
import asyncio
import collections
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
import pandas as pd
from loguru import logger
from config.settings import config, get_active_symbols, VERSION, build_config_snapshot
from data.exchange_client import exchange_client
from indicators.engine import IndicatorValues
from strategy.signal_engine import SignalResult, SignalType
from storage.database import db
from context.analyzer import context_engine
from context.scorer import context_scorer, ContextVerdict
from monitoring.metrics import scan_duration_seconds, signals_total
from market_structure.structure import check_mtf_alignment, get_htf_directional_bias
from market_structure.htf_bias import get_htf_bias, HTFBias, extract_structure_dict
from market_structure.htf_bias_v2 import get_htf_bias_v2, HTFBiasResult
from risk.market_regime import RegimeDetector, MarketRegime
from elliott_wave.wave_types import WaveDegree
from scheduler.circuit_breaker import is_circuit_breaker_active, check_recent_losses
from storage.trace import DecisionTraceBuilder, ExecutionSnapshot
from storage.audit_reasons import (
    COOLDOWN_ACTIVE, PORTFOLIO_MAX_ACTIVE, PORTFOLIO_MAX_RISK,
    DAILY_LIMIT_HIT, POSITION_LIMIT_HIT, DATA_INTEGRITY_FAIL,
    VOLATILITY_TOO_LOW, VOLATILITY_TOO_HIGH,
    REGIME_BLOCKED, SCORE_TOO_LOW, SWEEP_CONTINUATION_MISMATCH,
    BOS_NO_RETEST, SL_STRUCTURAL_TIGHT, TIME_OF_DAY_BLOCKED,
    PATTERN_NO_SETUP, SWEEP_NONE, SWEEP_FALSE_FILTERED,
    DISPLACEMENT_MISSING, MSS_NONE, MSS_DIRECTION_UNCLEAR,
    CONTINUATION_RANGING, CONTINUATION_NO_BOS,
    CONTINUATION_BOS_NOT_BREAKING, CONTINUATION_BOS_VS_TREND,
    ENTRY_ZONE_BLOCKED, BREAKOUT_FAKE,
    CONFIRMATION_LOW, OB_RETEST_FAILED, OB_TOO_OLD, OB_BROKEN,
    OB_MITIGATED, OB_TOO_FAR, OB_NOT_RETESTED, OB_NO_CONFIRMATION,
    SESSION_BLOCKED,
    HTF_SHORT_IN_BULLISH, HTF_LONG_IN_BEARISH,
    HTF_CONTINUATION_MISMATCH, HTF_REVERSAL_MISMATCH,
    SL_TP_FAILED, LTF_NO_CONFIRMATION, LTF_DATA_UNAVAILABLE,
    MIN_P_TP, RR_TOO_LOW, SL_TOO_TIGHT, SL_TOO_WIDE,
    SL_ATR_CONFLICT, POSITION_SIZE_BELOW_MIN, NEGATIVE_EV,
    ENTRY_TRIGGER_NO, DEDUP_OB, DEDUP_SAME_DIR, DEDUP_CROSS_DIR,
    SPREAD_TOO_WIDE, DEPTH_TOO_LOW, CORRELATION_BLOCKED, OK,
)

# ── Analytical overlay imports (A12: not true shadow — outputs influence sizing) ──
from strategy.market_phase_engine import MarketPhaseEngine
from strategy.scenario_engine import ScenarioEngine
from strategy.trade_thesis import TradeThesisManager
from strategy.scenario_memory import scenario_memory

# Analytical overlay singletons
_market_phase_engine = MarketPhaseEngine()
_scenario_engine = ScenarioEngine()
_thesis_manager = TradeThesisManager()

# ── Timeframe-dependent cooldown ───────────────────────────────────────
_TF_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720, "1d": 1440,
}


def _smt_to_score(smt_result) -> float:
    """Convert SMTResult to numeric score for Probability Engine.

    Returns: -1.0 (bearish SMT) to 1.0 (bullish SMT), 0.0 for None/neutral.
    """
    if smt_result is None:
        return 0.0
    if smt_result.direction == "bullish":
        return 1.0
    elif smt_result.direction == "bearish":
        return -1.0
    return 0.0

# ── EMA Spread History for Regime Detection ────────────────────────────
# Stores rolling EMA spread values per symbol/timeframe across scan cycles.
# Used by _detect_regime() to compute ema_spread_trend (rising/falling/stable).
_ema_spread_history: dict[str, list[float]] = {}

# ── Audit config version ───────────────────────────────────────────
# BUMP this integer when ANY threshold in config/settings.py or
# risk/engine.py changes (e.g. min_rr_ratio, volatility limits,
# sl_absolute_min/max, max_active_signals, etc.).
# Required for audit log versioning: signals under different configs
# are tagged with different config_version for A/B analysis.
_CONFIG_VERSION = 10  # v10: volatility_max_atr=8%, sweep_min_wick=0.01% (H-014)


async def _audit_log(
    symbol: str,
    timeframe: str,
    ts_event: datetime,
    stage: str,
    reason_code: str,
    passed: bool,
    setup_type: Optional[str] = None,
    direction: Optional[str] = None,
    features_snapshot: Optional[str] = None,
    meta: Optional[str] = None,
    as_of_utc: Optional[datetime] = None,
    is_final: bool = True,
    data_age_ms: Optional[int] = None,
):
    """Write one row to signal_audit_log. Fire-and-forget — errors logged, not raised."""
    try:
        await db.create_audit_entry(
            symbol=symbol,
            timeframe=timeframe,
            ts_event=ts_event,
            config_version=_CONFIG_VERSION,
            stage=stage,
            reason_code=reason_code,
            passed=passed,
            setup_type=setup_type,
            direction=direction,
            features_snapshot=features_snapshot,
            meta=meta,
            as_of_utc=as_of_utc,
            is_final=is_final,
            data_age_ms=data_age_ms,
        )
    except Exception as e:
        logger.debug(f"[AUDIT] write failed: {e}")


def get_cooldown_minutes(timeframe: str, base_minutes: int, multiplier: float) -> int:
    """Effective cooldown = max(base_minutes, timeframe_minutes × multiplier)."""
    tf_minutes = _TF_MINUTES.get(timeframe, 60)
    return max(base_minutes, int(tf_minutes * multiplier))


# ── Signal Funnel Logging ──────────────────────────────────────────────
_FUNNEL_GATES = [
    "cooldown", "portfolio_risk", "indicators", "pattern_engine",
    "structure_alignment", "sweep_required", "regime_block",
    "sl_tp", "risk_engine", "dedup",
]


class _FunnelCounter:
    """Tracks per-scan-cycle funnel statistics."""
    def __init__(self):
        self.entered = 0
        self.passed = 0
        self.blocked_by = collections.Counter()

    def log_gate(self, symbol: str, tf: str, gate: str, status: str, detail: str = ""):
        tag = f"[FUNNEL] {symbol} {tf}"
        if status == "PASS":
            logger.debug(f"{tag} → {gate}: PASS")
        elif status == "BLOCKED":
            reason = f" ({detail})" if detail else ""
            logger.bind(tags="signal_block").info(f"{tag} → {gate}: BLOCKED{reason}")
            self.blocked_by[gate] += 1
        elif status == "ENTER":
            self.entered += 1

    def log_summary(self):
        if self.entered == 0:
            return
        parts = [f"entered={self.entered}", f"sent={self.passed}"]
        for gate, count in self.blocked_by.most_common():
            parts.append(f"{gate}={count}")
        logger.info(f"[FUNNEL SUMMARY] {', '.join(parts)}")


_current_funnel = _FunnelCounter()
_scan_lock = asyncio.Lock()


# ── Dynamic Thesis caches (per symbol/timeframe) ─────────────────────
# These persist across scan cycles so the graph updates in-place
# instead of rebuilding from scratch every time.
_dynamic_graphs: dict = {}         # key = f"{symbol}_{timeframe}" → LiquidityGraph
_dynamic_theses: dict = {}         # key = f"{symbol}_{timeframe}" → DynamicTradeThesis
_dynamic_bar_counters: dict = {}   # key = f"{symbol}_{timeframe}" → int (bar count)


# ── Helpers ────────────────────────────────────────────────────────────

async def _is_cooldown_active(symbol: str, timeframe: str) -> tuple[bool, int]:
    """Check if cooldown is active for symbol+timeframe.
    
    In ob_aware mode, always returns False (cooldown handled in dedup phase).
    """
    # In ob_aware mode, skip early cooldown — dedup phase handles OB comparison
    if getattr(config, 'cooldown_mode', 'ob_aware') == 'ob_aware':
        return False, 0
    
    last = await db.get_cooldown(symbol, timeframe)
    if last is None:
        return False, 0
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - last
    effective = get_cooldown_minutes(
        timeframe, config.signal_cooldown_minutes, config.signal_cooldown_tf_multiplier
    )
    return delta < timedelta(minutes=effective), effective


async def _set_cooldown(symbol: str, timeframe: str) -> None:
    await db.set_cooldown(symbol, timeframe, datetime.now(timezone.utc))


async def _get_indicators(symbol: str, timeframe: str):
    df = await exchange_client.fetch_ohlcv(
        symbol,
        timeframe,
        limit=config.trading.candles_limit,
    )

    if df is None:
        logger.warning(f"OHLCV unavailable for {symbol} {timeframe}")
        return None

    if hasattr(df, "empty") and getattr(df, "empty", False) is True:
        logger.warning(f"Empty dataframe for {symbol} {timeframe}")
        return None

    from indicators.engine import indicator_engine
    ind = indicator_engine.calculate(df, symbol, timeframe)

    if ind is None:
        logger.warning(f"Indicator calculation failed for {symbol} {timeframe}")
        return None

    return ind, df


def _detect_regime(ind: IndicatorValues, df, symbol: str = "", timeframe: str = "") -> Optional[MarketRegime]:
    """Detect market regime from indicator values and OHLCV data.

    Maintains a rolling EMA spread history per symbol/timeframe across scan cycles
    to accurately detect rising/falling EMA spread trends.
    """
    try:
        adx = float(ind.adx) if ind.adx is not None else 20.0
        current_atr = float(ind.atr) if ind.atr is not None else 0.0
        current_volume = float(ind.volume) if ind.volume is not None else 0.0

        if len(df) >= 10:
            atr_history = []
            for _, row in df.tail(config.risk.regime_atr_lookback).iterrows():
                high_low = row['high'] - row['low']
                atr_history.append(float(high_low))
        else:
            atr_history = [current_atr] * 10

        ema_fast = float(ind.ema_fast) if ind.ema_fast is not None else 0.0
        ema_slow = float(ind.ema_slow) if ind.ema_slow is not None else 0.0
        current_spread = abs(ema_fast - ema_slow) if ema_slow > 0 else 0.0

        # Rolling EMA spread history across scan cycles
        history_key = f"{symbol}_{timeframe}" if symbol and timeframe else "_global"
        if history_key not in _ema_spread_history:
            _ema_spread_history[history_key] = []
        _ema_spread_history[history_key].append(current_spread)
        # Keep last N values based on config window
        max_history = max(config.risk.regime_ema_spread_window * 2, 10)
        _ema_spread_history[history_key] = _ema_spread_history[history_key][-max_history:]
        ema_spread_history = list(_ema_spread_history[history_key])

        if len(df) >= 10:
            volume_history = [float(row['volume']) for _, row in df.tail(20).iterrows()]
        else:
            volume_history = [current_volume] * 10

        detector = RegimeDetector(
            adx=adx,
            atr_history=atr_history,
            ema_spread_history=ema_spread_history,
            volume_history=volume_history,
            current_atr=current_atr,
            current_volume=current_volume,
        )
        return detector.detect()
    except Exception as e:
        logger.warning(f"Regime detection failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════
#  ICT Core Pipeline
# ══════════════════════════════════════════════════════════════════════

async def scan_symbol_v2(symbol: str, timeframe: str, notify_callback, blocked_callback=None) -> Optional[SignalResult]:
    """ICT Core pipeline: Pattern Engine → Feature Builder → Probability Engine → Risk Engine.

    Hard gates: Cooldown, Portfolio Risk, Data Integrity, R:R, SL limits, Dedup.
    All indicator-based filtering removed.
    """
    from strategy.pattern_engine import pattern_engine
    from strategy.feature_builder import feature_builder, _detect_session
    from strategy.probability_engine import probability_engine
    from risk.engine import risk_engine, PortfolioState
    from strategy.signal_engine import _calculate_sl_tp

    with scan_duration_seconds.labels(timeframe=timeframe).time():
        _current_funnel.log_gate(symbol, timeframe, "start", "ENTER")
        trace = DecisionTraceBuilder(symbol, timeframe)

        # ═══ Phase 0: Hard Gates (capital protection) ═══

        # 0.1 Cooldown
        cooldown_active, cooldown_minutes = await _is_cooldown_active(symbol, timeframe)
        if cooldown_active:
            _current_funnel.log_gate(symbol, timeframe, "cooldown", "BLOCKED",
                                     f"required {cooldown_minutes}m")
            trace.blocked("cooldown", f"cooldown {cooldown_minutes}m active")
            await trace.save(db)
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "cooldown", COOLDOWN_ACTIVE, False)
            return None
        trace.passed("cooldown")
        _current_funnel.log_gate(symbol, timeframe, "cooldown", "PASS")

        # 0.2 Portfolio risk
        max_sigs = config.max_active_signals
        max_risk = config.max_portfolio_risk_pct
        active_count = await db.get_active_signals_count()
        if active_count >= max_sigs:
            reason = f"max active signals ({active_count}/{max_sigs})"
            _current_funnel.log_gate(symbol, timeframe, "portfolio_risk", "BLOCKED", reason)
            trace.blocked("portfolio_risk", reason)
            await trace.save(db)
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "portfolio_risk", PORTFOLIO_MAX_ACTIVE, False)
            return None
        portfolio_risk = await db.get_portfolio_risk_sum()
        if portfolio_risk >= max_risk:
            reason = f"portfolio risk {portfolio_risk:.1f}% >= {max_risk}%"
            _current_funnel.log_gate(symbol, timeframe, "portfolio_risk", "BLOCKED", reason)
            trace.blocked("portfolio_risk", reason)
            await trace.save(db)
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "portfolio_risk", PORTFOLIO_MAX_RISK, False)
            return None
        trace.passed("portfolio_risk")
        _current_funnel.log_gate(symbol, timeframe, "portfolio_risk", "PASS")

        # 0.2b Daily Limits (TZ §9.3)
        from risk.daily_limits import daily_limits
        can_trade, remaining_risk, dl_reason = daily_limits.can_open_trade(
            risk_per_trade_pct=config.risk_engine.base_risk_pct
        )
        if not can_trade:
            reason = f"daily limits: {dl_reason}"
            _current_funnel.log_gate(symbol, timeframe, "daily_limits", "BLOCKED", reason)
            trace.blocked("daily_limits", reason)
            await trace.save(db)
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "daily_limits", DAILY_LIMIT_HIT, False)
            return None
        trace.passed("daily_limits")
        _current_funnel.log_gate(symbol, timeframe, "daily_limits", "PASS")

        # 0.2c Position Limits (TZ §9.4)
        from risk.daily_limits import daily_limits as _dl
        from storage.database import db as _db
        _dl_state = _dl.get_state()
        _active_outcomes = await _db.get_open_outcomes()
        _total_positions = len(_active_outcomes)

        # Direction-specific position counts via JOIN with signals table
        _long_positions = 0
        _short_positions = 0
        try:
            _outcomes_with_dir = await _db.get_open_outcomes_with_direction()
            for _o, _sig_type in _outcomes_with_dir:
                if _sig_type == "BUY":
                    _long_positions += 1
                elif _sig_type == "SELL":
                    _short_positions += 1
        except Exception:
            pass  # fallback: direction counts stay 0

        if _total_positions >= config.risk.max_positions_total:
            reason = f"max positions ({_total_positions}/{config.risk.max_positions_total})"
            _current_funnel.log_gate(symbol, timeframe, "position_limits", "BLOCKED", reason)
            trace.blocked("position_limits", reason)
            await trace.save(db)
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "position_limits", POSITION_LIMIT_HIT, False)
            return None

        # Direction-specific limits (check if signal direction would exceed limit)
        # (direction not yet known here, so we check total only at this stage)
        trace.passed("position_limits")
        _current_funnel.log_gate(symbol, timeframe, "position_limits", "PASS")

        # 0.3 Fetch OHLCV + Indicators
        ind_result = await _get_indicators(symbol, timeframe)
        if ind_result is None:
            _current_funnel.log_gate(symbol, timeframe, "indicators", "BLOCKED", "unavailable")
            trace.blocked("indicators", "OHLCV/indicator unavailable")
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "indicators", DATA_INTEGRITY_FAIL, False)
            await trace.save(db)
            return None
        ind, df = ind_result
        trace.passed("indicators")
        _current_funnel.log_gate(symbol, timeframe, "indicators", "PASS")

        # Compute point-in-time snapshot: as_of_utc = last closed candle timestamp
        # Note: exchange_client already drops the forming candle (iloc[:-1]),
        # so df.index[-1] is the last CLOSED candle.
        _as_of_utc = None
        _data_age_ms = None
        if df is not None and len(df) >= 1 and isinstance(df.index, pd.DatetimeIndex):
            _as_of_utc = df.index[-1]
            if _as_of_utc.tzinfo is None:
                _as_of_utc = _as_of_utc.replace(tzinfo=timezone.utc)
            _data_age_ms = int((datetime.now(timezone.utc) - _as_of_utc).total_seconds() * 1000)

        # 0.4 Volatility Filter (TZ §11.2) — hard gate
        if ind.atr and ind.close and ind.close > 0:
            atr_pct = ind.atr / ind.close * 100
            vol_min = config.trading.volatility_min_atr_percent
            vol_max = config.trading.volatility_max_atr_percent
            if atr_pct < vol_min or atr_pct > vol_max:
                reason = f"volatility {atr_pct:.2f}% outside [{vol_min}, {vol_max}]"
                _current_funnel.log_gate(symbol, timeframe, "volatility_filter", "BLOCKED", reason)
                trace.blocked("volatility_filter", reason)
                await trace.save(db)
                _vcode = VOLATILITY_TOO_LOW if atr_pct < vol_min else VOLATILITY_TOO_HIGH
                await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                 "volatility_filter", _vcode, False)
                return None
        trace.passed("volatility_filter")
        _current_funnel.log_gate(symbol, timeframe, "volatility_filter", "PASS")

        # 0.4b Compression Regime Gate (data-driven: 67% SL in compression)
        # block_compression_regime was dead code — now real gate
        _regime_early = _detect_regime(ind, df, symbol, timeframe)
        if _regime_early and _regime_early.regime == "compression" and config.trading.block_compression_regime:
            reason = f"compression regime (SL rate 67% — hard gate enabled)"
            _current_funnel.log_gate(symbol, timeframe, "regime_block", "BLOCKED", reason)
            trace.blocked("regime_block", reason)
            trace.set_version(VERSION, build_config_snapshot())
            await trace.save(db)
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "regime_block", REGIME_BLOCKED, False,
                             direction="unknown")
            return None

        # 0.4c Time-of-Day Gate — DISABLED (needs more live data to validate)
        # try:
        #     _current_hour = datetime.now(timezone.utc).hour
        #     _blocked_hours_str = getattr(config.trading, 'blocked_hours', '9,11,12,16')
        #     _blocked_hours = [int(h.strip()) for h in _blocked_hours_str.split(',') if h.strip()]
        #     if _current_hour in _blocked_hours:
        #         reason = f"blocked hour {_current_hour}:00 UTC (0% WR in live data)"
        #         _current_funnel.log_gate(symbol, timeframe, "time_of_day", "BLOCKED", reason)
        #         trace.blocked("time_of_day", reason)
        #         trace.set_version(VERSION, build_config_snapshot())
        #         await trace.save(db)
        #         await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
        #                          "time_of_day", TIME_OF_DAY_BLOCKED, False,
        #                          direction="unknown")
        #         return None
        # except Exception:
        #     pass

        # ═══ Phase 1: Pattern Engine (ICT setup detection) ═══

        _df_clean = df.dropna(subset=["open", "high", "low", "close", "volume"])
        sweeps = []
        order_blocks = []
        structure = None
        fvgs = []
        candle_quality = None

        try:
            if len(_df_clean) >= 10:
                from liquidity.sweep import detect_sweeps
                from liquidity.order_blocks import detect_order_blocks, find_ob_for_sweep
                from market_structure.structure import analyze_structure
                from liquidity.fvg import detect_fvg
                from liquidity.candle_quality import analyze_last_candle

                sweeps = detect_sweeps(_df_clean, lookback=50)
                order_blocks = detect_order_blocks(_df_clean, lookback=100)
                candle_quality = analyze_last_candle(_df_clean, atr_value=ind.atr)
                fvgs = detect_fvg(_df_clean, lookback=getattr(config, "liquidity_fvg_lookback", 100))

                # TZ §6.2: For each valid sweep, find OB by backward scan
                # and add to order_blocks if not already present
                for sweep in sweeps:
                    if not sweep.is_valid:
                        continue
                    sweep_idx = sweep.candle_index if hasattr(sweep, 'candle_index') else len(_df_clean) - 1
                    sweep_ts = sweep.timestamp if hasattr(sweep, 'timestamp') else datetime.now(timezone.utc)
                    # Convert int timestamp to datetime if needed
                    if isinstance(sweep_ts, (int, float)):
                        sweep_ts = datetime.fromtimestamp(sweep_ts, tz=timezone.utc)
                    elif sweep_ts and hasattr(sweep_ts, 'tzinfo') and sweep_ts.tzinfo is None:
                        sweep_ts = sweep_ts.replace(tzinfo=timezone.utc)
                    ob = find_ob_for_sweep(
                        _df_clean,
                        sweep_index=sweep_idx,
                        sweep_direction=sweep.type,
                        sweep_timestamp=sweep_ts,
                        lookback=20,
                    )
                    if ob is not None:
                        # Avoid duplicates by checking timestamp + type
                        existing = [
                            o for o in order_blocks
                            if o.type == ob.type and abs(o.midpoint - ob.midpoint) / max(ob.midpoint, 1e-10) < 0.001
                        ]
                        if not existing:
                            order_blocks.append(ob)
                            logger.debug(
                                f"Found sweep OB: {ob.type} midpoint={ob.midpoint:.4f} "
                                f"for sweep at idx={sweep_idx}"
                            )

                # Compute displacement_atr for MSS classification
                _disp_atr = 0.0
                if candle_quality and ind.atr and ind.atr > 0:
                    _disp_atr = candle_quality.body_atr_ratio if hasattr(candle_quality, 'body_atr_ratio') else 0.0

                structure = analyze_structure(
                    _df_clean, lookback=50,
                    sweeps=sweeps,
                    displacement_atr=_disp_atr,
                    atr_value=ind.atr if ind.atr else 0.0,
                )
        except Exception as e:
            logger.warning(f"Pattern analysis failed for {symbol} {timeframe}: {e}")

        setup = pattern_engine.detect(
            sweeps=sweeps,
            order_blocks=order_blocks,
            structure=structure,
            fvgs=fvgs,
            candle_quality=candle_quality,
            current_price=ind.close,
            atr=ind.atr if ind.atr else 0.0,
        )

        if not setup.detected:
            _current_funnel.log_gate(symbol, timeframe, "pattern_engine", "BLOCKED",
                                     setup.rejection_reason or "no setup")
            trace.blocked("pattern_engine", setup.rejection_reason or "no ICT setup")
            trace.set_features({"components": setup.components_count})
            trace.set_version(VERSION, build_config_snapshot())
            await trace.save(db)
            _rej = setup.rejection_reason or "no setup"
            _rcode = PATTERN_NO_SETUP
            if "no sweep" in _rej:
                _rcode = SWEEP_NONE
            elif "no MSS" in _rej:
                _rcode = MSS_NONE
            elif "MSS direction" in _rej:
                _rcode = MSS_DIRECTION_UNCLEAR
            elif "ranging" in _rej:
                _rcode = CONTINUATION_RANGING
            elif "no BOS" in _rej:
                _rcode = CONTINUATION_NO_BOS
            elif "BOS level" in _rej:
                _rcode = CONTINUATION_BOS_NOT_BREAKING
            elif "BOS bearish vs" in _rej or "BOS bullish vs" in _rej:
                _rcode = CONTINUATION_BOS_VS_TREND
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "pattern_engine", _rcode, False)
            logger.debug(f"No ICT setup: {symbol} {timeframe} — {setup.rejection_reason}")
            return None

        _current_funnel.log_gate(symbol, timeframe, "pattern_engine", "PASS",
                                 f"direction={setup.direction} components={setup.components_found}")
        trace.passed("pattern_engine")

        # 1.0b Score Quality Gate — controlled by MIN_SCORE_FOR_SIGNAL (default 2)
        # components_count = number of detected ICT components
        _min_score = config.scoring.min_score_for_signal
        if setup.components_count < _min_score:
            reason = f"score={setup.components_count} < min {_min_score} (components: {setup.components_found})"
            _current_funnel.log_gate(symbol, timeframe, "score_gate", "BLOCKED", reason)
            trace.blocked("score_gate", reason)
            trace.set_version(VERSION, build_config_snapshot())
            await trace.save(db)
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "score_gate", SCORE_TOO_LOW, False,
                             setup_type=setup.setup_type, direction=setup.direction)
            return None
        _current_funnel.log_gate(symbol, timeframe, "score_gate", "PASS",
                                 f"score={setup.components_count}")
        trace.passed("score_gate")

        # ═══ Phase 1.4: Setup-Type-Specific Gates ═══
        # Reversal: sweep + displacement + MSS (all hard gates)
        # Continuation: BOS + trend alignment (all hard gates)
        # Entry armed (OB/FVG proximity) — soft, log only

        # Detect regime (used later for analytics)
        _regime_for_gates = _detect_regime(ind, df, symbol, timeframe)

        if setup.setup_type == "reversal":
            # ── Reversal Gates ──
            if not setup.has_sweep:
                reason = "reversal: no sweep"
                _current_funnel.log_gate(symbol, timeframe, "sweep_required", "BLOCKED", reason)
                trace.blocked("sweep_required", reason)
                trace.set_version(VERSION, build_config_snapshot())
                await trace.save(db)
                await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                 "sweep_required", SWEEP_NONE, False,
                                 setup_type="reversal", direction=setup.direction)
                return None
            trace.passed("sweep_required")
            _current_funnel.log_gate(symbol, timeframe, "sweep_required", "PASS")

            if config.reversal_require_displacement and not setup.has_displacement:
                reason = "reversal: no displacement (reversal_require_displacement=true)"
                _current_funnel.log_gate(symbol, timeframe, "displacement_gate", "BLOCKED", reason)
                trace.blocked("displacement_gate", reason)
                trace.set_version(VERSION, build_config_snapshot())
                await trace.save(db)
                await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                 "displacement_gate", DISPLACEMENT_MISSING, False,
                                 setup_type="reversal", direction=setup.direction)
                return None
            trace.passed("displacement_gate")
            _current_funnel.log_gate(symbol, timeframe, "displacement_gate", "PASS")

            if not setup.has_mss:
                # Soft gate: sweep-only reversal (no MSS) — log but allow through
                # MSS is a quality signal, not a hard gate for data collection
                _current_funnel.log_gate(symbol, timeframe, "mss_gate", "SOFT",
                                         f"sweep-only (no MSS) — weaker setup")
                trace.passed("mss_gate")
            trace.passed("mss_gate")
            _current_funnel.log_gate(symbol, timeframe, "mss_gate", "PASS",
                                     f"mss_score={setup.mss_score:.0f}")

        elif setup.setup_type == "continuation":
            # ── Continuation Gates ──
            if not setup.has_bos:
                reason = "continuation: no BOS"
                _current_funnel.log_gate(symbol, timeframe, "bos_gate", "BLOCKED", reason)
                trace.blocked("bos_gate", reason)
                trace.set_version(VERSION, build_config_snapshot())
                await trace.save(db)
                await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                 "bos_gate", CONTINUATION_NO_BOS, False,
                                 setup_type="continuation", direction=setup.direction)
                return None
            trace.passed("bos_gate")
            _current_funnel.log_gate(symbol, timeframe, "bos_gate", "PASS",
                                     f"bos_type={setup.bos_type}")

            # 1.4b BOS Retest Filter (data-driven: 57% SL on impulse tail)
            # Require at least 2 bars after BOS to ensure retest, not impulse entry
            if structure and structure.last_bos and len(df) > 0:
                _bars_since_bos = len(df) - 1 - structure.last_bos.candle_index
                if _bars_since_bos < 2:
                    reason = f"bars_since_bos={_bars_since_bos} < 2 (impulse tail entry — 57% SL)"
                    _current_funnel.log_gate(symbol, timeframe, "bos_retest", "BLOCKED", reason)
                    trace.blocked("bos_retest", reason)
                    trace.set_version(VERSION, build_config_snapshot())
                    await trace.save(db)
                    await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                     "bos_retest", BOS_NO_RETEST, False,
                                     setup_type="continuation", direction=setup.direction)
                    return None
            _current_funnel.log_gate(symbol, timeframe, "bos_retest", "PASS")
            trace.passed("bos_retest")

        # ── Entry Zone (soft by default, hard when require_entry_zone=true) ──
        if not setup.entry_armed:
            if config.require_entry_zone:
                reason = "price not in OB/FVG zone (require_entry_zone=true)"
                _current_funnel.log_gate(symbol, timeframe, "entry_zone", "BLOCKED", reason)
                trace.blocked("entry_zone", reason)
                trace.set_version(VERSION, build_config_snapshot())
                await trace.save(db)
                await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                 "entry_zone", ENTRY_ZONE_BLOCKED, False,
                                 setup_type=setup.setup_type, direction=setup.direction)
                logger.info(f"EntryZone BLOCKED: {symbol} {timeframe} — {reason}")
                return None
            else:
                logger.debug(
                    f"Entry not armed: {symbol} {timeframe} — "
                    f"price not in OB/FVG zone (soft mode, signal fires anyway)"
                )
        else:
            _current_funnel.log_gate(symbol, timeframe, "entry_zone", "PASS")
            trace.passed("entry_zone")

        # ═══ Phase 1.42: Confirmation Score Gate (TZ §6.4) ═══
        # Weighted: BOS=2, FVG=1, OB=1. Minimum=2 for entry.
        _conf_score = setup.confirmation_score
        if _conf_score < 2:
            reason = f"confirmation_score={_conf_score} < min 2 (reversal: Sweep=2,MSS=1,FVG=1,OB=1; continuation: BOS=2,FVG=1,OB=1)"
            _current_funnel.log_gate(symbol, timeframe, "confirmation_score", "BLOCKED", reason)
            trace.blocked("confirmation_score", reason)
            trace.set_version(VERSION, build_config_snapshot())
            await trace.save(db)
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "confirmation_score", CONFIRMATION_LOW, False,
                             setup_type=setup.setup_type, direction=setup.direction,
                             meta=f"score={_conf_score}")
            logger.info(f"ConfirmationScore BLOCKED: {symbol} {timeframe} — {reason}")
            return None
        _current_funnel.log_gate(symbol, timeframe, "confirmation_score", "PASS",
                                 f"score={_conf_score}")
        trace.passed("confirmation_score")

        # ═══ Phase 1.44: SMT Divergence (soft feature — no blocking) ═══
        _smt_result = None
        if config.derivatives.smt_enabled:
            try:
                from derivatives.smt_divergence import fetch_smt_divergence
                _smt_result = await fetch_smt_divergence(symbol)
            except Exception as e:
                logger.debug(f"SMT divergence check failed for {symbol}: {e}")
        _smt_detail = _smt_result.detail if _smt_result else "SMT disabled or no data"
        trace.record("smt_divergence", True)
        logger.debug(f"SMT {symbol}: {_smt_detail}")

        # ═══ Phase 1.41: Breakout Quality (AMD sweep vs real breakout) ═══
        if config.breakout_quality_enabled:
            try:
                from liquidity.breakout_quality import classify_breakout
                _breakout_gate_passed = True
                _breakout_reason = ""

                _breakout_oi = None
                try:
                    from context.fetcher import context_fetcher
                    _oi_res = await context_fetcher.fetch_open_interest(symbol)
                    if _oi_res and _oi_res.get("open_interest_delta") is not None and not _oi_res.get("is_warmup"):
                        _breakout_oi = float(_oi_res["open_interest_delta"])
                except Exception:
                    _breakout_oi = None

                _bq = classify_breakout(
                    df=_df_clean,
                    direction=setup.direction,
                    atr=ind.atr if ind.atr else 0.0,
                    oi_change_pct=_breakout_oi,
                    lookback=config.breakout_quality_lookback,
                )

                logger.info(
                    f"[BREAKOUT] {symbol} {timeframe} [{setup.direction}] "
                    f"verdict={_bq.verdict} score={_bq.score:.0f} body={_bq.body_pct:.2f} "
                    f"retention={_bq.retention} vol={_bq.volume_ratio:.1f}x OI={_bq.oi_change_pct} "
                    f"triggers={_bq.triggers} warnings={_bq.warnings}"
                )
                trace.record("breakout_quality", _bq.verdict == "real")

                if config.breakout_quality_hard_gate:
                    # Block ONLY obvious AMD fake-breaks (revearse wick past a closed-in
                    # range). Signals with a low score are still allowed: the bot's entries
                    # are pullbacks, not range breaks, so a bare min-score gate kills ~99%
                    # of executable signals (A/B on the bot's own pipeline, see
                    # backtest/run_breakout_gate_ab.py).
                    if _bq.verdict == "fake":
                        _breakout_gate_passed = False
                        _breakout_reason = (
                            f"AMD fake-break (verdict={_bq.verdict}, wick {_bq.pierce_pct:.1f}% "
                            f"past boundary, close retraced inside range)"
                        )
                    else:
                        _breakout_gate_passed = True

                if config.breakout_quality_hard_gate:
                    if _breakout_gate_passed:
                        _current_funnel.log_gate(symbol, timeframe, "breakout_quality", "PASS",
                                                 f"verdict={_bq.verdict} score={_bq.score:.0f}")
                        trace.passed("breakout_quality")
                    else:
                        reason = _breakout_reason or "breakout_quality gate failed"
                        _current_funnel.log_gate(symbol, timeframe, "breakout_quality", "BLOCKED", reason)
                        trace.blocked("breakout_quality", reason)
                        trace.set_version(VERSION, build_config_snapshot())
                        await trace.save(db)
                        logger.info(f"BreakoutQuality BLOCKED: {symbol} {timeframe} — {reason}")
                        return None
            except Exception as e:
                logger.debug(f"Breakout quality check failed for {symbol} {timeframe}: {e}")

        # ═══ Phase 1.42: OB Retest + Mitigation Gate (v2.5) ═══
        _nearest_ob = None
        if config.require_ob_retest and setup.has_ob and setup.direction:
            _ob_gate_passed = False
            _ob_gate_reason = ""

            # Find the active OB for this direction
            _ob_dir = 'bullish' if setup.direction == 'buy' else 'bearish'
            _relevant_obs = [ob for ob in order_blocks if ob.type == _ob_dir and ob.is_valid]

            if _relevant_obs:
                _nearest_ob = min(_relevant_obs, key=lambda ob: abs(ob.midpoint - setup.ob_midpoint))

                # Check 1: OB age — if older than max_age and not retested → mitigated
                _ob_age = len(_df_clean) - _nearest_ob.candle_index - 1
                _max_age = getattr(config.liquidity, 'ob_max_age_candles', 35)
                if _ob_age > _max_age and not _nearest_ob.retested:
                    _ob_gate_reason = f"OB too old ({_ob_age} candles) and not retested"
                else:
                    # Check 2: OB mitigation state
                    from liquidity.ob_state import get_ob_state, OBState
                    _ob_state = get_ob_state(
                        _df_clean, _nearest_ob.high, _nearest_ob.low, _nearest_ob.type,
                    )
                    if _ob_state == OBState.BROKEN:
                        _ob_gate_reason = f"OB broken (state={_ob_state.value})"
                    elif _ob_state == OBState.MITIGATED:
                        _ob_gate_reason = f"OB mitigated (state={_ob_state.value})"
                    else:
                        # Check 3: OB retest confirmation
                        # Price must have returned to OB zone
                        _last_close = float(_df_clean['close'].iloc[-1])
                        _ob_touched = (
                            _nearest_ob.low <= _last_close <= _nearest_ob.high
                            or _nearest_ob.retested
                        )

                        if not _ob_touched:
                            # Check if price is within MAX_OB_DISTANCE_PCT
                            _dist = abs(_last_close - _nearest_ob.midpoint) / _last_close * 100
                            _max_dist = getattr(config, 'max_ob_distance_pct', 3.0)
                            if _dist > _max_dist:
                                _ob_gate_reason = f"OB too far ({_dist:.1f}% > {_max_dist}%)"
                            else:
                                _ob_gate_reason = f"OB not retested (distance={_dist:.1f}%)"
                        else:
                            # Check 4: Confirmation candle (engulfing or pin-bar)
                            _last_candle = _df_clean.iloc[-1]
                            _prev_candle = _df_clean.iloc[-2] if len(_df_clean) >= 2 else None

                            _has_confirmation = False
                            if _prev_candle is not None:
                                _last_body = abs(float(_last_candle['close']) - float(_last_candle['open']))
                                _last_range = float(_last_candle['high']) - float(_last_candle['low'])
                                _prev_body = abs(float(_prev_candle['close']) - float(_prev_candle['open']))

                                if _last_range > 0:
                                    _wick_ratio = (_last_range - _last_body) / _last_range
                                else:
                                    _wick_ratio = 0.0

                                # Bullish engulfing: green candle closes above prev open
                                if setup.direction == 'buy':
                                    _is_green = float(_last_candle['close']) > float(_last_candle['open'])
                                    _engulfing = _is_green and _last_body > _prev_body and float(_last_candle['close']) > float(_prev_candle['open'])
                                    _pin_bar = _is_green and _wick_ratio > 0.6 and _last_body / _last_range < 0.3 if _last_range > 0 else False
                                    _has_confirmation = _engulfing or _pin_bar

                                # Bearish engulfing: red candle closes below prev open
                                elif setup.direction == 'sell':
                                    _is_red = float(_last_candle['close']) < float(_last_candle['open'])
                                    _engulfing = _is_red and _last_body > _prev_body and float(_last_candle['close']) < float(_prev_candle['open'])
                                    _pin_bar = _is_red and _wick_ratio > 0.6 and _last_body / _last_range < 0.3 if _last_range > 0 else False
                                    _has_confirmation = _engulfing or _pin_bar

                            if _has_confirmation:
                                _ob_gate_passed = True
                            else:
                                _ob_gate_reason = "no confirmation candle at OB retest"

            if _ob_gate_passed:
                _current_funnel.log_gate(symbol, timeframe, "ob_retest", "PASS",
                                         f"OB retested + confirmed")
                trace.passed("ob_retest")
            else:
                reason = _ob_gate_reason or "OB retest gate failed"
                _current_funnel.log_gate(symbol, timeframe, "ob_retest", "BLOCKED", reason)
                trace.blocked("ob_retest", reason)
                trace.set_version(VERSION, build_config_snapshot())
                await trace.save(db)
                await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                 "ob_retest", OB_RETEST_FAILED, False,
                                 setup_type=setup.setup_type, direction=setup.direction,
                                 meta=f"reason={_ob_gate_reason}")
                logger.info(f"OB Retest BLOCKED: {symbol} {timeframe} — {reason}")
                return None

        # ═══ Phase 1.45: HTF Bias + Premium/Discount Zones ═══

        # ═══ Phase 1.43: Session Filter (Kill Zones) (v2.5) ═══
        if config.session_hard_gate:
            _current_session = _detect_session()
            _active_sessions = config.trading_sessions
            if _current_session not in _active_sessions and _current_session != "overlap":
                reason = f"outside trading session ({_current_session}, active={_active_sessions})"
                _current_funnel.log_gate(symbol, timeframe, "session_filter", "BLOCKED", reason)
                trace.blocked("session_filter", reason)
                trace.set_version(VERSION, build_config_snapshot())
                await trace.save(db)
                await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                 "session_filter", SESSION_BLOCKED, False,
                                 setup_type=setup.setup_type, direction=setup.direction,
                                 meta=f"session={_current_session}")
                logger.info(f"Session BLOCKED: {symbol} {timeframe} — {reason}")
                return None
            _current_funnel.log_gate(symbol, timeframe, "session_filter", "PASS",
                                     f"session={_current_session}")
            trace.passed("session_filter")

        try:
            df_1d = await exchange_client.fetch_ohlcv(symbol, "1d", limit=60)
            df_4h = await exchange_client.fetch_ohlcv(symbol, "4h", limit=60)
        except Exception:
            df_1d = None
            df_4h = None

        # ═══ Phase 1.5: HTF POI Detection ═══
        from strategy.htf_poi import detect_htf_pois
        _htf_poi_result = detect_htf_pois(
            df_1d=df_1d,
            df_4h=df_4h,
            current_price=float(ind.close) if ind else 0.0,
            direction=setup.direction if setup and setup.detected else None,
        )

        _htf_bias_penalty = 1.0
        _htf_result = None
        _zone_type = None
        _fib_level = None
        _zone_quality_multiplier = 1.0

        if config.htf_bias_v2:
            # ── HTF Bias V2: W1 → D1 → H4 → H1 ──
            try:
                df_1w = await exchange_client.fetch_ohlcv(symbol, "1w", limit=60)
            except Exception:
                df_1w = None
            try:
                df_1h = await exchange_client.fetch_ohlcv(symbol, "1h", limit=60)
            except Exception:
                df_1h = None

            _htf_result = get_htf_bias_v2(df_1w, df_1d, df_4h, df_1h)
            htf_bias_str = _htf_result.direction

            if htf_bias_str == 'bullish':
                _bias_enum = HTFBias.BULLISH
            elif htf_bias_str == 'bearish':
                _bias_enum = HTFBias.BEARISH
            else:
                _bias_enum = HTFBias.NEUTRAL

            # ── Direction Filter (v2.5): Block SHORT in bullish HTF, LONG in bearish HTF ──
            # Neutral HTF = no directional confirmation — allow signals through
            if _bias_enum != HTFBias.NEUTRAL:
                if setup.direction == 'sell' and _bias_enum == HTFBias.BULLISH:
                    if getattr(config, 'block_short_in_bullish_htf', True):
                        reason = f"SHORT blocked: HTF bias is bullish"
                        _current_funnel.log_gate(symbol, timeframe, "htf_bias", "BLOCKED", reason)
                        trace.blocked("htf_bias", reason)
                        trace.set_version(VERSION, build_config_snapshot())
                        await trace.save(db)
                        await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                         "htf_bias", HTF_SHORT_IN_BULLISH, False,
                                         setup_type=setup.setup_type, direction=setup.direction,
                                         meta=f"version=v2,htf_bias={htf_bias_str}")
                        return None
                if setup.direction == 'buy' and _bias_enum == HTFBias.BEARISH:
                    if getattr(config, 'block_long_in_bearish_htf', True):
                        reason = f"LONG blocked: HTF bias is bearish"
                        _current_funnel.log_gate(symbol, timeframe, "htf_bias", "BLOCKED", reason)
                        trace.blocked("htf_bias", reason)
                        trace.set_version(VERSION, build_config_snapshot())
                        await trace.save(db)
                        await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                         "htf_bias", HTF_LONG_IN_BEARISH, False,
                                         setup_type=setup.setup_type, direction=setup.direction,
                                         meta=f"version=v2,htf_bias={htf_bias_str}")
                        return None

                direction_map = {"buy": HTFBias.BULLISH, "sell": HTFBias.BEARISH}

                if setup.setup_type == "continuation":
                    setup_bias = direction_map.get(setup.direction)
                    if setup_bias != _bias_enum:
                        reason = f"HTF hard gate: continuation {setup.direction} vs HTF {htf_bias_str}"
                        _current_funnel.log_gate(symbol, timeframe, "htf_bias", "BLOCKED", reason)
                        trace.blocked("htf_bias", reason)
                        trace.set_version(VERSION, build_config_snapshot())
                        await trace.save(db)
                        await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                         "htf_bias", HTF_CONTINUATION_MISMATCH, False,
                                         setup_type=setup.setup_type, direction=setup.direction,
                                         meta=f"version=v2,htf_bias={htf_bias_str}")
                        return None
                    else:
                        trace.passed("htf_bias")
                        _current_funnel.log_gate(
                            symbol, timeframe, "htf_bias", "PASS",
                            f"continuation {setup.direction} aligned with HTF {htf_bias_str}",
                        )

                elif setup.setup_type == "reversal":
                    setup_bias = direction_map.get(setup.direction)
                    if setup_bias != _bias_enum:
                        # Soft penalty for reversal vs HTF mismatch (not a hard block)
                        _htf_bias_penalty = 0.85
                        reason = f"HTF soft penalty: reversal {setup.direction} vs HTF {htf_bias_str}"
                        _current_funnel.log_gate(symbol, timeframe, "htf_bias", "PASS",
                                                 f"penalty=0.85 {reason}")
                        trace.passed("htf_bias", note=reason)
                    else:
                        _current_funnel.log_gate(
                            symbol, timeframe, "htf_bias", "PASS",
                            f"reversal aligned with HTF {htf_bias_str}",
                        )
                        trace.passed("htf_bias")
            else:
                _current_funnel.log_gate(
                    symbol, timeframe, "htf_bias", "PASS", "HTF neutral — no bias applied",
                )
                trace.passed("htf_bias")

        else:
            # ── Fallback: HTF Bias V1 ──
            _struct_1d = extract_structure_dict(structure) if structure else None
            _struct_4h = None
            if df_4h is not None and len(df_4h) >= 60:
                try:
                    from market_structure.structure import analyze_structure as _analyze_4h
                    _htf_struct = _analyze_4h(df_4h, lookback=50, atr_value=ind.atr if ind.atr else 0.0)
                    _struct_4h = extract_structure_dict(_htf_struct)
                except Exception:
                    pass

            _bias_enum = get_htf_bias(df_1d, df_4h, _struct_1d, _struct_4h)
            htf_bias_str = _bias_enum.value

            # ── Direction Filter (v2.5): Block SHORT in bullish HTF, LONG in bearish HTF ──
            if _bias_enum != HTFBias.NEUTRAL:
                if setup.direction == 'sell' and _bias_enum == HTFBias.BULLISH:
                    if getattr(config, 'block_short_in_bullish_htf', True):
                        reason = f"SHORT blocked: HTF bias is bullish"
                        _current_funnel.log_gate(symbol, timeframe, "htf_bias", "BLOCKED", reason)
                        trace.blocked("htf_bias", reason)
                        trace.set_version(VERSION, build_config_snapshot())
                        await trace.save(db)
                        await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                         "htf_bias", HTF_SHORT_IN_BULLISH, False,
                                         setup_type=setup.setup_type, direction=setup.direction,
                                         meta=f"version=v1,htf_bias={htf_bias_str}")
                        return None
                if setup.direction == 'buy' and _bias_enum == HTFBias.BEARISH:
                    if getattr(config, 'block_long_in_bearish_htf', True):
                        reason = f"LONG blocked: HTF bias is bearish"
                        _current_funnel.log_gate(symbol, timeframe, "htf_bias", "BLOCKED", reason)
                        trace.blocked("htf_bias", reason)
                        trace.set_version(VERSION, build_config_snapshot())
                        await trace.save(db)
                        await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                         "htf_bias", HTF_LONG_IN_BEARISH, False,
                                         setup_type=setup.setup_type, direction=setup.direction,
                                         meta=f"version=v1,htf_bias={htf_bias_str}")
                        return None

                direction_map = {"buy": HTFBias.BULLISH, "sell": HTFBias.BEARISH}

                if setup.setup_type == "continuation":
                    setup_bias = direction_map.get(setup.direction)
                    if setup_bias != _bias_enum:
                        reason = f"HTF hard gate: continuation {setup.direction} vs HTF {_bias_enum.value}"
                        _current_funnel.log_gate(symbol, timeframe, "htf_bias", "BLOCKED", reason)
                        trace.blocked("htf_bias", reason)
                        trace.set_version(VERSION, build_config_snapshot())
                        await trace.save(db)
                        await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                         "htf_bias", HTF_CONTINUATION_MISMATCH, False,
                                         setup_type=setup.setup_type, direction=setup.direction,
                                         meta=f"version=v1,htf_bias={htf_bias_str}")
                        return None
                    else:
                        trace.passed("htf_bias")
                        _current_funnel.log_gate(
                            symbol, timeframe, "htf_bias", "PASS",
                            f"continuation {setup.direction} aligned with HTF {_bias_enum.value}",
                        )

                elif setup.setup_type == "reversal":
                    setup_bias = direction_map.get(setup.direction)
                    if setup_bias != _bias_enum:
                        # Soft penalty for reversal vs HTF mismatch (not a hard block)
                        _htf_bias_penalty = 0.85
                        reason = f"HTF soft penalty: reversal {setup.direction} vs HTF {_bias_enum.value}"
                        _current_funnel.log_gate(symbol, timeframe, "htf_bias", "PASS",
                                                 f"penalty=0.85 {reason}")
                        trace.passed("htf_bias", note=reason)
                    else:
                        _current_funnel.log_gate(
                            symbol, timeframe, "htf_bias", "PASS",
                            f"reversal aligned with HTF {_bias_enum.value}",
                        )
                        trace.passed("htf_bias")
            else:
                _current_funnel.log_gate(
                    symbol, timeframe, "htf_bias", "PASS", "HTF neutral — no bias applied",
                )
                trace.passed("htf_bias")

        # ═══ Premium/Discount Zone Detection ═══
        if config.premium_discount and df is not None and len(df) > 0:
            try:
                _swing_high = None
                _swing_low = None
                if structure and structure.recent_highs and structure.recent_lows:
                    _swing_high = max(structure.recent_highs)
                    _swing_low = min(structure.recent_lows)
                if _swing_high is None or _swing_low is None or _swing_high <= _swing_low:
                    _lookback = min(50, len(df))
                    _swing_high = float(df['high'].tail(_lookback).max())
                    _swing_low = float(df['low'].tail(_lookback).min())

                from market_structure.premium_discount import (
                    classify_zone as _classify_zone,
                    get_entry_zone_quality as _get_zone_quality,
                )
                zone_result = _classify_zone(df, htf_bias_str, _swing_high, _swing_low)
                _zone_type = zone_result.zone_type.value
                _fib_level = zone_result.fib_level
                _zone_quality_multiplier = _get_zone_quality(
                    zone_result, htf_bias_str, setup.setup_type,
                )
            except Exception as e:
                logger.debug(f"Zone classification failed for {symbol} {timeframe}: {e}")

        # ═══ Phase 1.5: Build Trade Plan (ICT-based) ═══

        from strategy.trade_engine import trade_engine

        trade_plan = trade_engine.build_trade_plan(
            ind=ind,
            direction=setup.direction,
            structure=structure,
            order_blocks=order_blocks,
            sweeps=sweeps,
            fvgs=fvgs,
            df=_df_clean,
            timeframe=timeframe,
            htf_poi_result=_htf_poi_result,
        )

        sl = trade_plan.sl
        tp = trade_plan.tp
        sl_source = trade_plan.sl_source

        if sl is None or tp is None:
            _current_funnel.log_gate(symbol, timeframe, "sl_tp", "BLOCKED", "calculation failed")
            trace.blocked("sl_tp", "SL/TP calculation failed")
            await trace.save(db)
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "sl_tp", SL_TP_FAILED, False,
                             setup_type=setup.setup_type, direction=setup.direction)
            return None

        entry_price = ind.close

        # ═══ Phase 1.6: Entry Trigger Check ═══
        # Validate price is in the optimal entry zone before signalling.
        # Uses trade_plan.entry_zone as target — not just current close.
        from strategy.entry_trigger import EntryTrigger, SimpleEntryTarget
        _entry_trigger = EntryTrigger(
            entry_proximity_pct=getattr(config, 'entry_proximity_pct', 0.3),
            max_spread_pct=getattr(config, 'max_entry_spread_pct', 0.1),
        )
        # Build target: use entry_zone from trade plan if available
        _entry_zone_low, _entry_zone_high = trade_plan.entry_zone if trade_plan.entry_zone else (0.0, 0.0)
        if setup.direction == "buy" and _entry_zone_low > 0:
            _target_entry = _entry_zone_low  # pullback to lower bound
        elif setup.direction == "sell" and _entry_zone_high > 0:
            _target_entry = _entry_zone_high  # pullback to upper bound
        else:
            _target_entry = entry_price  # fallback: current price

        _trigger_target = SimpleEntryTarget(direction=setup.direction, entry_price=_target_entry)
        _trigger_result = _entry_trigger.check(
            _trigger_target, current_price=ind.close,
            bid=getattr(ind, 'bid', None), ask=getattr(ind, 'ask', None),
        )
        if not _trigger_result.triggered:
            _reason = _trigger_result.reason or "entry trigger"
            _current_funnel.log_gate(symbol, timeframe, "entry_trigger", "BLOCKED", _reason)
            trace.blocked("entry_trigger", _reason)
            await trace.save(db)
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "entry_trigger", ENTRY_TRIGGER_NO, False,
                             setup_type=setup.setup_type, direction=setup.direction)
            logger.debug(f"Entry trigger miss: {symbol} {timeframe} — {_reason}")
            return None
        _current_funnel.log_gate(symbol, timeframe, "entry_trigger", "PASS",
                                 f"target={_target_entry:.4f} price={ind.close:.4f}")
        trace.passed("entry_trigger")

        # ═══ Phase 1.7: LTF Confirmation (multi_tf mode) ═══
        # Only runs when scan_mode == "multi_tf" and confirm_tf_enabled
        _confirm_result = None
        if (config.trading.scan_mode == "multi_tf"
                and config.trading.confirm_tf_enabled
                and config.trading.confirm_timeframe
                and config.trading.confirm_timeframe != timeframe):

            from strategy.confirmation_engine import find_confirmation

            _entry_zone = None
            if _nearest_ob:
                _entry_zone = (_nearest_ob.high, _nearest_ob.low)

            try:
                df_confirm = await exchange_client.fetch_ohlcv(
                    symbol, config.trading.confirm_timeframe, limit=100
                )
            except Exception:
                df_confirm = None

            if df_confirm is not None and len(df_confirm) >= 20:
                try:
                    from indicators.engine import indicator_engine as _ie
                    ind_5m = _ie.calculate(df_confirm, symbol, config.trading.confirm_timeframe)
                    atr_5m = ind_5m.atr if ind_5m and ind_5m.atr else 0.0
                except Exception:
                    atr_5m = 0.0

                _setup_ts = None
                if sweeps:
                    for s in sweeps:
                        if s.is_valid:
                            _setup_ts = s.timestamp
                            break
                if _setup_ts is None and structure and structure.last_bos:
                    _setup_ts = structure.last_bos.timestamp

                _confirm_result = find_confirmation(
                    df_5m=df_confirm,
                    direction=setup.direction,
                    entry_zone=_entry_zone,
                    sl_price=sl,
                    setup_timestamp=_setup_ts,
                    atr_5m=atr_5m,
                )

                if _confirm_result.confirmed:
                    entry_price = _confirm_result.entry_price
                    trace.passed("confirm_tf")
                    _current_funnel.log_gate(symbol, timeframe, "confirm_tf", "PASS",
                                             f"{_confirm_result.trigger_type} "
                                             f"(conf={_confirm_result.confidence:.1f})")
                else:
                    _current_funnel.log_gate(symbol, timeframe, "confirm_tf", "BLOCKED",
                                             "no 5m confirmation")
                    trace.blocked("confirm_tf", "no 5m confirmation")
                    await trace.save(db)
                    await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                     "confirm_tf", LTF_NO_CONFIRMATION, False,
                                     setup_type=setup.setup_type, direction=setup.direction)
                    return None
            else:
                _current_funnel.log_gate(symbol, timeframe, "confirm_tf", "BLOCKED",
                                         "5m OHLCV unavailable")
                trace.blocked("confirm_tf", "5m data unavailable")
                await trace.save(db)
                await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                 "confirm_tf", LTF_DATA_UNAVAILABLE, False,
                                 setup_type=setup.setup_type, direction=setup.direction)
                return None

        # ═══ Phase 1.55: Market Phase Detection (SHADOW MODE) ═══

        _phase_assessment = None
        try:
            _phase_assessment = _market_phase_engine.assess(
                adx=ind.adx if ind.adx else 0.0,
                atr_current=ind.atr if ind.atr else 0.0,
                atr_avg=getattr(ind, 'atr_avg', ind.atr) if ind.atr else 0.0,
                ema_fast=ind.ema_fast if ind.ema_fast else 0.0,
                ema_slow=ind.ema_slow if ind.ema_slow else 0.0,
                ema_trend=ind.ema_trend if hasattr(ind, 'ema_trend') and ind.ema_trend else 0.0,
                ema_fast_prev=0.0,
                ema_slow_prev=0.0,
                close=ind.close,
                high=ind.high,
                low=ind.low,
                has_bos=setup.bos_type is not None,
                bos_direction=setup.bos_type,
                has_choch=setup.has_mss,
                has_displacement=setup.has_displacement if hasattr(setup, 'has_displacement') else False,
                displacement_count=1 if setup.has_displacement else 0,
                volume_ratio=1.0,
                range_pct=0.0,
                bars_in_range=20,
            )
            logger.info(
                f"[OVERLAY] Phase: {symbol} {timeframe} | "
                f"phase={_phase_assessment.phase.value} "
                f"conf={_phase_assessment.confidence:.2f} "
                f"dur={_phase_assessment.duration_bars}bars"
            )
        except Exception as e:
            logger.debug(f"[OVERLAY] Phase detection failed for {symbol} {timeframe}: {e}")

        # ═══ Phase 1.6: Market Thesis Engine (SHADOW MODE) ═══
        # Dynamic approach: cache graph and thesis per symbol/timeframe.
        # Graph updates in-place on each candle close instead of rebuilding.
        # DynamicTradeThesis tracks competing BUY/SELL with stability.

        _thesis_score = 0.0
        _thesis_stability = 0.0

        try:
            from strategy.market_thesis_engine import (
                market_thesis_engine, LiquidityGraph, DynamicTradeThesis,
            )
            from liquidity.equal_levels import detect_equal_levels
            from liquidity.external import detect_external_liquidity

            _cache_key = f"{symbol}_{timeframe}"

            # Latest candle data for update_on_candle
            _last_row = _df_clean.iloc[-1] if len(_df_clean) > 0 else None
            _candle_data = {}
            if _last_row is not None:
                _candle_data = {
                    "open": float(_last_row["open"]),
                    "high": float(_last_row["high"]),
                    "low": float(_last_row["low"]),
                    "close": float(_last_row["close"]),
                    "volume": float(_last_row["volume"]),
                }

            if _cache_key in _dynamic_graphs:
                # ── UPDATE existing graph in-place ──
                _liq_graph = _dynamic_graphs[_cache_key]
                _thesis = _dynamic_theses.get(_cache_key)

                if _candle_data:
                    _liq_graph.update_on_candle(
                        _candle_data, entry_price, new_bar=True,
                    )

                if _thesis is not None:
                    _thesis.update(
                        _liq_graph, entry_price, _candle_data,
                        atr=ind.atr if ind.atr else 0,
                    )
                    _thesis_stability = _thesis.scenario_stability

                    # Use best scenario from dynamic thesis
                    _best = _thesis.best_scenario
                    if _best and _best.is_active:
                        _thesis_score = _best.score

                        logger.info(
                            f"[OVERLAY] Dynamic Thesis: {symbol} {timeframe} | "
                            f"BUY={_thesis.buy_scenario.probability:.2f} "
                            f"SELL={_thesis.sell_scenario.probability:.2f} | "
                            f"ambiguous={_thesis.is_ambiguous} | "
                            f"stability={_thesis_stability:.2f} | "
                            f"graph_v{_liq_graph.graph_version}"
                        )

                        if _thesis.is_ambiguous:
                            logger.debug(
                                f"[OVERLAY] Ambiguous thesis for {symbol} {timeframe} "
                                f"— probabilities too close"
                            )
                    else:
                        logger.debug(
                            f"[OVERLAY] No active scenario for {symbol} {timeframe}"
                        )
                else:
                    logger.debug(
                        f"[OVERLAY] No cached thesis for {symbol} {timeframe}"
                    )
            else:
                # ── FIRST TIME: build graph + create thesis ──
                _swing_highs = getattr(structure, "recent_highs", []) or []
                _swing_lows = getattr(structure, "recent_lows", []) or []
                _equal_levels = detect_equal_levels(_swing_highs, _swing_lows)
                _external_levels = (
                    detect_external_liquidity(_df_clean, lookback=200)
                    if _df_clean is not None else []
                )

                _liq_graph = market_thesis_engine.build_liquidity_graph(
                    current_price=entry_price,
                    sweeps=sweeps,
                    order_blocks=order_blocks,
                    fvgs=fvgs,
                    structure=structure,
                    equal_levels=_equal_levels,
                    external_levels=_external_levels,
                    candle_quality=candle_quality,
                    timeframe=timeframe,
                )

                _thesis = DynamicTradeThesis(
                    symbol=symbol, timeframe=timeframe,
                )
                if _candle_data:
                    _thesis.update(
                        _liq_graph, entry_price, _candle_data,
                        atr=ind.atr if ind.atr else 0,
                    )
                    _thesis_stability = _thesis.scenario_stability

                # Cache for next cycle
                _dynamic_graphs[_cache_key] = _liq_graph
                _dynamic_theses[_cache_key] = _thesis

                logger.debug(
                    f"[OVERLAY] Built initial graph for {symbol} {timeframe}: "
                    f"{len(_liq_graph.nodes)} nodes"
                )

            # Also evaluate backward-compatible opportunity for trade plan
            _thesis_opportunity = market_thesis_engine.evaluate_trade_opportunity(
                graph=_liq_graph,
                direction=setup.direction,
                entry_price=entry_price,
                atr=ind.atr if ind.atr else 0,
                symbol=symbol,
                timeframe=timeframe,
            )

            if _thesis_opportunity:
                trade_plan.market_thesis = _thesis_opportunity.thesis
                trade_plan.liquidity_path = _thesis_opportunity.expected_path
                trade_plan.scenario_score = _thesis_opportunity.scenario_score
                trade_plan.scenario_stability = _thesis_stability
                trade_plan.thesis_source = "market_thesis"

                logger.info(
                    f"[OVERLAY] Market Thesis: {symbol} {timeframe} | "
                    f"direction={_thesis_opportunity.direction} | "
                    f"score={_thesis_opportunity.scenario_score:.0f} | "
                    f"stability={_thesis_stability:.2f} | "
                    f"target={_thesis_opportunity.expected_target:.4f} | "
                    f"invalidation={_thesis_opportunity.invalidation:.4f} | "
                    f"rr=1:{_thesis_opportunity.expected_rr:.1f}"
                )

                if _thesis_opportunity.thesis.score_breakdown:
                    bd = _thesis_opportunity.thesis.score_breakdown.breakdown()
                    logger.info(
                        f"[OVERLAY] Score breakdown: OB={bd['ob']:.1f} "
                        f"Sweep={bd['sweep']:.1f} BOS={bd['bos']:.1f} "
                        f"FVG={bd['fvg']:.1f} Liq={bd['liquidity']:.1f} "
                        f"HTF={bd['htf']:.1f} total={bd['total']:.1f}"
                    )

            # Evaluate all ranked scenarios for comparison
            _scenarios = market_thesis_engine.evaluate_scenarios(
                graph=_liq_graph,
                direction=setup.direction,
                entry_price=entry_price,
                atr=ind.atr if ind.atr else 0,
                symbol=symbol,
                timeframe=timeframe,
            )
            if _scenarios:
                logger.info(
                    f"[OVERLAY] Scenarios ranked: "
                    + " | ".join(
                        f"#{s.alternative_rank + 1} score={s.score:.1f} "
                        f"conf={s.confidence:.0f} rr=1:{s.expected_rr:.1f}"
                        for s in _scenarios[:3]
                    )
                )
            else:
                logger.debug(f"[OVERLAY] No thesis for {symbol} {timeframe}")

        except Exception as e:
            logger.debug(f"[OVERLAY] Market Thesis Engine error for {symbol} {timeframe}: {e}")

        # ═══ Phase 1.7: Hypothesis Engine + Decision Engine ═══
        # NEW PIPELINE: generates all hypotheses, Decision Engine selects winner.
        # Runs in parallel with analytical overlays for comparison.

        _hypothesis_set = None
        _decision = None

        try:
            from strategy.hypothesis import HypothesisSet
            from strategy.decision_engine import DecisionEngine, MarketState

            if _liq_graph is not None:
                # 1. Build HypothesisSet (all competing hypotheses)
                _hypothesis_set = market_thesis_engine.build_hypothesis_set(
                    graph=_liq_graph,
                    direction=None,  # both buy and sell
                    atr=ind.atr if ind.atr else 0,
                    current_bar=_dynamic_bar_counters.get(_cache_key, 0),
                )

                # 2. Build MarketState from phase assessment
                if _phase_assessment:
                    _market_state = MarketState.from_assessment(_phase_assessment)
                else:
                    from strategy.market_phase_engine import MarketPhase
                    _market_state = MarketState(
                        phase=MarketPhase.COMPRESSION,
                        phase_confidence=0.5,
                        narrative_weights={},
                    )

                # 3. Decision Engine selects winner
                _decision_engine = DecisionEngine()
                _decision = _decision_engine.decide(
                    hypothesis_set=_hypothesis_set,
                    market_state=_market_state,
                )

                if _decision.trade and _decision.hypothesis:
                    h = _decision.hypothesis
                    logger.info(
                        f"[HYPOTHESIS] {symbol} {timeframe} | "
                        f"direction={h.direction} | "
                        f"narrative={h.narrative_type} | "
                        f"quality={h.quality:.0f} | "
                        f"confidence={h.confidence:.2f} | "
                        f"decay={h.decay_factor:.2f} | "
                        f"utility={_decision.utility:.3f} | "
                        f"phase={_market_state.phase.value} | "
                        f"hypotheses={len(_hypothesis_set)}"
                    )
                    # Store hypothesis in trace for ScenarioMemory tracking
                    trace.set_hypothesis(
                        hypothesis_id=h.id,
                        narrative_type=h.narrative_type,
                        direction=h.direction,
                        quality=h.quality,
                        confidence=h.confidence,
                        decay_factor=h.decay_factor,
                        utility=_decision.utility,
                        entry_price=h.entry_price,
                        invalidation_price=h.invalidation_price,
                        target_price=h.target_price,
                        rr_ratio=h.rr_ratio,
                        phase=_market_state.phase.value,
                    )
                    # Record expected metrics for future outcome tracking
                    scenario_memory.record_expected(
                        symbol=symbol,
                        hypothesis_name=h.name,
                        narrative_type=h.narrative_type,
                        direction=h.direction,
                        expected_rr=h.expected_rr,
                        expected_p_tp=h.expected_p_tp,
                        expected_quality=h.quality,
                        expected_confidence=h.confidence,
                    )
                else:
                    logger.debug(
                        f"[HYPOTHESIS] {symbol} {timeframe} | "
                        f"NO TRADE: {_decision.rejection_reason} | "
                        f"reasons={_decision.reasons}"
                    )

                # Log top hypotheses for debugging
                _top = _hypothesis_set.top(3)
                if _top:
                    _top_str = " | ".join(
                        f"{h.direction}:{h.narrative_type} "
                        f"q={h.quality:.0f} c={h.confidence:.2f} "
                        f"d={h.decay_factor:.2f}"
                        for h in _top
                    )
                    logger.debug(f"[HYPOTHESIS] Top: {_top_str}")

        except Exception as e:
            logger.debug(f"[HYPOTHESIS] Engine error for {symbol} {timeframe}: {e}")

        # ═══ Phase 2: Feature Builder ═══

        regime = _regime_for_gates
        from risk.volatility_regime import classify_volatility
        vol_regime = classify_volatility(ind.atr, ind.close)

        # MTF alignment (analytics — not a gate)
        mtf_aligned = False
        mtf_count = 0
        is_reversal = setup.is_reversal if setup.detected else False
        if config.market_structure.mtf_enabled:
            try:
                mtf_result = await check_mtf_alignment(
                    symbol=symbol,
                    direction="bullish" if setup.direction == "buy" else "bearish",
                    primary_tf=timeframe,
                    exchange_client=exchange_client,
                    required_alignment=1 if is_reversal else config.market_structure.mtf_required_alignment,
                )
                if mtf_result.aligned:
                    mtf_aligned = True
                    mtf_count = len(mtf_result.states)
            except Exception as e:
                logger.debug(f"MTF check failed for {symbol}: {e}")

        # Context enrichment (soft — no blocking)
        context_score_val = 0.0
        fear_greed_val = None
        funding_rate_val = None
        context_verdict = None
        if config.context_enabled:
            try:
                snapshot = await asyncio.wait_for(
                    context_engine.get_snapshot(symbol),
                    timeout=10.0,
                )
                context_verdict = context_scorer.score(setup.direction.upper(), snapshot)
                context_score_val = context_verdict.score
                fear_greed_val = snapshot.fear_greed_value
                funding_rate_val = snapshot.funding_rate
            except Exception as e:
                logger.debug(f"Context enrichment skipped for {symbol}: {e}")

        # OB state multiplier (mitigation factor for Probability Engine)
        _ob_state_multiplier = 1.0
        _nearest_ob = None
        if order_blocks and setup.has_ob and setup.direction:
            _rel_obs = [ob for ob in order_blocks
                        if ob.type == ('bullish' if setup.direction == 'buy' else 'bearish')]
            if _rel_obs:
                _nearest_ob = min(_rel_obs, key=lambda ob: abs(ob.midpoint - setup.ob_midpoint))
                from liquidity.ob_state import get_ob_state, get_ob_multiplier, OBState
                _ob_state = get_ob_state(_df_clean, _nearest_ob.high, _nearest_ob.low, _nearest_ob.type)
                if _ob_state == OBState.BROKEN:
                    _ob_state_multiplier = 0.0
                else:
                    _ob_state_multiplier = get_ob_multiplier(_ob_state)

        # ═══ Elliott Wave Analysis (soft feature) ═══
        _wave_analysis = None
        if config.wave.enabled:
            try:
                from elliott_wave.analysis import analyze_waves
                _wave_analysis = analyze_waves(
                    _df_clean, symbol, timeframe,
                    degree=WaveDegree.MINOR,
                )
            except Exception as e:
                logger.debug(f"Wave analysis failed for {symbol}: {e}")

        # ═══ Volume Profile (POC/VAH/VAL — ICT S/R layer) ═══
        _volume_profile = None
        try:
            from liquidity.volume_profile import compute_volume_profile
            _volume_profile = compute_volume_profile(_df_clean, bins=50, lookback=100)
            if _volume_profile and _volume_profile.is_valid:
                logger.debug(
                    f"Volume Profile: {symbol} {timeframe} | "
                    f"POC={_volume_profile.poc:.4f} VAH={_volume_profile.vah:.4f} "
                    f"VAL={_volume_profile.val:.4f} "
                    f"price_in_VA={_volume_profile.price_in_value_area(ind.close)}"
                )
        except Exception as e:
            logger.debug(f"Volume profile failed for {symbol}: {e}")

        # Build features
        features = feature_builder.build(
            setup=setup,
            ind=ind,
            structure=structure,
            regime=regime,
            vol_regime=vol_regime,
            mtf_aligned=mtf_aligned,
            mtf_count=mtf_count,
            context_score=context_score_val,
            fear_greed=fear_greed_val,
            funding_rate=funding_rate_val,
            sl=sl,
            tp=tp,
            entry_price=entry_price,
            candle_quality=candle_quality,
            is_reversal=is_reversal,
            htf_bias_penalty=_htf_bias_penalty,
            ob_state_multiplier=_ob_state_multiplier,
            smt_divergence_score=_smt_to_score(_smt_result),
            wave_analysis=_wave_analysis,
            volume_profile=_volume_profile,
        )

        # ═══ Phase 1.65: Scenario Engine (SHADOW MODE) ═══

        _new_scenarios = []
        _new_evaluations = []
        try:
            if _liq_graph is not None:
                _new_scenarios = _scenario_engine.detect_scenarios(
                    graph=_liq_graph,
                    structure=structure,
                    phase=_phase_assessment,
                    direction=setup.direction,
                )

                if _new_scenarios:
                    # Estimate probability for each scenario
                    from strategy.probability_engine import probability_engine
                    from strategy.weight_manager import weight_manager
                    for scenario in _new_scenarios[:5]:  # top 5
                        eval_result = probability_engine.estimate_scenario(
                            features=features,
                            scenario=scenario,
                        )
                        # WeightManager adjusts P(TP) based on historical stats
                        eval_result = weight_manager.adjust(
                            eval_result, symbol, scenario.name,
                            regime=regime.regime if regime else None,
                        )
                        _new_evaluations.append(eval_result)

                    logger.info(
                        f"[OVERLAY] ScenarioEngine: {symbol} {timeframe} | "
                        f"detected={len(_new_scenarios)} "
                        f"evaluated={len(_new_evaluations)} | "
                        + " | ".join(
                            f"{s.name}(p={e.probability:.2f})"
                            for s, e in zip(_new_scenarios[:3], _new_evaluations[:3])
                        )
                    )

                    # Record observations in ScenarioMemory
                    for scenario in _new_scenarios:
                        scenario_memory.record_observation(symbol, scenario.name)

                    # Update TradeThesisManager
                    _current_thesis = _thesis_manager.update(
                        symbol=symbol,
                        timeframe=timeframe,
                        scenarios=_new_scenarios,
                        evaluations=_new_evaluations,
                        bar=len(_df_clean),
                        price=entry_price,
                    )
                    if _current_thesis:
                        logger.info(
                            f"[OVERLAY] Thesis: {symbol} {timeframe} | "
                            f"status={_current_thesis.status} "
                            f"dir={_current_thesis.direction} "
                            f"scenario={_current_thesis.scenario.name} "
                            f"p={_current_thesis.evaluation.probability:.2f} "
                            f"age={_current_thesis.age_bars}"
                        )

        except Exception as e:
            logger.debug(f"[OVERLAY] ScenarioEngine error for {symbol} {timeframe}: {e}")

        # ═══ Phase 3: Probability Engine ═══

        # Build scenario name for memory lookup
        _scenario_name = ""
        if _decision and _decision.hypothesis:
            _scenario_name = _decision.hypothesis.narrative_type
        elif setup.setup_type == "reversal":
            _scenario_name = "reversal"
        elif setup.setup_type == "continuation":
            _scenario_name = "continuation"

        probability = probability_engine.predict(features, symbol=symbol, scenario_name=_scenario_name)

        # Apply zone quality multiplier
        if config.premium_discount and _zone_quality_multiplier != 1.0:
            probability.p_tp = min(probability.p_tp * _zone_quality_multiplier, 1.0)

        # ═══ Phase 3.1: min_p_tp gate (with direction-specific thresholds) ═══
        # Use higher thresholds for SHORT and REVERSAL signals
        _effective_min_p_tp = config.probability.min_p_tp
        if setup.direction == 'sell' and config.probability.min_p_tp_short > 0:
            _effective_min_p_tp = max(_effective_min_p_tp, config.probability.min_p_tp_short)
        if setup.setup_type == 'reversal' and config.probability.min_p_tp_reversal > 0:
            _effective_min_p_tp = max(_effective_min_p_tp, config.probability.min_p_tp_reversal)

        if _effective_min_p_tp > 0 and probability.p_tp < _effective_min_p_tp:
            reason = f"P(TP)={probability.p_tp:.1%} < min {_effective_min_p_tp:.0%} (dir={setup.direction}, setup={setup.setup_type})"
            _current_funnel.log_gate(symbol, timeframe, "min_p_tp", "BLOCKED", reason)
            trace.blocked("min_p_tp", reason)
            trace.set_version(VERSION, build_config_snapshot())
            await trace.save(db)
            _rr = abs(tp - entry_price) / abs(entry_price - sl) if entry_price != sl else 0
            _hyp = f",hyp_entry={entry_price:.4f},hyp_sl={sl:.4f},hyp_tp={tp:.4f},hyp_rr={_rr:.2f},hyp_ptp={probability.p_tp:.3f}"
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "min_p_tp", MIN_P_TP, False,
                             setup_type=setup.setup_type, direction=setup.direction,
                             meta=f"p_tp={probability.p_tp:.3f},threshold={_effective_min_p_tp:.3f}{_hyp}",
                             as_of_utc=_as_of_utc, data_age_ms=_data_age_ms)
            logger.info(f"min_p_tp BLOCKED: {symbol} {timeframe} — {reason}")
            return None
        trace.passed("min_p_tp")
        _current_funnel.log_gate(symbol, timeframe, "min_p_tp", "PASS")

        logger.info(
            f"Probability: P(TP)={probability.p_tp:.1%} | "
            f"RR={probability.expected_rr:.2f} | PF={probability.profit_factor:.2f} | "
            f"model={probability.model_type} | {symbol} {timeframe}"
        )

        # ═══ Phase 4: Risk Engine ═══

        portfolio_state = PortfolioState(
            active_count=active_count,
            total_risk_pct=portfolio_risk,
            max_active_signals=config.max_active_signals,
            max_portfolio_risk_pct=config.max_portfolio_risk_pct,
            equity=getattr(config, 'portfolio_equity_usdt', 0.0),
        )

        risk_decision = risk_engine.evaluate(
            features=features,
            probability=probability,
            portfolio=portfolio_state,
            entry_price=entry_price,
            sl=sl,
            tp=tp,
            scenario_score=_thesis_score,
            scenario_stability=_thesis_stability,
            mss_quality=setup.mss_score,
            atr=ind.atr if ind.atr else 0.0,
        )

        if not risk_decision.should_trade:
            _current_funnel.log_gate(symbol, timeframe, "risk_engine", "BLOCKED",
                                     risk_decision.rejection_reason)
            trace.blocked("risk_engine", risk_decision.rejection_reason)
            trace.set_version(VERSION, build_config_snapshot())
            await trace.save(db)
            _rr = risk_decision.rejection_reason or ""
            _rcode = SL_TOO_WIDE
            if "max active signals" in _rr:
                _rcode = PORTFOLIO_MAX_ACTIVE
            elif "portfolio risk limit" in _rr:
                _rcode = PORTFOLIO_MAX_RISK
            elif "invalid price data" in _rr or "zero risk distance" in _rr:
                _rcode = DATA_INTEGRITY_FAIL
            elif "too tight vs ATR" in _rr:
                _rcode = SL_ATR_CONFLICT
            elif "too tight" in _rr:
                _rcode = SL_TOO_TIGHT
            elif "RR=" in _rr:
                _rcode = RR_TOO_LOW
            elif "kelly=" in _rr:
                _rcode = NEGATIVE_EV
            elif "position size" in _rr:
                _rcode = POSITION_SIZE_BELOW_MIN
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "risk_engine", _rcode, False,
                             setup_type=setup.setup_type, direction=setup.direction,
                             meta=f"reason={_rr},hyp_entry={entry_price:.4f},hyp_sl={sl:.4f},hyp_tp={tp:.4f},hyp_rr={risk_decision.rr_ratio:.2f},hyp_ptp={probability.p_tp:.3f}",
                             as_of_utc=_as_of_utc, data_age_ms=_data_age_ms)
            logger.info(f"Risk BLOCKED: {symbol} {timeframe} — {risk_decision.rejection_reason}")
            return None

        _current_funnel.log_gate(symbol, timeframe, "risk_engine", "PASS",
                                 f"risk={risk_decision.risk_pct:.2f}%")
        trace.passed("risk_engine")

        # ═══ Phase 4.5: Entry Trigger Check (independent of Decision Engine) ═══
        # Uses Hypothesis when available, falls back to SimpleEntryTarget
        # when Decision Engine / Hypothesis Engine is skipped (_liq_graph=None).
        from strategy.entry_trigger import EntryTrigger, SimpleEntryTarget
        entry_trigger = EntryTrigger()

        # Build entry target: Hypothesis or SimpleEntryTarget fallback
        _entry_target = None
        if _decision and _decision.trade and _decision.hypothesis:
            _entry_target = _decision.hypothesis
        elif setup.direction and entry_price > 0:
            _entry_target = SimpleEntryTarget(
                direction=setup.direction,
                entry_price=entry_price,
            )

        if _entry_target is not None:
            # Get bid/ask for spread check and current price for trigger distance
            _ticker_for_trigger = await exchange_client.fetch_ticker_full(symbol)
            _bid = _ticker_for_trigger.get("bid") if _ticker_for_trigger else None
            _ask = _ticker_for_trigger.get("ask") if _ticker_for_trigger else None

            # Use live mid-price as current_price, not candle close
            _current_price = entry_price  # fallback
            if _bid and _ask and _bid > 0 and _ask > 0:
                _current_price = (_bid + _ask) / 2

            trigger_result = entry_trigger.check(
                hypothesis=_entry_target,
                current_price=_current_price,
                bid=_bid,
                ask=_ask,
            )

            if not trigger_result.triggered:
                _current_funnel.log_gate(symbol, timeframe, "entry_trigger", "BLOCKED",
                                         trigger_result.reason)
                trace.blocked("entry_trigger", trigger_result.reason)
                trace.set_version(VERSION, build_config_snapshot())
                await trace.save(db)
                logger.info(
                    f"EntryTrigger BLOCKED: {symbol} {timeframe} — "
                    f"{trigger_result.reason}"
                )
                await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                 "entry_trigger", ENTRY_TRIGGER_NO, False,
                                 setup_type=setup.setup_type, direction=setup.direction,
                                 meta=f"reason={trigger_result.reason},hyp_entry={entry_price:.4f},hyp_sl={sl:.4f},hyp_tp={tp:.4f},hyp_rr={risk_decision.rr_ratio:.2f},hyp_ptp={probability.p_tp:.3f}",
                                 as_of_utc=_as_of_utc, data_age_ms=_data_age_ms)
                return None

            _current_funnel.log_gate(symbol, timeframe, "entry_trigger", "PASS")
            trace.passed("entry_trigger")
        else:
            logger.debug(
                f"[ENTRY_TRIGGER] {symbol} {timeframe} | "
                f"SKIPPED: no entry target (setup.direction={setup.direction}, "
                f"entry_price={entry_price})"
            )

        # ═══ Phase 5: Build SignalResult ═══

        signal_type = SignalType.BUY if setup.direction == "buy" else SignalType.SELL

        reasons = features.to_reasoning()
        reasons.append(f"P(TP)={probability.p_tp:.1%}")
        reasons.append(f"Risk={risk_decision.risk_pct:.2f}%")

        result = SignalResult(
            signal=signal_type,
            symbol=symbol,
            timeframe=timeframe,
            close=ind.close,
            entry_price=entry_price,
            sl=risk_decision.sl_price,
            tp=risk_decision.tp_price,
            reasons=reasons,
            score=features.components_count,
            _has_trigger=setup.has_trigger,
            _has_leading_trigger=setup.has_trigger,
            _regime=regime.regime if regime else None,
            _structure_trend=structure.trend if structure else None,
            _structure_bos=setup.bos_type,
            _sl_source=sl_source,
            _htf_result=_htf_result,
            _zone_type=_zone_type,
            _fib_level=_fib_level,
            _zone_quality_multiplier=_zone_quality_multiplier,
            _htf_poi=_htf_poi_result,
            _wave_confidence=_wave_analysis.confidence if _wave_analysis else 0.0,
            _wave_label=_wave_analysis.primary.label if _wave_analysis and _wave_analysis.primary else "",
            _wave_conflict=_wave_analysis.conflict if _wave_analysis else False,
            _wave_conflict_details=_wave_analysis.conflict_details if _wave_analysis else "",
            _wave_alt_label=_wave_analysis.alternatives[0].label if _wave_analysis and _wave_analysis.alternatives else "",
            _wave_direction=_wave_analysis.primary.price_direction if _wave_analysis and _wave_analysis.primary else "",
            _wave_target=_wave_analysis.primary.end_price if _wave_analysis and _wave_analysis.primary else 0.0,
            _wave_current=_wave_analysis.primary.get_current_wave(entry_price) if _wave_analysis and _wave_analysis.primary else "",
        )

        # Attach probability data for display (capped at 85%)
        result._confidence_v2 = type('Obj', (object,), {
            'confidence_pct': min(85.0, probability.p_tp * 100),
            'quality': probability.quality_label,
            'total_score': probability.expected_rr,
            'factors': [],
        })()

        # ═══ Phase 6: Dedup ═══

        dedup_cooldown_minutes = get_cooldown_minutes(
            timeframe, config.signal_cooldown_minutes, config.signal_cooldown_tf_multiplier
        )
        last = await db.get_last_signal(symbol, timeframe)
        if last is not None:
            last_sent = last.sent_at or last.created_at
            if last_sent is not None:
                if last_sent.tzinfo is None:
                    last_sent = last_sent.replace(tzinfo=timezone.utc)
                same_direction = last.signal_type == result.signal.value
                within_cooldown = (
                    datetime.now(timezone.utc) - last_sent
                ) < timedelta(minutes=dedup_cooldown_minutes)

                if same_direction and within_cooldown:
                    elapsed = (datetime.now(timezone.utc) - last_sent).total_seconds() / 60

                    # OB-aware cooldown: compare OB midpoints
                    _cooldown_mode = getattr(config, 'cooldown_mode', 'ob_aware')
                    _ob_proximity = getattr(config, 'ob_proximity_pct', 0.5) / 100.0

                    if _cooldown_mode == 'ob_aware' and last.ob_midpoint is not None and _nearest_ob is not None:
                        ob_distance = abs(_nearest_ob.midpoint - last.ob_midpoint) / last.ob_midpoint
                        same_ob = ob_distance <= _ob_proximity

                        if not same_ob:
                            # Different OB → skip cooldown entirely
                            logger.info(
                                f"Dedup BYPASS (ob_aware): {symbol} {timeframe} — "
                                f"different OB ({_nearest_ob.midpoint:.1f} vs {last.ob_midpoint:.1f}, "
                                f"dist={ob_distance:.3%})"
                            )
                            trace.passed("dedup")
                            _current_funnel.log_gate(symbol, timeframe, "dedup", "PASS",
                                                     f"ob_aware: different OB, dist={ob_distance:.3%}")
                        else:
                            # Same OB → reduced cooldown (1/3 of full)
                            reduced_cooldown = dedup_cooldown_minutes // 3
                            if (datetime.now(timezone.utc) - last_sent) < timedelta(minutes=reduced_cooldown):
                                _current_funnel.log_gate(symbol, timeframe, "dedup", "BLOCKED",
                                                         f"same OB retest, {elapsed:.0f}m < {reduced_cooldown}m (reduced)")
                                trace.blocked("dedup", f"same OB retest, {elapsed:.0f}m < {reduced_cooldown}m (reduced)")
                                await trace.save(db)
                                await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                                 "dedup", DEDUP_OB, False,
                                                 setup_type=setup.setup_type, direction=setup.direction)
                                return None
                            else:
                                logger.info(
                                    f"Dedup BYPASS (ob_aware): {symbol} {timeframe} — "
                                    f"same OB retest cooldown passed ({elapsed:.0f}m >= {reduced_cooldown}m)"
                                )
                                trace.passed("dedup")
                                _current_funnel.log_gate(symbol, timeframe, "dedup", "PASS",
                                                         f"ob_aware: same OB retest cooldown passed")
                    else:
                        # Strict mode or no OB data → full cooldown
                        _current_funnel.log_gate(symbol, timeframe, "dedup", "BLOCKED",
                                                 f"same dir, {elapsed:.0f}m < {dedup_cooldown_minutes}m")
                        trace.blocked("dedup", f"same direction, {elapsed:.0f}m < {dedup_cooldown_minutes}m")
                        await trace.save(db)
                        await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                         "dedup", DEDUP_SAME_DIR, False,
                                         setup_type=setup.setup_type, direction=setup.direction)
                        return None

                if not same_direction and within_cooldown:
                    cross_cooldown = timedelta(minutes=dedup_cooldown_minutes // 2)
                    if (datetime.now(timezone.utc) - last_sent) < cross_cooldown:
                        _current_funnel.log_gate(symbol, timeframe, "dedup", "BLOCKED", "cross-dir cooldown")
                        trace.blocked("dedup", "cross-direction cooldown")
                        await trace.save(db)
                        await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                         "dedup", DEDUP_CROSS_DIR, False,
                                         setup_type=setup.setup_type, direction=setup.direction)
                        return None
        trace.passed("dedup")
        _current_funnel.log_gate(symbol, timeframe, "dedup", "PASS")

        # ═══ Phase 7: Save to DB ═══

        factor_fingerprint = "|".join(sorted(features.to_vector().keys()))

        # Calculate entry candle open time from dataframe index
        _entry_candle_open = None
        if df is not None and len(df) > 0 and isinstance(df.index, pd.DatetimeIndex):
            _entry_candle_open = df.index[-1]
            if _entry_candle_open.tzinfo is None:
                _entry_candle_open = _entry_candle_open.replace(tzinfo=timezone.utc)

        # Fetch execution snapshot data
        _ticker = await exchange_client.fetch_ticker_full(symbol)
        _tick_size = exchange_client.get_tick_size(symbol)
        _atr = features.atr if hasattr(features, 'atr') else None
        _last_candle = df.iloc[-1] if df is not None and len(df) > 0 else None

        # Execution Filters (TZ §11.3)
        if _ticker and _ticker.get("ask") and _ticker.get("bid"):
            _spread_pct = (_ticker["ask"] - _ticker["bid"]) / _ticker["bid"] * 100 if _ticker["bid"] > 0 else 0
            _max_spread = config.trading.max_spread_percent
            if _spread_pct > _max_spread:
                reason = f"spread {_spread_pct:.4f}% > {_max_spread}%"
                _current_funnel.log_gate(symbol, timeframe, "execution_filter", "BLOCKED", reason)
                trace.blocked("execution_filter", reason)
                await trace.save(db)
                await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                 "execution_filter", SPREAD_TOO_WIDE, False,
                                 setup_type=setup.setup_type, direction=setup.direction,
                                 meta=f"spread={_spread_pct:.4f}%,hyp_entry={entry_price:.4f},hyp_sl={sl:.4f},hyp_tp={tp:.4f},hyp_rr={risk_decision.rr_ratio:.2f},hyp_ptp={probability.p_tp:.3f}",
                                 as_of_utc=_as_of_utc, data_age_ms=_data_age_ms)
                return None

        # Depth check (TZ §7.3): order book depth within 0.5% > min_required_usdt
        if _ticker and _ticker.get("bid") and config.trading.min_depth_0_5_percent > 0:
            try:
                _depth = await exchange_client.fetch_order_book(symbol, limit=20)
                if _depth and _depth.get("bids") and _depth.get("asks"):
                    _mid = (_ticker["bid"] + _ticker["ask"]) / 2 if _ticker.get("ask") else _ticker["bid"]
                    _range = _mid * 0.005  # 0.5%
                    _bid_depth = sum(float(b[0]) * float(b[1]) for b in _depth["bids"]
                                     if _mid - _range <= float(b[0]) <= _mid)
                    _ask_depth = sum(float(a[0]) * float(a[1]) for a in _depth["asks"]
                                     if _mid <= float(a[0]) <= _mid + _range)
                    _total_depth = _bid_depth + _ask_depth
                    if _total_depth < config.trading.min_depth_0_5_percent:
                        reason = f"depth ${_total_depth:,.0f} < ${config.trading.min_depth_0_5_percent:,.0f}"
                        _current_funnel.log_gate(symbol, timeframe, "depth_check", "BLOCKED", reason)
                        trace.blocked("depth_check", reason)
                        await trace.save(db)
                        await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                         "depth_check", DEPTH_TOO_LOW, False,
                                         setup_type=setup.setup_type, direction=setup.direction,
                                         meta=f"depth=${_total_depth:,.0f},hyp_entry={entry_price:.4f},hyp_sl={sl:.4f},hyp_tp={tp:.4f},hyp_rr={risk_decision.rr_ratio:.2f},hyp_ptp={probability.p_tp:.3f}",
                                         as_of_utc=_as_of_utc, data_age_ms=_data_age_ms)
                        return None
            except Exception as e:
                logger.debug(f"Depth check failed for {symbol}: {e}")

        # No correlated entry (TZ §7.3): skip if already have open position in correlated symbol
        _correlated_symbols = getattr(config.trading, 'correlated_symbols', {})
        if _correlated_symbols:
            _group = _correlated_symbols.get(symbol)
            if _group:
                _group_symbols = [s for s, g in _correlated_symbols.items() if g == _group]
                _active_symbols = [getattr(o, 'symbol', None) for o in _active_outcomes] if '_active_outcomes' in dir() else []
                for _corr_sym in _group_symbols:
                    if _corr_sym != symbol and _corr_sym in _active_symbols:
                        reason = f"correlated entry: {_corr_sym} already open (group={_group})"
                        _current_funnel.log_gate(symbol, timeframe, "correlated_entry", "BLOCKED", reason)
                        trace.blocked("correlated_entry", reason)
                        await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                                         "correlated_entry", CORRELATION_BLOCKED, False,
                                         setup_type=setup.setup_type, direction=setup.direction,
                                         meta=f"corr_sym={_corr_sym},group={_group}")
                        await trace.save(db)
                        return None

        _current_funnel.log_gate(symbol, timeframe, "execution_filter", "PASS")

        # ═══ TOCTOU recheck: atomic portfolio reservation before save ═══
        # Between the portfolio check (Phase 0.2) and here, other coroutines
        # may have passed the same gate. Recheck atomically.
        _active_now = await db.get_active_signals_count()
        if _active_now >= config.max_active_signals:
            reason = f"TOCTOU: max active signals ({_active_now}/{config.max_active_signals})"
            _current_funnel.log_gate(symbol, timeframe, "portfolio_risk", "BLOCKED", reason)
            trace.blocked("portfolio_risk", reason)
            await trace.save(db)
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "portfolio_risk", PORTFOLIO_MAX_ACTIVE, False)
            return None
        _risk_now = await db.get_portfolio_risk_sum()
        if _risk_now >= config.max_portfolio_risk_pct:
            reason = f"TOCTOU: portfolio risk {_risk_now:.1f}% >= {config.max_portfolio_risk_pct}%"
            _current_funnel.log_gate(symbol, timeframe, "portfolio_risk", "BLOCKED", reason)
            trace.blocked("portfolio_risk", reason)
            await trace.save(db)
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "portfolio_risk", PORTFOLIO_MAX_RISK, False)
            return None

        # ═══ Phase 7.5: Pre-reserve daily limits BEFORE saving signal ═══
        # Atomic: check + reserve. If fails, reject before persisting signal.
        from risk.daily_limits import daily_limits
        _dl_pre_allowed, _dl_pre_actual, _dl_pre_reason = daily_limits.try_open_trade(risk_decision.risk_pct)
        if not _dl_pre_allowed:
            reason = f"daily limits (pre-reserve): {_dl_pre_reason}"
            _current_funnel.log_gate(symbol, timeframe, "daily_limits", "BLOCKED", reason)
            trace.blocked("daily_limits", reason)
            await trace.save(db)
            await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                             "daily_limits", DAILY_LIMIT_HIT, False)
            return None

        saved_signal = await db.save_signal(
            symbol=result.symbol,
            timeframe=result.timeframe,
            signal_type=result.signal.value,
            close_price=result.close,
            sl=result.sl,
            tp=result.tp,
            score=result.score,
            reasons=result.reasons,
            confirmed=False,
            factor_fingerprint=factor_fingerprint,
            confidence_v2_pct=probability.p_tp * 100,
            confidence_v2_factors=[],
            entry_candle_open=_entry_candle_open,
            # Execution snapshot
            entry_price_source="CLOSE",
            entry_open=float(_last_candle["open"]) if _last_candle is not None else None,
            entry_mid=float((_last_candle["high"] + _last_candle["low"]) / 2) if _last_candle is not None else None,
            entry_bid=_ticker.get("bid") if _ticker else None,
            entry_ask=_ticker.get("ask") if _ticker else None,
            entry_spread=(_ticker.get("ask") - _ticker.get("bid")) if _ticker and _ticker.get("ask") and _ticker.get("bid") else None,
            entry_atr=_atr,
            entry_tick_size=_tick_size,
            signal_detected_at=datetime.now(timezone.utc),
            # OB info for cooldown dedup
            ob_midpoint=_nearest_ob.midpoint if _nearest_ob else None,
            ob_type=_nearest_ob.type if _nearest_ob else None,
        )

        trace.set_signal(
            signal_type=result.signal.value,
            score=result.score,
            close_price=result.close,
            sl=result.sl,
            tp=result.tp,
        )

        # Build execution snapshot
        _signal_detected_at = saved_signal.signal_detected_at
        _telegram_sent_at = saved_signal.sent_at
        _latency_ms = None
        if _signal_detected_at and _telegram_sent_at:
            _latency_ms = (_telegram_sent_at - _signal_detected_at).total_seconds() * 1000

        _exec_snapshot = ExecutionSnapshot(
            entry_candle_open=_entry_candle_open.isoformat() if _entry_candle_open else None,
            entry_timestamp=_signal_detected_at.isoformat() if _signal_detected_at else None,
            entry_bar_index=len(df) - 1 if df is not None else None,
            spread=(_ticker.get("ask") - _ticker.get("bid")) if _ticker and _ticker.get("ask") and _ticker.get("bid") else None,
            atr=_atr,
            tick_size=_tick_size,
            buffer_total=abs(result.sl - result.close) if result.sl and result.close else None,
            execution_latency_ms=_latency_ms,
            entry_source="CLOSE",
            entry_price=result.close,
            bid=_ticker.get("bid") if _ticker else None,
            ask=_ticker.get("ask") if _ticker else None,
            open=float(_last_candle["open"]) if _last_candle is not None else None,
            close=float(_last_candle["close"]) if _last_candle is not None else None,
            mid=float((_last_candle["high"] + _last_candle["low"]) / 2) if _last_candle is not None else None,
            signal_detected_at=_signal_detected_at.isoformat() if _signal_detected_at else None,
            telegram_sent_at=_telegram_sent_at.isoformat() if _telegram_sent_at else None,
        )
        trace.set_execution_snapshot(_exec_snapshot)

        _trace_features = features.to_vector()
        _trace_features["p_tp"] = probability.p_tp
        _trace_features["expected_rr"] = probability.expected_rr
        _trace_features["risk_pct"] = risk_decision.risk_pct
        _trace_features["visual"] = features.to_visual()
        trace.set_features(_trace_features)
        trace.set_version(VERSION)
        await trace.save(db, signal_id=saved_signal.id)

        # Audit OK — signal passed all gates
        await _audit_log(symbol, timeframe, datetime.now(timezone.utc),
                         "pipeline", OK, True,
                         setup_type=setup.setup_type, direction=setup.direction,
                         features_snapshot=json.dumps(_trace_features) if _trace_features else None)

        # ═══ Phase 8: Atomic outcome + cooldown ═══
        # Daily limits already pre-reserved in Phase 7.5.
        try:
            await db.create_outcome(saved_signal.id, risk_pct=risk_decision.risk_pct)
        except Exception as e:
            logger.error(f"Phase 8 atomic save failed for {symbol} {timeframe}: {e}")
            # Rollback: release the pre-reserved daily limit
            try:
                from risk.daily_limits import daily_limits
                daily_limits.release_trade(risk_decision.risk_pct)
            except Exception:
                pass
            return None

        await _set_cooldown(symbol, timeframe)

        # Generate signal chart PNG
        _chart_png = None
        try:
            from charts.signal_chart import generate_signal_chart
            _visual = features.to_visual() if features else {}
            _chart_png = generate_signal_chart(
                df=_df_clean,
                direction=setup.direction,
                entry_price=entry_price,
                sl=risk_decision.sl_price,
                tp=risk_decision.tp_price,
                symbol=symbol,
                timeframe=timeframe,
                visual=_visual,
                score=features.components_count if features else 0,
                p_tp=probability.p_tp,
                expected_rr=risk_decision.rr_ratio,
            )
        except Exception as e:
            logger.debug(f"Chart generation failed for {symbol} {timeframe}: {e}")

        try:
            await notify_callback(result, context_verdict, chart_png=_chart_png)
        except Exception as e:
            logger.error(f"Failed to send notification for {result.signal} {symbol} {timeframe}: {e}")

        signals_total.labels(
            signal_type=result.signal.value,
            symbol=symbol,
            timeframe=timeframe,
        ).inc()

        _current_funnel.passed += 1
        logger.info(
            f"Signal: {result.signal.value} {symbol} {timeframe} | "
            f"P(TP)={probability.p_tp:.1%} RR={risk_decision.rr_ratio:.2f} "
            f"risk={risk_decision.risk_pct:.2f}%"
        )
        return result


# ══════════════════════════════════════════════════════════════════════
#  Scan Cycle
# ══════════════════════════════════════════════════════════════════════

async def run_scan_cycle(notify_callback, blocked_callback=None, timeframes: Optional[list[str]] = None):
    """One scan cycle —遍历 all symbols and timeframes in parallel."""
    if _scan_lock.locked():
        logger.warning("Scan cycle already in progress — skipping this trigger")
        return
    async with _scan_lock:
        await check_recent_losses()
        if is_circuit_breaker_active():
            logger.warning("Scan skipped — circuit breaker active (too many recent losses)")
            return

        symbols = get_active_symbols()
        disabled = await db.get_disabled_symbols() or []
        symbols = [s for s in symbols if s not in disabled]
        tfs = timeframes if timeframes is not None else config.trading.primary_timeframes

        logger.info(f"Starting scan: {len(symbols)} symbols × {tfs}")

        _current_funnel.__init__()

        tasks = []
        for symbol in symbols:
            for tf in tfs:
                tasks.append(scan_symbol_v2(symbol, tf, notify_callback, blocked_callback))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        signals_found = 0
        for result in results:
            if isinstance(result, SignalResult) and result is not None:
                signals_found += 1
            elif isinstance(result, Exception):
                logger.error(f"Scan task failed: {result}", exc_info=result)
        logger.info(f"Scan complete. Signals found: {signals_found}/{len(tasks)}")
    _current_funnel.log_summary()
