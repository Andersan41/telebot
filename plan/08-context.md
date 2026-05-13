# 2.9 context/ — Контекстное обогащение

## context/fetcher.py — HTTP-клиенты

**Что делает:**
- Использует `aiohttp.ClientSession` (timeout 8s)
- Кеширование запросов с TTL
- **8 источников данных:**

1. **Alternative.me Fear & Greed Index** — `GET /fng/?limit=1`, кеш 3600s
2. **CoinGecko market data** — `GET /coins/{coin_id}`, цена 24h/7d, объём, cap rank
3. **CoinGecko trending** — `GET /search/trending`, кеш 1800s
4. **Binance Funding Rate** — через ccxt `exchange.fetch_funding_rate()`
5. **Binance Open Interest** — `GET fapi/v1/openInterest?symbol=BTCUSDT`
6. **Binance Long/Short Ratio** — `GET futures/data/globalLongShortAccountRatio`
7. **CryptoPanic News** (если есть API key) — анализ голосов (positive/negative)
8. **RSS News** — CoinDesk + Cointelegraph RSS, эвристический сентимент (словари позитивных/негативных слов)

## context/analyzer.py — Сбор данных

**Что делает:**
- `get_snapshot(symbol)` → `ContextSnapshot`
- Запускает все fetcher'ы параллельно через `asyncio.gather`
- Собирает: F&G, CoinGecko, trending, funding rate, OI, L/S, новости
- Ошибки отдельных источников не фатальны — записываются в `snapshot.errors`

## context/scorer.py — Оценка и вердикт

**Что делает:**
- `score(signal_direction, snapshot)` → `ContextVerdict`

**Взвешенная система:**

| Параметр | Вес | BUY условия | SELL условия |
|---|---|---|---|
| Fear & Greed | 0.15 | <25 → +0.8, ≥80 → -0.8 | >80 → +0.8, <25 → -0.8 |
| Funding Rate | 0.25 | < -0.5% → +0.9, >2% → -0.9 | >2% → +0.9, < -0.5% → -0.9 |
| Long/Short | 0.20 | <0.7 → +0.7, >1.2 → -0.6 | >1.2 → +0.7, <0.7 → -0.6 |
| Open Interest Δ | 0.15 | >2% → +0.5, <-2% → -0.2 | Любое направление — одинаково |
| News Sentiment | 0.15 | Прямая передача score | Прямая передача score |
| Price Trend 7d | 0.10 | >5% → +0.5, <-5% → -0.5 | <-5% → +0.5, >5% → -0.5 |

**Вердикты** (по итоговому score, диапазон [-1.0, 1.0]):
- `score >= 0.4` → CONFIRMED (рынок подтверждает)
- `score >= 0.1` → WEAK (слабая поддержка)
- `score >= -0.1` → CONFLICTED (разнонаправленные сигналы)
- `score < -0.1` → BLOCKED (рынок против)

**При каких условиях:**
- Вызывается из `scanner.py` если `CONTEXT_ENABLED=True`
- Если `CONTEXT_BLOCK_ON_BLOCKED=True`, BLOCKED отменяет сигнал
- Timeout 10 секунд на весь сбор
