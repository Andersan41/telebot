# План развития Trading Signal Bot — OSINT Context Module

## Статус выполнения: 1/10 завершено

| # | Приоритет | Статус |
|---|-----------|--------|
| 1 | Модуль контекстного обогащения | ✅ ВЫПОЛНЕНО |
| 2 | Интеграция в существующий пайплайн | 🔄 В процессе |
| 3 | Структура данных | ✅ Встроено в п.1 |
| 4 | Логика скоринга | ✅ Встроено в п.1 |
| 5 | Кэширование и производительность | ✅ Встроено в п.1 |
| 6 | Формат сообщения в Telegram | ✅ Встроено в п.2 |
| 7 | Хранение данных в БД | ✅ Встроено в п.2 |
| 8 | Конфигурация | ✅ Встроено в п.1 |
| 9 | Зависимости | ✅ Встроено в п.1 |
| 10 | Тесты | ✅ 52 теста, все проходят |

---

## Приоритет 1: Модуль контекстного обогащения (✅ ВЫПОЛНЕНО)

Создать новую директорию `context/` с тремя модулями для подключения фундаментальных и сентимент-данных из открытых источников.

### Структура:
```
context/
├── __init__.py          # Инициализация
├── fetcher.py           # Асинхронный клиент для 8 источников
├── analyzer.py          # Сбор данных в ContextSnapshot, кэширование
└── scorer.py            # Взвешенная оценка → ContextVerdict
```

### Источники данных:

1. **Fear & Greed Index** (Alternative.me)
   - URL: `https://api.alternative.me/fng/?limit=1`
   - Без ключа, обновляется раз в сутки
   - Применимо к BTC/USDT напрямую, для альткоинов — как рыночный контекст

2. **CoinGecko** (рыночные данные + trending)
   - Основной: `https://api.coingecko.com/api/v3/coins/{coin_id}`
   - Трендовые: `https://api.coingecko.com/api/v3/search/trending`
   - Бесплатно, лимит ~30 req/min на IP

3. **Binance Funding Rate** (через ccxt)
   - Через существующий `exchange_client.fetch_funding_rate(symbol)`
   - Очень ценный бесплатный индикатор

4. **Binance Open Interest**
   - Через ccxt или HTTP: `https://fapi.binance.com/fapi/v1/openInterest`

5. **Binance Long/Short Ratio**
   - URL: `https://fapi.binance.com/futures/data/globalLongShortAccountRatio`
   - Публичный эндпоинт, без ключа

6. **CryptoPanic** (новости, опционально)
   - Требует бесплатную регистрацию для API ключа
   - Добавить `CRYPTOPANIC_API_KEY` в `.env`

7. **RSS-фиды** (резервный источник новостей)
   - CoinDesk: `https://www.coindesk.com/arc/outboundfeeds/rss/`
   - Cointelegraph: `https://cointelegraph.com/rss`
   - Парсинг через `feedparser`

---

## Приоритет 2: Интеграция в существующий пайплайн (✅ ВЫПОЛНЕНО)

### Точка интеграции:
Файл `scheduler/scanner.py`, после шага 4 (подтверждение на 15m) и перед шагом 5 (cooldown).

### Новый пайплайн:
```
1. Получить OHLCV данные (exchange_client.fetch_ohlcv)
2. Рассчитать индикаторы (indicator_engine.calculate)
3. Проверить сигнал (signal_engine.check_signal)
4. Подтвердить на 15m таймфрейме
4.5. Запустить context_engine.enrich(symbol, signal_direction)
     → получить ContextVerdict с timeout=10s
5. Если BLOCKED и CONTEXT_BLOCK_ON_BLOCKED=true — пропустить
6. Проверить cooldown
7. Отправить в Telegram (с контекстным блоком если доступен)
```

### Обработка ошибок:
- Все HTTP запросы через `asyncio.wait_for(..., timeout=10)`
- Если контекст не успел загрузиться — отправить без него с пометкой "context unavailable"
- Исключения ловить внутри fetcher, записывать в `ContextSnapshot.errors`

---

## Приоритет 3: Структура данных (✅ ВСТРОЕНО В П.1)

### ContextSnapshot (`context/analyzer.py`):
```python
@dataclass
class ContextSnapshot:
    symbol: str
    timestamp: datetime
    
    # Alternative.me Fear & Greed
    fear_greed_value: Optional[int] = None          # 0-100
    fear_greed_label: Optional[str] = None
    
    # CoinGecko
    price_change_24h: Optional[float] = None        # %
    price_change_7d: Optional[float] = None
    volume_change_24h: Optional[float] = None
    
    is_trending: bool = False                        # из trending coins
    
    # Binance Futures
    funding_rate: Optional[float] = None            # текущий
    open_interest_delta: Optional[float] = None     # % изменение
    long_short_ratio: Optional[float] = None
    
    # Новости
    news_sentiment_score: Optional[float] = None    # -1.0 до 1.0
    news_count: int = 0
    
    errors: list = field(default_factory=list)      # источники с ошибками
```

### ContextVerdict (`context/scorer.py`):
```python
@dataclass
class ContextVerdict:
    verdict: str           # CONFIRMED / WEAK / CONFLICTED / BLOCKED
    confidence: float      # 0.0 до 1.0
    score: float           # итоговый взвешенный балл [-1.0, 1.0]
    supporting: list       # список факторов ЗА сигнал
    opposing: list         # список факторов ПРОТИВ сигнала
    snapshot: ContextSnapshot
```

---

## Приоритет 4: Логика скоринга (✅ ВСТРОЕНО В П.1)

### Веса источников (настраиваемые через конфиг):
- Fear & Greed Index: **0.15** (менее важен для альткоинов)
- Funding Rate: **0.25** (самый информативный для фьючерсов)
- Long/Short Ratio: **0.20**
- Open Interest Delta: **0.15**
- News Sentiment: **0.15**
- Price/Volume Trend (7d): **0.10**

### Примеры интерпретации для BUY сигнала:
| Метрика | Значение | Балл |
|---------|----------|------|
| Fear & Greed < 25 | паника | +0.8 (contrarian) |
| Fear & Greed 25–45 | низкий страх | +0.3 |
| Fear & Greed 45–65 | нейтрально | 0.0 |
| Fear & Greed 65–80 | жадность | -0.3 (риск) |
| Fear & Greed > 80 | extreme greed | -0.8 |
| Funding Rate < -0.005% | шорты платят | +0.9 |
| Funding Rate 0.005–0.02% | лонги перегреты | -0.4 |
| Funding Rate > 0.02% | extreme heat | -0.9 |
| Long/Short < 0.7 | большинство в шорте | +0.7 (топливо для роста) |
| Long/Short > 1.5 | толпа в лонге | -0.6 |

### Перевод score в verdict:
- **score >= 0.4**: `CONFIRMED` — подтверждён, отправить сигнал
- **score 0.1–0.4**: `WEAK` — слабое подтверждение, отправить с пометкой
- **score -0.1–0.1**: `CONFLICTED` — противоречивые данные, отправить с предупреждением
- **score < -0.1**: `BLOCKED` — контекст против сигнала

### Перераспределение весов:
Если источник недоступен (ошибка сети), его вес перераспределяется пропорционально между остальными доступными.

---

## Приоритет 5: Кэширование и производительность (✅ ВСТРОЕНО В П.1)

### TTL для кэша в `ContextEngine`:
| Источник | TTL |
|----------|-----|
| Fear & Greed | 3600 сек (обновляется раз в сутки) |
| CoinGecko trending | 1800 сек |
| RSS новости | 300 сек |
| Funding Rate, OI, Long/Short | без кэша (быстрые данные) |

### Реализация:
- Простой кэш через словарь `{key: (data, timestamp)}`
- Параллельные запросы через `asyncio.gather(*tasks, return_exceptions=True)`
- Один `aiohttp.ClientSession` с таймаутом 8 сек на все HTTP запросы

### Лимиты CoinGecko:
- Free tier = ~30 req/min
- При большом количестве символов использовать один запрос `/coins/markets` для получения данных по всем токенам сразу

---

## Приоритет 6: Формат сообщения в Telegram (✅ ВЫПОЛНЕНО)

### Расширить `bot/notifier.py`:
К существующему сообщению сигнала добавить блок контекста (только если context_enabled и данные получены):

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

### Эмодзи для verdict:
- CONFIRMED = `✅`
- WEAK = `🟡`
- CONFLICTED = `⚠️`
- BLOCKED = `🚫`

### Важно:
Все динамические значения пропускать через `html.escape()` перед вставкой в HTML-сообщение Telegram (gotcha из AGENTS.md).

---

## Приоритет 7: Хранение данных в БД (✅ ВЫПОЛНЕНО)

### Новая таблица `context_snapshots`:
```python
class ContextSnapshotModel(Base):
    __tablename__ = "context_snapshots"
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), index=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=True)
    timestamp = Column(DateTime)
    verdict = Column(String(20))
    confidence = Column(Float)
    score = Column(Float)
    
    # Основные метрики
    fear_greed = Column(Integer, nullable=True)
    funding_rate = Column(Float, nullable=True)
    long_short_ratio = Column(Float, nullable=True)
    open_interest_delta = Column(Float, nullable=True)
    news_sentiment = Column(Float, nullable=True)
    
    raw_json = Column(Text)   # весь ContextSnapshot как JSON для истории
```

### Метод сохранения:
- Сохранять каждый `ContextSnapshot` при отправке сигнала
- Сериализация через `dataclasses.asdict()` + `json.dumps()` с кастомным encoder для datetime

---

## Приоритет 8: Конфигурация (✅ ВЫПОЛНЕНО)

### Добавить в `config/settings.py`:
```python
# Context module settings
context_enabled: bool = field(default_factory=lambda: os.getenv("CONTEXT_ENABLED", "true").lower() == "true")
context_min_verdict: str = os.getenv("CONTEXT_MIN_VERDICT", "WEAK")  # CONFIRMED/WEAK/CONFLICTED/BLOCKED
context_block_on_blocked: bool = field(default_factory=lambda: os.getenv("CONTEXT_BLOCK_ON_BLOCKED", "true").lower() == "true")

# Optional API keys
cryptopanic_api_key: str = os.getenv("CRYPTOPANIC_API_KEY", "")

# Symbol to CoinGecko slug mapping (string → dict)
coingecko_symbol_map_str: str = os.getenv("COINGECKO_SYMBOL_MAP", "BTC/USDT:bitcoin,ETH/USDT:ethereum")
```

### Парсинг `COINGECKO_SYMBOL_MAP`:
```python
def parse_coingecko_map(map_str: str) -> dict[str, str]:
    result = {}
    for pair in map_str.split(","):
        if ":" in pair:
            symbol, slug = pair.strip().split(":")
            result[symbol.strip()] = slug.strip()
    return result
```

### Добавить в `.env.example`:
```env
CONTEXT_ENABLED=true
CONTEXT_MIN_VERDICT=WEAK
CONTEXT_BLOCK_ON_BLOCKED=true
CRYPTOPANIC_API_KEY=
COINGECKO_SYMBOL_MAP=BTC/USDT:bitcoin,ETH/USDT:ethereum
```

---

## Приоритет 9: Зависимости (✅ ВЫПОЛНЕНО)

### Добавить в `requirements.txt`:
```txt
feedparser>=6.0.0      # RSS парсинг
pytest-aioresponses>=0.7.0  # мокирование HTTP запросов в тестах
```

---

## Приоритет 10: Тесты (✅ ВЫПОЛНЕНО — 52 теста, все проходят)

### Тестовый файл `tests/test_context.py`:
- Мокировать HTTP запросы через `pytest-aioresponses`
- Проверить логику скоринга для пограничных случаев:
  - Все источники недоступны
  - Только часть источников доступна
  - Extreme значения метрик (Fear & Greed = 0, 100; funding rate = -0.05, +0.05)

### Пример теста:
```python
@pytest.mark.asyncio
async def test_scorer_confirmed_buy_with_favorable_conditions():
    snapshot = ContextSnapshot(
        symbol="BTC/USDT",
        timestamp=datetime.now(timezone.utc),
        fear_greed_value=20,      # Fear — +0.8
        funding_rate=-0.006,       # Шорты платят — +0.9
        long_short_ratio=0.65,     # Большинство в шорте — +0.7
    )
    verdict = context_scorer.score("BUY", snapshot)
    assert verdict.verdict == "CONFIRMED"
    assert verdict.score > 0.4
```

---

## Порядок реализации (строго по инструкции):

1. ~~**config/settings.py** — добавить поля контекста и парсинг `coingecko_symbol_map`~~ ✅
2. ~~**context/__init__.py** — пустой файл для импорта~~ ✅
3. ~~**context/fetcher.py** — все HTTP клиенты (8 методов)~~ ✅
4. ~~**context/analyzer.py** — сбор данных через `asyncio.gather`, кэш с TTL, `ContextEngine` singleton~~ ✅
5. ~~**context/scorer.py** — взвешенная оценка, пороги в константах, `ContextScorer` singleton~~ ✅
6. **scheduler/scanner.py** — интеграция после 15m подтверждения с `asyncio.wait_for(timeout=10)`
7. **bot/notifier.py** — функция `format_context_block(verdict)` для HTML-блоков
8. **storage/database.py** — модель `ContextSnapshotModel` + метод сохранения
9. ~~**tests/test_context.py** — мокированные тесты с `pytest-aioresponses`~~ ✅ (52 теста)

---

## Gotchas (обязательно соблюдать):

- ❌ Не менять существующий `signal_engine.py` и `indicator_engine.py`
- ✅ Все внешние HTTP запросы должны иметь явный таймаут (8 сек)
- 📌 CoinGecko slug и биржевой символ — разные вещи (BTC/USDT = "bitcoin")
- 🔒 Если символ не найден в маппинге — пропустить CoinGecko запрос
- 🔄 Binance Futures API (`fapi.binance.com`) работает только для фьючерсных пар
- 🔍 RSS парсинг — искать символ как отдельное слово: `\bBTC\b`
- 📦 Сериализация `ContextSnapshot` в JSON через `dataclasses.asdict()` + кастомный encoder
- 🚫 При BLOCKED verdict с `CONTEXT_BLOCK_ON_BLOCKED=true` сигнал не отправлять

---

## Next Steps (после реализации):

- Установить реальные API-ключи обратно в `.env`
- Запустить бота и проверить контекстные блоки в Telegram
- Docker: обновить образ на `python:3.12-slim` (если ещё не обновлён)
- Аналитика: отслеживать корреляцию технических + контекстных сигналов
