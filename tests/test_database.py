import sys
import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.database import db, Base, Signal


@pytest.fixture(autouse=True)
async def setup_db(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/test_signals.db"
    db._engine = create_async_engine(db_url, echo=False)
    db._session_factory = sessionmaker(
        db._engine, class_=AsyncSession, expire_on_commit=False
    )
    async with db._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await db._engine.dispose()


class TestDatabase:
    @pytest.mark.asyncio
    async def test_init(self, setup_db):
        await db.init()
        assert db._engine is not None

    @pytest.mark.asyncio
    async def test_save_and_read_signal(self, setup_db):
        await db.init()
        await db.save_signal(
            symbol="BTC/USDT",
            timeframe="1h",
            signal_type="BUY",
            close_price=50000.0,
            sl=48500.0,
            tp=53000.0,
            score=5,
            reasons=["RSI oversold", "Supertrend bullish"],
        )
        last = await db.get_last_signal("BTC/USDT", "1h")
        assert last is not None
        assert last.symbol == "BTC/USDT"
        assert last.signal_type == "BUY"
        assert last.close_price == 50000.0

    @pytest.mark.asyncio
    async def test_get_last_signal_none(self, setup_db):
        await db.init()
        result = await db.get_last_signal("NONEXISTENT", "1h")
        assert result is None

    @pytest.mark.asyncio
    async def test_recent_signals(self, setup_db):
        await db.init()
        await db.save_signal("ETH/USDT", "1h", "BUY", 3000.0, 2900.0, 3300.0, 6, [])
        await db.save_signal("SOL/USDT", "1h", "SELL", 150.0, 160.0, 130.0, 4, [])
        recent = await db.get_recent_signals(limit=5)
        assert len(recent) == 2

    @pytest.mark.asyncio
    async def test_settings_crud(self, setup_db):
        await db.init()
        await db.set_setting("min_score", "4")
        val = await db.get_setting("min_score")
        assert val == "4"
        missing = await db.get_setting("nonexistent")
        assert missing == ""

    @pytest.mark.asyncio
    async def test_update_setting(self, setup_db):
        await db.init()
        await db.set_setting("min_score", "4")
        await db.set_setting("min_score", "5")
        val = await db.get_setting("min_score")
        assert val == "5"
