# ИНСТРУКЦИЯ: Модуль подтверждения сигналов через открытые источники данных

## КОНТЕКСТ ЗАДАЧИ

В существующем боте уже работает технический анализ (EMA, RSI, MACD, ADX, ATR, Supertrend) и система подтверждения на таймфрейме 15m. Задача — добавить дополнительный слой подтверждения сигналов через фундаментальные и сентимент-данные из бесплатных открытых источников. Новый модуль должен встраиваться в существующий пайплайн без его разрушения: сначала технический сигнал, затем контекстное обогащение, затем взвешенное решение.

---

## АРХИТЕКТУРА НОВОГО МОДУЛЯ

Создать новую директорию `context/` рядом с существующими `indicators/`, `strategy/`, `scheduler/`. Внутри неё три файла:

`context/fetcher.py` — асинхронный клиент, который параллельно опрашивает все источники данных и возвращает сырые данные.

`context/analyzer.py` — берёт сырые данные от fetcher, вычисляет числовые метрики (sentiment score, fear & greed index, funding rate, open interest delta, on-chain активность) и возвращает единый объект `ContextSnapshot`.

`context/scorer.py` — принимает технический сигнал (BUY/SELL) и `ContextSnapshot`, применяет весовую логику и возвращает `ContextVerdict` с итоговой рекомендацией: CONFIRMED / WEAK / CONFLICTED / BLOCKED.

Синглтон `context_engine` создаётся в `context/analyzer.py` по тому же паттерну что `signal_engine`, `indicator_engine` и т.д. в проекте.

---

## ИСТОЧНИКИ ДАННЫХ — ПОЛНЫЙ СПИСОК

### 1. Alternative.me — Fear & Greed Index
URL: `https://api.alternative.me/fng/?limit=1`
Бесплатно, без ключа, без регистрации. Возвращает JSON с полями `value` (0–100) и `value_classification` (Extreme Fear / Fear / Neutral / Greed / Extreme Greed). Обновляется раз в сутки. Применимо только для BTC/USDT напрямую, для альткоинов — как рыночный контекст. Интерпретация: значение ниже 25 = рынок в панике, хорошо для BUY против тренда; выше 75 = перегрев, осторожно с BUY, подтверждает SELL.

### 2. CoinGecko — рыночные данные токена
URL: `https://api.coingecko.com/api/v3/coins/{coin_id}?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false`
Бесплатно, без ключа (лимит ~30 запросов в минуту на IP, этого достаточно). Параметр `coin_id` — это slug CoinGecko (btc = "bitcoin", eth = "ethereum"). Нужно хранить маппинг символов к slug в конфиге. Из ответа брать: `market_data.price_change_percentage_24h`, `market_data.price_change_percentage_7d`, `market_data.total_volume.usd`, `market_data.market_cap_rank`. Высокий rank (топ-20) и положительный 7d change при BUY сигнале — подтверждение. Резкое падение volume на 24h — предупреждение.

### 3. CoinGecko — trending coins
URL: `https://api.coingecko.com/api/v3/search/trending`
Без ключа. Возвращает список из 7 трендовых монет за последние 24 часа. Если сканируемый токен есть в этом списке — слабое подтверждение BUY (токен в фокусе рынка).

### 4. Binance — Funding Rate (уже есть доступ через ccxt)
Через уже существующий `exchange_client` вызвать `exchange.fetch_funding_rate(symbol)`. Возвращает текущий funding rate. Логика: положительный высокий funding (> 0.01%) при BUY сигнале — предупреждение (лонги перегреты, возможен шорт-сквиз вниз); отрицательный funding при BUY — подтверждение (шорты платят лонгам). При SELL сигнале — наоборот. Это очень ценный бесплатный индикатор через уже имеющийся ccxt клиент.

### 5. Binance — Open Interest
Через ccxt: `exchange.fetch_open_interest(symbol)`. Или через прямой HTTP запрос: `https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT`. Без ключа для публичных эндпоинтов фьючерсов. Сравнивать текущий OI с предыдущим значением (хранить в базе или в памяти синглтона). Рост OI + рост цены = подтверждение тренда. Рост OI + падение цены = усиление давления продавцов.

### 6. Binance — Long/Short Ratio (глобальный)
URL: `https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=1h&limit=1`
Публичный эндпоинт, без ключа. Возвращает соотношение длинных и коротких позиций по аккаунтам. Ratio > 1.5 при BUY сигнале — толпа уже в лонге, осторожно. Ratio < 0.7 при BUY — большинство в шорте, contrarian подтверждение.

### 7. CryptoPanic — новостной сентимент
URL: `https://cryptopanic.com/api/v1/posts/?auth_token=YOUR_TOKEN&currencies=BTC&filter=important&public=true`
Требует бесплатную регистрацию на cryptopanic.com для получения auth_token (бесплатный план доступен). Добавить `CRYPTOPANIC_API_KEY` в `.env`. Фильтровать новости за последние 6 часов по полю `created_at`. Считать количество новостей с `votes.negative` > `votes.positive` vs наоборот. Если негативных новостей > 60% — предупреждение при BUY.

### 8. RSS-фиды (резервный источник новостей, без ключа)
CoinDesk RSS: `https://www.coindesk.com/arc/outboundfeeds/rss/`
Cointelegraph RSS: `https://cointelegraph.com/rss`
Парсить через стандартную библиотеку `feedparser`. Искать упоминания символа токена в заголовках за последние 2 часа. Простой счётчик: заголовки с негативными словами (hack, crash, ban, lawsuit, exploit, fraud, scam, liquidation) vs позитивными (partnership, launch, upgrade, adoption, ETF, approval). Это грубый но бесплатный и надёжный сигнал без лимитов.

---

## СТРУКТУРА ДАННЫХ

Определить dataclass `ContextSnapshot` в `context/analyzer.py`:

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class ContextSnapshot:
    symbol: str
    timestamp: datetime
    fear_greed_value: Optional[int] = None          # 0-100
    fear_greed_label: Optional[str] = None
    price_change_24h: Optional[float] = None        # процент
    price_change_7d: Optional[float] = None
    volume_change_24h: Optional[float] = None       # vs среднему
    is_trending: bool = False
    funding_rate: Optional[float] = None            # текущий
    open_interest_delta: Optional[float] = None     # % изменение
    long_short_ratio: Optional[float] = None
    news_sentiment_score: Optional[float] = None    # -1.0 до 1.0
    news_count: int = 0
    errors: list = field(default_factory=list)      # источники с ошибками
```

Определить dataclass `ContextVerdict` в `context/scorer.py`:

```python
@dataclass
class ContextVerdict:
    verdict: str           # CONFIRMED / WEAK / CONFLICTED / BLOCKED
    confidence: float      # 0.0 до 1.0
    score: float           # итоговый взвешенный балл
    supporting: list       # список факторов ЗА сигнал
    opposing: list         # список факторов ПРОТИВ сигнала
    snapshot: ContextSnapshot
```

---

## ЛОГИКА СКОРИНГА (context/scorer.py)

Каждый источник добавляет или вычитает баллы из общего score в диапазоне [-1.0, 1.0]. Направление сигнала (BUY=+1, SELL=-1) учитывается при интерпретации.

Веса источников (настраиваемые через конфиг):
- Fear & Greed Index: вес 0.15 (менее важен для альткоинов)
- Funding Rate: вес 0.25 (самый информативный для фьючерсов)
- Long/Short Ratio: вес 0.20
- Open Interest Delta: вес 0.15
- News Sentiment: вес 0.15
- Price/Volume Trend (7d): вес 0.10

Логика перевода метрик в баллы для BUY сигнала:
- Fear & Greed < 25: +0.8 (contrarian, страх = возможность)
- Fear & Greed 25–45: +0.3
- Fear & Greed 45–65: 0.0 (нейтрально)
- Fear & Greed 65–80: -0.3 (жадность, риск)
- Fear & Greed > 80: -0.8 (extreme greed, высокий риск)
- Funding Rate < -0.005: +0.9 (шорты платят, лонги в преимуществе)
- Funding Rate -0.005 до 0.005: +0.1 (нейтрально)
- Funding Rate 0.005 до 0.02: -0.4 (лонги перегреты)
- Funding Rate > 0.02: -0.9 (экстремальная перегретость)
- Long/Short < 0.7: +0.7 (большинство в шорте = топливо для роста)
- Long/Short 0.7–1.2: 0.0
- Long/Short > 1.5: -0.6 (толпа в лонге)
- OI растёт при росте цены: +0.5 (сила тренда)
- OI растёт при падении цены: -0.5 (нарастание давления продавцов)
- OI падает: -0.2 (тренд ослабевает)

Итоговый score = взвешенная сумма всех компонентов. Если источник недоступен (ошибка сети), его вес перераспределяется пропорционально между остальными.

Перевод score в verdict:
- score >= 0.4: CONFIRMED (подтверждён, отправить сигнал)
- score 0.1 до 0.4: WEAK (слабое подтверждение, отправить с пометкой)
- score -0.1 до 0.1: CONFLICTED (противоречивые данные, отправить с предупреждением)
- score < -0.1: BLOCKED (контекст против сигнала, не отправлять или отправить как информационный)

Добавить конфиг-переменные в `config/settings.py`:
```
CONTEXT_ENABLED=true
CONTEXT_MIN_VERDICT=WEAK          # минимальный verdict для отправки сигнала
CONTEXT_BLOCK_ON_BLOCKED=true     # блокировать ли сигнал при BLOCKED
CRYPTOPANIC_API_KEY=              # опционально
COINGECKO_SYMBOL_MAP=BTC/USDT:bitcoin,ETH/USDT:ethereum  # маппинг для CoinGecko
```

---

## ИНТЕГРАЦИЯ В СУЩЕСТВУЮЩИЙ ПАЙПЛАЙН

Точка интеграции — файл `scheduler/scanner.py`. Сейчас пайплайн выглядит примерно так:

1. Получить OHLCV данные (`exchange_client.fetch_ohlcv`)
2. Рассчитать индикаторы (`indicator_engine.calculate`)
3. Проверить сигнал (`signal_engine.check_signal`)
4. Подтвердить на 15m таймфрейме
5. Проверить cooldown
6. Отправить в Telegram

После шага 4 и перед шагом 5 добавить шаг 4.5:

4.5. Запустить `context_engine.enrich(symbol, signal_direction)` — получить `ContextVerdict`. Если `CONTEXT_BLOCK_ON_BLOCKED=true` и verdict == BLOCKED, пропустить сигнал (залогировать причину). Иначе — передать verdict в notifier для отображения в сообщении.

Важно: вызов `context_engine.enrich()` должен быть через `asyncio.gather` с таймаутом 10 секунд. Если контекст не успел загрузиться — не блокировать сигнал, отправить без контекста с пометкой "context unavailable".

---

## ФОРМАТ СООБЩЕНИЯ В TELEGRAM

Расширить `bot/notifier.py`. К существующему сообщению сигнала добавить блок (только если context_enabled и данные получены):

```
📊 Контекст рынка:
├ Fear & Greed: 34 (Fear) ⚠️
├ Funding: -0.003% ✅
├ Long/Short: 0.68 ✅
├ OI: +4.2% ✅
└ Новости: нейтральный 😐

🔍 Вердикт: CONFIRMED (уверенность 76%)
  ✅ Шорты платят лонгам
  ✅ Большинство в короткой позиции
  ⚠️ Fear & Greed в зоне страха
```

Эмодзи для verdict: CONFIRMED = ✅, WEAK = 🟡, CONFLICTED = ⚠️, BLOCKED = 🚫

Все динамические значения обязательно пропускать через `html.escape()` перед вставкой в HTML-сообщение Telegram (это уже описано в AGENTS.md как gotcha).

---

## КЭШИРОВАНИЕ И ПРОИЗВОДИТЕЛЬНОСТЬ

Данные от Fear & Greed, CoinGecko trending, RSS — обновляются редко. Кэшировать их в памяти синглтона `context_engine` с TTL:
- Fear & Greed: TTL 3600 секунд (обновляется раз в сутки)
- CoinGecko trending: TTL 1800 секунд
- RSS новости: TTL 300 секунд
- Funding Rate, OI, Long/Short: без кэша, запрашивать при каждом сигнале (быстрые данные)

Реализовать простой кэш через словарь `{key: (data, timestamp)}` внутри класса `ContextEngine`.

Параллельные запросы: все источники опрашивать через `asyncio.gather(*tasks, return_exceptions=True)`. Исключения ловить, записывать в `ContextSnapshot.errors`, не падать.

Лимиты: CoinGecko бесплатный tier = ~30 req/min. При большом количестве символов добавить `asyncio.sleep(2)` между запросами к CoinGecko или использовать один запрос `/coins/markets` для получения данных по всем токенам сразу:
`https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=bitcoin,ethereum&order=market_cap_desc&per_page=50`

---

## ХРАНЕНИЕ ДАННЫХ В БАЗЕ

Добавить новую таблицу `context_snapshots` в `storage/database.py` (SQLAlchemy модель):

```python
class ContextSnapshotModel(Base):
    __tablename__ = "context_snapshots"
    id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=True)
    timestamp = Column(DateTime)
    verdict = Column(String)
    confidence = Column(Float)
    score = Column(Float)
    fear_greed = Column(Integer, nullable=True)
    funding_rate = Column(Float, nullable=True)
    long_short_ratio = Column(Float, nullable=True)
    open_interest_delta = Column(Float, nullable=True)
    news_sentiment = Column(Float, nullable=True)
    raw_json = Column(Text)   # весь ContextSnapshot как JSON для истории
```

Сохранять каждый ContextSnapshot при отправке сигнала. Это позволит позже анализировать, какие комбинации технических + контекстных сигналов давали лучшие результаты.

---

## ФАЙЛ ЗАВИСИМОСТЕЙ

Добавить в `requirements.txt`:
```
feedparser>=6.0.0      # RSS парсинг
aiohttp>=3.9.0         # асинхронные HTTP запросы (возможно уже есть)
```

Использовать `aiohttp.ClientSession` с таймаутом `aiohttp.ClientTimeout(total=8)` для всех внешних запросов. Создавать одну сессию в `ContextFetcher.__init__` и переиспользовать (не создавать новую на каждый запрос).

---

## ПОРЯДОК РЕАЛИЗАЦИИ ДЛЯ АГЕНТА

Агент должен реализовывать файлы строго в этом порядке, чтобы не было проблем с импортами:

1. Добавить новые поля в `config/settings.py`: `context_enabled`, `context_min_verdict`, `context_block_on_blocked`, `cryptopanic_api_key`, `coingecko_symbol_map` (строка вида "BTC/USDT:bitcoin,ETH/USDT:ethereum", парсить в dict при инициализации).

2. Создать `context/` директорию с пустым `context/__init__.py`.

3. Написать `context/fetcher.py` с классом `ContextFetcher`. Методы: `fetch_fear_greed()`, `fetch_coingecko(coin_id)`, `fetch_trending()`, `fetch_funding_rate(symbol)`, `fetch_open_interest(symbol)`, `fetch_long_short_ratio(symbol)`, `fetch_cryptopanic(symbol)` (опционально, только если ключ задан), `fetch_rss_news(symbol)`. Каждый метод — async, возвращает dict или None при ошибке. Логировать ошибки через loguru с уровнем WARNING, не поднимать исключения наружу.

4. Написать `context/analyzer.py` с классом `ContextEngine`. Метод `async def get_snapshot(symbol: str) -> ContextSnapshot` вызывает все fetcher методы через `asyncio.gather`, собирает результаты в `ContextSnapshot`. Реализовать кэш с TTL для медленных источников. Синглтон `context_engine = ContextEngine()` в конце файла.

5. Написать `context/scorer.py` с классом `ContextScorer`. Метод `score(signal_direction: str, snapshot: ContextSnapshot) -> ContextVerdict`. Все пороги и веса вынести в константы вверху файла для удобного тюнинга. Синглтон `context_scorer = ContextScorer()` в конце файла.

6. Изменить `scheduler/scanner.py`: после получения подтверждённого технического сигнала и до проверки cooldown добавить вызов `context_engine.get_snapshot()` и `context_scorer.score()`. Обернуть в `asyncio.wait_for(..., timeout=10.0)` с обработкой `asyncio.TimeoutError`.

7. Изменить `bot/notifier.py`: добавить форматирование `ContextVerdict` в отдельную функцию `format_context_block(verdict: ContextVerdict) -> str`, которая возвращает HTML-строку для добавления к сообщению. Все значения через `html.escape()`.

8. Изменить `storage/database.py`: добавить модель `ContextSnapshotModel` и метод `async def save_context_snapshot(snapshot_data)`.

9. Написать тесты `tests/test_context.py`: мокировать HTTP запросы через `unittest.mock.AsyncMock` или `pytest-aioresponses`, проверить логику скоринга для пограничных случаев (все источники недоступны, только часть источников доступна, extreme значения).

---

## ВАЖНЫЕ ОГРАНИЧЕНИЯ И GOTCHAS

Не изменять существующий `signal_engine.py` и `indicator_engine.py` — контекстное подтверждение работает поверх них, не внутри.

Все внешние HTTP запросы должны иметь явный таймаут. Без таймаута один зависший источник заблокирует весь пайплайн.

CoinGecko slug и биржевой символ — разные вещи. BTC/USDT на Binance = "bitcoin" в CoinGecko. Маппинг хранить в конфиге, не хардкодить в коде. Если символ не найден в маппинге — пропустить CoinGecko запрос, не падать.

Binance Futures API (`fapi.binance.com`) для funding rate и OI работает только для фьючерсных пар. Если токен есть только в spot — пропустить эти источники, не выдавать ошибку пользователю.

RSS парсинг может давать ложные срабатывания (например, "ETH" в слове "ether" или названии компании). Искать символ как отдельное слово: `re.search(r'\b' + re.escape(base_currency) + r'\b', title, re.IGNORECASE)` где `base_currency = symbol.split('/')[0]`.

При сохранении в базу сериализовать `ContextSnapshot` в JSON через `dataclasses.asdict()` + `json.dumps()` с обработкой `datetime` объектов через кастомный encoder.
