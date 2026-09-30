import sys
import os
import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storage.database import (
    db,
    Base,
    Signal,
    DecisionTrace,
    SignalAuditLog,
    configure_sqlite_engine,
)


@pytest.fixture(autouse=True)
async def setup_db(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path}/test_signals.db"
    db._engine = create_async_engine(db_url, echo=False, connect_args={"timeout": 30})
    configure_sqlite_engine(db._engine)
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
            # B-020: WR is money-PnL based — losses must have negative pnl
            pnl = 4.0 if status == "HIT_TP" else -6.0
            await db.close_outcome(outcome.id, status, 52000.0, pnl)

        # Create signals with fingerprint B (20% WR)
        for i in range(8):
            sig = await db.save_signal(
                "BTC/USDT", "1h", "BUY", 50000.0, 48000.0, 53000.0, 5, [],
                factor_fingerprint="fingerprint_b",
            )
            outcome = await db.create_outcome(sig.id)
            status = "HIT_TP" if i < 2 else "HIT_SL"
            pnl = 4.0 if status == "HIT_TP" else -6.0
            await db.close_outcome(outcome.id, status, 52000.0, pnl)

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


class TestSaveSignalWithRisk:
    """v2.1 B-019 — atomic admission: Signal + OPEN outcome + cooldown."""

    @pytest.mark.asyncio
    async def test_admission_success(self, setup_db):
        await db.init()
        sig, reason = await db.save_signal_with_risk(
            risk_pct=1.0,
            symbol="BTC/USDT",
            timeframe="1h",
            signal_type="BUY",
            close_price=50000.0,
            sl=49000.0,
            tp=53000.0,
            score=5,
            reasons=["test"],
        )
        assert sig is not None and reason is None
        stats = await db.get_outcome_stats()
        assert stats["open"] == 1

    @pytest.mark.asyncio
    async def test_admission_blocks_cooldown(self, setup_db):
        await db.init()
        sig1, _ = await db.save_signal_with_risk(
            risk_pct=1.0,
            symbol="BTC/USDT",
            timeframe="1h",
            signal_type="BUY",
            close_price=50000.0,
            sl=49000.0,
            tp=53000.0,
            score=5,
            reasons=["a"],
        )
        assert sig1 is not None
        sig2, reason = await db.save_signal_with_risk(
            risk_pct=1.0,
            symbol="BTC/USDT",
            timeframe="1h",
            signal_type="BUY",
            close_price=50000.0,
            sl=49000.0,
            tp=53000.0,
            score=5,
            reasons=["b"],
        )
        assert sig2 is None
        assert reason and reason.startswith("cooldown")

    @pytest.mark.asyncio
    async def test_admission_blocks_risk_budget(self, setup_db):
        await db.init()
        # Pre-fill OPEN outcomes up to risk budget.
        # Patch storage.database.config (not config.settings) — test_config's
        # importlib.reload leaves database bound to the pre-reload singleton.
        import storage.database as _dbmod
        _cfg = _dbmod.config
        _orig = _cfg.max_portfolio_risk_pct
        object.__setattr__(_cfg, "max_portfolio_risk_pct", 1.0)
        try:
            # Force one open outcome without cooldown interference: different symbols
            sig0, _ = await db.save_signal_with_risk(
                risk_pct=0.8,
                symbol="ETH/USDT",
                timeframe="4h",
                signal_type="BUY",
                close_price=3000.0,
                sl=2900.0,
                tp=3300.0,
                score=5,
                reasons=["seed"],
            )
            assert sig0 is not None
            sig, reason = await db.save_signal_with_risk(
                risk_pct=0.5,
                symbol="BTC/USDT",
                timeframe="1h",
                signal_type="BUY",
                close_price=50000.0,
                sl=49000.0,
                tp=53000.0,
                score=5,
                reasons=["over"],
            )
            assert sig is None
            assert reason and reason.startswith("risk_budget")
        finally:
            object.__setattr__(_cfg, "max_portfolio_risk_pct", _orig)

    @pytest.mark.asyncio
    async def test_admission_rejects_invalid_risk(self, setup_db):
        await db.init()
        sig, reason = await db.save_signal_with_risk(
            risk_pct=float("nan"),
            symbol="BTC/USDT",
            timeframe="1h",
            signal_type="BUY",
            close_price=50000.0,
            sl=49000.0,
            tp=53000.0,
            score=5,
            reasons=["x"],
        )
        assert sig is None
        assert reason == "invalid_new_risk"


class TestSQLiteLockHandling:
    """Guards for the "database is locked" fix: WAL + busy_timeout + retry."""

    @pytest.mark.asyncio
    async def test_wal_and_pragmas_applied(self, setup_db):
        await db.init()
        async with db._engine.connect() as conn:
            journal = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
            busy = (await conn.execute(text("PRAGMA busy_timeout"))).scalar()
            synchronous = (await conn.execute(text("PRAGMA synchronous"))).scalar()
        assert journal == "wal"
        assert busy == 30000
        assert synchronous == 1  # NORMAL

    @pytest.mark.asyncio
    async def test_concurrent_writes_do_not_fail_with_locked(self, setup_db):
        await db.init()

        async def write_trace(i: int):
            return await db.save_decision_trace(
                f"SYM{i % 5}/USDT",
                "1h",
                gate_results={"cooldown": True, "pattern_engine": False},
                final_stage="pattern_engine",
                blocked_reason="unit-test",
                signal_generated=False,
            )

        async def write_audit(i: int):
            return await db.create_audit_entry(
                symbol=f"SYM{i % 5}/USDT",
                timeframe="1h",
                ts_event=datetime.now(timezone.utc),
                config_version=1,
                stage="pattern_engine",
                reason_code="unit_test",
                passed=False,
            )

        tasks = [write_trace(i) for i in range(25)]
        tasks += [write_audit(i) for i in range(25)]
        # Any surviving SQLITE_BUSY raises out of gather and fails the test.
        await asyncio.gather(*tasks)

        async with db._session_factory() as session:
            n_traces = (await session.execute(
                select(func.count()).select_from(DecisionTrace)
            )).scalar_one()
            n_audit = (await session.execute(
                select(func.count()).select_from(SignalAuditLog)
            )).scalar_one()
        assert n_traces == 25
        assert n_audit == 25

    @pytest.mark.asyncio
    async def test_retry_recovers_from_transient_lock(self, monkeypatch):
        import storage.database as dbmod
        monkeypatch.setattr(dbmod, "DB_LOCK_RETRY_ATTEMPTS", 4)
        monkeypatch.setattr(dbmod, "DB_LOCK_RETRY_BASE_DELAY", 0.01)
        calls = {"n": 0}

        @dbmod.retry_on_db_lock
        async def flaky_write():
            calls["n"] += 1
            if calls["n"] < 3:
                raise OperationalError(
                    "INSERT INTO t VALUES (?)",
                    {},
                    sqlite3.OperationalError("database is locked"),
                )
            return "ok"

        assert await flaky_write() == "ok"
        assert calls["n"] == 3

    @pytest.mark.asyncio
    async def test_retry_does_not_swallow_other_errors(self, monkeypatch):
        import storage.database as dbmod
        monkeypatch.setattr(dbmod, "DB_LOCK_RETRY_BASE_DELAY", 0.01)
        calls = {"n": 0}

        @dbmod.retry_on_db_lock
        async def hard_failure():
            calls["n"] += 1
            raise OperationalError(
                "SELECT 1", {}, sqlite3.OperationalError("no such table: nope")
            )

        with pytest.raises(OperationalError):
            await hard_failure()
        assert calls["n"] == 1
