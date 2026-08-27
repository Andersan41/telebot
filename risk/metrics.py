"""
risk/metrics.py — Trade performance metrics and daily reporting.

Tracks win rate, breakeven rate, expectancy, exit reasons.
Sends daily Telegram report.
"""
from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from loguru import logger


class TradeMetrics:
    """Track trade performance metrics."""

    def __init__(self):
        self.total_trades = 0
        self.win_count = 0
        self.loss_count = 0
        self.be_count = 0  # Breakeven closes

        self.total_risked = 0.0
        self.total_return = 0.0

        self.rr_distribution: list[float] = []
        self.exit_reasons: dict[str, int] = defaultdict(int)
        self.slippage_pct: list[float] = []

        self._last_report_time = datetime.now(timezone.utc)

    def record_trade(
        self,
        entry_price: float,
        exit_price: float,
        exit_reason: str,
        direction: str,
        quantity: float = 1.0,
        fee_pct: float = 0.0005,
        expected_rr: float = 0.0,
        actual_rr: float = 0.0,
    ) -> None:
        """Record a completed trade."""
        self.total_trades += 1
        self.exit_reasons[exit_reason] += 1

        # Calculate PnL
        if direction == "BUY":
            gross_pnl_pct = (exit_price - entry_price) / entry_price * 100
        else:
            gross_pnl_pct = (entry_price - exit_price) / entry_price * 100

        # Deduct fees (round-trip)
        round_trip_fee = fee_pct * 2 * 100
        net_pnl_pct = gross_pnl_pct - round_trip_fee

        self.total_return += net_pnl_pct * quantity
        self.total_risked += abs(entry_price * 0.01 * quantity)  # 1% risk

        # Track slippage if available
        if expected_rr > 0 and actual_rr > 0:
            slippage = abs(expected_rr - actual_rr) / expected_rr * 100
            self.slippage_pct.append(slippage)

        # Classify outcome
        if exit_reason == "BREAKEVEN":
            self.be_count += 1
        elif net_pnl_pct > 0:
            self.win_count += 1
        elif net_pnl_pct < -0.1:  # Not BE
            self.loss_count += 1
        else:
            self.be_count += 1  # Micro-loss counts as BE

        self.rr_distribution.append(actual_rr)

    @property
    def win_rate(self) -> float:
        """Win rate as percentage (excluding BE)."""
        non_be = self.total_trades - self.be_count
        if non_be == 0:
            return 0.0
        return self.win_count / non_be * 100

    @property
    def expectancy_r(self) -> float:
        """Expected value per trade in R units."""
        if self.total_trades == 0 or self.total_risked == 0:
            return 0.0
        return (self.total_return / self.total_risked) * 100

    @property
    def be_rate(self) -> float:
        """Breakeven close rate as percentage."""
        if self.total_trades == 0:
            return 0.0
        return self.be_count / self.total_trades * 100

    @property
    def avg_rr(self) -> float:
        """Average R:R of completed trades."""
        if not self.rr_distribution:
            return 0.0
        return sum(self.rr_distribution) / len(self.rr_distribution)

    @property
    def avg_slippage(self) -> float:
        """Average slippage percentage."""
        if not self.slippage_pct:
            return 0.0
        return sum(self.slippage_pct) / len(self.slippage_pct)

    def format_daily_report(self) -> str:
        """Format daily Telegram report."""
        lines = [
            f"📊 <b>Daily Report</b>",
            f"",
            f"Trades: {self.total_trades} | "
            f"Wins: {self.win_count} | "
            f"Losses: {self.loss_count} | "
            f"BE: {self.be_count}",
            f"",
            f"Win Rate: {self.win_rate:.1f}% | "
            f"BE Rate: {self.be_rate:.1f}%",
            f"Expectancy: {self.expectancy_r:+.2f}R",
            f"",
            f"<b>Exit reasons:</b>",
        ]

        for reason, count in sorted(self.exit_reasons.items(), key=lambda x: -x[1]):
            lines.append(f"  {reason}: {count}")

        lines.extend([
            f"",
            f"Avg R:R: {self.avg_rr:.2f}",
            f"Avg slippage: {self.avg_slippage:.2f}%",
        ])

        return "\n".join(lines)

    def should_send_report(self, interval_hours: int = 24) -> bool:
        """Check if it's time to send the daily report."""
        now = datetime.now(timezone.utc)
        elapsed = now - self._last_report_time
        return elapsed >= timedelta(hours=interval_hours)

    def mark_report_sent(self) -> None:
        """Mark that the report was sent."""
        self._last_report_time = datetime.now(timezone.utc)


# Singleton
trade_metrics = TradeMetrics()


async def send_daily_report() -> None:
    """Send daily report to Telegram if interval elapsed."""
    if not trade_metrics.should_send_report():
        return

    try:
        from config.settings import config
        if not config.telegram.channel_id:
            return

        from bot.notifier import get_bot
        from telegram.constants import ParseMode

        bot = get_bot()
        report = trade_metrics.format_daily_report()

        await bot.send_message(
            chat_id=config.telegram.channel_id,
            text=report,
            parse_mode=ParseMode.HTML,
        )

        trade_metrics.mark_report_sent()
        logger.info("Daily metrics report sent")

    except Exception as e:
        logger.warning(f"Failed to send daily report: {e}")
