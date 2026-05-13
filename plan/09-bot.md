# 2.10 bot/handlers.py — Обработчики команд

**Что делает:**
- `/start` — отправляет главное меню (inline keyboard)
- `/help` — справка по командам и логике сигналов
- `/status` — статус бота: кол-во символов, таймфреймы, cooldown
- `/lastsignal` — последние 5 сигналов из БД (с эмодзи + время UTC)
- `/symbols` — список отслеживаемых символов
- `/scan` — **admin-only**: ручной запуск `run_scan_cycle()` (выполняется синхронно с ожиданием)
- `/settings` — **admin-only**: текущие настройки индикаторов
- **Role check**: декоратор `_admin_only` проверяет `user_id in TELEGRAM_ADMIN_IDS`

**При каких условиях:**
- Пользователь отправляет команду в личку боту
- Для admin-команд — проверка прав, иначе "⛔ Доступ запрещён."

---

# 2.11 bot/menu.py — Инлайн-меню

**Что делает:**
- **Главное меню** (4 кнопки):
  1. 🔍 Анализ токена — выбирает токен → полный разбор (все индикаторы, SL/TP, сигнал)
  2. 📊 Индикаторы — выбирает токен → компактный просмотр всех индикаторов
  3. 📡 Авто-скан всех — `_do_scan_all()`: BUY/SELL/NEUTRAL для всех символов (RSI, ADX)
  4. ⚙️ Настройки — текущие параметры

- **Анализ своего токена**: пользователь может ввести текстом тикер (BTC, BTCUSDT, ETH/USDT) → нормализуется в формат XXX/USDT → полный анализ
- **Callback'и**: `m:analyze`, `m:pick_token`, `m:scan_all`, `m:settings`, `analyze:SYMBOL`, `token:SYMBOL`, `m:custom_token`, `m:back`
- Полный анализ включает: EMA alignment, RSI, MACD, ADX, ATR, Supertrend, Volume, SL/TP, R/R, список причин, TradingView ссылка
- `_do_scan_all()`: для каждого символа — RSI + ADX + сигнал (BUY/SELL/NEUTRAL)

**При каких условиях:**
- Пользователь нажимает кнопки в меню
- При вводе произвольного текста (не команды) — проверяется состояние WAITING

---

# 2.12 bot/notifier.py — Уведомления

**Что делает:**
- `send_signal(result, context_verdict)` — отправляет сигнал в Telegram-канал:
  - Форматирует через `result.format_message()` (HTML)
  - Если есть `context_verdict` — добавляет блок контекста:
    - Fear & Greed с эмодзи
    - Funding Rate (long/short позиции)
    - Long/Short Ratio
    - Open Interest Δ
    - News Sentiment
    - Итоговый вердикт + уверенность + поддерживающие/противодействующие факторы
  - Отправляет через `bot.send_message(parse_mode=ParseMode.HTML)`
- `send_error_alert(message)` — отправляет ERROR всем админам

**При каких условиях:**
- `send_signal()` — из scanner.py после успешного прохождения всех этапов
- `send_error_alert()` — из main.py при фатальной ошибке, из scanner.py при ошибке джобы
