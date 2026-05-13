# 2.1 main.py — Точка входа

**Что делает:**
- Добавляет корень проекта в `sys.path`
- Импортирует `config.logger` (инициализирует loguru: консоль + файл с ротацией 10MB)
- Инициализирует БД (`db.init()` — создаёт таблицы)
- Подключается к бирже (`exchange_client.connect()`)
- Создаёт `Application` от python-telegram-bot, регистрирует обработчики
- Настраивает и запускает `TaskScheduler` (APScheduler)
- Запускает polling (с `drop_pending_updates=True`)
- Логирует стартовый блок: имя биржи, символы, таймфреймы, `confirm_timeframe`, канал (`main.py:48-53`)
- Держит event loop через бесконечный `while True: await asyncio.sleep(3600)` (`main.py:65-66`)
- Обрабатывает shutdown: останавливает scheduler, exchange, бота, app
  (для updater проверка `app.updater.running` перед `stop()` — `main.py:77`)

**При каких условиях:**
- Всегда при запуске `python main.py`
- Должен быть `TELEGRAM_BOT_TOKEN` в .env — иначе `sys.exit(1)`
- При `KeyboardInterrupt` / `SystemExit` — graceful shutdown
- При любой другой ошибке — `send_error_alert()` админам
