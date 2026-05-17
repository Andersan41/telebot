# F1. SL/PnL трекинг открытых сигналов

> **Статус**: ✅ сделано (разбита на подзадачи F1.1, F1.2, F1.3)
> **Приоритет**: 🟢 low — новая функциональность, не bugfix.
> **Зависимости**: нет

**Цель**: после публикации сигнала отслеживать, достиг ли он TP или сработал SL, и
рассчитывать кумулятивную статистику (win rate, средний R/R, суммарный PnL).

> ⚠️ Объём работ большой. Разбита на 3 подзадачи:

| #  | Файл                                        | Кратко                          |
|----|---------------------------------------------|---------------------------------|
| F1.1 | [F1.1-db-model.md](improvements/F1.1-db-model.md) | Модель SignalOutcome + CRUD    |
| F1.2 | [F1.2-outcome-tracker.md](improvements/F1.2-outcome-tracker.md) | Фоновый loop проверки TP/SL    |
| F1.3 | [F1.3-stats-command.md](improvements/F1.3-stats-command.md)   | /stats команда + связка signal→outcome |

**Файлы**:

| Файл                        | Что делать                                                |
|-----------------------------|-----------------------------------------------------------|
| `storage/database.py`       | новая модель `SignalOutcome`, методы CRUD                 |
| `scheduler/outcome_tracker.py` (new) | фоновая задача опроса цен                        |
| `scheduler/__init__.py`     | регистрация задачи в общий scheduler                      |
| `bot/handlers.py` или `bot/admin.py` | команда `/stats`                                 |
| `tests/test_outcome_tracker.py` (new) | unit-тесты на закрытие по TP/SL                 |

**Пошагово**:

1. **Модель в БД** (`storage/database.py`, рядом с `Signal`):
   ```python
   class SignalOutcome(Base):
       __tablename__ = "signal_outcomes"

       id = Column(Integer, primary_key=True, autoincrement=True)
       signal_id = Column(
           Integer, ForeignKey("signals.id"), nullable=False, index=True
       )
       status = Column(String(20), nullable=False, default="OPEN")
       # OPEN / HIT_TP / HIT_SL / EXPIRED / MANUAL_CLOSE
       closed_at = Column(DateTime, nullable=True)
       close_price = Column(Float, nullable=True)
       pnl_pct = Column(Float, nullable=True)
       checked_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
   ```
   В `Database` добавь методы:
   ```python
   async def create_outcome(self, signal_id: int) -> "SignalOutcome":
       async with self._session_factory() as session:
           outcome = SignalOutcome(signal_id=signal_id, status="OPEN")
           session.add(outcome)
           await session.commit()
           await session.refresh(outcome)
           return outcome

   async def get_open_outcomes(self) -> list["SignalOutcome"]:
       async with self._session_factory() as session:
           result = await session.execute(
               select(SignalOutcome).where(SignalOutcome.status == "OPEN")
           )
           return list(result.scalars().all())

   async def close_outcome(
       self, outcome_id: int, status: str, close_price: float, pnl_pct: float
   ) -> None:
       async with self._session_factory() as session:
           result = await session.execute(
               select(SignalOutcome).where(SignalOutcome.id == outcome_id)
           )
           row = result.scalar_one()
           row.status = status
           row.close_price = close_price
           row.pnl_pct = pnl_pct
           row.closed_at = datetime.now(timezone.utc)
           await session.commit()
   ```
   `Base.metadata.create_all` (строки 71-74) автоматически создаст таблицу при следующем
   запуске. Миграция не нужна (sqlite + dev-стадия проекта).

2. **Создание outcome при публикации сигнала** (`scheduler/scanner.py`, после
   `saved_signal = await db.save_signal(...)` на строке 154):
   ```python
   await db.create_outcome(saved_signal.id)
   ```

3. **Фоновая задача** (`scheduler/outcome_tracker.py`, new):
   ```python
   import asyncio
   from datetime import datetime, timezone, timedelta
   from loguru import logger
   from config.settings import config
   from data.exchange_client import exchange_client
   from storage.database import db, Signal

   OUTCOME_CHECK_INTERVAL_SECONDS = int(
       __import__("os").getenv("OUTCOME_CHECK_INTERVAL_SECONDS", "300")
   )
   OUTCOME_TTL_DAYS = int(__import__("os").getenv("OUTCOME_TTL_DAYS", "7"))


   async def check_open_outcomes() -> None:
       outcomes = await db.get_open_outcomes()
       if not outcomes:
           return
       logger.debug(f"Checking {len(outcomes)} open outcomes")
       for outcome in outcomes:
           signal = await db.get_signal(outcome.signal_id)  # ← добавь get_signal в БД
           if signal is None:
               continue
           # Просроченный сигнал → EXPIRED
           age = datetime.now(timezone.utc) - signal.created_at.replace(
               tzinfo=timezone.utc
           )
           if age > timedelta(days=OUTCOME_TTL_DAYS):
               await db.close_outcome(
                   outcome.id, "EXPIRED",
                   close_price=signal.close_price, pnl_pct=0.0,
               )
               continue
           # Текущая цена через 1m свечу
           df = await exchange_client.fetch_ohlcv(signal.symbol, "1m", limit=2)
           if df is None or df.empty:
               continue
           current = float(df["close"].iloc[-1])
           hit_tp = (
               signal.signal_type == "BUY" and signal.tp and current >= signal.tp
           ) or (
               signal.signal_type == "SELL" and signal.tp and current <= signal.tp
           )
           hit_sl = (
               signal.signal_type == "BUY" and signal.sl and current <= signal.sl
           ) or (
               signal.signal_type == "SELL" and signal.sl and current >= signal.sl
           )
           if hit_tp:
               pnl = (current - signal.close_price) / signal.close_price * 100
               if signal.signal_type == "SELL":
                   pnl = -pnl
               await db.close_outcome(outcome.id, "HIT_TP", current, pnl)
               logger.info(f"Outcome HIT_TP: signal_id={signal.id} pnl={pnl:.2f}%")
           elif hit_sl:
               pnl = (current - signal.close_price) / signal.close_price * 100
               if signal.signal_type == "SELL":
                   pnl = -pnl
               await db.close_outcome(outcome.id, "HIT_SL", current, pnl)
               logger.info(f"Outcome HIT_SL: signal_id={signal.id} pnl={pnl:.2f}%")


   async def outcome_tracker_loop() -> None:
       while True:
           try:
               await check_open_outcomes()
           except Exception as e:
               logger.warning(f"Outcome tracker error: {e}")
           await asyncio.sleep(OUTCOME_CHECK_INTERVAL_SECONDS)
   ```

4. **Регистрация задачи**. В точке входа scheduler'а (`scheduler/__init__.py` или там,
   где идёт `apscheduler` setup) добавь:
   ```python
   import asyncio
   from scheduler.outcome_tracker import outcome_tracker_loop

   # Запустить как фоновую задачу при старте event loop
   asyncio.create_task(outcome_tracker_loop())
   ```
   Точное место зависит от структуры — посмотри `plan/07-scheduler.md` и текущий код
   `scheduler/`.

5. **Команда `/stats`** (`bot/handlers.py` или `bot/admin.py`):
   ```python
   from telegram import Update
   from telegram.ext import ContextTypes
   from telegram.constants import ParseMode

   @_admin_only
   async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
       stats = await db.get_outcome_stats()  # ← добавь в БД (см. ниже)
       total = stats["closed"] or 1
       win_rate = stats["wins"] / total * 100
       text = (
           f"📊 <b>Статистика сигналов</b>\n\n"
           f"Всего закрытых: <b>{stats['closed']}</b>\n"
           f"Открытых: <b>{stats['open']}</b>\n"
           f"Win rate: <b>{win_rate:.1f}%</b> ({stats['wins']}/{total})\n"
           f"Средний PnL: <b>{stats['avg_pnl']:.2f}%</b>\n"
           f"Лучший: <b>{stats['best_pnl']:.2f}%</b>\n"
           f"Худший: <b>{stats['worst_pnl']:.2f}%</b>"
       )
       await update.message.reply_text(text, parse_mode=ParseMode.HTML)
   ```
   Добавь `get_outcome_stats` в `Database`:
   ```python
   async def get_outcome_stats(self) -> dict:
       async with self._session_factory() as session:
           closed = await session.execute(
               select(SignalOutcome).where(SignalOutcome.status != "OPEN")
           )
           closed_rows = list(closed.scalars().all())
           opened = await session.execute(
               select(SignalOutcome).where(SignalOutcome.status == "OPEN")
           )
           opened_rows = list(opened.scalars().all())
       pnls = [r.pnl_pct for r in closed_rows if r.pnl_pct is not None]
       return {
           "closed": len(closed_rows),
           "open": len(opened_rows),
           "wins": sum(1 for r in closed_rows if r.status == "HIT_TP"),
           "avg_pnl": sum(pnls) / len(pnls) if pnls else 0.0,
           "best_pnl": max(pnls) if pnls else 0.0,
           "worst_pnl": min(pnls) if pnls else 0.0,
       }
   ```
   Зарегистрируй handler: `application.add_handler(CommandHandler("stats", stats_command))`.

6. **Тест** (`tests/test_outcome_tracker.py`):
    - Замокать `db.get_open_outcomes`, `db.get_signal`, `exchange_client.fetch_ohlcv`.
    - Кейсы: цена > TP (BUY) → HIT_TP с положительным PnL; цена < SL → HIT_SL;
      цена в коридоре → outcome остаётся OPEN; просроченный сигнал → EXPIRED.

**Edge cases**:

- ccxt rate limits — `fetch_ohlcv` для каждого open outcome на каждом тике может ударить
  по rate-лимиту, если открытых сигналов десятки. Если планируется > 20 open outcomes —
  батчить через `fetch_tickers` (один запрос на список символов).
- Двойное закрытие — `get_open_outcomes` фильтрует `status == "OPEN"`, после `close_outcome`
  outcome уже не вернётся.
- Биржа упала / нет данных — `fetch_ohlcv` возвращает `None`, проверка скипается, повтор через
  `OUTCOME_CHECK_INTERVAL_SECONDS`.
- Свеча 1m даёт `close` на момент закрытия минуты; реальная цена может пробить TP/SL внутри
  минуты и вернуться. Для строгости брать `high`/`low` 1m свечи, а не `close`.

**Готовность**:

- `pytest tests/test_outcome_tracker.py -v` зелёный.
- При ручном тесте: сгенерируй сигнал, дождись пока цена пробьёт TP/SL —
  `sqlite3 data/signals.db "select * from signal_outcomes"` показывает закрытие.
- `/stats` в Telegram возвращает осмысленные числа.
