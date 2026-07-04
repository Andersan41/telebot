"""
scheduler/outcome_tracker.py — Фоновый трекинг закрытия сигналов (SL/TP).

PnL is calculated AFTER costs:
- Exchange commission (taker fee, both sides)
- Slippage (both sides)
- Estimated funding cost for perpetuals (0.01% per 8h, scaled by hold time)
"""
import asyncio
import html
import os
from datetime import datetime, timezone, timedelta
from loguru import logger
from data.exchange_client import exchange_client
from storage.database import db
from config.settings import config


OUTCOME_CHECK_INTERVAL_SECONDS = int(
    os.getenv("OUTCOME_CHECK_INTERVAL_SECONDS", "300")
)
OUTCOME_TTL_DAYS = int(os.getenv("OUTCOME_TTL_DAYS", "7"))

# Funding rate estimate for perpetuals (default 0.01% per 8h)
FUNDING_RATE_8H = float(os.getenv("FUNDING_RATE_8H", "0.0001"))

# Per-symbol failure tracking: after SYMBOL_FETCH_FAIL_THRESHOLD consecutive
# failures, skip the symbol for SYMBOL_FETCH_COOLDOWN_SECONDS.
SYMBOL_FETCH_FAIL_THRESHOLD = 3
SYMBOL_FETCH_COOLDOWN_SECONDS = 600  # 10 min cooldown
_symbol_fail_count: dict[str, int] = {}
_symbol_cooldown_until: dict[str, datetime] = {}


async def _send_close_notification(
    signal, status: str, current_price: float, net_pnl: float
) -> None:
    """Отправить уведомление в Telegram о закрытии сделки (TP/SL)."""
    if not config.telegram.channel_id:
        return
    try:
        from bot.notifier import get_bot
        from telegram.constants import ParseMode

        bot = get_bot()
        emoji = "✅" if status == "HIT_TP" else "🛑"
        action = "Тейк Профит" if status == "HIT_TP" else "Стоп Лосс"
        pnl_sign = "+" if net_pnl >= 0 else ""
        pnl_cls = "green" if net_pnl >= 0 else "red"

        text = (
            f"{emoji} <b>Сделка закрыта — {action}</b>\n\n"
            f"📊 {html.escape(signal.signal_type)} {html.escape(signal.symbol)} {html.escape(signal.timeframe)}\n"
            f"💰 Entry: <code>{signal.close_price}</code>\n"
            f"📍 Закрытие: <code>{current_price}</code>\n"
            f"📈 PnL: <b>{pnl_sign}{net_pnl:.2f}%</b>"
        )

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

        hit_tp = (
            signal.signal_type == "BUY" and signal.tp and candle_high >= signal.tp
        ) or (
            signal.signal_type == "SELL" and signal.tp and candle_low <= signal.tp
        )
        hit_sl = (
            signal.signal_type == "BUY" and signal.sl and candle_low <= signal.sl
        ) or (
            signal.signal_type == "SELL" and signal.sl and candle_high >= signal.sl
        )
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
            await db.close_outcome(outcome.id, "HIT_TP", close_price, net_pnl)
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
            except Exception:
                pass
            logger.info(
                f"Outcome RESOLVED: {signal.symbol} {signal.signal_type} -> HIT_TP "
                f"at {current_price} gross={gross_pnl:+.2f}% net={net_pnl:+.2f}% "
                f"(entry={signal.close_price}, SL={signal.sl}, TP={signal.tp})"
            )
            await _send_close_notification(signal, "HIT_TP", current_price, net_pnl)
        elif hit_sl:
            # Use SL price as close if candle hit it (better fill estimate)
            close_price = signal.sl if (
                (signal.signal_type == "BUY" and candle_low <= signal.sl) or
                (signal.signal_type == "SELL" and candle_high >= signal.sl)
            ) else current_price
            gross_pnl, net_pnl = _calculate_net_pnl(
                signal.signal_type, signal.close_price, close_price,
                signal.created_at.replace(tzinfo=timezone.utc), now,
            )
            await db.close_outcome(outcome.id, "HIT_SL", close_price, net_pnl)
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
            except Exception:
                pass
            logger.info(
                f"Outcome RESOLVED: {signal.symbol} {signal.signal_type} -> HIT_SL "
                f"at {current_price} gross={gross_pnl:+.2f}% net={net_pnl:+.2f}% "
                f"(entry={signal.close_price}, SL={signal.sl}, TP={signal.tp})"
            )
            await _send_close_notification(signal, "HIT_SL", current_price, net_pnl)
        else:
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
