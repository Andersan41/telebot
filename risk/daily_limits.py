"""
risk/daily_limits.py — Daily Limits tracker (TZ §9.3).

Tracks:
- Daily risk used (remaining_risk = max_risk_per_day - used)
- Daily trades count
- Consecutive losses
- Daily drawdown
- Daily profit target

Implements can_open_trade() logic from TZ:
    remaining_risk = DAILY_MAX_RISK - daily_risk_used
    actual_risk = min(RISK_PER_TRADE, remaining_risk)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from loguru import logger


@dataclass
class DailyLimitsState:
    """Current daily limits state."""
    daily_risk_used_pct: float = 0.0
    daily_trades_count: int = 0
    consecutive_losses: int = 0
    daily_pnl_pct: float = 0.0
    last_reset_date: Optional[str] = None  # "YYYY-MM-DD"

    @property
    def remaining_risk_pct(self) -> float:
        from config.settings import config
        return max(0.0, config.risk.max_risk_per_day_pct - self.daily_risk_used_pct)


class DailyLimitsTracker:
    """Tracks daily risk, trades, losses, and drawdown.

    Resets at midnight UTC.
    """

    def __init__(self):
        self._state = DailyLimitsState()
        self._last_reset_date: Optional[str] = None

    def _today_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _maybe_reset(self) -> None:
        """Reset counters if a new day started."""
        today = self._today_str()
        if self._last_reset_date != today:
            logger.info(
                f"Daily limits reset: {self._last_reset_date} → {today} "
                f"(risk_used={self._state.daily_risk_used_pct:.2f}%, "
                f"trades={self._state.daily_trades_count}, "
                f"pnl={self._state.daily_pnl_pct:+.2f}%)"
            )
            self._state = DailyLimitsState(last_reset_date=today)
            self._last_reset_date = today

    def can_open_trade(
        self,
        risk_per_trade_pct: float,
    ) -> tuple[bool, float, str]:
        """Check if a new trade can be opened per daily limits.

        Args:
            risk_per_trade_pct: intended risk % for this trade

        Returns:
            (allowed, actual_risk_pct, reason)
            - allowed: True if trade is permitted
            - actual_risk_pct: effective risk (min of intended and remaining)
            - reason: rejection reason if not allowed
        """
        self._maybe_reset()

        from config.settings import config
        rc = config.risk

        # 1. Remaining daily risk
        remaining = self._state.remaining_risk_pct
        if remaining <= 0:
            return False, 0.0, "daily risk limit reached"

        # 2. Max trades per day
        if self._state.daily_trades_count >= rc.max_trades_per_day:
            return False, 0.0, f"daily trades limit ({rc.max_trades_per_day})"

        # 3. Consecutive losses
        if self._state.consecutive_losses >= rc.max_consecutive_losses:
            return False, 0.0, f"consecutive losses ({rc.max_consecutive_losses})"

        # 4. Max drawdown daily
        if self._state.daily_pnl_pct <= -rc.max_drawdown_daily_pct:
            return False, 0.0, f"daily drawdown limit ({rc.max_drawdown_daily_pct}%)"

        # 5. Profit target daily
        if self._state.daily_pnl_pct >= rc.profit_target_daily_pct:
            return False, 0.0, f"daily profit target reached ({rc.profit_target_daily_pct}%)"

        # Actual risk = min(intended, remaining)
        actual_risk = min(risk_per_trade_pct, remaining)

        return True, actual_risk, ""

    def try_open_trade(
        self,
        risk_per_trade_pct: float,
    ) -> tuple[bool, float, str]:
        """Atomically check daily limits AND reserve the risk slot.

        Combines can_open_trade() + record_trade_opened() to prevent TOCTOU.
        Use this instead of calling them separately.
        """
        allowed, actual_risk, reason = self.can_open_trade(risk_per_trade_pct)
        if allowed:
            self.record_trade_opened(actual_risk)
        return allowed, actual_risk, reason

    def record_trade_opened(self, risk_pct: float) -> None:
        """Record that a trade was opened."""
        self._maybe_reset()
        self._state.daily_risk_used_pct += risk_pct
        self._state.daily_trades_count += 1
        logger.info(
            f"Daily limits: trade opened risk={risk_pct:.2f}% "
            f"(used={self._state.daily_risk_used_pct:.2f}%/{self._state.remaining_risk_pct:.2f}% remaining, "
            f"trades={self._state.daily_trades_count})"
        )

    def record_trade_closed(self, pnl_pct: float, was_loss: bool, risk_pct: float = 0.0) -> None:
        """Record trade closure outcome."""
        self._maybe_reset()
        self._state.daily_pnl_pct += pnl_pct

        # Free up the risk budget consumed by this trade
        if risk_pct > 0:
            self._state.daily_risk_used_pct = max(
                0.0, self._state.daily_risk_used_pct - risk_pct
            )

        if was_loss:
            self._state.consecutive_losses += 1
        else:
            self._state.consecutive_losses = 0

        logger.info(
            f"Daily limits: trade closed pnl={pnl_pct:+.2f}% risk_freed={risk_pct:.2f}% "
            f"(daily_pnl={self._state.daily_pnl_pct:+.2f}%, "
            f"risk_used={self._state.daily_risk_used_pct:.2f}%, "
            f"consecutive_losses={self._state.consecutive_losses})"
        )

    def release_trade(self, risk_pct: float) -> None:
        """Release a pre-reserved risk slot (rollback on failure)."""
        self._maybe_reset()
        self._state.daily_risk_used_pct = max(
            0.0, self._state.daily_risk_used_pct - risk_pct
        )
        self._state.daily_trades_count = max(
            0, self._state.daily_trades_count - 1
        )

    def get_state(self) -> DailyLimitsState:
        """Get current daily limits state (for logging/display)."""
        self._maybe_reset()
        return self._state

    def get_remaining_risk(self) -> float:
        """Get remaining daily risk %."""
        self._maybe_reset()
        return self._state.remaining_risk_pct


# Singleton
daily_limits = DailyLimitsTracker()
