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


class TestHistoricalWinrate:
    """Task 6.1 — Historical winrate lookup by factor fingerprint."""

    @pytest.mark.asyncio
    async def test_no_history_returns_none(self, setup_db):
        await db.init()
        result = await db.get_historical_winrate("nonexistent_fingerprint")
        assert result is None

    @pytest.mark.asyncio
    async def test_insufficient_samples_returns_none(self, setup_db):
        await db.init()
        # Create 3 signals with same fingerprint but only 2 closed outcomes (< min_samples=5)
        sig1 = await db.save_signal(
            "BTC/USDT", "1h", "BUY", 50000.0, 48000.0, 53000.0, 5, [],
            factor_fingerprint="ema_bullish|macd_pos",
        )
        sig2 = await db.save_signal(
            "BTC/USDT", "1h", "BUY", 50500.0, 48500.0, 53500.0, 5, [],
            factor_fingerprint="ema_bullish|macd_pos",
        )
        sig3 = await db.save_signal(
            "BTC/USDT", "1h", "BUY", 51000.0, 49000.0, 54000.0, 5, [],
            factor_fingerprint="ema_bullish|macd_pos",
        )
        await db.create_outcome(sig1.id)
        await db.create_outcome(sig2.id)
        await db.create_outcome(sig3.id)
        # Close only 2 outcomes
        await db.close_outcome(1, "HIT_TP", 52000.0, 4.0)
        await db.close_outcome(2, "HIT_SL", 47000.0, -6.0)
        # 3rd outcome still open

        result = await db.get_historical_winrate("ema_bullish|macd_pos")
        assert result is None  # only 2 closed < min_samples=5

    @pytest.mark.asyncio
    async def test_winrate_calculated_correctly(self, setup_db):
        await db.init()
        # Create 10 signals with same fingerprint
        for i in range(10):
            sig = await db.save_signal(
                "BTC/USDT", "1h", "BUY", 50000.0 + i * 100, 48000.0, 53000.0, 5, [],
                factor_fingerprint="ema_bullish|macd_pos|st_bullish",
            )
            outcome = await db.create_outcome(sig.id)
            # 6 wins, 4 losses → 60% WR
            status = "HIT_TP" if i < 6 else "HIT_SL"
            close_price = 52000.0 if status == "HIT_TP" else 47000.0
            pnl = 4.0 if status == "HIT_TP" else -6.0
            await db.close_outcome(outcome.id, status, close_price, pnl)

        result = await db.get_historical_winrate("ema_bullish|macd_pos|st_bullish")
        assert result == 60.0

    @pytest.mark.asyncio
    async def test_different_fingerprints_separate(self, setup_db):
        await db.init()
        # Create signals with fingerprint A (80% WR)
        for i in range(8):
            sig = await db.save_signal(
                "BTC/USDT", "1h", "BUY", 50000.0, 48000.0, 53000.0, 5, [],
                factor_fingerprint="fingerprint_a",
            )
            outcome = await db.create_outcome(sig.id)
            status = "HIT_TP" if i < 7 else "HIT_SL"
            await db.close_outcome(outcome.id, status, 52000.0, 4.0)

        # Create signals with fingerprint B (20% WR)
        for i in range(8):
            sig = await db.save_signal(
                "BTC/USDT", "1h", "BUY", 50000.0, 48000.0, 53000.0, 5, [],
                factor_fingerprint="fingerprint_b",
            )
            outcome = await db.create_outcome(sig.id)
            status = "HIT_TP" if i < 2 else "HIT_SL"
            await db.close_outcome(outcome.id, status, 52000.0, 4.0)

        wr_a = await db.get_historical_winrate("fingerprint_a")
        wr_b = await db.get_historical_winrate("fingerprint_b")
        assert wr_a == 87.5  # 7/8 = 87.5%
        assert wr_b == 25.0  # 2/8 = 25%

    @pytest.mark.asyncio
    async def test_save_signal_with_fingerprint(self, setup_db):
        await db.init()
        sig = await db.save_signal(
            "ETH/USDT", "4h", "SELL", 3000.0, 3100.0, 2800.0, 4, [],
            factor_fingerprint="ema_bearish|macd_neg",
        )
        last = await db.get_last_signal("ETH/USDT", "4h")
        assert last is not None
        assert last.factor_fingerprint == "ema_bearish|macd_neg"

    @pytest.mark.asyncio
    async def test_save_signal_without_fingerprint(self, setup_db):
        await db.init()
        sig = await db.save_signal(
            "SOL/USDT", "1h", "BUY", 150.0, 140.0, 170.0, 5, [],
        )
        last = await db.get_last_signal("SOL/USDT", "1h")
        assert last is not None
        assert last.factor_fingerprint is None
