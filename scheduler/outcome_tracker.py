"""
scheduler/outcome_tracker.py — Фоновый трекинг закрытия сигналов (SL/TP).

PnL is calculated AFTER costs:
- Exchange commission (taker fee, both sides)
- Slippage (both sides)
- Estimated funding cost for perpetuals (0.01% per 8h, scaled by hold time)
"""
import asyncio
import html
import json
import os
from datetime import datetime, timezone, timedelta
from loguru import logger
from data.exchange_client import exchange_client
from storage.database import db
from config.settings import config
from strategy.scenario_memory import scenario_memory, ScenarioOutcomeRecord


OUTCOME_CHECK_INTERVAL_SECONDS = int(
    os.getenv("OUTCOME_CHECK_INTERVAL_SECONDS", "300")
)
OUTCOME_TTL_DAYS = int(os.getenv("OUTCOME_TTL_DAYS", "7"))

# Time Stop: max hold duration (TZ §8.6)
# Default 2880 min = 48h; overridden per-TF below
TIME_STOP_MAX_MINUTES = int(os.getenv("TIME_STOP_MAX_MINUTES", "2880"))

# Per-timeframe time stop: ~20 bars on the entry TF
_TIME_STOP_BY_TF = {
    "1m": 20,       # 20 min
    "3m": 60,       # 1h
    "5m": 100,      # ~1.7h (TZ original)
    "15m": 300,     # 5h
    "30m": 600,     # 10h
    "1h": 1200,     # 20h
    "2h": 2400,     # 40h (~1.7 days)
    "4h": 5760,     # 96h (~4 days)
    "6h": 8640,     # 6 days
    "12h": 17280,   # 12 days
    "1d": 28800,    # 20 days
}


def _get_time_stop_minutes(timeframe: str) -> int:
    """Get time stop limit for a given timeframe (20 bars equivalent)."""
    return _TIME_STOP_BY_TF.get(timeframe, TIME_STOP_MAX_MINUTES)

# Funding rate estimate for perpetuals (default 0.01% per 8h)
FUNDING_RATE_8H = float(os.getenv("FUNDING_RATE_8H", "0.0001"))

# Per-symbol failure tracking: after SYMBOL_FETCH_FAIL_THRESHOLD consecutive
# failures, skip the symbol for SYMBOL_FETCH_COOLDOWN_SECONDS.
SYMBOL_FETCH_FAIL_THRESHOLD = 3
SYMBOL_FETCH_COOLDOWN_SECONDS = 600  # 10 min cooldown
_symbol_fail_count: dict[str, int] = {}
_symbol_cooldown_until: dict[str, datetime] = {}

# ── Position State (TZ §8) ─────────────────────────────────────────────
# Module-level state for position management (breakeven, trailing, partial close).
# Persisted in-memory; resets on restart. For full persistence, use database.
from risk.position_manager import (
    ManagedPosition,
    check_breakeven,
    check_partial_closes,
    check_sweep_breach,
    apply_partial_close,
    calculate_trailing_stop,
    manage_position,
    BREAKEVEN_RR_TRIGGER,
)
from risk.metrics import trade_metrics
from storage.position_store import (
    save_position,
    load_open_positions,
    update_position_state,
    close_position,
    get_position_id,
)
_position_state: dict[str, ManagedPosition] = {}  # key = signal.id


async def _calc_atr_for_signal(signal, period: int = 14) -> float:
    """Calculate ATR for a signal's symbol/timeframe."""
    import pandas as pd

    try:
        candle_df = await exchange_client.fetch_ohlcv(signal.symbol, signal.timeframe, limit=period + 10)
        if candle_df is None or len(candle_df) < period + 1:
            return 0.0
        high = candle_df["high"].astype(float)
        low = candle_df["low"].astype(float)
        close = candle_df["close"].astype(float)
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return float(tr.iloc[-period:].mean())
    except Exception:
        return 0.0


async def _get_wave_info(signal_id: int) -> tuple[str, str]:
    """Get wave label and direction from DecisionTrace for a signal."""
    try:
        from storage.database import DecisionTrace, db as _db
        from sqlalchemy import select
        async with _db._session_factory() as session:
            result = await session.execute(
                select(DecisionTrace).where(DecisionTrace.signal_id == signal_id)
            )
            trace_row = result.scalar_one_or_none()
            if trace_row:
                return (trace_row.wave_label or "", trace_row.wave_direction or "")
    except Exception:
        pass
    return ("", "")


async def _send_close_notification(
    signal, status: str, current_price: float, net_pnl: float,
    actual_sl: float = None, actual_tp: float = None,
    wave_label: str = "", wave_direction: str = "",
) -> None:
    """Отправить уведомление в Telegram о закрытии сделки (TP/SL)."""
    if not config.telegram.channel_id:
        return
    try:
        from bot.notifier import get_bot
        from telegram.constants import ParseMode

        bot = get_bot()
        _STATUS_LABELS = {
            "HIT_TP": ("✅", "Тейк Профит"),
            "HIT_SL": ("🛑", "Стоп Лосс"),
            "TIME_STOP": ("⏰", "Тайм Стоп"),
            "FLIP_BIAS": ("🔄", "Смена Тренда"),
            "SWEEP_BREACH": ("💥", "Пробой Уровня"),
        }
        emoji, action = _STATUS_LABELS.get(status, ("🛑", status))
        pnl_sign = "+" if net_pnl >= 0 else ""
        pnl_cls = "green" if net_pnl >= 0 else "red"

        # Use actual SL/TP from position state if available
        sl_val = actual_sl if actual_sl is not None else signal.sl
        tp_val = actual_tp if actual_tp is not None else signal.tp

        text = (
            f"{emoji} <b>Сделка закрыта — {action}</b>\n\n"
            f"📊 {html.escape(signal.signal_type)} {html.escape(signal.symbol)} {html.escape(signal.timeframe)}\n"
            f"💰 Entry: <code>{signal.close_price}</code>\n"
            f"📍 Закрытие: <code>{current_price}</code>\n"
            f"📈 PnL: <b>{pnl_sign}{net_pnl:.2f}%</b>"
        )
        if wave_label and wave_direction:
            direction_icon = "🟢" if wave_direction == "bullish" else "🔴" if wave_direction == "bearish" else "⚪"
            text += f"\n🌊 Волна: {html.escape(wave_label)} {direction_icon}"

        await bot.send_message(
            chat_id=config.telegram.channel_id,
            text=text,
            parse_mode=ParseMode.HTML,
        )
        logger.info(f"Close notification sent: {signal.symbol} {status}")
    except Exception as e:
        logger.warning(f"Failed to send close notification: {e}")


def _calculate_net_pnl(
    signal_type: str,
    entry_price: float,
    exit_price: float,
    created_at: datetime,
    resolved_at: datetime,
) -> tuple[float, float]:
    """Calculate net PnL after costs.

    Costs deducted:
    - Exchange commission (both sides)
    - Slippage (both sides)
    - Estimated funding for perpetuals

    Returns:
        (gross_pnl_pct, net_pnl_pct)
    """
    fee_pct = config.trading.exchange_fee_pct
    slippage_pct = config.trading.slippage_pct

    # Gross PnL (before costs)
    if signal_type == "BUY":
        gross_pnl = (exit_price - entry_price) / entry_price * 100
    else:
        gross_pnl = (entry_price - exit_price) / entry_price * 100

    # Total round-trip cost: commission(2x) + slippage(2x)
    round_trip_cost_pct = (fee_pct + slippage_pct) * 2

    # Funding cost for perpetuals (estimated)
    funding_cost_pct = 0.0
    if config.exchange.market_type in ("swap", "future"):
        hold_hours = (resolved_at - created_at).total_seconds() / 3600
        n_funding_periods = hold_hours / 8.0  # funding every 8h
        funding_cost_pct = n_funding_periods * FUNDING_RATE_8H * 100

    net_pnl = gross_pnl - round_trip_cost_pct - funding_cost_pct
    return gross_pnl, net_pnl


def _calculate_excursion(
    signal_type: str,
    entry_price: float,
    high: float,
    low: float,
) -> tuple[float, float]:
    """Calculate Maximum Favorable Excursion (MFE) and Maximum Adverse Excursion (MAE).

    Returns:
        (mfe_pct, mae_pct) — both as percentages
    """
    if signal_type == "BUY":
        # For BUY: favorable = price goes up, adverse = price goes down
        mfe_pct = ((high - entry_price) / entry_price) * 100 if entry_price > 0 else 0
        mae_pct = ((entry_price - low) / entry_price) * 100 if entry_price > 0 else 0
    else:  # SELL
        # For SELL: favorable = price goes down, adverse = price goes up
        mfe_pct = ((entry_price - low) / entry_price) * 100 if entry_price > 0 else 0
        mae_pct = ((high - entry_price) / entry_price) * 100 if entry_price > 0 else 0
    return mfe_pct, mae_pct


async def check_open_outcomes() -> None:
    outcomes = await db.get_open_outcomes()
    if not outcomes:
        return
    logger.info(f"Checking {len(outcomes)} open outcomes")
    now = datetime.now(timezone.utc)
    for outcome in outcomes:
        signal = await db.get_signal(outcome.signal_id)
        if signal is None:
            continue
        # Просроченный сигнал → EXPIRED
        age = now - signal.created_at.replace(tzinfo=timezone.utc)
        if age > timedelta(days=OUTCOME_TTL_DAYS):
            await db.close_outcome(
                outcome.id, "EXPIRED",
                close_price=signal.close_price, pnl_pct=0.0,
            )
            try:
                from storage.database import DecisionTrace
                from sqlalchemy import select
                async with db._session_factory() as session:
                    result = await session.execute(
                        select(DecisionTrace).where(DecisionTrace.signal_id == signal.id)
                    )
                    trace_row = result.scalar_one_or_none()
                    if trace_row:
                        trace_row.outcome = "EXPIRED"
                        trace_row.pnl_pct = 0.0
                        await session.commit()
                        _record_hypothesis_outcome(
                            trace_row, signal, "EXPIRED", 0.0,
                            0.0, 0.0, 0,
                        )
            except Exception:
                pass
            continue

        # Skip if current candle is the same as the entry candle.
        # This prevents same-bar SL resolution when the candle's wick
        # already breached the SL level at signal creation time.
        # Uses entry_candle_open stored at signal creation (preferred)
        # or falls back to calculated value for backward compatibility.
        entry_candle_open = None
        if hasattr(signal, 'entry_candle_open') and signal.entry_candle_open is not None:
            entry_candle_open = signal.entry_candle_open.replace(tzinfo=timezone.utc)
        else:
            # Fallback: calculate from created_at and timeframe
            _TF_MINUTES = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
                           "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720, "1d": 1440}
            tf_minutes = _TF_MINUTES.get(signal.timeframe, 60)
            signal_ts = signal.created_at.replace(tzinfo=timezone.utc)
            tf_seconds = tf_minutes * 60
            signal_epoch = int(signal_ts.timestamp())
            entry_candle_open = datetime.fromtimestamp(
                signal_epoch - (signal_epoch % tf_seconds), tz=timezone.utc
            )

        # Calculate current candle open time
        now_epoch = int(now.timestamp())
        tf_minutes = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
                      "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720, "1d": 1440}
        tf_minutes_val = tf_minutes.get(signal.timeframe, 60)
        tf_seconds = tf_minutes_val * 60
        current_candle_open = datetime.fromtimestamp(
            now_epoch - (now_epoch % tf_seconds), tz=timezone.utc
        )

        if current_candle_open <= entry_candle_open:
            logger.debug(
                f"Skipping {signal.symbol} {signal.timeframe}: "
                f"still on or before entry candle "
                f"(entry_open={entry_candle_open.isoformat()}, "
                f"current_open={current_candle_open.isoformat()})"
            )
            continue

        # Skip symbols on cooldown after repeated fetch failures
        cooldown_until = _symbol_cooldown_until.get(signal.symbol)
        if cooldown_until and now < cooldown_until:
            continue
        # Текущая цена через ticker (real-time, не свеча)
        current_price = await exchange_client.fetch_ticker_price(signal.symbol)
        if current_price is None:
            _symbol_fail_count[signal.symbol] = _symbol_fail_count.get(signal.symbol, 0) + 1
            if _symbol_fail_count[signal.symbol] >= SYMBOL_FETCH_FAIL_THRESHOLD:
                _symbol_cooldown_until[signal.symbol] = now + timedelta(seconds=SYMBOL_FETCH_COOLDOWN_SECONDS)
                logger.warning(
                    f"Symbol {signal.symbol} hit {SYMBOL_FETCH_FAIL_THRESHOLD} consecutive "
                    f"fetch failures — skipping for {SYMBOL_FETCH_COOLDOWN_SECONDS}s"
                )
            continue
        # Success — reset failure tracking
        _symbol_fail_count.pop(signal.symbol, None)

        # Also check recent candle high/low to catch TP/SL spikes
        # that happened between tracker intervals
        candle_high = current_price
        candle_low = current_price
        try:
            candle_df = await exchange_client.fetch_ohlcv(signal.symbol, signal.timeframe, limit=2)
            if candle_df is not None and len(candle_df) >= 1:
                last_candle = candle_df.iloc[-1]
                candle_high = float(last_candle["high"])
                candle_low = float(last_candle["low"])
        except Exception:
            pass

        # ── Position Management (TZ §8) ──────────────────────────────
        # Create or retrieve ManagedPosition for this signal
        sig_id = str(signal.id)
        if sig_id not in _position_state:
            _position_state[sig_id] = ManagedPosition(
                symbol=signal.symbol,
                direction=signal.signal_type,
                entry_price=signal.close_price,
                stop_loss=signal.sl or signal.close_price,
                take_profit=signal.tp,
                entry_time=signal.created_at.replace(tzinfo=timezone.utc),
            )
            # Persist new position to DB
            try:
                await save_position(_position_state[sig_id])
            except Exception as e:
                logger.debug(f"Failed to save position to DB: {e}")
        pos = _position_state[sig_id]

        # Fetch ATR for trailing stop calculation
        atr = 0.0
        try:
            atr = await _calc_atr_for_signal(signal)
        except Exception:
            pass

        # Detect last BOS for Flip Bias check
        last_bos_type = None
        last_bos_timestamp = None
        try:
            from market_structure.structure import analyze_structure
            bos_df = await exchange_client.fetch_ohlcv(signal.symbol, signal.timeframe, limit=50)
            if bos_df is not None and len(bos_df) >= 10:
                struct = analyze_structure(bos_df, lookback=50)
                if struct and struct.last_bos:
                    last_bos_type = struct.last_bos.type
                    last_bos_timestamp = struct.last_bos.timestamp
                    # Convert int timestamp to datetime if needed
                    if isinstance(last_bos_timestamp, (int, float)):
                        last_bos_timestamp = datetime.fromtimestamp(last_bos_timestamp, tz=timezone.utc)
                    elif last_bos_timestamp and hasattr(last_bos_timestamp, 'tzinfo') and last_bos_timestamp.tzinfo is None:
                        last_bos_timestamp = last_bos_timestamp.replace(tzinfo=timezone.utc)
        except Exception:
            pass

        # Run position management checks
        mgmt = manage_position(
            pos,
            candle_high=candle_high,
            candle_low=candle_low,
            candle_close=current_price,
            atr=atr,
            current_time=now,
            last_bos_type=last_bos_type,
            last_bos_timestamp=last_bos_timestamp,
        )

        # Handle position management actions
        if mgmt["close"]:
            reason = mgmt["reason"]
            gross_pnl, net_pnl = _calculate_net_pnl(
                signal.signal_type, signal.close_price, current_price,
                signal.created_at.replace(tzinfo=timezone.utc), now,
            )
            mfe_pct, mae_pct = _calculate_excursion(
                signal.signal_type, signal.close_price, candle_high, candle_low,
            )
            await db.close_outcome(outcome.id, reason, current_price, net_pnl)
            await db.update_signal_excursion(signal.id, mfe_pct, mae_pct)

            # Record in metrics
            trade_metrics.record_trade(
                entry_price=signal.close_price,
                exit_price=current_price,
                exit_reason=reason,
                direction=signal.signal_type,
            )

            # Update position DB
            pos_id = await get_position_id(pos)
            await close_position(pos_id, current_price, reason)

            try:
                await db.update_candidate_outcome_by_signal(signal.id, reason, net_pnl)
            except Exception:
                pass
            try:
                from storage.database import DecisionTrace
                from sqlalchemy import select
                async with db._session_factory() as session:
                    result = await session.execute(
                        select(DecisionTrace).where(DecisionTrace.signal_id == signal.id)
                    )
                    trace_row = result.scalar_one_or_none()
                    if trace_row:
                        trace_row.outcome = reason
                        trace_row.pnl_pct = net_pnl
                        await session.commit()
                        _record_hypothesis_outcome(
                            trace_row, signal, reason, net_pnl,
                            mfe_pct, mae_pct, hold_bars,
                        )
            except Exception:
                pass
            logger.info(
                f"Outcome RESOLVED: {signal.symbol} {signal.signal_type} -> {reason} "
                f"at {current_price} gross={gross_pnl:+.2f}% net={net_pnl:+.2f}% "
                f"(entry={signal.close_price}, SL={pos.stop_loss:.6f}, TP={signal.tp})"
            )
            wave_label, wave_dir = await _get_wave_info(signal.id)
            await _send_close_notification(signal, reason, current_price, net_pnl,
                                           actual_sl=pos.stop_loss,
                                           wave_label=wave_label, wave_direction=wave_dir)
            from risk.daily_limits import daily_limits
            daily_limits.record_trade_closed(net_pnl, was_loss=(net_pnl < 0), risk_pct=outcome.risk_pct or 0.0)
            _position_state.pop(sig_id, None)
            continue

        # Update SL if breakeven or trailing moved it
        if mgmt["new_sl"] is not None:
            pos.stop_loss = mgmt["new_sl"]
            # Persist state change
            pos_id = await get_position_id(pos)
            await update_position_state(pos_id, stop_loss=mgmt["new_sl"])
            logger.debug(
                f"SL updated for {signal.symbol}: {mgmt['new_sl']:.4f} "
                f"(breakeven={mgmt['breakeven']}, trailing={mgmt['trailing']})"
            )

        # Persist partial close state
        if mgmt["partial_closes"]:
            pos_id = await get_position_id(pos)
            await update_position_state(
                pos_id,
                remaining_percent=pos.remaining_percent,
                completed_targets=pos.completed_targets,
                breakeven_moved=pos.breakeven_moved,
                trailing_active=pos.trailing_active,
            )

        hit_tp = (
            signal.signal_type == "BUY" and signal.tp and candle_high >= signal.tp
        ) or (
            signal.signal_type == "SELL" and signal.tp and candle_low <= signal.tp
        )
        # Use actual SL from position state (may have been moved by BE/trailing)
        actual_sl = pos.stop_loss
        hit_sl = (
            signal.signal_type == "BUY" and actual_sl and candle_low <= actual_sl
        ) or (
            signal.signal_type == "SELL" and actual_sl and candle_high >= actual_sl
        )
        # Calculate hold bars for ScenarioMemory
        hold_bars = int((now - signal.created_at.replace(tzinfo=timezone.utc)).total_seconds() / 60 / max(1, {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "2h": 120, "4h": 240, "6h": 360, "12h": 720, "1d": 1440}.get(signal.timeframe, 60)))
        if hit_tp:
            # Use TP price as close if candle hit it (better fill estimate)
            close_price = signal.tp if (
                (signal.signal_type == "BUY" and candle_high >= signal.tp) or
                (signal.signal_type == "SELL" and candle_low <= signal.tp)
            ) else current_price
            gross_pnl, net_pnl = _calculate_net_pnl(
                signal.signal_type, signal.close_price, close_price,
                signal.created_at.replace(tzinfo=timezone.utc), now,
            )
            # Calculate MFE/MAE using entry price and candle extremes
            mfe_pct, mae_pct = _calculate_excursion(
                signal.signal_type, signal.close_price, candle_high, candle_low,
            )
            await db.close_outcome(outcome.id, "HIT_TP", close_price, net_pnl)
            await db.update_signal_excursion(signal.id, mfe_pct, mae_pct)
            try:
                await db.update_candidate_outcome_by_signal(signal.id, "HIT_TP", net_pnl)
            except Exception:
                pass
            try:
                from storage.database import DecisionTrace
                from sqlalchemy import select
                async with db._session_factory() as session:
                    result = await session.execute(
                        select(DecisionTrace).where(DecisionTrace.signal_id == signal.id)
                    )
                    trace_row = result.scalar_one_or_none()
                    if trace_row:
                        trace_row.outcome = "HIT_TP"
                        trace_row.pnl_pct = net_pnl
                        await session.commit()
                        # Record outcome in ScenarioMemory
                        _record_hypothesis_outcome(
                            trace_row, signal, "HIT_TP", net_pnl,
                            mfe_pct, mae_pct, hold_bars,
                        )
            except Exception:
                pass
            logger.info(
                f"Outcome RESOLVED: {signal.symbol} {signal.signal_type} -> HIT_TP "
                f"at {current_price} gross={gross_pnl:+.2f}% net={net_pnl:+.2f}% "
                f"(entry={signal.close_price}, SL={signal.sl}, TP={signal.tp})"
            )
            wave_label, wave_dir = await _get_wave_info(signal.id)
            await _send_close_notification(signal, "HIT_TP", close_price, net_pnl,
                                           wave_label=wave_label, wave_direction=wave_dir)
            # Record daily limits
            from risk.daily_limits import daily_limits
            daily_limits.record_trade_closed(net_pnl, was_loss=False, risk_pct=outcome.risk_pct or 0.0)
        elif hit_sl:
            # Use actual SL price as close (may have been moved by BE/trailing)
            close_price = actual_sl if (
                (signal.signal_type == "BUY" and candle_low <= actual_sl) or
                (signal.signal_type == "SELL" and candle_high >= actual_sl)
            ) else current_price
            gross_pnl, net_pnl = _calculate_net_pnl(
                signal.signal_type, signal.close_price, close_price,
                signal.created_at.replace(tzinfo=timezone.utc), now,
            )
            # Calculate MFE/MAE using entry price and candle extremes
            mfe_pct, mae_pct = _calculate_excursion(
                signal.signal_type, signal.close_price, candle_high, candle_low,
            )
            await db.close_outcome(outcome.id, "HIT_SL", close_price, net_pnl)
            await db.update_signal_excursion(signal.id, mfe_pct, mae_pct)
            try:
                await db.update_candidate_outcome_by_signal(signal.id, "HIT_SL", net_pnl)
            except Exception:
                pass
            try:
                from storage.database import DecisionTrace
                from sqlalchemy import select
                async with db._session_factory() as session:
                    result = await session.execute(
                        select(DecisionTrace).where(DecisionTrace.signal_id == signal.id)
                    )
                    trace_row = result.scalar_one_or_none()
                    if trace_row:
                        trace_row.outcome = "HIT_SL"
                        trace_row.pnl_pct = net_pnl
                        await session.commit()
                        # Record outcome in ScenarioMemory
                        _record_hypothesis_outcome(
                            trace_row, signal, "HIT_SL", net_pnl,
                            mfe_pct, mae_pct, hold_bars,
                        )
            except Exception:
                pass
            logger.info(
                f"Outcome RESOLVED: {signal.symbol} {signal.signal_type} -> HIT_SL "
                f"at {current_price} gross={gross_pnl:+.2f}% net={net_pnl:+.2f}% "
                f"(entry={signal.close_price}, SL={actual_sl:.6f}, TP={signal.tp})"
            )
            wave_label, wave_dir = await _get_wave_info(signal.id)
            await _send_close_notification(signal, "HIT_SL", close_price, net_pnl,
                                           actual_sl=actual_sl,
                                           wave_label=wave_label, wave_direction=wave_dir)
            # Record daily limits
            from risk.daily_limits import daily_limits
            daily_limits.record_trade_closed(net_pnl, was_loss=(net_pnl < 0), risk_pct=outcome.risk_pct or 0.0)
        else:
            # Time Stop (TZ §8.6) — PAUSED
            await db.touch_outcome_checked(outcome.id)
            logger.debug(
                    f"Outcome still open: signal_id={signal.id} {signal.symbol} "
                    f"{signal.signal_type} price={current_price:.4f} SL={signal.sl:.4f} TP={signal.tp:.4f}"
                )


async def outcome_tracker_loop() -> None:
    while True:
        try:
            await check_open_outcomes()
        except Exception as e:
            logger.warning(f"Outcome tracker error: {e}")
        await asyncio.sleep(OUTCOME_CHECK_INTERVAL_SECONDS)


def _record_hypothesis_outcome(
    trace_row,
    signal,
    outcome: str,
    pnl_pct: float,
    mfe_pct: float,
    mae_pct: float,
    hold_bars: int,
) -> None:
    """Record trade outcome in ScenarioMemory for future learning.

    Extracts hypothesis data from DecisionTrace.hypothesis_snapshot JSON
    and creates a ScenarioOutcomeRecord.
    """
    try:
        if not trace_row.hypothesis_snapshot:
            return

        h_data = json.loads(trace_row.hypothesis_snapshot)
        narrative_type = h_data.get("narrative_type", "")
        if not narrative_type:
            return

        # Calculate actual RR from entry/exit
        entry_price = signal.close_price
        exit_price = signal.tp if outcome == "HIT_TP" else signal.sl
        if entry_price and exit_price and entry_price > 0:
            if signal.signal_type == "BUY":
                actual_rr = (exit_price - entry_price) / (entry_price - signal.sl) if signal.sl and entry_price > signal.sl else 0.0
            else:
                actual_rr = (entry_price - exit_price) / (signal.sl - entry_price) if signal.sl and signal.sl > entry_price else 0.0
        else:
            actual_rr = 0.0

        record = ScenarioOutcomeRecord(
            symbol=signal.symbol,
            hypothesis_name=h_data.get("hypothesis_id", ""),
            narrative_type=narrative_type,
            direction=h_data.get("direction", signal.signal_type.lower()),
            expected_rr=h_data.get("rr_ratio", 0.0),
            expected_p_tp=h_data.get("confidence", 0.0),
            expected_quality=h_data.get("quality", 0.0),
            expected_confidence=h_data.get("confidence", 0.0),
            actual_rr=actual_rr,
            actual_pnl_pct=pnl_pct,
            outcome=outcome,
            mfe_pct=mfe_pct,
            mae_pct=mae_pct,
            hold_bars=hold_bars,
        )
        scenario_memory.record_outcome(record)
        logger.debug(
            f"ScenarioMemory: recorded {outcome} for {signal.symbol} "
            f"{narrative_type} (rr={actual_rr:.2f}, pnl={pnl_pct:.2f}%)"
        )
    except Exception as e:
        logger.debug(f"Failed to record hypothesis outcome: {e}")
