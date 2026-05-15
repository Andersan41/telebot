"""
tests/test_outcome_tracker.py — Unit-тесты на закрытие сигналов по TP/SL.
"""
import sys
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.database import db, Base, Signal, SignalOutcome
from scheduler.outcome_tracker import check_open_outcomes


@pytest.fixture(autouse=True)
async def setup_db(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/test_outcome.db"
    db._engine = create_async_engine(db_url, echo=False)
    db._session_factory = sessionmaker(
        db._engine, class_=AsyncSession, expire_on_commit=False
    )
    async with db._engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await db._engine.dispose()


@pytest.fixture
async def buy_signal():
    """Создаёт BUY-сигнал: entry=100, SL=95, TP=110."""
    sig = await db.save_signal(
        symbol="BTC/USDT",
        timeframe="1h",
        signal_type="BUY",
        close_price=100.0,
        sl=95.0,
        tp=110.0,
        score=5,
        reasons=["test"],
    )
    await db.create_outcome(sig.id)
    return sig


@pytest.fixture
async def sell_signal():
    """Создаёт SELL-сигнал: entry=100, SL=105, TP=90."""
    sig = await db.save_signal(
        symbol="ETH/USDT",
        timeframe="1h",
        signal_type="SELL",
        close_price=100.0,
        sl=105.0,
        tp=90.0,
        score=5,
        reasons=["test"],
    )
    await db.create_outcome(sig.id)
    return sig


def _make_ohlcv(close_price):
    """Helper: DataFrame с двумя свечами (входная цена + текущая)."""
    return pd.DataFrame({"close": [100.0, close_price]})


class TestHitTP:
    """Цена пробивает TP → HIT_TP."""

    @pytest.mark.asyncio
    async def test_buy_hit_tp(self, buy_signal, setup_db):
        mock_df = _make_ohlcv(112.0)  # выше TP=110
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ohlcv",
            new_callable=AsyncMock, return_value=mock_df,
        ):
            await check_open_outcomes()

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 1
        assert stats["wins"] == 1
        assert stats["avg_pnl"] > 0

    @pytest.mark.asyncio
    async def test_sell_hit_tp(self, sell_signal, setup_db):
        mock_df = _make_ohlcv(88.0)  # ниже TP=90 для SELL
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ohlcv",
            new_callable=AsyncMock, return_value=mock_df,
        ):
            await check_open_outcomes()

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 1
        assert stats["wins"] == 1


class TestHitSL:
    """Цена пробивает SL → HIT_SL."""

    @pytest.mark.asyncio
    async def test_buy_hit_sl(self, buy_signal, setup_db):
        mock_df = _make_ohlcv(93.0)  # ниже SL=95 для BUY
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ohlcv",
            new_callable=AsyncMock, return_value=mock_df,
        ):
            await check_open_outcomes()

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 1
        assert stats["wins"] == 0  # SL — не win
        assert stats["avg_pnl"] < 0

    @pytest.mark.asyncio
    async def test_sell_hit_sl(self, sell_signal, setup_db):
        mock_df = _make_ohlcv(107.0)  # выше SL=105 для SELL
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ohlcv",
            new_callable=AsyncMock, return_value=mock_df,
        ):
            await check_open_outcomes()

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 1
        assert stats["wins"] == 0


class TestNoHit:
    """Цена в коридоре → outcome остаётся OPEN."""

    @pytest.mark.asyncio
    async def test_price_in_corridor(self, buy_signal, setup_db):
        mock_df = _make_ohlcv(105.0)  # между SL=95 и TP=110
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ohlcv",
            new_callable=AsyncMock, return_value=mock_df,
        ):
            await check_open_outcomes()

        open_outcomes = await db.get_open_outcomes()
        assert len(open_outcomes) == 1
        stats = await db.get_outcome_stats()
        assert stats["open"] == 1
        assert stats["closed"] == 0


class TestExpired:
    """Просроченный сигнал → EXPIRED."""

    @pytest.mark.asyncio
    async def test_expired_signal(self, setup_db):
        old_ts = datetime.now(timezone.utc) - timedelta(days=8)
        sig = await db.save_signal(
            symbol="SOL/USDT",
            timeframe="1h",
            signal_type="BUY",
            close_price=50.0,
            sl=48.0,
            tp=55.0,
            score=5,
            reasons=["test"],
        )
        # Обновляем created_at в БД на 8 дней назад
        async with db._session_factory() as session:
            result = await session.execute(
                select(Signal).where(Signal.id == sig.id)
            )
            row = result.scalar_one()
            row.created_at = old_ts
            await session.commit()
        await db.create_outcome(sig.id)

        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ohlcv",
            new_callable=AsyncMock, return_value=pd.DataFrame({"close": [50.0, 51.0]}),
        ):
            await check_open_outcomes()

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 1
        open_outcomes = await db.get_open_outcomes()
        assert len(open_outcomes) == 0


class TestGetOutcomeStats:
    """Проверка get_outcome_stats."""

    @pytest.mark.asyncio
    async def test_empty_stats(self, setup_db):
        stats = await db.get_outcome_stats()
        assert stats["closed"] == 0
        assert stats["open"] == 0
        assert stats["wins"] == 0
        assert stats["avg_pnl"] == 0.0

    @pytest.mark.asyncio
    async def test_stats_with_mixed_results(self, setup_db):
        sig1 = await db.save_signal(
            symbol="BTC/USDT", timeframe="1h", signal_type="BUY",
            close_price=100.0, sl=95.0, tp=110.0, score=5, reasons=["a"],
        )
        sig2 = await db.save_signal(
            symbol="ETH/USDT", timeframe="1h", signal_type="BUY",
            close_price=200.0, sl=190.0, tp=220.0, score=5, reasons=["b"],
        )
        await db.create_outcome(sig1.id)
        await db.create_outcome(sig2.id)

        # Первый сигнал → HIT_TP (цена 115)
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ohlcv",
            new_callable=AsyncMock, return_value=pd.DataFrame({"close": [100.0, 115.0]}),
        ):
            await check_open_outcomes()

        # Второй сигнал → HIT_SL (цена 185)
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ohlcv",
            new_callable=AsyncMock, return_value=pd.DataFrame({"close": [200.0, 185.0]}),
        ):
            await check_open_outcomes()

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 2
        assert stats["wins"] == 1
        assert stats["open"] == 0
        assert stats["avg_pnl"] != 0.0
        assert stats["best_pnl"] > 0
        assert stats["worst_pnl"] < 0


class TestFetchError:
    """fetch_ohlcv возвращает None → скип, outcome остаётся OPEN."""

    @pytest.mark.asyncio
    async def test_fetch_returns_none(self, buy_signal, setup_db):
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ohlcv",
            new_callable=AsyncMock, return_value=None,
        ):
            await check_open_outcomes()

        open_outcomes = await db.get_open_outcomes()
        assert len(open_outcomes) == 1


class TestFetchEmpty:
    """fetch_ohlcv возвращает пустой DataFrame → скип."""

    @pytest.mark.asyncio
    async def test_fetch_returns_empty(self, buy_signal, setup_db):
        empty_df = pd.DataFrame({"close": []})
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ohlcv",
            new_callable=AsyncMock, return_value=empty_df,
        ):
            await check_open_outcomes()

        open_outcomes = await db.get_open_outcomes()
        assert len(open_outcomes) == 1
