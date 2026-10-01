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
from storage.position_store import PositionModel
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
    # Clear module-level position state between tests
    from scheduler.outcome_tracker import _position_state
    _position_state.clear()
    yield
    await db._engine.dispose()


@pytest.fixture
async def buy_signal():
    """Создаёт BUY-сигнал: entry=100, SL=95, TP=110."""
    # Set entry_candle_open to 2 hours ago to avoid same-candle skip
    entry_candle = datetime.now(timezone.utc) - timedelta(hours=2)
    sig = await db.save_signal(
        symbol="BTC/USDT",
        timeframe="1h",
        signal_type="BUY",
        close_price=100.0,
        sl=95.0,
        tp=110.0,
        score=5,
        reasons=["test"],
        entry_candle_open=entry_candle,
    )
    await db.create_outcome(sig.id)
    return sig


@pytest.fixture
async def sell_signal():
    """Создаёт SELL-сигнал: entry=100, SL=105, TP=90."""
    # Set entry_candle_open to 2 hours ago to avoid same-candle skip
    entry_candle = datetime.now(timezone.utc) - timedelta(hours=2)
    sig = await db.save_signal(
        symbol="ETH/USDT",
        timeframe="1h",
        signal_type="SELL",
        close_price=100.0,
        sl=105.0,
        tp=90.0,
        score=5,
        reasons=["test"],
        entry_candle_open=entry_candle,
    )
    await db.create_outcome(sig.id)
    return sig


@pytest.fixture(autouse=True)
def mock_notification():
    """Mock Telegram notifications to prevent real messages during tests."""
    with patch(
        "scheduler.outcome_tracker._send_close_notification",
        new_callable=AsyncMock,
    ):
        yield


class TestHitTP:
    """Цена пробивает TP → HIT_TP."""

    @pytest.mark.asyncio
    async def test_buy_hit_tp(self, buy_signal, setup_db):
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=112.0,
        ):
            await check_open_outcomes()

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 1
        assert stats["wins"] == 1
        assert stats["avg_pnl"] > 0

    @pytest.mark.asyncio
    async def test_sell_hit_tp(self, sell_signal, setup_db):
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=88.0,
        ):
            await check_open_outcomes()

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 1
        assert stats["wins"] == 1


class TestHitSL:
    """Цена пробивает SL → HIT_SL."""

    @pytest.mark.asyncio
    async def test_buy_hit_sl(self, buy_signal, setup_db):
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=93.0,
        ):
            await check_open_outcomes()

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 1
        assert stats["wins"] == 0  # SL — не win
        assert stats["avg_pnl"] < 0

    @pytest.mark.asyncio
    async def test_sell_hit_sl(self, sell_signal, setup_db):
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=107.0,
        ):
            await check_open_outcomes()

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 1
        assert stats["wins"] == 0


class TestNoHit:
    """Цена в коридоре → outcome остаётся OPEN."""

    @pytest.mark.asyncio
    async def test_price_in_corridor(self, buy_signal, setup_db):
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=105.0,
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
            entry_candle_open=old_ts - timedelta(hours=1),
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
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=51.0,
        ):
            await check_open_outcomes()

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 1
        open_outcomes = await db.get_open_outcomes()
        assert len(open_outcomes) == 0

        # B-018: EXPIRED uses real PnL (entry=50 → mark=51 = +2% before fees)
        async with db._session_factory() as session:
            from sqlalchemy import select as _sel
            from storage.database import SignalOutcome as _SO
            row = (await session.execute(_sel(_SO))).scalars().first()
            assert row is not None
            assert row.status == "EXPIRED"
            assert row.pnl_pct is not None
            assert row.pnl_pct > 0

    @pytest.mark.asyncio
    async def test_expired_unknown_price_keeps_pnl_none(self, setup_db):
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
            entry_candle_open=old_ts - timedelta(hours=1),
        )
        async with db._session_factory() as session:
            result = await session.execute(
                select(Signal).where(Signal.id == sig.id)
            )
            row = result.scalar_one()
            row.created_at = old_ts
            await session.commit()
        await db.create_outcome(sig.id)

        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=None,
        ):
            await check_open_outcomes()

        async with db._session_factory() as session:
            from sqlalchemy import select as _sel
            from storage.database import SignalOutcome as _SO
            row = (await session.execute(_sel(_SO))).scalars().first()
            assert row is not None
            assert row.status == "EXPIRED"
            # Unknown price ≠ scratch 0.0 — pnl stays None (B-018)
            assert row.pnl_pct is None


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
        entry_candle = datetime.now(timezone.utc) - timedelta(hours=2)
        sig1 = await db.save_signal(
            symbol="BTC/USDT", timeframe="1h", signal_type="BUY",
            close_price=100.0, sl=95.0, tp=110.0, score=5, reasons=["a"],
            entry_candle_open=entry_candle,
        )
        sig2 = await db.save_signal(
            symbol="ETH/USDT", timeframe="1h", signal_type="BUY",
            close_price=200.0, sl=190.0, tp=220.0, score=5, reasons=["b"],
            entry_candle_open=entry_candle,
        )
        await db.create_outcome(sig1.id)
        await db.create_outcome(sig2.id)

        # Первый сигнал → HIT_TP (цена 115)
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=115.0,
        ):
            await check_open_outcomes()

        # Второй сигнал → HIT_SL (цена 185)
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=185.0,
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
    """fetch_ticker_price возвращает None → скип, outcome остаётся OPEN."""

    @pytest.mark.asyncio
    async def test_fetch_returns_none(self, buy_signal, setup_db):
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=None,
        ):
            await check_open_outcomes()

        open_outcomes = await db.get_open_outcomes()
        assert len(open_outcomes) == 1


class TestTickerSLBreachWhileCandleInside:
    """Регрессионный тест: ticker пробивает SL, но закрытая свеча внутри диапазона.

    Баг: outcome_tracker использовал close последней ЗАКРЫТОЙ свечи (iloc[:-1]).
    Если SL пробит на ТЕКУЩЕЙ незакрытой свече — трекер не видел пробоя.
    Исправление: используем fetch_ticker_price (real-time).
    """

    @pytest.mark.asyncio
    async def test_sell_sl_breach_ticker_only(self, sell_signal, setup_db):
        """SELL entry=100, SL=105. Candle close=102 (внутри), ticker=106 (SL пробит)."""
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=106.0,
        ):
            await check_open_outcomes()

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 1
        assert stats["wins"] == 0  # SL

    @pytest.mark.asyncio
    async def test_buy_sl_breach_ticker_only(self, buy_signal, setup_db):
        """BUY entry=100, SL=95. Candle close=97 (внутри), ticker=94 (SL пробит)."""
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=94.0,
        ):
            await check_open_outcomes()

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 1
        assert stats["wins"] == 0  # SL

    @pytest.mark.asyncio
    async def test_sell_tp_breach_ticker_only(self, sell_signal, setup_db):
        """SELL entry=100, TP=90. Candle close=92 (внутри), ticker=89 (TP пробит)."""
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=89.0,
        ):
            await check_open_outcomes()

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 1
        assert stats["wins"] == 1  # TP


class TestPositionRowClosed:
    """Регрессионный тест: HIT_TP / HIT_SL / EXPIRED должны закрывать строку в positions.

    Баг: только ветка mgmt["close"] вызывала close_position(). Ветки hit_tp/hit_sl
    (и EXPIRED) закрывали signal_outcomes, но позиция в таблице positions навсегда
    оставалась OPEN — реальный ETC/USDT HIT_SL (signal id=6) оставил фантомную
    OPEN-строку. Дашборд читает signal_outcomes, но таблица positions рассинхронизировалась.
    """

    @staticmethod
    async def _get_position(symbol: str):
        async with db._session_factory() as session:
            result = await session.execute(
                select(PositionModel).where(PositionModel.symbol == symbol)
            )
            return result.scalars().first()

    @pytest.mark.asyncio
    async def test_hit_sl_closes_position_row(self, buy_signal, setup_db):
        """BUY entry=100 SL=95, ticker=93 → outcome HIT_SL, position row CLOSED."""
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=93.0,
        ):
            await check_open_outcomes()

        row = await self._get_position("BTC/USDT")
        assert row is not None, "position row should have been created by tracker"
        assert row.status == "CLOSED"
        assert row.close_reason == "HIT_SL"
        assert row.close_price is not None

        from scheduler.outcome_tracker import _position_state
        assert str(buy_signal.id) not in _position_state

    @pytest.mark.asyncio
    async def test_hit_tp_closes_position_row(self, buy_signal, setup_db):
        """BUY entry=100 TP=110, ticker=112 → outcome HIT_TP, position row CLOSED."""
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=112.0,
        ):
            await check_open_outcomes()

        row = await self._get_position("BTC/USDT")
        assert row is not None
        assert row.status == "CLOSED"
        assert row.close_reason == "HIT_TP"

        from scheduler.outcome_tracker import _position_state
        assert str(buy_signal.id) not in _position_state

    @pytest.mark.asyncio
    async def test_sell_hit_sl_closes_position_row(self, sell_signal, setup_db):
        """SELL entry=100 SL=105, ticker=107 → outcome HIT_SL, position row CLOSED."""
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=107.0,
        ):
            await check_open_outcomes()

        row = await self._get_position("ETH/USDT")
        assert row is not None
        assert row.status == "CLOSED"
        assert row.close_reason == "HIT_SL"

    @pytest.mark.asyncio
    async def test_expired_closes_existing_position_row(self, setup_db):
        """EXPIRED (TTL 8 дней) → ранее созданная OPEN-позиция должна закрыться."""
        old_ts = datetime.now(timezone.utc) - timedelta(days=8)
        sig = await db.save_signal(
            symbol="AVAX/USDT", timeframe="1h", signal_type="BUY",
            close_price=50.0, sl=48.0, tp=55.0, score=5, reasons=["test"],
            entry_candle_open=old_ts - timedelta(hours=1),
        )
        async with db._session_factory() as session:
            result = await session.execute(select(Signal).where(Signal.id == sig.id))
            row = result.scalar_one()
            row.created_at = old_ts
            await session.commit()
        await db.create_outcome(sig.id)

        # Позиция была создана при прошлом проходе трекера (id по created_at)
        pos_id = f"AVAX/USDT_{int(old_ts.timestamp())}"
        async with db._session_factory() as session:
            session.add(PositionModel(
                id=pos_id, symbol="AVAX/USDT", direction="BUY",
                entry_price=50.0, stop_loss=48.0, quantity=1.0,
                entry_time=old_ts.replace(tzinfo=None), status="OPEN",
            ))
            await session.commit()

        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=51.0,
        ):
            await check_open_outcomes()

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 1

        async with db._session_factory() as session:
            result = await session.execute(
                select(PositionModel).where(PositionModel.id == pos_id)
            )
            pos_row = result.scalar_one()
        assert pos_row.status == "CLOSED"
        assert pos_row.close_reason == "EXPIRED"


class TestCloseNotificationLabels:
    """R-лесеночное закрытие не должно выглядеть как fill по signal.tp."""

    def test_r_ladder_label_differs_from_signal_tp(self):
        from scheduler.outcome_tracker import _STATUS_LABELS

        assert _STATUS_LABELS["HIT_TP"] == ("✅", "Тейк Профит")
        for key, rr in (("TP1_FULL", "2R"), ("TP2_FULL", "3R"), ("TP3_FULL", "4R")):
            emoji, label = _STATUS_LABELS[key]
            assert rr in label
            assert _STATUS_LABELS[key] != _STATUS_LABELS["HIT_TP"]


def _single_candle(high: float, low: float, close: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [close],
            "high": [high],
            "low": [low],
            "close": [close],
            "volume": [100.0],
        }
    )


class TestBreakevenThenLadder:
    """Регрессия NEAR/USDT (signal_id=8): breakeven на 1.5R переносил SL на
    entry → risk=0 → все R-цели схлопывались в цену entry → лесенка
    закрывалась одной свечей по рынку с reason=TP3_FULL («✅ Тейк Профит»),
    хотя до signal.tp цена не доходила.
    """

    @staticmethod
    async def _get_position(symbol: str):
        async with db._session_factory() as session:
            result = await session.execute(
                select(PositionModel).where(PositionModel.symbol == symbol)
            )
            return result.scalars().first()

    @pytest.mark.asyncio
    async def test_be_persisted_and_position_stays_open(self, buy_signal, setup_db):
        # entry=100, SL=95 → 1.5R=107.5; свеча 107..108 двигает SL на entry,
        # 2R (110) при этом ещё не достигнут
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=108.0,
        ), patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ohlcv",
            new_callable=AsyncMock, return_value=_single_candle(108.0, 107.0, 108.0),
        ):
            await check_open_outcomes()

        row = await self._get_position("BTC/USDT")
        assert row is not None
        assert row.status == "OPEN"
        assert row.stop_loss == pytest.approx(100.0)
        assert row.breakeven_moved is True

        # Второй цикл: цена 108 < 2R (110) — позиция должна остаться открытой
        with patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ticker_price",
            new_callable=AsyncMock, return_value=108.0,
        ), patch(
            "scheduler.outcome_tracker.exchange_client.fetch_ohlcv",
            new_callable=AsyncMock, return_value=_single_candle(108.0, 107.0, 108.0),
        ):
            await check_open_outcomes()

        row = await self._get_position("BTC/USDT")
        assert row.status == "OPEN"
        assert row.close_reason is None

        stats = await db.get_outcome_stats()
        assert stats["closed"] == 0
