"""
scheduler/scanner.py — Основной сканер рынка.
Логика: проверяем сигнал на 1H/4H, подтверждаем на 15M.
"""
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional
from loguru import logger
from config.settings import config, get_active_symbols
from data.exchange_client import exchange_client
from indicators.engine import indicator_engine, IndicatorValues
from strategy.signal_engine import signal_engine, SignalResult, SignalType
from strategy.levels import get_support_resistance, validate_levels_vs_trade
from storage.database import db
from context.analyzer import context_engine, ContextSnapshot
from context.scorer import context_scorer, ContextVerdict
from monitoring.metrics import scan_duration_seconds, signals_total
from market_structure.distance_filter import check_distance_filter
from market_structure.tp_path import evaluate_tp_path
from market_structure.structure import analyze_structure, check_mtf_alignment
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from liquidity.candle_quality import analyze_last_candle
from derivatives.btc_correlation import fetch_btc_context
from derivatives.eth_correlation import fetch_eth_context
from derivatives.funding import classify_funding
from derivatives.open_interest import classify_oi
from risk.volatility_regime import classify_volatility
from risk.dynamic_risk import calculate_risk
from risk.no_trade_zones import check_no_trade_zones
from risk.market_regime import RegimeDetector, MarketRegime
from scoring.confidence_v2 import (
    confidence_engine_v2,
    score_htf_trend,
    score_structure,
    score_liquidity,
    score_volume,
    score_btc_correlation,
    score_funding_from_state,
    score_oi_from_state,
    score_rsi,
    score_macd,
    score_adx,
)
from scheduler.circuit_breaker import is_circuit_breaker_active, check_recent_losses

# Порядок вердиктов от худшего к лучшему — используется для CONTEXT_MIN_VERDICT.
_VERDICT_RANK = {"BLOCKED": 0, "CONFLICTED": 1, "WEAK": 2, "CONFIRMED": 3}


def _build_factor_fingerprint(
    ind,
    result: SignalResult,
    mtf_aligned: bool,
    liq_bullish_sweeps: int,
    liq_bearish_sweeps: int,
    liq_has_bullish_ob: bool,
    liq_has_bearish_ob: bool,
    liq_has_bullish_fvg: bool,
    liq_has_bearish_fvg: bool,
) -> str:
    """Build a deterministic fingerprint string for the factor combination (Task 6.1).

    Format: sorted key=value pairs joined by '|', e.g.:
    'adx_strong|ema_bullish|macd_pos|mtf_aligned|st_bullish|vol_above'
    """
    flags: list[str] = []

    # Trend factors
    if result._structure_trend == "bullish":
        flags.append("trend_bullish")
    elif result._structure_trend == "bearish":
        flags.append("trend_bearish")

    if result._structure_bos == "bullish":
        flags.append("bos_bullish")
    elif result._structure_bos == "bearish":
        flags.append("bos_bearish")

    # EMA alignment (from reasons or factor_strengths)
    ema_strength = result._factor_strengths.get("EMA", 0)
    if ema_strength > 0:
        flags.append("ema_bullish")
    elif ema_strength < 0:
        flags.append("ema_bearish")

    # Supertrend
    st_strength = result._factor_strengths.get("Supertrend", 0)
    if st_strength > 0:
        flags.append("st_bullish")
    elif st_strength < 0:
        flags.append("st_bearish")

    # MACD
    macd_strength = result._factor_strengths.get("MACD", 0)
    if macd_strength > 0:
        flags.append("macd_pos")
    elif macd_strength < 0:
        flags.append("macd_neg")

    # RSI
    rsi_val = float(ind.rsi) if ind.rsi is not None else 50
    if rsi_val < config.trading.rsi_oversold:
        flags.append("rsi_oversold")
    elif rsi_val >= config.trading.rsi_overbought:
        flags.append("rsi_overbought")

    # Volume
    vol_strength = result._factor_strengths.get("Volume", 0)
    if vol_strength > 0:
        flags.append("vol_above")
    elif vol_strength < 0:
        flags.append("vol_below")

    # ADX
    adx_val = float(ind.adx) if ind.adx is not None else 0
    if adx_val >= 25:
        flags.append("adx_strong")

    # MTF
    if mtf_aligned:
        flags.append("mtf_aligned")

    # Liquidity
    if liq_bullish_sweeps > 0:
        flags.append("liq_bull_sweep")
    if liq_bearish_sweeps > 0:
        flags.append("liq_bear_sweep")
    if liq_has_bullish_ob:
        flags.append("liq_bull_ob")
    if liq_has_bearish_ob:
        flags.append("liq_bear_ob")
    if liq_has_bullish_fvg:
        flags.append("liq_bull_fvg")
    if liq_has_bearish_fvg:
        flags.append("liq_bear_fvg")

    return "|".join(sorted(flags))


def _verdict_passes_min(verdict: str) -> bool:
    """True, если фактический verdict ≥ настроенного CONTEXT_MIN_VERDICT.

    Пустая строка / неизвестное значение → гейт отключён.
    """
    min_v = (config.context_min_verdict or "").strip().upper()
    if min_v not in _VERDICT_RANK:
        return True
    return _VERDICT_RANK.get(verdict, 0) >= _VERDICT_RANK[min_v]


def _detect_regime(ind: IndicatorValues, df) -> Optional[MarketRegime]:
    """Detect market regime from indicator values and OHLCV data."""
    try:
        adx = float(ind.adx) if ind.adx is not None else 20.0
        current_atr = float(ind.atr) if ind.atr is not None else 0.0
        current_volume = float(ind.volume) if ind.volume is not None else 0.0

        # Build ATR history from dataframe (approximate using high-low range)
        if len(df) >= 10:
            atr_history = []
            for _, row in df.tail(config.risk.regime_atr_lookback).iterrows():
                high_low = row['high'] - row['low']
                atr_history.append(float(high_low))
        else:
            atr_history = [current_atr] * 10

        # Build EMA spread history (approximate from recent values)
        ema_fast = float(ind.ema_fast) if ind.ema_fast is not None else 0.0
        ema_slow = float(ind.ema_slow) if ind.ema_slow is not None else 0.0
        current_spread = abs(ema_fast - ema_slow) if ema_slow > 0 else 0.0
        ema_spread_history = [current_spread] * 5

        # Volume history from dataframe
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


async def _is_cooldown_active(symbol: str, timeframe: str) -> bool:
    last = await db.get_cooldown(symbol, timeframe)
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - last
    return delta < timedelta(minutes=config.signal_cooldown_minutes)


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

    ind = indicator_engine.calculate(df, symbol, timeframe)

    if ind is None:
        logger.warning(
            f"Indicator calculation failed for {symbol} {timeframe}"
        )
        return None

    return ind, df


async def scan_symbol(symbol: str, timeframe: str, notify_callback) -> Optional[SignalResult]:
    """
    Сканируем один символ на одном таймфрейме.
    Если есть сигнал — подтверждаем на 15M.
    """
    with scan_duration_seconds.labels(timeframe=timeframe).time():
        if await _is_cooldown_active(symbol, timeframe):
            logger.debug(f"Cooldown active: {symbol} {timeframe}")
            return None

        # Шаг 1: Основной таймфрейм
        ind_result = await _get_indicators(symbol, timeframe)
        if ind_result is None:
            return None
        ind, df = ind_result

        # Detect Market regime (Task 4.2)
        regime = _detect_regime(ind, df)

        # Early liquidity/structure analysis for structural SL/TP (Task 5.1)
        _sweeps: list = []
        _order_blocks: list = []
        _structure = None
        _df_clean = None
        try:
            _df_clean = df.dropna(subset=["open", "high", "low", "close", "volume"])
            if len(_df_clean) >= 10:
                _sweeps = detect_sweeps(_df_clean, lookback=50)
                _order_blocks = detect_order_blocks(_df_clean, lookback=100)
                _structure = analyze_structure(_df_clean, lookback=50)
        except Exception as e:
            logger.warning(f"Early structure/liquidity analysis failed for {symbol} {timeframe}: {e}")

        result = signal_engine.evaluate(
            ind,
            regime=regime,
            sweeps=_sweeps,
            order_blocks=_order_blocks,
            structure=_structure,
        )
        if not result.is_actionable:
            logger.debug(f"No signal: {symbol} {timeframe}")
            return None

        logger.info(f"Signal candidate: {result.signal} {symbol} {timeframe} (score={result.score})")

        # FIX M7: define is_buy once at function scope to avoid stale scope bug
        is_buy = result.signal == SignalType.BUY

        # Шаг 2: Подтверждение на 15M
        confirm_tf = config.trading.confirm_timeframe
        entry_price: Optional[float] = None
        confirmed_on_lower_tf = False
        if confirm_tf != timeframe:
            ind_confirm_result = await _get_indicators(symbol, confirm_tf)
            if ind_confirm_result is not None:
                ind_confirm, _df_confirm = ind_confirm_result
                confirm_ok = signal_engine.evaluate_confirm(
                    ind_confirm,
                    direction='buy' if result.signal == SignalType.BUY else 'sell'
                )
                if not confirm_ok:
                    logger.info(
                        f"Signal NOT confirmed on {confirm_tf}: "
                        f"direction mismatch — {symbol}"
                    )
                    return None
                entry_price = ind_confirm.close
                confirmed_on_lower_tf = True
                logger.info(f"Signal CONFIRMED on {confirm_tf}: {result.signal} {symbol}")
                result.reasons.append(f"✅ Подтверждение на {confirm_tf}")
                result._confirmed_tf = confirm_tf
            else:
                logger.warning(f"Could not get {confirm_tf} data for {symbol}, skipping confirmation")
                entry_price = result.close
        else:
            entry_price = result.close

        # Шаг 2.5: Уровни поддержки/сопротивления
        sr_levels = {}
        # Liquidity data tracked at function scope for V2 confidence
        _liq_bullish_sweeps = 0
        _liq_bearish_sweeps = 0
        _liq_has_bullish_ob = False
        _liq_has_bearish_ob = False
        _liq_has_bullish_fvg = False
        _liq_has_bearish_fvg = False
        # MTF alignment tracking
        _mtf_aligned = False
        _mtf_count = 0
        # BTC/ETH context tracking
        _btc_ctx = None
        _btc_allows = True
        _btc_strong = False
        _eth_ctx = None
        _eth_allows = True
        for sr_tf in ['1h', '4h']:
            try:
                sr_df = await exchange_client.fetch_ohlcv(symbol, sr_tf, limit=100)
                if sr_df is not None and len(sr_df) > 0:
                    current_price = entry_price or result.close
                    levels = get_support_resistance(sr_df, current_price)
                    if levels['resistance'] or levels['support']:
                        sr_levels[sr_tf] = levels
            except Exception as e:
                logger.warning(f"Failed to calculate S/R levels for {symbol} {sr_tf}: {e}")

        if sr_levels:
            result.sr_levels = sr_levels
            result.level_warnings = validate_levels_vs_trade(
                sr_levels, entry_price or result.close, result.sl, result.tp, is_buy
            )

            # Шаг 2.6: Distance Filter
            direction = "long" if is_buy else "short"
            dist_result = check_distance_filter(
                direction=direction,
                entry_price=entry_price or result.close,
                sr_levels=sr_levels,
            )
            if dist_result.blocked:
                logger.info(
                    f"Signal BLOCKED by distance filter: {result.signal} {symbol} {timeframe} — "
                    f"{'; '.join(dist_result.reasons)}"
                )
                return None
            result._distance_filter_blocked = False

            # Шаг 2.7: TP Path Quality
            tp_eval = evaluate_tp_path(
                direction=direction,
                entry_price=entry_price or result.close,
                tp_price=result.tp or 0,
                sr_levels=sr_levels,
            )
            result._tp_path_score = tp_eval.score
            result._tp_path_blocked = tp_eval.blocked
            if tp_eval.blocked:
                logger.info(
                    f"Signal BLOCKED by TP path quality: {result.signal} {symbol} {timeframe} — "
                    f"{tp_eval.reject_reason}"
                )
                return None
            for obs in tp_eval.obstacles:
                result.level_warnings.append(f"⚠️ TP path: {obs.description}")

            # Шаг 2.8: Market Structure Analysis (reuses early-computed data from Task 5.1)
            try:
                if _structure is not None:
                    result._structure_trend = _structure.trend
                    if _structure.last_bos:
                        result._structure_bos = _structure.last_bos.type
                    logger.debug(
                        f"Structure {symbol} {timeframe}: trend={_structure.trend}, "
                        f"bos={_structure.last_bos.type if _structure.last_bos else 'none'}, "
                        f"breaks={_structure.structure_breaks}"
                    )
                else:
                    logger.warning(f"Structure data not available: {symbol} {timeframe}")
            except Exception as e:
                logger.warning(f"Structure analysis failed for {symbol} {timeframe}: {e}")

            # Шаг 2.8b: Liquidity Analysis (reuses early-computed data from Task 5.1)
            try:
                if _sweeps and _order_blocks:
                    valid_bullish_sweeps = [s for s in _sweeps if s.type == "bullish" and s.is_valid]
                    valid_bearish_sweeps = [s for s in _sweeps if s.type == "bearish" and s.is_valid]
                    _liq_bullish_sweeps = len(valid_bullish_sweeps)
                    _liq_bearish_sweeps = len(valid_bearish_sweeps)

                    if valid_bullish_sweeps:
                        result.reasons.append(
                            f"Liquidity: bullish sweep detected (reclaim in {valid_bullish_sweeps[-1].reclaim_candles} candles)"
                        )

                    if valid_bearish_sweeps:
                        result.reasons.append(
                            f"Liquidity: bearish sweep detected (reclaim in {valid_bearish_sweeps[-1].reclaim_candles} candles)"
                        )

                    if _order_blocks:
                        recent_ob = _order_blocks[-1]
                        _liq_has_bullish_ob = recent_ob.type == "bullish"
                        _liq_has_bearish_ob = recent_ob.type == "bearish"
                        result.reasons.append(
                            f"Order Block: {recent_ob.type} at {recent_ob.midpoint:.4f}"
                        )

                    # FVG detection still needs to run separately
                    fvgs = detect_fvg(_df_clean, lookback=getattr(config, "liquidity_fvg_lookback", 100))
                    if fvgs:
                        active_fvgs = [f for f in fvgs if f.is_active]
                        recent_fvg = active_fvgs[-1] if active_fvgs else None
                        if recent_fvg:
                            _liq_has_bullish_fvg = recent_fvg.type == "bullish"
                            _liq_has_bearish_fvg = recent_fvg.type == "bearish"
                            result.reasons.append(
                                f"FVG: {recent_fvg.type} ({recent_fvg.size_pct:.2f}%)"
                            )
                        else:
                            filled_count = len(fvgs) - len(active_fvgs)
                            logger.debug(f"All {len(fvgs)} FVGs filled ({filled_count}) for {symbol} {timeframe}")

                    # Recalculate TP with FVGs (Task 5.2 — Dynamic TP)
                    if fvgs and result.tp is not None:
                        try:
                            from risk.dynamic_risk import calculate_structural_tp as recalc_tp
                            atr_val = float(ind.atr) if ind.atr is not None else 0.0
                            if atr_val <= 0:
                                atr_val = float(ind.close) * 0.02 if ind.close else 0.02
                            new_targets = recalc_tp(
                                direction=result.signal.value,
                                entry=entry_price or result.close,
                                sl=result.sl or (entry_price or result.close),
                                sweeps=_sweeps,
                                order_blocks=_order_blocks,
                                structure=_structure,
                                fvgs=fvgs,
                                atr=atr_val,
                                close=float(ind.close) if ind.close else 0.0,
                            )
                            if new_targets:
                                old_tp = result.tp
                                result.tp = new_targets[0].price
                                if result.tp != old_tp:
                                    logger.info(
                                        f"TP recalculated with FVG for {symbol} {timeframe}: "
                                        f"{old_tp:.4f} → {result.tp:.4f} (RR={new_targets[0].rr:.1f})"
                                    )
                                    result.reasons.append(f"TP adjusted by FVG: {result.tp:.4f}")
                        except Exception as e:
                            logger.warning(f"TP recalculation with FVG failed for {symbol} {timeframe}: {e}")

                    candle_quality = analyze_last_candle(_df_clean, atr_value=ind.atr)
                    if candle_quality:
                        if candle_quality.is_displacement:
                            direction_label = "bullish" if candle_quality.is_bullish else "bearish"
                            result.reasons.append(
                                f"Candle: {direction_label} displacement (body={candle_quality.body_pct:.0%})"
                            )
                        if candle_quality.is_weak:
                            result.level_warnings.append(
                                f"Weak candle pattern (body={candle_quality.body_pct:.0%}, momentum={candle_quality.momentum_score:+.2f})"
                            )

                    tp_eval_with_liquidity = evaluate_tp_path(
                        direction=direction,
                        entry_price=entry_price or result.close,
                        tp_price=result.tp or 0,
                        sr_levels=sr_levels,
                        order_blocks=_order_blocks,
                        fvgs=fvgs,
                    )
                    if tp_eval_with_liquidity.blocked and not tp_eval.blocked:
                        logger.info(
                            f"Signal BLOCKED by liquidity obstacles: {result.signal} {symbol} {timeframe} — "
                            f"{tp_eval_with_liquidity.reject_reason}"
                        )
                        return None
                    for obs in tp_eval_with_liquidity.obstacles:
                        if obs not in tp_eval.obstacles:
                            result.level_warnings.append(f"TP path: {obs.description}")
                else:
                    logger.warning(f"Liquidity data not available: {symbol} {timeframe}")
            except Exception as e:
                logger.warning(f"Liquidity analysis failed for {symbol} {timeframe}: {e}")

            # Шаг 2.9: Multi-Timeframe Alignment
            if config.market_structure.mtf_enabled and result.tp:
                try:
                    mtf_result = await check_mtf_alignment(
                        symbol=symbol,
                        direction="bullish" if is_buy else "bearish",
                        primary_tf=timeframe,
                        exchange_client=exchange_client,
                    )
                    if not mtf_result.aligned:
                        logger.info(
                            f"Signal BLOCKED by MTF alignment: {result.signal} {symbol} {timeframe} — "
                            f"state={mtf_result.alignment_state}, not enough HTFs aligned"
                        )
                        return None
                    _mtf_aligned = True
                    _mtf_count = len(mtf_result.states)
                    _mtf_state = mtf_result.alignment_state
                    logger.debug(
                        f"MTF alignment OK for {symbol} {timeframe}: "
                        f"state={mtf_result.alignment_state}, {len(mtf_result.states)} HTFs checked"
                    )
                except Exception as e:
                    logger.warning(f"MTF alignment check failed for {symbol} {timeframe}: {e}")

            # Шаг 2.10: BTC Correlation Gate
            if config.derivatives.btc_correlation_enabled:
                try:
                    _btc_ctx = await fetch_btc_context()
                    if _btc_ctx is not None:
                        if is_buy and not _btc_ctx.allows_long():
                            logger.info(
                                f"Signal BLOCKED by BTC correlation: LONG not allowed "
                                f"(above_ema200={_btc_ctx.above_ema200}, structure={_btc_ctx.structure})"
                            )
                            return None
                        if not is_buy and not _btc_ctx.allows_short():
                            logger.info(
                                f"Signal BLOCKED by BTC correlation: SHORT not allowed "
                                f"(bullish breakout detected)"
                            )
                            return None
                        _btc_allows = True
                        _btc_strong = _btc_ctx.above_ema200 if is_buy else not _btc_ctx.above_ema200
                        logger.debug(
                            f"BTC correlation OK for {symbol}: "
                            f"price={_btc_ctx.price:.0f}, ema200={_btc_ctx.ema200_4h:.0f}, "
                            f"structure={_btc_ctx.structure}"
                        )
                except Exception as e:
                    logger.warning(f"BTC correlation check failed for {symbol}: {e}")

            # Шаг 2.11: ETH Correlation Gate (FIX E1)
            if config.derivatives.eth_correlation_enabled:
                try:
                    _eth_ctx = await fetch_eth_context()
                    if _eth_ctx is not None:
                        if is_buy and not _eth_ctx.allows_long(symbol):
                            logger.info(
                                f"Signal BLOCKED by ETH correlation: LONG not allowed "
                                f"for {symbol} (ETH structure={_eth_ctx.structure}, momentum={_eth_ctx.momentum:+.1f}%)"
                            )
                            return None
                        if not is_buy and not _eth_ctx.allows_short(symbol):
                            logger.info(
                                f"Signal BLOCKED by ETH correlation: SHORT not allowed "
                                f"for {symbol} (ETH impulsive up, momentum={_eth_ctx.momentum:+.1f}%)"
                            )
                            return None
                        _eth_allows = True
                        logger.debug(
                            f"ETH correlation OK for {symbol}: "
                            f"structure={_eth_ctx.structure}, impulsive={_eth_ctx.is_impulsive_up}"
                        )
                except Exception as e:
                    logger.warning(f"ETH correlation check failed for {symbol}: {e}")

        # Шаг 2.12: Volatility Regime & Dynamic Risk (Phase 4)
        vol_regime = classify_volatility(ind.atr, ind.close)
        logger.debug(
            f"Volatility regime {symbol} {timeframe}: "
            f"regime={vol_regime.regime}, atr_pct={vol_regime.atr_pct:.2f}%"
        )

        if not vol_regime.allow_breakout:
            logger.info(
                f"Signal BLOCKED by volatility regime: {result.signal} {symbol} {timeframe} — "
                f"low volatility (ATR%={vol_regime.atr_pct:.2f}), breakout trades disabled"
            )
            return None

        # Шаг 3: Контекстное обогащение (moved BEFORE no-trade check)
        context_verdict: Optional[ContextVerdict] = None
        if config.context_enabled:
            try:
                snapshot = await asyncio.wait_for(
                    context_engine.get_snapshot(symbol),
                    timeout=10.0,
                )
                context_verdict = context_scorer.score(result.signal.value, snapshot)

                result._context_score = context_verdict.score

                # Формируем элементы контекста для вывода
                snap = context_verdict.snapshot
                if snap:
                    ctx_items = []
                    if snap.fear_greed_value is not None:
                        fg_score = context_scorer._score_fear_greed(snap.fear_greed_value, result.signal.value)
                        fg_emoji = "✅" if fg_score > 0 else ("⚠️" if fg_score == 0 else "🔴")
                        ctx_items.append(f"{fg_emoji} Fear & Greed: {snap.fear_greed_value} ({snap.fear_greed_label})")
                    if snap.funding_rate is not None:
                        fr_score = context_scorer._score_funding_rate(snap.funding_rate, result.signal.value)
                        fr_emoji = "✅" if fr_score > 0 else ("⚠️" if fr_score == 0 else "🔴")
                        ctx_items.append(f"{fr_emoji} Funding: {snap.funding_rate * 100:.3f}%")
                    if snap.long_short_ratio is not None:
                        ls_score = context_scorer._score_long_short(snap.long_short_ratio, result.signal.value)
                        ls_emoji = "✅" if ls_score > 0 else ("⚠️" if ls_score == 0 else "🔴")
                        ctx_items.append(f"{ls_emoji} Long/Short: {snap.long_short_ratio:.2f}")
                    if snap.open_interest_delta is not None:
                        oi_score = context_scorer._score_oi(snap.open_interest_delta, result.signal.value)
                        oi_emoji = "✅" if oi_score > 0 else ("⚠️" if oi_score == 0 else "🔴")
                        ctx_items.append(f"{oi_emoji} OI: {snap.open_interest_delta:+.1f}%")

                    # Derivatives classification (Phase 3)
                    if snap.funding_rate is not None:
                        f_state = classify_funding(snap.funding_rate)
                        f_contrib = f_state.contributes_to(result.signal.value)
                        if f_state.strength == "strong":
                            dir_emoji = "✅" if f_contrib > 0 else "🔴"
                            ctx_items.append(
                                f"{dir_emoji} Funding: {f_state.state} ({f_state.strength}, "
                                f"contrib={f_contrib:+d})"
                            )
                    if snap.open_interest_delta is not None:
                        price_change = snap.price_change_24h or 0.0
                        oi_state = classify_oi(snap.open_interest_delta, price_change)
                        oi_contrib = oi_state.contributes_to(result.signal.value)
                        if oi_state.significance != "ignore":
                            dir_emoji = "✅" if oi_contrib > 0 else "🔴"
                            ctx_items.append(
                                f"{dir_emoji} OI: {oi_state.pattern} ({oi_state.significance}, "
                                f"contrib={oi_contrib:+d})"
                            )

                    result._context_items = ctx_items

                if config.context_block_on_blocked and context_verdict.verdict == "BLOCKED":
                    logger.info(
                        f"Signal BLOCKED by context: {result.signal} {symbol} {timeframe} "
                        f"(score={context_verdict.score:.2f})"
                    )
                    return None

                if not _verdict_passes_min(context_verdict.verdict):
                    logger.info(
                        f"Signal rejected by CONTEXT_MIN_VERDICT={config.context_min_verdict}: "
                        f"actual={context_verdict.verdict} for {result.signal} {symbol} {timeframe}"
                    )
                    return None

                logger.info(
                    f"Context verdict: {context_verdict.verdict} "
                    f"(score={context_verdict.score:.2f}) for {result.signal} {symbol}"
                )
            except asyncio.TimeoutError:
                logger.warning(f"Context enrichment timeout for {symbol}")
            except Exception as e:
                logger.warning(f"Context enrichment error for {symbol}: {e}")

        # Сохраняем контекст в БД
        if context_verdict is not None:
            try:
                await db.save_context_snapshot(
                    symbol=symbol,
                    signal_id=None,
                    verdict=context_verdict.verdict,
                    confidence=context_verdict.confidence,
                    score=context_verdict.score,
                    fear_greed=context_verdict.snapshot.fear_greed_value if context_verdict.snapshot else None,
                    funding_rate=context_verdict.snapshot.funding_rate if context_verdict.snapshot else None,
                    long_short_ratio=context_verdict.snapshot.long_short_ratio if context_verdict.snapshot else None,
                    open_interest_delta=context_verdict.snapshot.open_interest_delta if context_verdict.snapshot else None,
                    news_sentiment=context_verdict.snapshot.news_sentiment_score if context_verdict.snapshot else None,
                    raw_json=context_verdict.snapshot.to_json() if context_verdict.snapshot else None,
                )
            except Exception as e:
                logger.warning(f"Failed to save context snapshot: {e}")

        # No-trade zone check (reuses cached BTC/ETH contexts from correlation gates)
        btc_ok = True
        eth_ok = True
        try:
            if config.derivatives.btc_correlation_enabled and _btc_ctx is not None:
                btc_ok = _btc_ctx.allows_long() if is_buy else _btc_ctx.allows_short()
        except Exception:
            pass

        try:
            if config.derivatives.eth_correlation_enabled and _eth_ctx is not None:
                eth_ok = _eth_ctx.allows_short(symbol) if not is_buy else True
        except Exception:
            pass

        funding_state_val = None
        funding_strength_val = None
        oi_sig_val = None
        oi_pattern_val = None
        if context_verdict is not None and context_verdict.snapshot:
            snap = context_verdict.snapshot
            if snap.funding_rate is not None:
                f_st = classify_funding(snap.funding_rate)
                funding_state_val = f_st.state
                funding_strength_val = f_st.strength
            if snap.open_interest_delta is not None:
                oi_st = classify_oi(snap.open_interest_delta, snap.price_change_24h or 0.0)
                oi_sig_val = oi_st.significance
                oi_pattern_val = oi_st.pattern

        structure_trend = getattr(result, "_structure_trend", None)
        tp_blocked = getattr(result, "_tp_path_blocked", False)

        no_trade = check_no_trade_zones(
            funding_state=funding_state_val,
            funding_strength=funding_strength_val,
            atr_pct=vol_regime.atr_pct,
            market_structure=structure_trend,
            btc_aligned=btc_ok,
            tp_blocked=tp_blocked,
            oi_significance=oi_sig_val,
            oi_pattern=oi_pattern_val,
            market_type=config.exchange.market_type,
        )

        if no_trade.blocked:
            logger.info(
                f"Signal BLOCKED by no-trade zones: {result.signal} {symbol} {timeframe} — "
                f"{'; '.join(no_trade.reasons)}"
            )
            return None

        # Dynamic risk calculation
        setup_quality = result.verdict.lower() if result.verdict.lower() in ("strong", "moderate", "weak") else "moderate"
        risk_params = calculate_risk(
            setup_quality=setup_quality,
            volatility_regime=vol_regime.regime,
            btc_aligned=btc_ok,
            eth_aligned=eth_ok,
        )
        logger.debug(
            f"Risk params {symbol} {timeframe}: "
            f"quality={setup_quality}, base_risk={risk_params.base_risk_pct}%, "
            f"effective_risk={risk_params.effective_risk_pct}%, should_trade={risk_params.should_trade}"
        )

        if not risk_params.should_trade:
            logger.info(
                f"Signal BLOCKED by dynamic risk: {result.signal} {symbol} {timeframe} — "
                f"weak setup, trading disabled"
            )
            return None

        # Шаг 3.5: Confidence Engine V2 — weighted factor scoring
        direction_v2 = result.signal.value  # "BUY" or "SELL"
        # Funding / OI from context snapshot
        _funding_state = "neutral"
        _funding_strength = "weak"
        _oi_pattern = "neutral"
        _oi_significance = "ignore"
        if context_verdict is not None and context_verdict.snapshot:
            snap = context_verdict.snapshot
            if snap.funding_rate is not None:
                f_st = classify_funding(snap.funding_rate)
                _funding_state = f_st.state
                _funding_strength = f_st.strength
            if snap.open_interest_delta is not None:
                oi_st = classify_oi(snap.open_interest_delta, snap.price_change_24h or 0.0)
                _oi_pattern = oi_st.pattern
                _oi_significance = oi_st.significance

        vol_ratio = (ind.volume / ind.volume_sma) if ind.volume_sma > 0 else 1.0
        mtf_required = config.market_structure.mtf_required_alignment

        # Task 6.1: Build factor fingerprint and query historical winrate
        factor_fingerprint = _build_factor_fingerprint(
            ind, result, _mtf_aligned,
            _liq_bullish_sweeps, _liq_bearish_sweeps,
            _liq_has_bullish_ob, _liq_has_bearish_ob,
            _liq_has_bullish_fvg, _liq_has_bearish_fvg,
        )
        try:
            historical_wr = await db.get_historical_winrate(factor_fingerprint)
            if historical_wr is not None:
                logger.info(
                    f"Historical WR for fingerprint '{factor_fingerprint}': "
                    f"{historical_wr}% (blended with score)"
                )
        except Exception as e:
            logger.warning(f"Failed to get historical winrate: {e}")
            historical_wr = None

        conf_v2 = confidence_engine_v2.compute(
            direction=direction_v2,  # type: ignore[arg-type]
            htf_trend_score=score_htf_trend(_mtf_aligned, _mtf_count, mtf_required),
            structure_score=score_structure(
                result._structure_trend, result._structure_bos, direction_v2
            ),
            liquidity_score=score_liquidity(
                bullish_sweeps=_liq_bullish_sweeps,
                bearish_sweeps=_liq_bearish_sweeps,
                has_bullish_ob=_liq_has_bullish_ob,
                has_bearish_ob=_liq_has_bearish_ob,
                has_bullish_fvg=_liq_has_bullish_fvg,
                has_bearish_fvg=_liq_has_bearish_fvg,
            ),
            volume_score=score_volume(ind.volume_above_avg, vol_ratio),
            btc_corr_score=score_btc_correlation(_btc_allows, _btc_strong),
            funding_score=score_funding_from_state(_funding_state, _funding_strength, direction_v2),
            oi_score=score_oi_from_state(_oi_pattern, _oi_significance, direction_v2),
            rsi_score=score_rsi(
                ind.rsi, direction_v2,
                overbought=config.trading.rsi_overbought,
                oversold=config.trading.rsi_oversold,
                bull_min=config.trading.rsi_bull_min,
                bear_max=config.trading.rsi_bear_max,
            ),
            macd_score=score_macd(ind.macd_hist, ind.close, direction_v2),
            adx_score=score_adx(ind.adx, ind.dmi_plus, ind.dmi_minus, direction_v2, config.trading.adx_min),
            historical_winrate=historical_wr,
        )
        result._confidence_v2 = conf_v2
        logger.info(
            f"Confidence V2: {conf_v2.quality} (score={conf_v2.total_score:+.1f}, "
            f"conf={conf_v2.confidence_pct:.1f}%) for {direction_v2} {symbol}"
        )

        # Шаг 4: Сохраняем сигнал в БД
        saved_signal = await db.save_signal(
            symbol=result.symbol,
            timeframe=result.timeframe,
            signal_type=result.signal.value,
            close_price=result.close,
            sl=result.sl,
            tp=result.tp,
            score=result.score,
            reasons=result.reasons,
            confirmed=confirmed_on_lower_tf,
            factor_fingerprint=factor_fingerprint,
        )

        # F1: создаём outcome для трекинга SL/TP
        await db.create_outcome(saved_signal.id)

        # Сохраняем связь сигнала с контекстом
        if context_verdict is not None:
            try:
                await db.save_context_snapshot(
                    symbol=symbol,
                    signal_id=saved_signal.id,
                    verdict=context_verdict.verdict,
                    confidence=context_verdict.confidence,
                    score=context_verdict.score,
                    fear_greed=context_verdict.snapshot.fear_greed_value if context_verdict.snapshot else None,
                    funding_rate=context_verdict.snapshot.funding_rate if context_verdict.snapshot else None,
                    long_short_ratio=context_verdict.snapshot.long_short_ratio if context_verdict.snapshot else None,
                    open_interest_delta=context_verdict.snapshot.open_interest_delta if context_verdict.snapshot else None,
                    news_sentiment=context_verdict.snapshot.news_sentiment_score if context_verdict.snapshot else None,
                    raw_json=context_verdict.snapshot.to_json() if context_verdict.snapshot else None,
                )
            except Exception as e:
                logger.warning(f"Failed to save context snapshot with signal link: {e}")

        # Шаг 5: Cooldown
        await _set_cooldown(symbol, timeframe)

        # Шаг 6: Уведомляем
        result.entry_price = entry_price
        try:
            await notify_callback(result, context_verdict)
        except Exception as e:
            logger.error(
                f"Failed to send notification for {result.signal} "
                f"{symbol} {timeframe}: {e}"
            )

        signals_total.labels(
            signal_type=result.signal.value,
            symbol=symbol,
            timeframe=timeframe,
        ).inc()

        return result


async def run_scan_cycle(notify_callback, timeframes: Optional[list[str]] = None):
    """
    Один цикл сканирования — обходим все символы и таймфреймы параллельно.

    `timeframes=None` → берёт `config.trading.primary_timeframes` целиком
    (поведение по умолчанию для ручного запуска /scan).
    Cron-джоб может передавать конкретный список, чтобы не дублировать
    сканирование других ТФ.
    """
    # Circuit breaker check — pause after series of losses
    await check_recent_losses()
    if is_circuit_breaker_active():
        logger.warning("Scan skipped — circuit breaker active (too many recent losses)")
        return

    symbols = get_active_symbols()
    disabled = await db.get_disabled_symbols() or []
    symbols = [s for s in symbols if s not in disabled]
    tfs = timeframes if timeframes is not None else config.trading.primary_timeframes

    logger.info(f"Starting scan: {len(symbols)} symbols × {tfs}")

    tasks = []
    for symbol in symbols:
        for tf in tfs:
            tasks.append(scan_symbol(symbol, tf, notify_callback))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    signals_found = 0
    for result in results:
        if isinstance(result, SignalResult) and result is not None:
            signals_found += 1
        elif isinstance(result, Exception):
            logger.error(f"Scan task failed: {result}")
    logger.info(f"Scan complete. Signals found: {signals_found}/{len(tasks)}")
