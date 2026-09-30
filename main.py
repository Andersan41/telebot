"""
main.py — Точка входа. Запускает бота и планировщик.
"""
import asyncio
import sys
import os
import atexit

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Lock-файл для защиты от повторного запуска.
# Переопределяемый через env — чтобы тесты не трогали боевой файл.
LOCK_FILE = os.environ.get(
    "TRADING_BOT_LOCK_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".trading_bot.lock"),
)

_lock_handle = None

# Лок на байт с большим смещением: вне содержимого файла, поэтому PID в
# начале файла читается любым процессом, а сам лок всё равно эксклюзивен.
_LOCK_OFFSET = 1024


def _lock_exclusive(fh):
    """Byte-range lock: удерживается ядром, снимается при смерти процесса."""
    if os.name == "nt":
        import msvcrt
        fh.seek(_LOCK_OFFSET)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fh):
    if os.name == "nt":
        import msvcrt
        fh.seek(_LOCK_OFFSET)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def acquire_lock(lock_file=None):
    """Один экземпляр бота.

    Решает не PID в файле, а блокировка ОС: устаревший файл (мёртвый PID,
    PID из git-истории, PID переиспользованный другим процессом) не мешает
    старту. Старая схема `os.kill(pid, 0)` на Windows ломалась двояко:
    PermissionError от OpenProcess трактовался как «процесс мёртв»
    (пропуск второго экземпляра), а сам файл лежит в git и исчезал при
    любом checkout/запуске тестов — после чего guard молча пропускал
    всё. Файл при выходе не удаляется: unlink создал бы гонку inode'ов
    между завершающимся и стартующим процессом.
    """
    global _lock_handle
    path = lock_file or LOCK_FILE
    fh = open(path, "a+")
    try:
        fh.seek(0)
        holder = fh.read().strip() or "unknown"
    except OSError:
        holder = "unknown"
    try:
        fh.seek(0)
        _lock_exclusive(fh)
    except OSError:
        fh.close()
        print(f"Bot already running (PID {holder}). Exiting.")
        sys.exit(1)
    try:
        # свой же лок процесс не блокирует
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
    except OSError:
        pass
    _lock_handle = fh
    atexit.register(release_lock)


def release_lock():
    global _lock_handle
    if _lock_handle is None:
        return
    try:
        _unlock(_lock_handle)
    except OSError:
        pass
    try:
        _lock_handle.close()
    except OSError:
        pass
    _lock_handle = None

from loguru import logger
import config.logger  # noqa — инициализирует логгер

# T3.4 — Prometheus metrics HTTP-сервер (opt-in через METRICS_ENABLED=true)
from monitoring.metrics import _start_metrics_server
_start_metrics_server()

from telegram.ext import Application
from telegram.error import NetworkError, TimedOut
import httpx
from config.settings import config, refresh_runtime_symbols
from data.exchange_client import exchange_client
from storage.database import db
from bot.handlers import register_handlers
from bot.notifier import send_signal, send_error_alert
from scheduler.tasks import TaskScheduler
from context.fetcher import context_fetcher
from web.server import start_web_server


def _is_retryable_start_error(e: Exception) -> bool:
    """Сетевые/транспортные сбои, при которых имеет смысл перезапускать старт.

    Ключевой случай — httpx.ConnectError [SSL: WRONG_VERSION_NUMBER]:
    TLS-хендшейк упёрся в plain-HTTP ответ (обход/блокировка TLS к
    api.telegram.org). Раньше такой сбой рос в Fatal error и гасил весь
    бота, хотя через минуту сеть была исправна (28.09.23:59 vs 29.09.01:35).
    Conflict — зависшая polling-сессия на стороне Telegram, лечится тем же
    способом, что и раньше.
    """
    if isinstance(
        e,
        (
            httpx.ConnectError,
            httpx.ReadError,
            httpx.WriteError,
            httpx.RemoteProtocolError,
            httpx.TimeoutException,
            ConnectionError,
            TimeoutError,
            OSError,
            NetworkError,
            TimedOut,
        ),
    ):
        return True
    return "Conflict" in str(e)


async def _start_telegram(app, attempts: int = 5) -> None:
    """initialize() + start() + start_polling() с повторами.

    Ошибки инициализации (get_me, старт polling) теперь не роняют процесс
    с первого раза: до 5 попыток с растущей паузой, между попытками
    Application приводится в исходное состояние (updater.stop -> stop ->
    shutdown), PTB 20.7 идемпотентно переинициализируется.
    """
    for attempt in range(1, attempts + 1):
        try:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            return
        except Exception as e:
            if not _is_retryable_start_error(e) or attempt == attempts:
                raise
            conflict = "Conflict" in str(e)
            delay = attempt * 5 if conflict else min(30, 4 * attempt)
            logger.warning(
                f"Telegram start failed (attempt {attempt}/{attempts}): "
                f"{type(e).__name__}: {e} — retrying in {delay}s"
            )
            for cleanup in (app.updater.stop, app.stop, app.shutdown):
                try:
                    await cleanup()
                except Exception:
                    pass
            await asyncio.sleep(delay)


async def main():
    acquire_lock()

    logger.info("=" * 60)
    logger.info("  Trading Signal Bot starting...")
    logger.info("=" * 60)

    # Проверяем обязательные переменные
    if not config.telegram.token:
        logger.error("TELEGRAM_BOT_TOKEN is not set! Check .env file.")
        sys.exit(1)

    # Инициализируем БД
    await db.init()
    await refresh_runtime_symbols()
    from config.settings import reload_filter_toggles
    await reload_filter_toggles()

    # Подключаемся к бирже
    await exchange_client.connect()

    # Запускаем веб-сервер (дашборд)
    web_runner = None
    if config.web.enabled:
        try:
            web_runner = await start_web_server()
        except Exception as e:
            logger.warning(f"Web server failed to start: {e}")

    # Создаём Telegram Application с устойчивой к сетевым ошибкам конфигурацией
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )
    app = Application.builder().token(config.telegram.token).request(request).build()

    # T3.3 — мониторинг ошибок хендлеров
    from telegram.error import NetworkError, TimedOut

    async def _handle_app_error(_, context):
        if isinstance(context.error, (NetworkError, TimedOut)):
            logger.warning(f"Telegram network issue: {context.error}")
            return
        logger.error(f"Unhandled app error: {context.error}")

    app.add_error_handler(_handle_app_error)
    register_handlers(app)

    # T3.2 — Telegram error sink для ERROR+ логов
    from config.logger import setup_error_sink
    setup_error_sink(app.bot)

    # Настраиваем планировщик
    scheduler = TaskScheduler(notify_callback=send_signal)
    scheduler.setup()
    scheduler.start()

    logger.info(f"Bot configured:")
    logger.info(f"  Exchange: {config.exchange.name}")
    logger.info(f"  Symbols: {', '.join(config.trading.symbols)}")
    logger.info(f"  Timeframes: {', '.join(config.trading.primary_timeframes)}")
    logger.info(f"  Confirmation TF: {config.trading.confirm_timeframe}")
    logger.info(f"  Channel: {config.telegram.channel_id}")
    if config.web.enabled:
        logger.info(f"  Web Dashboard: http://{config.web.host}:{config.web.port}")

    # F1: запустить фоновый трекинг outcome'ов
    from scheduler.outcome_tracker import outcome_tracker_loop
    asyncio.create_task(outcome_tracker_loop())

    try:
        # Запускаем бота в режиме polling
        logger.info("Starting Telegram bot (polling mode)...")
        # повторы на сетевые сбои (httpx.ConnectError/Conflict) — см.
        # _start_telegram: раньше одиночный сбой рос в Fatal error
        await _start_telegram(app)

        logger.info("✅ Bot is running. Press Ctrl+C to stop.")

        # Держим event loop живым
        while True:
            await asyncio.sleep(3600)

    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown signal received")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        await send_error_alert(str(e))
    finally:
        logger.info("Shutting down...")
        scheduler.stop()
        await exchange_client.close()
        await context_fetcher.close()
        if web_runner:
            await web_runner.cleanup()
        if app.updater and app.updater.running:
            await app.updater.stop()
        if app.running:
            await app.stop()
        await app.shutdown()
        release_lock()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    # FIX N3: Windows asyncio compatibility
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        logger.error(f"Fatal: {e}", exc_info=True)
        sys.exit(1)
