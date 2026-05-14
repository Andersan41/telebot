# A5. 15M-подтверждение в меню `_do_full_analysis`

> **Статус**: ✅ сделано
> **Приоритет**: 🟡 medium — UX-разрыв между меню и реальной публикацией сигналов.
> **Зависимости**: нет.

**Цель**: меню «🔍 Анализ токена» (см. `bot/menu.py:232-299`) сейчас оценивает сигнал только
на primary_tf (`1h` по умолчанию). Пользователь видит «BUY», но scheduler этот же сигнал не
публикует, если 15M показывает противоположное направление (см. `scheduler/scanner.py:77-99`).
Привести вывод меню в соответствие со scheduler'ом — показать пользователю статус подтверждения.

**Файлы и точные места**:

| Файл                  | Что делать                                                        |
|-----------------------|-------------------------------------------------------------------|
| `bot/menu.py:232-299` | вставить блок 15M-подтверждения в `_do_full_analysis`             |
| `plan/09-bot.md`      | в разделе `_do_full_analysis` отметить, что теперь делает confirm |

**Предусловия**:

- В `bot/menu.py:225-229` уже определён `_get_indicators(symbol, timeframe)` — переиспользуем.
- `cfg = config.trading` уже инициализирован в `_do_full_analysis` (строка 234).
- `primary_tf = cfg.primary_timeframes[0]` (строка 235).

**Пошагово**:

1. В `bot/menu.py:_do_full_analysis` **после** строки 239 (`result = signal_engine.evaluate(ind)`)
   вставь блок подтверждения:
   ```python
   # --- 15M-подтверждение (зеркало логики scheduler.scanner.scan_symbol) ---
   confirm_tf = cfg.confirm_timeframe
   confirm_status = "—"
   if result.is_actionable and confirm_tf and confirm_tf != primary_tf:
       ind_confirm = await _get_indicators(symbol, confirm_tf)
       if ind_confirm is None:
           confirm_status = f"⚠️ нет данных {confirm_tf}"
       else:
           confirm_result = signal_engine.evaluate(ind_confirm)
           if confirm_result.signal == result.signal:
               confirm_status = f"✅ {confirm_tf} подтверждает"
           else:
               confirm_status = (
                   f"❌ {confirm_tf}: {confirm_result.signal.value}"
               )
   ```
2. В уже существующем блоке `lines = [...]` (формируется построчно через `lines.append`),
   **сразу после** строки с сообщением о флэте
   (`lines.append(f"  ❌ Флэт (ADX &lt; {config.trading.adx_min})")`) и **до** блока ATR
   (`lines.append(f"\n🌡 ATR ...")`) добавь:
   ```python
   lines.append(f"\n🔁 <b>Подтверждение {confirm_tf}:</b> {confirm_status}")
   ```
   ⚠️ Опирайся на содержимое строк (точные `lines.append(...)` выше), а не на номера —
   между релизами они смещаются.
   ⚠️ Использовать `html.escape` тут **не нужно** — `confirm_status` собирается из контролируемых
   литералов и `confirm_result.signal.value` (`BUY`/`SELL`/`NO_SIGNAL`).
3. **Не вырезай** показ деталей сигнала, если 15M не совпало — функция называется
   `analysis`, не `signal generation`. Аналитика идёт полностью, только пометка статуса.
4. В `plan/09-bot.md` найди раздел про `_do_full_analysis` и допиши абзац:
   «Дополнительно теперь делает confirmation lookup на `confirm_timeframe`
   (по умолчанию 15M) и выводит статус подтверждения, не блокируя показ аналитики».

**Edge cases**:

- `result.signal == NO_SIGNAL` → `result.is_actionable == False` → блок не выполняется,
  `confirm_status` остаётся `"—"`. Корректно.
- `confirm_tf == primary_tf` (юзер указал `CONFIRM_TIMEFRAME=1h`) → блок не выполняется,
  `confirm_status = "—"`. Корректно — подтверждать самим собой бессмысленно.
- `confirm_tf` — пустая строка в env → `if ... confirm_tf and ...` — блок пропускается.
- `_get_indicators` возвращает `None` (нет данных на 15M) → `"⚠️ нет данных {tf}"` —
  пользователь видит честный статус, аналитика на primary не страдает.

**Готовность**:

- Запусти бот: `python main.py`. В Telegram: `/menu → 🔍 Анализ токена → BTC`.
  В ответе должна появиться строка `🔁 Подтверждение 15m: ...`.
- Сравни вывод меню и сообщение от scheduler'а (`/scan` или авто-цикл) для того же символа:
  если меню показывает `❌ 15m: SELL` при BUY на 1H — scheduler этот сигнал **не** опубликует
  (увидишь `Signal NOT confirmed on 15m: ...` в логах).
- `pytest -v` зелёный (новых тестов не требует, но регрессии не должно быть).
