# Plan — ICT Analysis Menu (13.05.2026)

## Goal
Добавить в меню Telegram бота новый пункт "Анализ ICT" под "Авто-скан всех", с возможностью выбора токена из списка или ввода своего, с выводом ICT-анализа, силы тренда в % и уровней поддержки/сопротивления.

## Changes

### 1. `indicators/ict_engine.py`

**ICTSignal dataclass** — добавить поля:
```python
support_levels: List[float] = field(default_factory=list)
resistance_levels: List[float] = field(default_factory=list)
```

**Метод `analyze()`** — заполнять support/resistance levels:
- Support: swing lows, SSL, OB low, FVG low
- Resistance: swing highs, BSL, OB high, FVG high

### 2. `bot/menu.py`

**Импорт:**
```python
from indicators.ict_engine import ict_engine, ICTSignal, SignalType as ICTSignalType
```

**main_menu_keyboard()** — добавить кнопку (3-й ряд):
```python
[
    InlineKeyboardButton("📡 Авто-скан всех", callback_data="m:scan_all"),
    InlineKeyboardButton("🧠 Анализ ICT", callback_data="m:ict_analyze"),
],
[
    InlineKeyboardButton("⚙️ Настройки", callback_data="m:settings"),
]
```

**token_list_keyboard(cb_prefix)** — поддержка для ICT:
```python
if cb_prefix == "ict_analyze":
    rows.append([InlineKeyboardButton("✏️ Свой токен", callback_data="m:ict_custom_token")])
```

**handle_menu_callback()** — добавить обработчики:
- `m:ict_analyze` → показать токены с префиксом `ict_analyze`
- `m:ict_custom_token` → `WAITING[chat_id] = "ict_analyze"`, промпт для ввода
- `ict_analyze:<SYMBOL>` → вызвать `_do_ict_analysis(symbol)`

**handle_menu_message()** — добавить:
```python
elif state == "ict_analyze":
    symbol = _normalize_symbol(text)
    m = await context.bot.send_message(chat_id, f"⏳ Анализирую ICT <b>{symbol}</b>…", parse_mode=ParseMode.HTML)
    result = await _do_ict_analysis(symbol)
    await context.bot.edit_message_text(result, chat_id=chat_id, message_id=m.message_id, reply_markup=back_keyboard(), parse_mode=ParseMode.HTML)
```

**`_do_ict_analysis(symbol)`** — новая функция:
- Получить OHLCV для primary timeframe
- Вызвать `ict_engine.analyze(df)`
- Вычислить силу тренда: `strength = min(40 + (adx-20)*1.2, 100)` (ADX<20 → 0-40%, ADX≥20 → 40-100%)
- Отформатировать вывод

**Формат вывода:**
```
🧠 <b>ICT Анализ: BTC/USDT</b>

💰 Цена: 67,432.50

📈 Структура: BULLISH (BOS)
🌊 Сила тренда: 68% (ADX: 34.2)
📊 DMI: +DI 28.5 / -DI 15.3

📍 PD Array: DISCOUNT
⏰ Kill Zone: LONDON (HIGH)

🛡️ <b>Поддержка:</b>
  • 67,100.00 (Swing Low)
  • 66,800.00 (OB Low)
  • 66,500.00 (SSL)

🧱 <b>Сопротивление:</b>
  • 68,200.00 (Swing High)
  • 68,500.00 (BSL)

📦 OB: 66,800.00 – 67,200.00
🟩 FVG: 66,950.00 – 67,050.00

🎯 BUY
  Вход: 67,432.50
  SL: 66,500.00
  TP1: 68,200.00
  TP2: 68,500.00
  R/R: 1:2.45
  Уверенность: 5/7 ⭐⭐⭐

📈 <a href='https://www.tradingview.com/chart/?symbol=BINANCE:BTCUSDT'>Открыть график</a>
```

## Files to Change

1. `indicators/ict_engine.py` — добавить поля support/resistance в ICTSignal, заполнить в analyze()
2. `bot/menu.py` — добавить кнопку, обработчики callback, функцию _do_ict_analysis()

## Test

После изменений запустить:
```bash
pytest -v
```

---

## ✅ Completed (13.05.2026)

### Changes Made

**1. `indicators/ict_engine.py`:**
- Added `support_levels: List[float]` and `resistance_levels: List[float]` to `ICTSignal` dataclass
- In `analyze()`, computed levels from swing points, liquidity (BSL/SSL), OB zones, and FVG zones
- Passed levels to all `ICTSignal(...)` calls (both BUY/SELL and NO_SIGNAL returns)

**2. `bot/menu.py`:**
- Imported `ict_engine`, `ICTSignal`, `SignalType as ICTSignalType`
- Added `"🧠 Анализ ICT"` button (callback `m:ict_analyze`) as 3rd row in `main_menu_keyboard()`
- `token_list_keyboard()` supports `ict_analyze` prefix with its own `m:ict_custom_token` button
- Added callbacks: `m:ict_analyze`, `m:ict_custom_token`, `ict_analyze:<SYMBOL>`
- Added `_do_ict_analysis()` — fetches OHLCV → `ict_engine.analyze(df)` → formatted output with trend strength %, S/R levels, OB/FVG zones, kill zone, confidence
- Added `_calc_trend_strength(adx)` — maps ADX 0-20→0-40%, ADX 20-50→40-100%
- Added `_fmt_ict_signal()` helper
- Added `"ict_analyze"` state handling in `handle_menu_message()`

### Tests (new: 12 ICT engine + 16 ICT menu = 28 new tests)

**`tests/test_ict_engine.py`:**
- `TestSupportResistanceLevels` (8 tests): fields exist, populated on BUY/SELL, sorted, no duplicates, from swings/OB/liquidity

**`tests/test_ict_menu.py`** (new file, 16 tests):
- `TestKeyboardStructure` (5 tests): ICT button in main menu, 3 rows, custom token button, back button, original analyze unchanged
- `TestNormalizeSymbol` (5 tests)
- `TestFmtPrice` (5 tests)
- `TestCalcTrendStrength` (7 tests)

### Results
**185/185 tests pass** (was 157, added 28 new)