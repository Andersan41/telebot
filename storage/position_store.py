"""
storage/position_store.py — Persistent position state (SQLite).

Saves/loads ManagedPosition to survive bot restarts.
"""
import json
from datetime import datetime, timezone
from typing import List, Optional

from loguru import logger
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, select

from storage.database import Base, db


class PositionModel(Base):
    """SQLite model for open positions."""
    __tablename__ = "positions"

    id = Column(String(50), primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    direction = Column(String(10), nullable=False)
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=True)
    quantity = Column(Float, nullable=False, default=1.0)
    entry_time = Column(DateTime, nullable=False)

    # Breakeven
    breakeven_moved = Column(Boolean, default=False)

    # Partial Close
    remaining_percent = Column(Float, default=100.0)
    completed_targets = Column(Text, default="[]")  # JSON array

    # Trailing
    trailing_active = Column(Boolean, default=False)
    trailing_atr = Column(Float, default=0.0)

    # Sweep context
    sweep_level = Column(Float, nullable=True)
    sweep_extreme = Column(Float, nullable=True)
    sweep_timestamp = Column(DateTime, nullable=True)

    # Status
    status = Column(String(20), default="OPEN", index=True)
    close_price = Column(Float, nullable=True)
    close_reason = Column(String(30), nullable=True)
    close_time = Column(DateTime, nullable=True)

    # Metrics
    expected_rr = Column(Float, nullable=True)
    actual_rr = Column(Float, nullable=True)
    pnl_usdt = Column(Float, nullable=True)
    pnl_percent = Column(Float, nullable=True)


async def _ensure_table():
    """Create positions table if not exists."""
    try:
        async with db._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as e:
        logger.warning(f"Failed to create positions table: {e}")


async def save_position(position) -> None:
    """Save a ManagedPosition to the database."""
    await _ensure_table()

    from risk.position_manager import ManagedPosition

    completed = json.dumps(list(position.completed_targets))
    entry_time = position.entry_time.replace(tzinfo=timezone.utc) if position.entry_time.tzinfo is None else position.entry_time

    sweep_ts = None
    if position.sweep_timestamp is not None:
        sweep_ts = position.sweep_timestamp.replace(tzinfo=timezone.utc) if position.sweep_timestamp.tzinfo is None else position.sweep_timestamp

    model = PositionModel(
        id=f"{position.symbol}_{int(entry_time.timestamp())}",
        symbol=position.symbol,
        direction=position.direction,
        entry_price=position.entry_price,
        stop_loss=position.stop_loss,
        take_profit=position.take_profit,
        quantity=position.quantity,
        entry_time=entry_time,
        breakeven_moved=position.breakeven_moved,
        remaining_percent=position.remaining_percent,
        completed_targets=completed,
        trailing_active=position.trailing_active,
        trailing_atr=position.trailing_atr,
        sweep_level=position.sweep_level,
        sweep_extreme=position.sweep_extreme,
        sweep_timestamp=sweep_ts,
        status="OPEN",
    )

    try:
        async with db._session_factory() as session:
            await session.merge(model)
            await session.commit()
    except Exception as e:
        logger.error(f"Failed to save position {position.symbol}: {e}")


async def load_open_positions() -> list:
    """Load all OPEN positions from the database."""
    await _ensure_table()

    from risk.position_manager import ManagedPosition

    try:
        async with db._session_factory() as session:
            result = await session.execute(
                select(PositionModel).where(PositionModel.status == "OPEN")
            )
            rows = result.scalars().all()

        positions = []
        for row in rows:
            completed = set(json.loads(row.completed_targets)) if row.completed_targets else set()
            pos = ManagedPosition(
                symbol=row.symbol,
                direction=row.direction,
                entry_price=row.entry_price,
                stop_loss=row.stop_loss,
                take_profit=row.take_profit,
                quantity=row.quantity,
                entry_time=row.entry_time.replace(tzinfo=timezone.utc) if row.entry_time.tzinfo is None else row.entry_time,
                breakeven_moved=row.breakeven_moved,
                remaining_percent=row.remaining_percent,
                completed_targets=completed,
                trailing_active=row.trailing_active,
                trailing_atr=row.trailing_atr,
                sweep_level=row.sweep_level,
                sweep_extreme=row.sweep_extreme,
                sweep_timestamp=row.sweep_timestamp.replace(tzinfo=timezone.utc) if row.sweep_timestamp and row.sweep_timestamp.tzinfo is None else row.sweep_timestamp,
            )
            positions.append(pos)

        if positions:
            logger.info(f"Loaded {len(positions)} open positions from DB")
        return positions

    except Exception as e:
        logger.error(f"Failed to load positions: {e}")
        return []


async def update_position_state(position_id: str, **kwargs) -> None:
    """Atomically update position fields."""
    try:
        async with db._session_factory() as session:
            result = await session.execute(
                select(PositionModel).where(PositionModel.id == position_id)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return

            for key, value in kwargs.items():
                if hasattr(model, key):
                    if key == "completed_targets" and isinstance(value, set):
                        value = json.dumps(list(value))
                    setattr(model, key, value)

            await session.commit()
    except Exception as e:
        logger.error(f"Failed to update position {position_id}: {e}")


async def close_position(position_id: str, close_price: float, reason: str) -> None:
    """Mark a position as closed."""
    now = datetime.now(timezone.utc)
    await update_position_state(
        position_id,
        status="CLOSED",
        close_price=close_price,
        close_reason=reason,
        close_time=now,
    )


async def get_position_id(position) -> str:
    """Get the database ID for a ManagedPosition."""
    entry = position.entry_time.replace(tzinfo=timezone.utc) if position.entry_time.tzinfo is None else position.entry_time
    return f"{position.symbol}_{int(entry.timestamp())}"
