# T3. Прочее — операционные улучшения (mini-tickets)

> **Статус**: ✅ сделано
> **Приоритет**: 🟢 low — улучшения эксплуатации, не баги.
> **Зависимости**: нет. Каждый подпункт независим, выбирай по приоритету.

Каждый подпункт — самостоятельный мини-тикет. Берись по приоритету (см. шпаргалку внизу).
Все они «low» и не требуют срочности; обоснование добавлено в каждом.

## T3.1. CI/CD pipeline (деплой)

**Цель**: после зелёных тестов автоматически собрать Docker-образ и запушить в registry.

**Файлы (новые)**:

- `.github/workflows/deploy.yml`
- `Dockerfile` (если отсутствует — проверь корень репо)

**Пошагово**:

1. Минимальный `Dockerfile` (если нет):
   ```dockerfile
   FROM python:3.11-slim
   WORKDIR /app
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY . .
   CMD ["python", "main.py"]
   ```
2. Workflow `.github/workflows/deploy.yml`:
   ```yaml
   name: deploy
   on:
     push:
       branches: [master]
     workflow_run:
       workflows: [tests]
       types: [completed]
   jobs:
     build:
       if: ${{ github.event.workflow_run.conclusion == 'success' || github.event_name == 'push' }}
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: docker/setup-buildx-action@v3
         - uses: docker/login-action@v3
           with:
             registry: ghcr.io
             username: ${{ github.actor }}
             password: ${{ secrets.GITHUB_TOKEN }}
         - uses: docker/build-push-action@v5
           with:
             context: .
             push: true
             tags: |
               ghcr.io/${{ github.repository }}:latest
               ghcr.io/${{ github.repository }}:${{ github.sha }}
   ```
3. В Settings → Packages дай repo access. Образ появится в `ghcr.io/<owner>/<repo>`.

**Edge cases**:

- В образе не должно быть `.env` / `data/*.db` — добавь `.dockerignore`:
  ```
  .env
  data/
  logs/
  .git/
  __pycache__/
  tests/
  ```

## T3.2. Мониторинг и алертинг

**Цель**: получать алёрт о падении бота, а не узнавать постфактум.

**Простой вариант** — отдельный Telegram-канал для ERROR-логов:

1. В `config/settings.py` добавь:
   ```python
   error_channel_id: str = os.getenv("TELEGRAM_ERROR_CHANNEL_ID", "")
   ```
2. В `config/logging.py` (или там, где настраивается loguru) добавь sink:
   ```python
   from loguru import logger

   if config.telegram.error_channel_id:
       async def telegram_sink(message):
           # message — Record (loguru). Берём message.record["message"]
           await application.bot.send_message(
               config.telegram.error_channel_id,
               text=f"⚠️ {message.record['message'][:3500]}",
           )
       # Уровень ERROR и выше
       logger.add(telegram_sink, level="ERROR", enqueue=True)
   ```
3. Тест: `logger.error("test alert")` — должно прилететь в канал.

**Альтернатива** — Sentry SDK: `pip install sentry-sdk`, в `main.py` до старта бота
`sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"), traces_sample_rate=0.0)`. Хватает default-конфига.

⚠️ Если выбираешь Sentry — убери Telegram-sink: получишь два уведомления на каждый ERROR.

## T3.3. Rate limiting

**Цель**: защитить бота от спама от одного пользователя.

**Файлы**: `bot/handlers.py` или `bot/middleware.py` (новый).

**Шаги**:

1. Добавь `aiolimiter>=1.1` в `requirements.txt`.
2. Создай `bot/rate_limit.py`:
   ```python
   from collections import defaultdict
   from aiolimiter import AsyncLimiter

   # 5 событий в 10 секунд на user_id
   _limiters: dict[int, AsyncLimiter] = defaultdict(
       lambda: AsyncLimiter(max_rate=5, time_period=10)
   )

   def get_limiter(user_id: int) -> AsyncLimiter:
       return _limiters[user_id]
   ```
3. В `bot/menu.py:handle_menu_callback` (строка 72) первой строкой:
   ```python
   from bot.rate_limit import get_limiter
   limiter = get_limiter(update.effective_user.id)
   if not limiter.has_capacity():
       await query.answer("⏳ Слишком часто, подожди 10 секунд", show_alert=True)
       return
   async with limiter:
       ...  # остальная логика
   ```

**Edge cases**: память без верхней границы — для prod добавь LRU/`functools.lru_cache(maxsize=10000)`.

## T3.4. Метрики Prometheus

**Цель**: иметь дашборд по работе бота (сигналы, длительность сканов, ошибки контекста).

**Файлы**:

- `requirements.txt` — добавь `prometheus_client>=0.20`.
- `monitoring/metrics.py` (новый).
- `main.py` — стартовать HTTP-сервер с `start_http_server`.

**Шаги**:

1. `monitoring/metrics.py`:
   ```python
   from prometheus_client import Counter, Histogram

   signals_total = Counter(
       "tgbot_signals_total",
       "Сигналы, опубликованные ботом",
       labelnames=("signal_type", "symbol", "timeframe"),
   )

   scan_duration_seconds = Histogram(
       "tgbot_scan_duration_seconds",
       "Длительность одного scan_symbol",
       labelnames=("timeframe",),
   )

   context_fetch_errors_total = Counter(
       "tgbot_context_fetch_errors_total",
       "Ошибки в контекстном модуле",
       labelnames=("source",),
   )
   ```
2. В `scheduler/scanner.py:scan_symbol` оберни тело в `Histogram.time()`:
   ```python
   from monitoring.metrics import scan_duration_seconds, signals_total
   ...
   async def scan_symbol(symbol, timeframe, notify_callback):
       with scan_duration_seconds.labels(timeframe=timeframe).time():
           ... # текущее тело
           # перед `return result`:
           signals_total.labels(
               signal_type=result.signal.value,
               symbol=symbol,
               timeframe=timeframe,
           ).inc()
           return result
   ```
3. В `context/analyzer.py` (где ловятся exceptions источников) перед `logger.warning`:
   ```python
   from monitoring.metrics import context_fetch_errors_total
   context_fetch_errors_total.labels(source="cryptopanic").inc()
   ```
4. В `main.py` до старта event loop:
   ```python
   from prometheus_client import start_http_server
   start_http_server(int(os.getenv("METRICS_PORT", "9090")))
   ```
5. Проверь: `curl localhost:9090/metrics | grep tgbot_` — должны быть строки.

**Edge cases**: если порт 9090 занят — сделай конфигурируемым (env `METRICS_PORT`, как
в коде выше). Если бот не должен слушать сеть — оставь экспорт opt-in через
`METRICS_ENABLED=false` гейт.
