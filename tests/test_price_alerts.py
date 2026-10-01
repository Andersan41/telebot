"""tests/test_price_alerts.py — веб-алерты на цену.

Покрытие:
- CRUD в price_alerts (tmp SQLite)
- логика срабатывания _is_triggered (ABOVE / BELOW / ANY / гэп)
- check_price_alerts: триггер, one-shot гашение, ошибка отправки, cooldown
- API /api/price-alerts (GET/POST/DELETE) через aiohttp TestClient
- send_price_alert: админам, HTML-экранирование
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _DbProxy:
    """Всегда текущий синглтон storage.database.db.

    test_architecture.py::test_db_singleton удаляет storage.database из
    sys.modules и импортирует его заново — появляется НОВЫЙ Database().
    Статический `from storage.database import db` на уровне модуля (import в
    момент collection) отвязался бы от него, и тесты ходили бы в чужую БД.
    """

    def __getattr__(self, name):
        from storage.database import db as _db
        return getattr(_db, name)


db = _DbProxy()


@pytest.fixture(autouse=True)
async def setup_db(tmp_path):
    import storage.database as sdb
    db_url = f"sqlite+aiosqlite:///{tmp_path}/alerts.db"
    sdb.db._engine = create_async_engine(db_url, echo=False, connect_args={"timeout": 30})
    sdb.configure_sqlite_engine(sdb.db._engine)
    sdb.db._session_factory = sessionmaker(
        sdb.db._engine, class_=AsyncSession, expire_on_commit=False
    )
    async with sdb.db._engine.begin() as conn:
        await conn.run_sync(sdb.Base.metadata.create_all)
    yield
    await sdb.db._engine.dispose()


# ─── CRUD ──────────────────────────────────────────────────────────────────

class TestCRUD:
    @pytest.mark.asyncio
    async def test_add_and_get(self):
        alert_id = await db.add_price_alert(
            "BTC/USDT", 100000.0, "ABOVE", prev_price=95000.0
        )
        assert alert_id > 0
        alerts = await db.get_price_alerts(active_only=True)
        assert len(alerts) == 1
        a = alerts[0]
        assert a.symbol == "BTC/USDT"
        assert a.price == 100000.0
        assert a.direction == "ABOVE"
        assert a.prev_price == 95000.0
        assert a.active is True
        assert a.triggered_at is None

    @pytest.mark.asyncio
    async def test_trigger_one_shot(self):
        alert_id = await db.add_price_alert("ETH/USDT", 4000.0, "BELOW")
        await db.trigger_price_alert(alert_id, 3980.0)

        active = await db.get_price_alerts(active_only=True)
        assert active == []

        all_rows = await db.get_price_alerts(active_only=False)
        assert len(all_rows) == 1
        a = all_rows[0]
        assert a.active is False
        assert a.triggered_price == 3980.0
        assert a.triggered_at is not None

    @pytest.mark.asyncio
    async def test_delete(self):
        alert_id = await db.add_price_alert("SOL/USDT", 200.0, "ANY", prev_price=190.0)
        assert await db.delete_price_alert(alert_id) is True
        assert await db.delete_price_alert(alert_id) is False
        assert await db.get_price_alerts(active_only=False) == []

    @pytest.mark.asyncio
    async def test_update_prev(self):
        alert_id = await db.add_price_alert("BTC/USDT", 100000.0, "ANY", prev_price=95000.0)
        await db.update_price_alert_prev(alert_id, 99000.0)
        (a,) = await db.get_price_alerts()
        assert a.prev_price == 99000.0
        assert a.active is True  # касание prev не гасит алерт

    @pytest.mark.asyncio
    async def test_active_only_filtering(self):
        id1 = await db.add_price_alert("BTC/USDT", 1.0, "ABOVE")
        await db.add_price_alert("ETH/USDT", 2.0, "BELOW")
        await db.trigger_price_alert(id1, 1.5)
        active = await db.get_price_alerts(active_only=True)
        assert [a.symbol for a in active] == ["ETH/USDT"]


# ─── Логика срабатывания ───────────────────────────────────────────────────

class TestTriggerLogic:
    @staticmethod
    def _alert(direction, price, prev_price=95.0):
        return SimpleNamespace(direction=direction, price=price, prev_price=prev_price)

    def test_above(self):
        from scheduler.price_alerts import _is_triggered
        assert not _is_triggered(self._alert("ABOVE", 100), 99.99)
        assert _is_triggered(self._alert("ABOVE", 100), 100.0)
        assert _is_triggered(self._alert("ABOVE", 100), 101.0)

    def test_below(self):
        from scheduler.price_alerts import _is_triggered
        assert not _is_triggered(self._alert("BELOW", 100), 100.01)
        assert _is_triggered(self._alert("BELOW", 100), 100.0)
        assert _is_triggered(self._alert("BELOW", 100), 99.0)

    def test_any_exact_touch(self):
        from scheduler.price_alerts import _is_triggered
        assert _is_triggered(self._alert("ANY", 100), 100.0)

    def test_any_crossing_up(self):
        from scheduler.price_alerts import _is_triggered
        assert not _is_triggered(self._alert("ANY", 100), 99.0)  # ещё не пересёк
        assert _is_triggered(self._alert("ANY", 100), 105.0)      # пересёк вверх

    def test_any_crossing_down(self):
        from scheduler.price_alerts import _is_triggered
        a = self._alert("ANY", 100, prev_price=105.0)
        assert _is_triggered(a, 99.0)  # пробил уровень вниз

    def test_any_gap_over_level(self):
        from scheduler.price_alerts import _is_triggered
        # тик с 99 сразу в 101 — уровень пересечён, хотя 100 не видели
        assert _is_triggered(self._alert("ANY", 100), 101.0)

    def test_any_same_side_no_trigger(self):
        from scheduler.price_alerts import _is_triggered
        assert not _is_triggered(self._alert("ANY", 100, prev_price=105.0), 110.0)
        assert not _is_triggered(self._alert("ANY", 100, prev_price=95.0), 90.0)

    def test_any_no_prev(self):
        from scheduler.price_alerts import _is_triggered
        a = self._alert("ANY", 100, prev_price=None)
        assert not _is_triggered(a, 99.0)
        assert _is_triggered(a, 100.0)  # точное касание и без prev


# ─── Фоновый цикл check_price_alerts ───────────────────────────────────────

@pytest.fixture()
def pa_env(monkeypatch):
    """Изолированный окруж для scheduler.price_alerts."""
    import storage.database as sdb
    import scheduler.price_alerts as pa

    # перебиндить на ТЕКУЩИЙ синглтон (см. _DbProxy — test_architecture
    # может переимпортировать storage.database)
    monkeypatch.setattr(pa, "db", sdb.db)
    monkeypatch.setattr(pa, "_fail_counts", {})
    monkeypatch.setattr(pa, "_cooldowns", {})
    stub = SimpleNamespace(
        _exchange=object(),  # не None — иначе fetch пропускается
        fetch_ticker_price=AsyncMock(return_value=105.0),
    )
    monkeypatch.setattr(pa, "exchange_client", stub)
    notify = AsyncMock()
    monkeypatch.setattr(pa, "send_price_alert", notify)
    return SimpleNamespace(pa=pa, exchange=stub, notify=notify)


class TestCheckPriceAlerts:
    @pytest.mark.asyncio
    async def test_above_triggers_and_deactivates(self, pa_env):
        alert_id = await db.add_price_alert("BTC/USDT", 100.0, "ABOVE", prev_price=95.0)
        n = await pa_env.pa.check_price_alerts()
        assert n == 1
        pa_env.notify.assert_awaited_once_with("BTC/USDT", 100.0, 105.0, "ABOVE")

        (a,) = await db.get_price_alerts(active_only=False)
        assert a.id == alert_id
        assert a.active is False
        assert a.triggered_price == 105.0
        assert await db.get_price_alerts(active_only=True) == []

    @pytest.mark.asyncio
    async def test_above_not_triggered(self, pa_env):
        await db.add_price_alert("BTC/USDT", 100.0, "ABOVE", prev_price=95.0)
        pa_env.exchange.fetch_ticker_price.return_value = 95.0
        n = await pa_env.pa.check_price_alerts()
        assert n == 0
        pa_env.notify.assert_not_awaited()
        # ABOVE: prev не обновляется (нужен только для ANY)
        (a,) = await db.get_price_alerts()
        assert a.prev_price == 95.0
        assert a.active is True

    @pytest.mark.asyncio
    async def test_any_updates_prev_when_quiet(self, pa_env):
        await db.add_price_alert("BTC/USDT", 100.0, "ANY", prev_price=95.0)
        pa_env.exchange.fetch_ticker_price.return_value = 97.0
        n = await pa_env.pa.check_price_alerts()
        assert n == 0
        (a,) = await db.get_price_alerts()
        assert a.prev_price == 97.0
        assert a.active is True

    @pytest.mark.asyncio
    async def test_notify_failure_keeps_alert_active(self, pa_env):
        await db.add_price_alert("BTC/USDT", 100.0, "ABOVE", prev_price=95.0)
        pa_env.notify.side_effect = RuntimeError("telegram down")
        n = await pa_env.pa.check_price_alerts()
        assert n == 0
        (a,) = await db.get_price_alerts()
        assert a.active is True  # повтор на следующем тике

    @pytest.mark.asyncio
    async def test_fetch_failures_then_cooldown(self, pa_env):
        await db.add_price_alert("BTC/USDT", 100.0, "ABOVE", prev_price=95.0)
        pa_env.exchange.fetch_ticker_price.return_value = None

        for _ in range(3):
            n = await pa_env.pa.check_price_alerts()
            assert n == 0
        assert pa_env.exchange.fetch_ticker_price.await_count == 3
        assert "BTC/USDT" in pa_env.pa._cooldowns

        # в cooldown fetch больше не дёргается
        n = await pa_env.pa.check_price_alerts()
        assert n == 0
        assert pa_env.exchange.fetch_ticker_price.await_count == 3

    @pytest.mark.asyncio
    async def test_no_active_alerts_no_fetch(self, pa_env):
        n = await pa_env.pa.check_price_alerts()
        assert n == 0
        pa_env.exchange.fetch_ticker_price.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_shared_fetch_for_same_symbol(self, pa_env):
        await db.add_price_alert("BTC/USDT", 100.0, "ABOVE", prev_price=95.0)
        await db.add_price_alert("BTC/USDT", 90.0, "BELOW", prev_price=95.0)
        pa_env.exchange.fetch_ticker_price.return_value = 96.0
        n = await pa_env.pa.check_price_alerts()
        assert n == 0  # 96: не >= 100 и не <= 90
        assert pa_env.exchange.fetch_ticker_price.await_count == 1  # 1 тик на символ


# ─── API ───────────────────────────────────────────────────────────────────

@pytest.fixture()
async def client(monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer
    from data.exchange_client import exchange_client
    from web.server import create_app

    monkeypatch.setattr(
        exchange_client, "is_symbol_available",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        exchange_client, "fetch_ticker_price",
        AsyncMock(return_value=95000.0),
    )
    tc = TestClient(TestServer(create_app()))
    await tc.start_server()
    yield tc
    await tc.close()


class TestApi:
    @pytest.mark.asyncio
    async def test_get_empty(self, client):
        resp = await client.get("/api/price-alerts")
        assert resp.status == 200
        data = await resp.json()
        assert data == {"alerts": []}

    @pytest.mark.asyncio
    async def test_create_above_ok(self, client):
        resp = await client.post(
            "/api/price-alerts",
            json={"symbol": "BTC", "price": 100000, "direction": "ABOVE"},
        )
        assert resp.status == 201
        data = await resp.json()
        assert data["symbol"] == "BTC/USDT"  # нормализация
        assert data["price"] == 100000.0
        assert data["direction"] == "ABOVE"
        assert data["active"] is True
        assert data["current_price"] == 95000.0
        assert data["id"] > 0

        resp2 = await client.get("/api/price-alerts")
        rows = (await resp2.json())["alerts"]
        assert len(rows) == 1
        assert rows[0]["symbol"] == "BTC/USDT"

    @pytest.mark.asyncio
    async def test_create_normalizes_symbol_variants(self, client):
        # BELOW + цена 1.0: текущая 95000 > 1, проверка стороны пройдёт
        for raw in ("btcusdt", "ETH", "eth/usdt", "  SOLUSDT  "):
            resp = await client.post(
                "/api/price-alerts",
                json={"symbol": raw, "price": 1.0, "direction": "BELOW"},
            )
            assert resp.status == 201, raw
            data = await resp.json()
            assert "/" in data["symbol"]
            assert data["symbol"] == data["symbol"].upper()
            await client.delete(f"/api/price-alerts/{data['id']}")

    @pytest.mark.asyncio
    async def test_create_bad_direction(self, client):
        resp = await client.post(
            "/api/price-alerts",
            json={"symbol": "BTC", "price": 100000, "direction": "SIDEWAYS"},
        )
        assert resp.status == 400
        assert "direction" in (await resp.json())["error"]

    @pytest.mark.asyncio
    async def test_create_bad_price(self, client):
        for price in (-5, 0, "abc", None):
            resp = await client.post(
                "/api/price-alerts",
                json={"symbol": "BTC", "price": price, "direction": "ABOVE"},
            )
            assert resp.status == 400, price

    @pytest.mark.asyncio
    async def test_create_missing_symbol(self, client):
        resp = await client.post(
            "/api/price-alerts", json={"price": 100000, "direction": "ABOVE"}
        )
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_create_unknown_symbol(self, client, monkeypatch):
        from data.exchange_client import exchange_client
        monkeypatch.setattr(
            exchange_client, "is_symbol_available", AsyncMock(return_value=False)
        )
        resp = await client.post(
            "/api/price-alerts",
            json={"symbol": "FAKE/USDT", "price": 1, "direction": "ABOVE"},
        )
        assert resp.status == 400
        assert "not available" in (await resp.json())["error"]

    @pytest.mark.asyncio
    async def test_create_above_but_price_already_there(self, client):
        resp = await client.post(
            "/api/price-alerts",
            json={"symbol": "BTC", "price": 94000, "direction": "ABOVE"},
        )
        assert resp.status == 400  # текущая 95000 >= 94000
        assert "already" in (await resp.json())["error"]

    @pytest.mark.asyncio
    async def test_create_below_but_price_already_there(self, client):
        resp = await client.post(
            "/api/price-alerts",
            json={"symbol": "BTC", "price": 96000, "direction": "BELOW"},
        )
        assert resp.status == 400  # текущая 95000 <= 96000

    @pytest.mark.asyncio
    async def test_ticker_unavailable(self, client, monkeypatch):
        from data.exchange_client import exchange_client
        monkeypatch.setattr(
            exchange_client, "fetch_ticker_price", AsyncMock(return_value=None)
        )
        resp = await client.post(
            "/api/price-alerts",
            json={"symbol": "BTC", "price": 100000, "direction": "ABOVE"},
        )
        assert resp.status == 503

    @pytest.mark.asyncio
    async def test_delete_roundtrip(self, client):
        resp = await client.post(
            "/api/price-alerts",
            json={"symbol": "BTC", "price": 100000, "direction": "ABOVE"},
        )
        alert_id = (await resp.json())["id"]

        resp = await client.delete(f"/api/price-alerts/{alert_id}")
        assert resp.status == 200
        assert (await resp.json())["deleted"] == alert_id

        resp = await client.delete(f"/api/price-alerts/{alert_id}")
        assert resp.status == 404

        resp = await client.delete("/api/price-alerts/notanumber")
        assert resp.status == 400

        resp = await client.get("/api/price-alerts")
        assert (await resp.json())["alerts"] == []


# ─── Telegram-уведомление ──────────────────────────────────────────────────

class TestSendPriceAlert:
    @pytest.fixture(autouse=True)
    def reset_bot(self):
        import bot.notifier as n
        n._bot = None
        yield
        n._bot = None

    @pytest.mark.asyncio
    async def test_sends_to_all_admins(self):
        from bot.notifier import send_price_alert
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("bot.notifier.config.telegram.admin_ids", [111, 222])
            mp.setattr("bot.notifier.config.telegram.token", "fake:token")
            mock_bot = SimpleNamespace(send_message=AsyncMock())
            mp.setattr("bot.notifier.Bot", lambda token: mock_bot)

            await send_price_alert("BTC/USDT", 100000.0, 100500.0, "ABOVE")

            assert mock_bot.send_message.await_count == 2
            text = mock_bot.send_message.call_args.kwargs["text"]
            assert "BTC/USDT" in text
            assert "100000" in text
            assert "100500" in text
            assert "рост" in text  # метка направления ABOVE
            assert mock_bot.send_message.call_args.kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_no_admins_no_send(self):
        from bot.notifier import send_price_alert
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("bot.notifier.config.telegram.admin_ids", [])
            mock_bot = SimpleNamespace(send_message=AsyncMock())
            mp.setattr("bot.notifier.Bot", lambda token: mock_bot)

            await send_price_alert("ETH/USDT", 4000.0, 3990.0, "BELOW")
            mock_bot.send_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_html_escaped(self):
        from bot.notifier import send_price_alert
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("bot.notifier.config.telegram.admin_ids", [1])
            mp.setattr("bot.notifier.config.telegram.token", "fake:token")
            mock_bot = SimpleNamespace(send_message=AsyncMock())
            mp.setattr("bot.notifier.Bot", lambda token: mock_bot)

            await send_price_alert("<BTC>", 1.0, 2.0, "ANY")
            text = mock_bot.send_message.call_args.kwargs["text"]
            assert "&lt;BTC&gt;" in text
            assert "<BTC>" not in text
