# 📋 План улучшений бота — Этап 4: Рекомендации

> Не критично, но улучшит стабильность и качество. Выполнять после всех багов.
> **Статус**: ✅ сделано (items #9, #10, #11, #12). #13 — крупный рефакторинг, отложен.

---

## 9. Нет retry в Telegram Notifier

**Файл:** `bot/notifier.py`  
**Сложность:** Низкая  
**Время:** ~10 минут

### Проблема
При временной ошибке сети или rate limit сигнал теряется без повторной попытки.

### Исправление
```python
async def send_signal(self, result, context_verdict, retries=3):
    for attempt in range(retries):
        try:
            await self.bot.send_message(...)
            return
        except TelegramError as e:
            if attempt < retries - 1:
                await asyncio.sleep(2 ** attempt)  # exponential backoff
            else:
                logger.error(f"Failed to send signal after {retries} attempts: {e}")
```

---

## 10. OI warm-up: первый delta=0.0 после рестарта

**Файл:** `context/fetcher.py`, `fetch_open_interest()`  
**Сложность:** Низкая  
**Время:** ~15 минут

### Проблема
После рестарта первый вызов вернёт `open_interest_delta = 0.0`. При частых рестартах — первый цикл сканирования с нулевым OI delta.

### Исправление
Добавить поле `oi_is_warmup: bool = False` в `OIState` или `ContextSnapshot`. В scorer:

```python
if snapshot.oi_is_warmup:
    oi_weight = 0  # не учитывать при warm-up
```

---

## 11. RSS news: примитивный keyword matching

**Файл:** `context/fetcher.py`, `fetch_rss_news()`  
**Сложность:** Высокая  
**Время:** TBD

### Проблема
Ложные срабатывания на "not a hack", "no ban expected" и т.д.

### Временное решение
Снизить вес news в scorer с 0.15 до 0.05 до внедрения NLP.

---

## 12. BTC/ETH correlation fetches делаются дважды

**Файл:** `scheduler/scanner.py`  
**Сложность:** Низкая  
**Время:** ~10 минут

### Проблема
BTC и ETH данные запрашиваются в шагах 12-13 (correlation gate) и повторно в шаге 15 (no-trade zones).

### Исправление
Кэшировать результат в рамках одного `scan_symbol`:

```python
btc_ctx = await fetch_btc_context()   # один раз
eth_ctx = await fetch_eth_context()   # один раз

# Передавать btc_ctx/eth_ctx в обе проверки
```

---

## 13. scan_symbol (685 строк) слишком большая

**Файл:** `scheduler/scanner.py`  
**Сложность:** Высокая  
**Время:** TBD

### Проблема
Функцию тяжело тестировать и поддерживать.

### Исправление
Вынести логику в отдельные методы:

```python
class SignalPipeline:
    async def run(self, symbol, timeframe) -> Optional[SignalResult]:
        if not await self._check_cooldown(): return None
        ind = await self._calculate_indicators()
        if not ind: return None
        signal = await self._evaluate_signal(ind)
        if not signal: return None
        await self._enrich_context(signal)
        await self._validate_levels(signal)
        return signal
```
