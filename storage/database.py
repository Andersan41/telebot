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


db = Database()
