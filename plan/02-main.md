# 2.1 main.py — Точка входа

**Что делает:**
- Добавляет корень проекта в `sys.path`
- Импортирует `config.logger` (инициализирует loguru: консоль + файл с ротацией 10MB)
- Инициализирует БД (`db.init()` — создаёт таблицы)
- Подключается к бирже (`exchange_client.connect()`)
- Создаёт `Application` от python-telegram-bot, регистрирует обработчики
- Настраивает и запускает `TaskScheduler` (APScheduler)
- Запускает polling (с `drop_pending_updates=True`)
- Держит event loop через `asyncio.sleep(3600)`
- Обрабатывает shutdown: останавливает scheduler, exchange, бота, app

**При каких условиях:**
- Всегда при запуске `python main.py`
- Должен быть `TELEGRAM_BOT_TOKEN` в .env — иначе `sys.exit(1)`
- При `KeyboardInterrupt` / `SystemExit` — graceful shutdown
- При любой другой ошибке — `send_error_alert()` админам
