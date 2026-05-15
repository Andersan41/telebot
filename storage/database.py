"""
storage/database.py — SQLAlchemy модели и методы работы с БД
"""
import os
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, select, desc, ForeignKey
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from loguru import logger
from config.settings import config

Base = declarative_base()


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, index=True)
    timeframe = Column(String(10), nullable=False)
    signal_type = Column(String(10), nullable=False)  # BUY / SELL
    close_price = Column(Float, nullable=False)
    sl = Column(Float, nullable=True)
    tp = Column(Float, nullable=True)
    score = Column(Integer, default=0)
    reasons = Column(Text, nullable=True)
    confirmed = Column(Boolean, default=False)  # Подтверждён на 15M
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    sent_at = Column(DateTime, nullable=True)


class BotSetting(Base):
    __tablename__ = "bot_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ContextSnapshotModel(Base):
    __tablename__ = "context_snapshots"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), index=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    verdict = Column(String(20))
    confidence = Column(Float)
    score = Column(Float)
    fear_greed = Column(Integer, nullable=True)
    funding_rate = Column(Float, nullable=True)
    long_short_ratio = Column(Float, nullable=True)
    open_interest_delta = Column(Float, nullable=True)
    news_sentiment = Column(Float, nullable=True)
    raw_json = Column(Text, nullable=True)


class SignalOutcome(Base):
    __tablename__ = "signal_outcomes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(
        Integer, ForeignKey("signals.id"), nullable=False, index=True
    )
    status = Column(String(20), nullable=False, default="OPEN")
    closed_at = Column(DateTime, nullable=True)
    close_price = Column(Float, nullable=True)
    pnl_pct = Column(Float, nullable=True)
    checked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Database:
    def __init__(self):
        os.makedirs("data", exist_ok=True)
        self._engine = create_async_engine(
            config.database_url,
            echo=False,
        )
        self._session_factory = sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init(self):
        """Создаём таблицы при первом запуске"""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized")

    async def save_signal(
        self,
        symbol: str,
        timeframe: str,
        signal_type: str,
        close_price: float,
        sl: Optional[float],
        tp: Optional[float],
        score: int,
        reasons: List[str],
        confirmed: bool = False,
    ) -> Signal:
        async with self._session_factory() as session:
            sig = Signal(
                symbol=symbol,
                timeframe=timeframe,
                signal_type=signal_type,
                close_price=close_price,
                sl=sl,
                tp=tp,
                score=score,
                reasons="\n".join(reasons),
                confirmed=confirmed,
                sent_at=datetime.now(timezone.utc),
            )
            session.add(sig)
            await session.commit()
            await session.refresh(sig)
            return sig

    async def get_last_signal(self, symbol: str, timeframe: str) -> Optional[Signal]:
        """Последний сигнал по символу и таймфрейму"""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Signal)
                .where(Signal.symbol == symbol, Signal.timeframe == timeframe)
                .order_by(desc(Signal.created_at))
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def get_recent_signals(self, limit: int = 10) -> List[Signal]:
        """Последние N сигналов"""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Signal).order_by(desc(Signal.created_at)).limit(limit)
            )
            return list(result.scalars().all())

    async def get_setting(self, key: str, default: str = "") -> str:
        async with self._session_factory() as session:
            result = await session.execute(
                select(BotSetting).where(BotSetting.key == key)
            )
            row = result.scalar_one_or_none()
            return row.value if row else default

    async def set_setting(self, key: str, value: str):
        async with self._session_factory() as session:
            result = await session.execute(
                select(BotSetting).where(BotSetting.key == key)
            )
            row = result.scalar_one_or_none()
            if row:
                row.value = value
                row.updated_at = datetime.now(timezone.utc)
            else:
                session.add(BotSetting(key=key, value=value))
            await session.commit()

    async def get_cooldown(
        self, symbol: str, timeframe: str
    ) -> Optional[datetime]:
        key = f"cooldown:{symbol}:{timeframe}"
        val = await self.get_setting(key, "")
        if not val:
            return None
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None

    async def set_cooldown(
        self, symbol: str, timeframe: str, ts: datetime
    ) -> None:
        key = f"cooldown:{symbol}:{timeframe}"
        await self.set_setting(key, ts.isoformat())

    async def get_dynamic_symbols(self) -> Optional[list[str]]:
        """None — динамический список не задан, использовать env SYMBOLS."""
        val = await self.get_setting("dynamic_symbols", "")
        if not val:
            return None
        return [s.strip() for s in val.split(",") if s.strip()]

    async def set_dynamic_symbols(self, symbols: list[str]) -> None:
        await self.set_setting("dynamic_symbols", ",".join(symbols))

    async def get_disabled_symbols(self) -> Optional[list[str]]:
        """None — список отключённых символов не задан."""
        val = await self.get_setting("disabled_symbols", "")
        if not val:
            return None
        return [s.strip() for s in val.split(",") if s.strip()]

    async def set_disabled_symbols(self, symbols: list[str]) -> None:
        await self.set_setting("disabled_symbols", ",".join(symbols))

    async def save_context_snapshot(
        self,
        symbol: str,
        signal_id: Optional[int],
        verdict: str,
        confidence: float,
        score: float,
        fear_greed: Optional[int] = None,
        funding_rate: Optional[float] = None,
        long_short_ratio: Optional[float] = None,
        open_interest_delta: Optional[float] = None,
        news_sentiment: Optional[float] = None,
        raw_json: Optional[str] = None,
    ) -> ContextSnapshotModel:
        async with self._session_factory() as session:
            snap = ContextSnapshotModel(
                symbol=symbol,
                signal_id=signal_id,
                verdict=verdict,
                confidence=confidence,
                score=score,
                fear_greed=fear_greed,
                funding_rate=funding_rate,
                long_short_ratio=long_short_ratio,
                open_interest_delta=open_interest_delta,
                news_sentiment=news_sentiment,
                raw_json=raw_json,
            )
            session.add(snap)
            await session.commit()
            await session.refresh(snap)
            return snap

    async def get_signal(self, signal_id: int) -> Optional[Signal]:
        """Получить сигнал по ID (нужен outcome_tracker)."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Signal).where(Signal.id == signal_id)
            )
            return result.scalar_one_or_none()

    async def create_outcome(self, signal_id: int) -> "SignalOutcome":
        async with self._session_factory() as session:
            outcome = SignalOutcome(signal_id=signal_id, status="OPEN")
            session.add(outcome)
            await session.commit()
            await session.refresh(outcome)
            return outcome

    async def get_open_outcomes(self) -> list["SignalOutcome"]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(SignalOutcome).where(SignalOutcome.status == "OPEN")
            )
            return list(result.scalars().all())

    async def close_outcome(
        self, outcome_id: int, status: str, close_price: float, pnl_pct: float
    ) -> None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(SignalOutcome).where(SignalOutcome.id == outcome_id)
            )
            row = result.scalar_one()
            row.status = status
            row.close_price = close_price
            row.pnl_pct = pnl_pct
            row.closed_at = datetime.now(timezone.utc)
            await session.commit()

    async def get_outcome_stats(self) -> dict:
        async with self._session_factory() as session:
            closed = await session.execute(
                select(SignalOutcome).where(SignalOutcome.status != "OPEN")
            )
            closed_rows = list(closed.scalars().all())
            opened = await session.execute(
                select(SignalOutcome).where(SignalOutcome.status == "OPEN")
            )
            opened_rows = list(opened.scalars().all())
        pnls = [r.pnl_pct for r in closed_rows if r.pnl_pct is not None]
        return {
            "closed": len(closed_rows),
            "open": len(opened_rows),
            "wins": sum(1 for r in closed_rows if r.status == "HIT_TP"),
            "avg_pnl": sum(pnls) / len(pnls) if pnls else 0.0,
            "best_pnl": max(pnls) if pnls else 0.0,
            "worst_pnl": min(pnls) if pnls else 0.0,
        }


db = Database()
