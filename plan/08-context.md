# 2.9 context/ — Контекстное обогащение

## context/fetcher.py — HTTP-клиенты

**Что делает:**

- Использует `aiohttp.ClientSession` (timeout 8s)
- Кеширование запросов с TTL
- **8 источников данных:**

1. **Alternative.me Fear & Greed Index** — `GET /fng/?limit=1`, кеш 3600s.
2. **CoinGecko market data** — `GET /coins/{coin_id}`, цена 24h/7d, объём, cap rank.
3. **CoinGecko trending** — `GET /search/trending`, кеш 1800s.
4. **Binance Funding Rate** — `GET fapi/v1/premiumIndex?symbol=…`. Берём
   `lastFundingRate`. Прямой HTTP, не через ccxt — тот же путь, что у OI/LS.
5. **Binance Open Interest** — `GET fapi/v1/openInterest?symbol=…`.
   Хранится last-OI per-symbol в `_last_oi` (in-memory), возвращается
   `{"open_interest", "open_interest_delta": Δ%, "timestamp"}`. На первом
   запуске delta = 0.0.
6. **Binance Long/Short Ratio** — `GET futures/data/globalLongShortAccountRatio`.
7. **CryptoPanic News** — анализ голосов (positive/negative), только если задан
   `CRYPTOPANIC_API_KEY`.
8. **RSS News** — CoinDesk + Cointelegraph, эвристический сентимент по словарям.
   Кеш 300s.

## context/analyzer.py — Сбор данных

**Что делает:**

- `get_snapshot(symbol)` → `ContextSnapshot`
- Запускает все fetcher'ы параллельно через `asyncio.gather`.
- Собирает: F&G, CoinGecko (24h/7d/vol/rank), trending, funding rate, OI, L/S, news.
- News-сентимент от CryptoPanic и RSS аккумулируется в локальный список
  `[(score, count), ...]` и сворачивается **после** `asyncio.gather`
  в средневзвешенный по количеству статей `news_sentiment_score`. Порядок
  завершения корутин больше не влияет на итог.
- Ошибки отдельных источников не фатальны — пишутся в `snapshot.errors`.

## context/scorer.py — Оценка и вердикт

**Что делает:**

- `score(signal_direction, snapshot)` → `ContextVerdict`
- Нормализует итог: `weighted_sum / total_weight` (если источники недоступны — вес перераспределяется)
- Ограничение результата в [-1.0, 1.0]; `confidence = abs(score)`

**Взвешенная система:**

| Параметр       | Вес  | BUY условия                                                              | SELL условия                                    |
|----------------|------|--------------------------------------------------------------------------|-------------------------------------------------|
| Fear & Greed   | 0.15 | <25 → +0.8; <45 → +0.3; 65–80 → −0.3; ≥80 → −0.8                         | <25 → −0.8; ≥80 → +0.8; средние полосы → +0.3/0 |
| Funding Rate   | 0.25 | < −0.5% → +0.9; <0.5% → +0.1; <2% → −0.4; ≥2% → −0.9                     | зеркально знаки                                 |
| Long/Short     | 0.20 | <0.7 → +0.7; 0.7–1.2 → 0; >1.2 → −0.6                                    | <0.7 → −0.6; 0.7–1.2 → 0; >1.2 → +0.7           |
| Open Interest  | 0.15 | **direction игнорируется**: Δ>2% → +0.5; Δ>0 → +0.2; Δ>−2% → −0.1; иначе −0.2 |                                            |
| News Sentiment | 0.15 | Прямая передача score `[-1..1]`                                          | то же                                           |
| Price Trend 7d | 0.10 | >5% → +0.5; >0 → +0.3; >−5% → 0; иначе −0.5                              | зеркально                                       |

⚠️ Колонка OI применяется **одинаково** для BUY и SELL — пробел в логике
шкалы (для SELL рост OI идёт «в плюс» так же, как для BUY). Если рассматривать
рост OI как подтверждение тренда — это корректно, но для SELL должно быть
зеркально. См. [17-improvements.md](17-improvements.md).

**Вердикты** (по итоговому score, диапазон [-1.0, 1.0]):

- `score >= 0.4` → CONFIRMED (рынок подтверждает)
- `score >= 0.1` → WEAK (слабая поддержка)
- `score >= -0.1` → CONFLICTED (разнонаправленные сигналы)
- `score < -0.1` → BLOCKED (рынок против)

## Использование в scanner

- Вызывается из `scanner.py`, если `CONTEXT_ENABLED=True`.
- Таймаут на весь сбор — 10 секунд (`asyncio.wait_for`).
- Если `CONTEXT_BLOCK_ON_BLOCKED=True` и вердикт `BLOCKED` — сигнал отменяется.
- Если фактический `verdict` ниже `CONTEXT_MIN_VERDICT` по рангу
  (`BLOCKED < CONFLICTED < WEAK < CONFIRMED`) — сигнал отменяется. Пустая
  строка / неизвестное значение в `CONTEXT_MIN_VERDICT` — гейт отключён.
  По умолчанию `CONTEXT_MIN_VERDICT=WEAK`: CONFLICTED-сигналы тоже отсекаются.
