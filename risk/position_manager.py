"""
risk/position_manager.py — Position Management (TZ §8).

Implements breakeven, partial close, trailing stop, and sweep breach detection.
Designed for signal-based tracking (no live order execution).

Key formulas (A15: mirror-correct for LONG and SHORT):
- Breakeven: entry ± fee_buffer when current R:R >= 1.5
  NOTE: fee_buffer (0.05%) < round-trip costs (~0.20%). This is a move to entry,
  NOT a net-BE. Net-BE requires accounting for realized PnL from partial closes.
- Partial Close: TP1=2R→25%, TP2=3R→35%, TP3=4R→40% (of initial position)
- Trailing: ATR(14) × TRAILING_ATR_MULTIPLIER, only after TP2 (3R), only on remaining 40%
  Long: new_sl = price - ATR*1.5 (ratchet UP only)
  Short: new_sl = price + ATR*1.5 (ratchet DOWN only)
- Sweep Breach: close beyond sweep level = early exit
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

from loguru import logger


# TZ §8.4: Breakeven trigger at 1.5R
BREAKEVEN_RR_TRIGGER = 1.5

# TZ §8.4: Fee buffer = 0.05% (covers round-trip maker+taker)
FEE_BUFFER_PERCENT = 0.0005

# TZ §8.3: Partial close targets
PARTIAL_CLOSE_TARGETS = [
    {"rr": 2.0, "close_pct": 25, "action": "breakeven"},
    {"rr": 3.0, "close_pct": 35, "action": "trailing"},
    {"rr": 4.0, "close_pct": 40, "action": "close_all"},
]

# TZ §8.5: Trailing stop activation at TP2 (3R)
TRAILING_RR_TRIGGER = 3.0
TRAILING_ATR_MULTIPLIER = 1.5
TRAILING_MIN_DISTANCE_PCT = 0.005  # 0.5% from entry

# TZ §8.6: Time stop
TIME_STOP_MAX_MINUTES = 100  # 20 bars on 5m
TIME_STOP_ENABLED = os.getenv("TIME_STOP_ENABLED", "false").lower() == "true"


@dataclass
class ExitPlan:
    """A13: Versioned exit plan linking TradeEngine TP to PositionManager rules.

    Created BEFORE signal publication. All modules (notification, simulator,
    risk, model) use this single plan. Immutable after creation.

    The structural TP from TradeEngine defines the primary target.
    Partial close rules define the scaling-out policy relative to R-multiples.
    """
    # Primary target from TradeEngine (liquidity-based)
    primary_tp_price: float = 0.0
    primary_tp_source: str = ""  # "liquidity" / "atr" / "ob" / "fvg"
    primary_tp_rr: float = 0.0   # R-multiples to primary TP

    # Initial SL from TradeEngine
    initial_sl_price: float = 0.0
    initial_sl_source: str = ""  # "sweep" / "ob" / "swing" / "bos" / "atr"

    # Partial close policy (R-multiples → % of INITIAL position)
    # Default: 2R→25%, 3R→35%, 4R→40% (total = 100%)
    partial_close_targets: list = field(default_factory=lambda: [
        {"rr": 2.0, "close_pct": 25, "action": "breakeven"},
        {"rr": 3.0, "close_pct": 35, "action": "trailing"},
        {"rr": 4.0, "close_pct": 40, "action": "close_all"},
    ])

    # Breakeven rule
    breakeven_trigger_rr: float = 1.5

    # Trailing rule
    trailing_trigger_rr: float = 3.0
    trailing_atr_multiplier: float = 1.5

    # Time stop
    time_stop_minutes: float = 0.0  # 0 = disabled

    # Versioning (for A/B analysis and replay)
    plan_version: str = "1.0"
    created_at: Optional[datetime] = None

    def gross_r_if_full_path(self) -> float:
        """Total gross R if all partial closes execute at their R-multiples."""
        return sum(
            (t["rr"] * t["close_pct"] / 100.0)
            for t in self.partial_close_targets
        )

    def max_rr(self) -> float:
        """Maximum R-multiple among partial close targets."""
        if not self.partial_close_targets:
            return 0.0
        return max(t["rr"] for t in self.partial_close_targets)


def create_exit_plan(
    tp_price: float,
    tp_source: str,
    sl_price: float,
    sl_source: str,
    rr_ratio: float,
    partial_targets: Optional[list] = None,
) -> ExitPlan:
    """A13: Factory to create ExitPlan from TradeEngine output.

    Call this when building TradePlan to ensure PositionManager uses the same targets.
    """
    return ExitPlan(
        primary_tp_price=tp_price,
        primary_tp_source=tp_source,
        primary_tp_rr=rr_ratio,
        initial_sl_price=sl_price,
        initial_sl_source=sl_source,
        partial_close_targets=partial_targets or PARTIAL_CLOSE_TARGETS,
        created_at=datetime.now(timezone.utc),
    )


@dataclass
class ManagedPosition:
    """Position with full lifecycle tracking (TZ §8)."""
    # Core fields
    symbol: str
    direction: Literal["BUY", "SELL"]
    entry_price: float
    stop_loss: float
    take_profit: Optional[float] = None
    quantity: float = 1.0
    entry_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # A13: Exit plan — links TradeEngine TP to position management rules
    exit_plan: Optional[ExitPlan] = None

    # Breakeven (TZ §8.4)
    breakeven_moved: bool = False

    # Partial Close (TZ §8.3)
    remaining_percent: float = 100.0
    completed_targets: set = field(default_factory=set)

    # Trailing Stop (TZ §8.5)
    trailing_active: bool = False
    trailing_atr: float = 0.0  # ATR at activation time

    # Sweep context (TZ §10.2)
    sweep_level: Optional[float] = None
    sweep_extreme: Optional[float] = None
    sweep_timestamp: Optional[datetime] = None

    @property
    def risk(self) -> float:
        """Distance from entry to SL in price units."""
        if self.direction == "BUY":
            return self.entry_price - self.stop_loss
        else:
            return self.stop_loss - self.entry_price

    def current_rr(self, current_price: float) -> float:
        """Calculate current R:R ratio."""
        if self.risk <= 0:
            return 0.0
        if self.direction == "BUY":
            reward = current_price - self.entry_price
        else:
            reward = self.entry_price - current_price
        return reward / self.risk

    def target_price(self, rr: float) -> float:
        """Calculate price at given R:R level."""
        if self.direction == "BUY":
            return self.entry_price + self.risk * rr
        else:
            return self.entry_price - self.risk * rr

    def elapsed_minutes(self, current_time: Optional[datetime] = None) -> float:
        """Minutes since entry."""
        now = current_time or datetime.now(timezone.utc)
        entry = self.entry_time.replace(tzinfo=timezone.utc) if self.entry_time.tzinfo is None else self.entry_time
        return (now - entry).total_seconds() / 60.0


def calculate_breakeven_sl(position: ManagedPosition) -> float:
    """TZ §8.4: SL = entry ± fee_buffer.

    fee_buffer covers round-trip commissions (maker+taker ≈ 0.04-0.06%).
    NOTE: This is a move-to-entry, not true net-BE. See ExitPlan docstring.

    For BUY: SL is clamped to entry (not above) to prevent negative risk
    which would invert all R-based partial close targets.
    """
    fee_buffer = position.entry_price * FEE_BUFFER_PERCENT
    if position.direction == "BUY":
        return position.entry_price  # Clamp to entry, not above
    else:
        return position.entry_price  # Clamp to entry, not below


def check_breakeven(position: ManagedPosition, current_price: float) -> Optional[float]:
    """Check if breakeven should be activated (mirror-correct for long/short).

    Returns new SL if BE should move, None otherwise.
    TZ §8.4: trigger at BREAKEVEN_RR_TRIGGER R.

    NOTE: fee_buffer (0.05%) covers only commission, not full round-trip costs.
    This is a "move to entry" not a true net-BE. After partial closes with
    realized profit, the effective BE for remaining position may differ.
    """
    if position.breakeven_moved:
        return None

    rr = position.current_rr(current_price)
    if rr >= BREAKEVEN_RR_TRIGGER:
        new_sl = calculate_breakeven_sl(position)
        logger.info(
            f"Breakeven triggered: {position.symbol} "
            f"RR={rr:.2f} >= {BREAKEVEN_RR_TRIGGER} → SL={new_sl:.4f}"
        )
        return new_sl

    return None


def check_partial_closes(
    position: ManagedPosition,
    candle_high: float,
    candle_low: float,
    atr: float = 0.0,
) -> list[dict]:
    """Check all partial close targets.

    Uses ExitPlan.partial_close_targets if available, otherwise module defaults.
    Returns list of actions to execute:
    [{"action": "breakeven"|"trailing"|"close_all", "close_pct": int, "rr": float}]
    """
    actions = []

    targets = (
        position.exit_plan.partial_close_targets
        if position.exit_plan
        else PARTIAL_CLOSE_TARGETS
    )

    for target in targets:
        rr = target["rr"]
        if rr in position.completed_targets:
            continue

        target_price = position.target_price(rr)

        if position.direction == "BUY":
            hit = candle_high >= target_price
        else:
            hit = candle_low <= target_price

        if hit:
            actions.append({
                "action": target["action"],
                "close_pct": target["close_pct"],
                "rr": rr,
                "target_price": target_price,
            })

    return actions


def apply_partial_close(
    position: ManagedPosition,
    action: dict,
    atr: float = 0.0,
) -> None:
    """Apply a partial close action to the position."""
    rr = action["rr"]
    close_pct = action["close_pct"]
    action_type = action["action"]

    position.completed_targets.add(rr)
    position.remaining_percent -= close_pct

    logger.info(
        f"Partial close: {position.symbol} "
        f"TP@{rr}R → close {close_pct}% (remaining={position.remaining_percent}%)"
    )

    if action_type == "breakeven":
        new_sl = calculate_breakeven_sl(position)
        position.stop_loss = new_sl
        position.breakeven_moved = True
        logger.info(f"  SL moved to breakeven: {new_sl:.4f}")

    elif action_type == "trailing":
        position.trailing_active = True
        position.trailing_atr = atr
        logger.info(f"  Trailing activated (ATR={atr:.4f})")

    elif action_type == "close_all":
        position.remaining_percent = 0.0
        logger.info(f"  Position fully closed at {rr}R")


def calculate_trailing_stop(
    position: ManagedPosition,
    current_price: float,
    atr: float,
) -> Optional[float]:
    """TZ §8.5: Trailing stop calculation (mirror-correct for long/short).

    Only active after TP2 (3R). ATR-based, TRAILING_ATR_MULTIPLIER.
    Only on remaining position (after partial closes).

    Long:  new_sl = price - ATR*1.5, ratchet UP only, never below breakeven
    Short: new_sl = price + ATR*1.5, ratchet DOWN only, never above breakeven
    """
    if not position.trailing_active:
        return None
    if atr <= 0:
        return None

    atr_buffer = atr * TRAILING_ATR_MULTIPLIER

    if position.direction == "BUY":
        new_sl = current_price - atr_buffer
        # Don't pull SL below breakeven
        be_sl = calculate_breakeven_sl(position)
        new_sl = max(new_sl, be_sl)
        # Don't move SL down
        if new_sl > position.stop_loss:
            return new_sl
    else:
        new_sl = current_price + atr_buffer
        be_sl = calculate_breakeven_sl(position)
        new_sl = min(new_sl, be_sl)
        if new_sl < position.stop_loss:
            return new_sl

    return None


def check_sweep_breach(
    position: ManagedPosition,
    candle_close: float,
) -> bool:
    """TZ §10.2: Sweep breach detection.

    If price closes BEYOND the sweep level with body (not wick),
    the sweep was a true break, not manipulation. Close early.
    """
    if position.sweep_level is None:
        return False

    if position.direction == "BUY":
        # Bullish sweep: price swept lows. Breach = close below sweep level
        if candle_close < position.sweep_level:
            logger.warning(
                f"Sweep breach: {position.symbol} "
                f"close={candle_close:.4f} < sweep_level={position.sweep_level:.4f}"
            )
            return True
    else:
        # Bearish sweep: price swept highs. Breach = close above sweep level
        if candle_close > position.sweep_level:
            logger.warning(
                f"Sweep breach: {position.symbol} "
                f"close={candle_close:.4f} > sweep_level={position.sweep_level:.4f}"
            )
            return True

    return False


def check_time_stop(
    position: ManagedPosition,
    current_price: float,
    current_time: Optional[datetime] = None,
) -> bool:
    """TZ §8.6: Time stop — close if held too long without hitting TP."""
    if not TIME_STOP_ENABLED:
        return False
    if current_time is None:
        return False
    hold_minutes = position.elapsed_minutes(current_time)
    if hold_minutes >= TIME_STOP_MAX_MINUTES:
        logger.info(
            f"Time stop triggered: {position.symbol} held {hold_minutes:.0f}min "
            f">= {TIME_STOP_MAX_MINUTES}min"
        )
        return True
    return False


def check_flip_bias(
    position: ManagedPosition,
    last_bos_type: Optional[str] = None,
    last_bos_timestamp: Optional[datetime] = None,
) -> bool:
    """Check if market structure flipped against the position.

    If a new BOS occurs AGAINST the position direction after entry,
    the structure is broken — close early.
    """
    if last_bos_type is None or last_bos_timestamp is None:
        return False

    # Only check BOS that occurred AFTER entry
    entry = position.entry_time.replace(tzinfo=timezone.utc) if position.entry_time.tzinfo is None else position.entry_time
    if last_bos_timestamp <= entry:
        return False

    if position.direction == "BUY":
        # Bullish position broken by bearish BOS
        if last_bos_type.upper() == "BEARISH":
            logger.warning(
                f"Flip bias: {position.symbol} "
                f"bearish BOS at {last_bos_timestamp.isoformat()} "
                f"after entry at {entry.isoformat()}"
            )
            return True
    else:
        # Bearish position broken by bullish BOS
        if last_bos_type.upper() == "BULLISH":
            logger.warning(
                f"Flip bias: {position.symbol} "
                f"bullish BOS at {last_bos_timestamp.isoformat()} "
                f"after entry at {entry.isoformat()}"
            )
            return True

    return False


def manage_position(
    position: ManagedPosition,
    candle_high: float,
    candle_low: float,
    candle_close: float,
    atr: float = 0.0,
    current_time: Optional[datetime] = None,
    last_bos_type: Optional[str] = None,
    last_bos_timestamp: Optional[datetime] = None,
) -> dict:
    """Full position management check per bar.

    Returns dict with actions to take:
    {
        "close": bool,
        "reason": str,
        "partial_closes": list[dict],
        "new_sl": float or None,
        "breakeven": bool,
        "trailing": bool,
    }
    """
    result = {
        "close": False,
        "reason": "",
        "partial_closes": [],
        "new_sl": None,
        "breakeven": False,
        "trailing": False,
    }

    # 1. Flip Bias check — BOS against position after entry
    if check_flip_bias(position, last_bos_type, last_bos_timestamp):
        result["close"] = True
        result["reason"] = "FLIP_BIAS"
        return result

    # 2. Sweep breach check (TZ §10.2)
    if check_sweep_breach(position, candle_close):
        result["close"] = True
        result["reason"] = "SWEEP_BREACH"
        return result

    # 3. Time stop check (TZ §8.6)
    if check_time_stop(position, candle_close, current_time):
        result["close"] = True
        result["reason"] = "TIME_STOP"
        return result

    # 4. Partial closes (TZ §8.3)
    actions = check_partial_closes(position, candle_high, candle_low, atr)
    for action in actions:
        apply_partial_close(position, action, atr)
        result["partial_closes"].append(action)

        if action["action"] == "close_all":
            result["close"] = True
            result["reason"] = f"TP{len(position.completed_targets)}_FULL"
            return result

    # 5. Breakeven check (TZ §8.4) — use intra-bar high/low, not close
    _be_price = candle_high if position.direction == "BUY" else candle_low
    be_sl = check_breakeven(position, _be_price)
    if be_sl is not None:
        result["new_sl"] = be_sl
        result["breakeven"] = True

    # 6. Trailing stop check (TZ §8.5)
    trail_sl = calculate_trailing_stop(position, candle_close, atr)
    if trail_sl is not None:
        result["new_sl"] = trail_sl
        result["trailing"] = True

    return result
