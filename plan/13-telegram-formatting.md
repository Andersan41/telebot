# 5. Правила Telegram-форматирования

- **HTML-разметка**: `parse_mode=ParseMode.HTML` для всех сообщений.
- **Экранирование**: динамические строки — через `html.escape()` (особенно
  «ADX < 20», вычисляемые R/R, и любые подставляемые символы / тикеры).
- **Двойная обработка ошибок HTML** есть **только** в `_do_full_analysis()`
  (`bot/menu.py:137-140`): при `BadRequest` парсера выполняется
  `result.replace("<","&lt;").replace(">","&gt;")` и повторная отправка.
- **`_indicator_view` / `_format_indicator_view`** (`bot/menu.py:302-356`)
  второго fallback **не имеют** — один `html.escape()` на reasons
  (`menu.py:351`) и всё. Если в индикаторных reasons всплывёт неэкранированный
  HTML — сообщение упадёт без recovery.
- **`handle_menu_message`** (`bot/menu.py:181`) на втором падении отправляет
  ответ **без `parse_mode`** — HTML-теги при этом видны как сырой текст.
- **Лимиты**: сообщения не должны превышать ~4096 символов (Telegram).
- **`(score/8)`** — итоговый максимум `buy_score` / `sell_score`. См.
  [06-signal-engine.md](06-signal-engine.md).
