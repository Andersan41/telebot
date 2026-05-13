# A6. Score-формула: ADX/DMI как реальные критерии (опционально)

> **Статус**: 🔴 не сделано
> **Приоритет**: 🟢 low — рефакторинг, не bugfix. Меняет чувствительность сигналов.
> **Зависимости**: нет, но требует согласования с владельцем перед стартом.

**Цель**: формализовать «6 факторов + ADX-фильтр» — добавить ADX/DMI как реальные баллы,
тогда max score = 8 и `format_message` снова будет отражать корректное `/N`.

> ⚠️ **Это рефакторинг, не bugfix**. Меняет чувствительность сигналов на исторических данных.
> Запускать **только** если согласован с владельцем. Если согласования нет — пропусти задачу.

**Файлы и точные места**:

| Файл                               | Что делать                                           |
|------------------------------------|------------------------------------------------------|
| `strategy/signal_engine.py:69-178` | переписать `evaluate()` (см. шаги 1-3)               |
| `strategy/signal_engine.py:57`     | заменить `({self.score}/6)` → `({self.score}/8)`     |
| `bot/menu.py:289`                  | заменить `({result.score}/6)` → `({result.score}/8)` |
| `bot/menu.py:354`                  | то же                                                |
| `plan/06-signal-engine.md`         | обновить таблицу критериев и блок-схему              |
| `plan/12-flowchart.md`             | синхронизировать ветки «score >= 4»                  |
| `tests/test_signal.py`             | обновить ожидания по `result.score`                  |

**Выбор варианта**: используем **вариант A** (ADX как `+1` и DMI direction match как `+1`,
итого max score = 8). Зеркальный вариант (`/7`, только ADX) отклонён — DMI несёт независимую
информацию о направлении и должен учитываться отдельно.

**Пошагово**:

1. В `strategy/signal_engine.py:evaluate` **после** блока «--- Объём ---»
   (строки 133-138 — оба append'а `vol_reason` в `buy_reasons` и `sell_reasons`) и
   **перед** блоком «=== Принятие решения ===» (строка 139) добавь:
   ```python
   # --- ADX strong trend (≥ 25 — реальный «сильный» тренд, не просто > adx_min) ---
   if ind.adx >= 25.0:
       adx_strong_reason = f"ADX={ind.adx:.1f} (strong trend ≥ 25)"
       buy_reasons.append(adx_strong_reason)
       sell_reasons.append(adx_strong_reason)

   # --- DMI direction match (ассиметричный — даёт +1 только подходящей стороне) ---
   if ind.dmi_plus > ind.dmi_minus:
       buy_reasons.append(
           f"DMI+ > DMI- (+{ind.dmi_plus - ind.dmi_minus:.1f})"
       )
   else:
       sell_reasons.append(
           f"DMI- > DMI+ (+{ind.dmi_minus - ind.dmi_plus:.1f})"
       )
   ```
2. В обоих возвратах `return SignalResult(...)` (BUY на строках 146-157, SELL на
   строках 159-170) **убери** `+ [adx_reason, dmi_reason]` из `reasons=...`. Эти причины
   теперь уже сидят в `buy_reasons` / `sell_reasons` (см. шаг 1) — повторное добавление
   создаст дубли. Стало:
   ```python
   reasons=buy_reasons,
   ```
   и
   ```python
   reasons=sell_reasons,
   ```
3. Удали локальные переменные `adx_reason` и `dmi_reason` (строки 126-131) — они больше
   не используются.
4. Обнови знаменатель `/6` → `/8`:
    - `strategy/signal_engine.py:57` — `({self.score}/6)` → `({self.score}/8)`.
    - `bot/menu.py:289` — `({result.score}/6)` → `({result.score}/8)`.
    - `bot/menu.py:354` — то же.
   Sanity: `rg -n '/6\)' strategy bot` — после правок должен ничего не находить.
5. Порог `min_score = 4` (строка 144) — **оставь как есть**. Пропорция «4 of 8» ≈ «3 of 6»,
   чувствительность чуть мягче, и это намеренный side-effect рефакторинга.
   ⚠️ Если хочешь сохранить старую жёсткость — подними `min_score` до 5 и пересчитай тесты.
6. **Тесты** (`tests/test_signal.py`):
    - Найди все `assert result.score >= 4` / `assert result.score == N` — пересчитай.
      Для типичного полного сигнала (все 6 факторов + ADX-strong + DMI-match) ожидаемый score = 8.
    - При `20 ≤ ADX < 25` (тренд между `adx_min` и 25) score уменьшается на 1.
    - Запусти `pytest tests/test_signal.py -v` и обнови ассерты под фактические числа.

**Edge cases**:

- `ind.adx >= 25` уже подразумевает `adx_min == 20` пройден (фильтр флэта на строке 73).
  Без фильтра флэта `evaluate` вернёт `NO_SIGNAL` ещё раньше — добавочный балл не успеет.
- ADX и Volume оба дают `+1` обеим сторонам — перевес определяется EMA/RSI/MACD/DMI.
- DMI равные (`dmi_plus == dmi_minus`) — попадают в `else` (SELL). Это маргинальный случай,
  но не баг; альтернатива — не давать балл никому.

**Готовность**:

- `pytest tests/test_signal.py -v` зелёный.
- В Telegram сигнал показывает `(N/8)` (где `N` ≥ 4).
- `plan/06-signal-engine.md` и `plan/12-flowchart.md` синхронизированы.
  Sanity: `rg -n '/6' plan/` — не должно быть устаревших ссылок на старый знаменатель.
