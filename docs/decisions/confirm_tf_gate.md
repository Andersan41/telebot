# CONFIRM_TF_GATE — pourquoi il est désactivé

**Статус:** закрыто до появления данных из paper trading
**Дата:** 2026-06-25
**Gate:** `CONFIRM_TF_ENABLED` (по умолчанию `true`, установлено `false`)

---

## Что делает gate

`signal_engine.py:781-803` — `evaluate_confirm(ind, direction)`

Проверяет на 15m таймфрейме **два условия** (достаточно **одного** — OR логика):

1. **EMA alignment:** `ema_fast > ema_slow` (BUY) / `ema_fast < ema_slow` (SELL)
2. **Supertrend direction:** `== 1` (BUY) / `== -1` (SELL)

```python
return ema_aligned or st_aligned
```

Вызывается из `scanner.py:400-427` до основного `signal_engine.evaluate()`.

---

## Почему отключён

### 1. OR логика слишком мягкая, но всё равно блокирует 33%

OR (достаточно одного условия) — максимально щадящий вариант. Даже с ним gate отсекает **23 из 70** комбинаций (33%). Причина — 15m шумнее 1h/4h, EMA часто пересекаются в обратную сторону даже при устойчивом тренде на основном TF.

### 2. Дыры в проверке — gate непоследователен

```python
if ind is None:
    return True           # нет данных → пропуск

st_aligned = ind.supertrend_direction is None or ind.supertrend_direction == 1
#                          ↑ None → True
```

- `ind=None` → gate пропускает без проверки
- `supertrend=None` → `st_aligned=True`, gate пропускает

Gate иногда не проверяет вообще ничего. Это не баг — так задумано как fallback, но делает фильтр ненадёжным.

### 3. Структурное свойство 15m, не баг

На 15m EMA пересекаются в обратную сторону даже при устойчивом 1h тренде. Это не аномалия — 15m просто шумнее. Пытаться фильтровать 1h сигналы через 15m alignment — борьба с собственной природой таймфрейма.

### 4. Бэктест: gate ухудшает результат

| Метрика | Значение |
|---------|----------|
| `gate_only` PnL | **−27.82%** |
| Отключение в full_old→full_new | **+106.91% net PnL** |

На 20 символах gate стабильно снижает profitability.

### 5. unified_entry уже учитывает 15m

`unified_entry` использует `close` с 15m как цену входа (`scanner.py:422`). Информация с 15m уже встроена в entry — через alignment gate она дублируется и добавляет шум.

---

## Когда вернуть gate

Только при **всех** условиях:

1. **OR → AND:** оба условия (EMA + Supertrend) должны совпадать одновременно
2. **Убрать дыры:** `None → False` (не пропуск), а не `True`
3. **Бэктест на 20+ символах:** `gate_only` PnL должен быть **значительно положительным**
4. **Paper trading:** положительный результат в реальных условиях

---

## Конфигурация

```env
CONFIRM_TF_ENABLED=false
CONFIRM_TIMEFRAME=15m  # оставлен для документации, не используется
```
