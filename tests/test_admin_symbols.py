import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class _MockDB:
    """Заглушка, заменяющая Database с in-memory хранилищем."""
    def __init__(self, store):
        self._store = store

    async def get_setting(self, key: str, default: str = "") -> str:
        return self._store.get(key, default)

    async def set_setting(self, key: str, value: str) -> None:
        self._store[key] = value

    async def get_dynamic_symbols(self):
        val = self._store.get("dynamic_symbols", "")
        if not val:
            return None
        return [s.strip() for s in val.split(",") if s.strip()]

    async def set_dynamic_symbols(self, symbols: list[str]) -> None:
        await self.set_setting("dynamic_symbols", ",".join(symbols))

    async def get_disabled_symbols(self):
        val = self._store.get("disabled_symbols", "")
        if not val:
            return None
        return [s.strip() for s in val.split(",") if s.strip()]

    async def set_disabled_symbols(self, symbols: list[str]) -> None:
        await self.set_setting("disabled_symbols", ",".join(symbols))


@pytest.fixture
def mock_db(monkeypatch):
    """Подменяет db на in-memory хранилище.
    Патчит storage.database.db (для TestDatabaseDynamicSymbols и refresh_runtime_symbols).
    """
    store: dict[str, str] = {}
    mock_obj = _MockDB(store)

    # Патчим storage.database.db (для TestDatabaseDynamicSymbols и refresh_runtime_symbols)
    monkeypatch.setattr("storage.database.db", mock_obj)
    return store


@pytest.fixture
def mock_db_obj(monkeypatch):
    """Возвращает сам _MockDB объект для вызова методов."""
    store: dict[str, str] = {}
    mock_obj = _MockDB(store)
    monkeypatch.setattr("bot.admin.db", mock_obj)
    monkeypatch.setattr("storage.database.db", mock_obj)
    monkeypatch.setattr("scheduler.scanner.db", mock_obj)
    return mock_obj


@pytest.fixture
def mock_admin_user():
    user = MagicMock()
    user.id = 111111
    return user


@pytest.fixture
def mock_regular_user():
    user = MagicMock()
    user.id = 999999
    return user


@pytest.fixture
def mock_update(mock_admin_user):
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    msg.effective_user = mock_admin_user
    update = MagicMock()
    update.message = msg
    update.effective_user = mock_admin_user
    update.callback_query = None
    return update


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.args = []
    return ctx


class TestDatabaseDynamicSymbols:
    @pytest.mark.asyncio
    async def test_get_dynamic_symbols_empty(self, mock_db):
        from storage.database import db
        result = await db.get_dynamic_symbols()
        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get_dynamic_symbols(self, mock_db):
        from storage.database import db
        await db.set_dynamic_symbols(["BTC/USDT", "ETH/USDT"])
        result = await db.get_dynamic_symbols()
        assert result == ["BTC/USDT", "ETH/USDT"]

    @pytest.mark.asyncio
    async def test_set_dynamic_symbols_single(self, mock_db):
        from storage.database import db
        await db.set_dynamic_symbols(["SOL/USDT"])
        result = await db.get_dynamic_symbols()
        assert result == ["SOL/USDT"]

    @pytest.mark.asyncio
    async def test_set_dynamic_symbols_overwrite(self, mock_db):
        from storage.database import db
        await db.set_dynamic_symbols(["BTC/USDT"])
        await db.set_dynamic_symbols(["ETH/USDT", "SOL/USDT"])
        result = await db.get_dynamic_symbols()
        assert result == ["ETH/USDT", "SOL/USDT"]


class TestRuntimeSymbolsCache:
    @pytest.fixture(autouse=True)
    def _reset_cache(self, monkeypatch):
        """Сброс кэша перед каждым тестом."""
        import config.settings as settings
        settings._runtime_symbols_cache = None
        yield
        settings._runtime_symbols_cache = None

    @pytest.mark.asyncio
    async def test_get_active_symbols_fallback_to_env(self, mock_db, monkeypatch):
        """Когда dynamic_symbols не задан — используется env SYMBOLS."""
        import config.settings as settings
        import importlib
        monkeypatch.setenv("SYMBOLS", "BTC/USDT,ETH/USDT")
        importlib.reload(settings)

        result = settings.get_active_symbols()
        assert result == ["BTC/USDT", "ETH/USDT"]

    @pytest.mark.asyncio
    async def test_refresh_merges_dynamic_with_env(self, mock_db, monkeypatch):
        """Когда dynamic_symbols в БД — env + dynamic."""
        import config.settings as settings
        import importlib
        monkeypatch.setenv("SYMBOLS", "BTC/USDT,ETH/USDT")
        importlib.reload(settings)

        mock_db["dynamic_symbols"] = "SOL/USDT,DOGE/USDT"
        await settings.refresh_runtime_symbols()

        result = settings.get_active_symbols()
        assert result == ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT"]

    @pytest.mark.asyncio
    async def test_refresh_none_fallback(self, mock_db, monkeypatch):
        """Когда в БД пусто — fallback на env."""
        import config.settings as settings
        import importlib
        monkeypatch.setenv("SYMBOLS", "BTC/USDT")
        importlib.reload(settings)

        await settings.refresh_runtime_symbols()
        result = settings.get_active_symbols()
        assert result == ["BTC/USDT"]

    @pytest.mark.asyncio
    async def test_empty_db_returns_env_list(self, mock_db, monkeypatch):
        """Пустая БД (без dynamic_symbols и disabled_symbols) возвращает полный список из .env."""
        import config.settings as settings
        import importlib
        monkeypatch.setenv("SYMBOLS", "BTC/USDT,ETH/USDT,SOL/USDT,DOGE/USDT")
        importlib.reload(settings)

        # Убедимся что в store пусто
        assert "dynamic_symbols" not in mock_db
        assert "disabled_symbols" not in mock_db

        await settings.refresh_runtime_symbols()
        result = settings.get_active_symbols()
        assert result == ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT"]




class TestAdminCommands:
    """Тесты команд управления символами.

    Новая логика: dynamic_symbols хранит только ДОБАВЛЕННЫЕ символы.
    Итоговый список = env SYMBOLS + dynamic.
    """

    @pytest.fixture(autouse=True)
    def _reload_modules(self, monkeypatch):
        """Перезагрузка config.settings и bot.admin после каждого теста."""
        import importlib
        import config.settings as settings
        importlib.reload(settings)
        if "bot.admin" in sys.modules:
            import bot.admin as admin_mod
            importlib.reload(admin_mod)
        yield
        importlib.reload(settings)
        if "bot.admin" in sys.modules:
            import bot.admin as admin_mod
            importlib.reload(admin_mod)

    def _setup_admin(self, monkeypatch):
        """Настройка админа для тестов команд. Патчит config.settings.config."""
        import config.settings as settings
        settings.config.telegram.admin_ids = [111111]

    @pytest.mark.asyncio
    async def test_addsymbol_success(self, mock_update, mock_context, mock_db_obj, monkeypatch):
        import config.settings as settings
        import bot.admin as admin_mod
        import importlib
        monkeypatch.setenv("SYMBOLS", "BTC/USDT,ETH/USDT")
        importlib.reload(settings)
        importlib.reload(admin_mod)
        self._setup_admin(monkeypatch)

        mock_context.args = ["DOGE/USDT"]
        from bot.admin import addsymbol_command
        await addsymbol_command(mock_update, mock_context)

        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "Добавлено" in call_args or "\u2705" in call_args
        dynamic = await mock_db_obj.get_dynamic_symbols() or []
        assert "DOGE/USDT" in dynamic

    @pytest.mark.asyncio
    async def test_addsymbol_already_exists_in_env(self, mock_update, mock_context, mock_db_obj, monkeypatch):
        import config.settings as settings
        import bot.admin as admin_mod
        import importlib
        monkeypatch.setenv("SYMBOLS", "BTC/USDT,ETH/USDT")
        importlib.reload(settings)
        importlib.reload(admin_mod)
        self._setup_admin(monkeypatch)

        mock_context.args = ["BTC/USDT"]
        from bot.admin import addsymbol_command
        await addsymbol_command(mock_update, mock_context)

        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "Уже" in call_args

    @pytest.mark.asyncio
    async def test_addsymbol_already_exists_in_dynamic(self, mock_update, mock_context, mock_db_obj, monkeypatch):
        import config.settings as settings
        import bot.admin as admin_mod
        import importlib
        monkeypatch.setenv("SYMBOLS", "BTC/USDT,ETH/USDT")
        importlib.reload(settings)
        importlib.reload(admin_mod)
        self._setup_admin(monkeypatch)
        await mock_db_obj.set_dynamic_symbols(["DOGE/USDT"])
        await settings.refresh_runtime_symbols()

        mock_context.args = ["DOGE/USDT"]
        from bot.admin import addsymbol_command
        await addsymbol_command(mock_update, mock_context)

        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "Уже" in call_args

    @pytest.mark.asyncio
    async def test_addsymbol_no_slash(self, mock_update, mock_context, mock_db_obj, monkeypatch):
        import config.settings as settings
        import bot.admin as admin_mod
        import importlib
        monkeypatch.setenv("SYMBOLS", "BTC/USDT")
        importlib.reload(settings)
        importlib.reload(admin_mod)
        self._setup_admin(monkeypatch)

        mock_context.args = ["SOL"]
        from bot.admin import addsymbol_command
        await addsymbol_command(mock_update, mock_context)

        dynamic = await mock_db_obj.get_dynamic_symbols() or []
        assert "SOL/USDT" in dynamic

    @pytest.mark.asyncio
    async def test_addsymbol_no_args(self, mock_update, mock_context, mock_db_obj, monkeypatch):
        import config.settings as settings
        import bot.admin as admin_mod
        import importlib
        importlib.reload(settings)
        importlib.reload(admin_mod)
        self._setup_admin(monkeypatch)
        mock_context.args = []
        from bot.admin import addsymbol_command
        await addsymbol_command(mock_update, mock_context)
        mock_update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_removesymbol_success(self, mock_update, mock_context, mock_db_obj, monkeypatch):
        import config.settings as settings
        import bot.admin as admin_mod
        import importlib
        monkeypatch.setenv("SYMBOLS", "BTC/USDT,ETH/USDT")
        importlib.reload(settings)
        importlib.reload(admin_mod)
        self._setup_admin(monkeypatch)
        await mock_db_obj.set_dynamic_symbols(["DOGE/USDT", "LINK/USDT"])
        await settings.refresh_runtime_symbols()

        mock_context.args = ["DOGE/USDT"]
        from bot.admin import removesymbol_command
        await removesymbol_command(mock_update, mock_context)

        dynamic = await mock_db_obj.get_dynamic_symbols() or []
        assert "DOGE/USDT" not in dynamic
        assert "LINK/USDT" in dynamic

    @pytest.mark.asyncio
    async def test_removesymbol_not_in_list(self, mock_update, mock_context, mock_db_obj, monkeypatch):
        import config.settings as settings
        import bot.admin as admin_mod
        import importlib
        monkeypatch.setenv("SYMBOLS", "BTC/USDT,ETH/USDT")
        importlib.reload(settings)
        importlib.reload(admin_mod)
        self._setup_admin(monkeypatch)

        mock_context.args = ["DOGE/USDT"]
        from bot.admin import removesymbol_command
        await removesymbol_command(mock_update, mock_context)

        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "Нет" in call_args or "нет" in call_args

    @pytest.mark.asyncio
    async def test_removesymbol_removes_from_dynamic(self, mock_update, mock_context, mock_db_obj, monkeypatch):
        import config.settings as settings
        import bot.admin as admin_mod
        import importlib
        monkeypatch.setenv("SYMBOLS", "BTC/USDT,ETH/USDT")
        importlib.reload(settings)
        importlib.reload(admin_mod)
        self._setup_admin(monkeypatch)
        await mock_db_obj.set_dynamic_symbols(["DOGE/USDT"])
        await settings.refresh_runtime_symbols()

        mock_context.args = ["DOGE/USDT"]
        from bot.admin import removesymbol_command
        await removesymbol_command(mock_update, mock_context)

        dynamic = await mock_db_obj.get_dynamic_symbols()
        assert dynamic is None or dynamic == []

    @pytest.mark.asyncio
    async def test_removesymbol_no_slash(self, mock_update, mock_context, mock_db_obj, monkeypatch):
        import config.settings as settings
        import bot.admin as admin_mod
        import importlib
        monkeypatch.setenv("SYMBOLS", "BTC/USDT,ETH/USDT")
        importlib.reload(settings)
        importlib.reload(admin_mod)
        self._setup_admin(monkeypatch)
        await mock_db_obj.set_dynamic_symbols(["SOL/USDT"])
        await settings.refresh_runtime_symbols()

        mock_context.args = ["SOL"]
        from bot.admin import removesymbol_command
        await removesymbol_command(mock_update, mock_context)

        dynamic = await mock_db_obj.get_dynamic_symbols()
        assert dynamic is None or dynamic == []

    @pytest.mark.asyncio
    async def test_listsymbols(self, mock_update, mock_context, mock_db, monkeypatch):
        from config.settings import config
        monkeypatch.setattr(config.telegram, "admin_ids", [111111])
        monkeypatch.setenv("SYMBOLS", "BTC/USDT,ETH/USDT")

        import config.settings as settings
        monkeypatch.setattr(settings, "get_active_symbols", lambda: ["BTC/USDT", "ETH/USDT"])

        mock_context.args = []
        from bot.admin import listsymbols_command
        await listsymbols_command(mock_update, mock_context)

        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "BTC/USDT" in call_args
        assert "ETH/USDT" in call_args

    @pytest.mark.asyncio
    async def test_addsymbol_denies_non_admin(self, mock_update, mock_context, mock_regular_user, monkeypatch):
        """Не-админ не может добавить символ."""
        mock_update.effective_user = mock_regular_user
        mock_update.message.effective_user = mock_regular_user
        mock_context.args = ["DOGE/USDT"]
        from bot.admin import addsymbol_command
        await addsymbol_command(mock_update, mock_context)

        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "Доступ" in call_args or "\u26d4" in call_args

    @pytest.mark.asyncio
    async def test_removesymbol_denies_non_admin(self, mock_update, mock_context, mock_regular_user, monkeypatch):
        """Не-админ не может удалить символ."""
        mock_update.effective_user = mock_regular_user
        mock_update.message.effective_user = mock_regular_user
        mock_context.args = ["BTC/USDT"]
        from bot.admin import removesymbol_command
        await removesymbol_command(mock_update, mock_context)

        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "Доступ" in call_args or "\u26d4" in call_args

    @pytest.mark.asyncio
    async def test_listsymbols_denies_non_admin(self, mock_update, mock_context, mock_regular_user, monkeypatch):
        """Не-админ не может увидеть список."""
        mock_update.effective_user = mock_regular_user
        mock_update.message.effective_user = mock_regular_user
        mock_context.args = []
        from bot.admin import listsymbols_command
        await listsymbols_command(mock_update, mock_context)

        call_args = mock_update.message.reply_text.call_args[0][0]
        assert "Доступ" in call_args or "\u26d4" in call_args
