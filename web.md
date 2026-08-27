# Web Dashboard Audit

## Stack

- **Backend**: Python `aiohttp` (async HTTP + WebSocket server)
- **Frontend**: Vanilla JS (no framework), Chart.js 4.4.1 (CDN), CSS (custom dark theme)
- **Communication**: WebSocket (primary, real-time push), REST API (filters + open trades)
- **Entry point**: `web/server.py` → `create_app()` → started from `main.py` via `start_web_server()`

## File Structure

```
web/
├── __init__.py          # empty
├── server.py            # backend: WS handler, REST API, broadcast loop
└── public/
    ├── index.html       # single-page dashboard
    ├── css/
    │   └── dashboard.css  # all styles (dark theme, responsive)
    └── js/
        └── app.js       # all frontend logic (WS client, renderers)
```

## Configuration

From `config/settings.py` → `WebConfig`:

| Env Var | Default | Purpose |
|---------|---------|---------|
| `WEB_PORT` | `3002` | Server port |
| `WEB_HOST` | `0.0.0.0` | Bind address |
| `WEB_ENABLED` | `true` | Enable/disable |
| `WEB_UPDATE_INTERVAL` | `5` | Broadcast interval (seconds) |

## WebSocket Protocol

**Connection**: `ws://{host}:{port}/ws`

**Client → Server messages**:
```json
{"type": "subscribe", "symbol": "BTC"}
```
- Symbol auto-converted: `BTC` → `BTC/USDT` if no `/` present
- Default subscription: first symbol from `config.trading.symbols`

**Server → Client message types**:

### 1. `type: "update"` — Market data (pushed every `WEB_UPDATE_INTERVAL` seconds)

```json
{
  "type": "update",
  "symbol": "BTC/USDT",
  "timestamp": 1723000000000,
  "price": 61234.56,
  "indicators": { ... },
  "structure": { ... },
  "liquidity": { ... },
  "levels": { ... },
  "signal": { ... },
  "priceHistory": [ ... ]
}
```

#### `indicators` object (from `_compute_indicators` → `indicators/engine.py`)

| Field | Type | Description |
|-------|------|-------------|
| `value` | float | Current close price |
| `rsi` | float | RSI (1 decimal) |
| `macd` | float | MACD line |
| `macd_signal` | float | MACD signal line |
| `macd_hist` | float | MACD histogram |
| `ema_fast` | float | Fast EMA value |
| `ema_slow` | float | Slow EMA value |
| `ema_trend` | float | Trend EMA value |
| `adx` | float | ADX value |
| `dmi_plus` | float | DMI+ |
| `dmi_minus` | float | DMI- |
| `atr` | float | ATR value |
| `supertrend` | float | Supertrend level |
| `supertrend_direction` | int | 1=bull, -1=bear |
| `volume` | float | Current volume |
| `volume_sma` | float | Volume SMA |
| `volume_delta_pct` | float\|null | Volume delta % |
| `ema_bullish_cross` | bool | EMA bullish crossover |
| `ema_bearish_cross` | bool | EMA bearish crossover |
| `ema_bullish_alignment` | bool | EMAs aligned bullish |
| `ema_bearish_alignment` | bool | EMAs aligned bearish |
| `macd_bullish_cross` | bool | MACD bullish crossover |
| `macd_bearish_cross` | bool | MACD bearish crossover |
| `volume_above_avg` | bool | Volume > SMA |
| `trend_is_strong` | bool | ADX > threshold |
| `supertrend_bullish` | bool | Supertrend bullish |

**Data source**: `indicators.engine.indicator_engine.calculate(df, symbol, timeframe)` → `IndicatorValues` dataclass.

#### `structure` object (from `_compute_structure` → `market_structure/structure.py`)

```json
{
  "trend": "bullish" | "bearish" | "unknown",
  "bos": {
    "type": "bullish" | "bearish" | "none",
    "level": 61000.0
  },
  "swing_highs": [61500.0, 62000.0],
  "swing_lows": [60500.0, 60000.0]
}
```

**Data source**: `market_structure.structure.analyze_structure(df)` → `StructureState`.

#### `liquidity` object (from `_compute_liquidity`)

```json
{
  "order_blocks": [
    {"type": "bullish", "price": 60800.0}
  ],
  "fvg": [
    {"type": "bullish", "top": 61200.0, "bottom": 60900.0}
  ],
  "sweep": {
    "detected": true,
    "type": "bullish"
  }
}
```

**Data sources**:
- `liquidity.order_blocks.detect_order_blocks(df)` — last 3 OBs
- `liquidity.fvg.detect_fvg(df)` — last 3 FVGs
- `liquidity.sweep.detect_sweeps(df)` — latest sweep

#### `levels` object (from `_compute_sr_levels` → `strategy/levels.py`)

```json
{
  "resistance": [
    {"price": 62000.0, "strength": "medium"}
  ],
  "support": [
    {"price": 60000.0, "strength": "medium"}
  ]
}
```

Up to 3 resistance (sorted ↑) and 3 support (sorted ↓). Strength: `"strong"` | `"medium"` | `"weak"`.

**Data source**: `strategy.levels.get_support_resistance(df, last_price)` → dict with `resistance`/`support` lists.

#### `signal` object (from `_compute_signal_light`)

```json
{
  "signal": "BUY" | "SELL" | "NO_SIGNAL",
  "score": 3,
  "verdict": "СИЛЬНЫЙ" | "УМЕРЕННЫЙ" | "СЛАБЫЙ",
  "confidence": 75.0,
  "reasons": ["EMA fast > slow", "RSI 62 > 55", "MACD hist > 0"],
  "entry": 61234.56,
  "sl": null,
  "tp": null,
  "regime": null
}
```

Heuristic scoring (not the full pipeline):
- EMA fast vs slow: +1/-1
- RSI > 55 / < 45: +1/-1
- MACD hist > 0 / < 0: +1/-1
- ADX > 20 with DMI+ vs DMI-: +1/-1
- Score ≥ 2 → BUY, ≤ -2 → SELL, else NO_SIGNAL
- `confidence` = `|score| / 4 * 100`

#### `priceHistory` array

```json
[
  {"time": 1723000000000, "close": 61234.56}
]
```

Last 20 candles (close prices + timestamps in ms). Used for the Chart.js line chart.

### 2. `type: "open_trades"` — Open positions (pushed alongside updates)

```json
{
  "type": "open_trades",
  "trades": [
    {
      "id": 123,
      "symbol": "BTC/USDT",
      "timeframe": "1h",
      "signal_type": "BUY",
      "entry": 61234.56,
      "sl": 60500.0,
      "tp": 63000.0,
      "sent_at": "2025-08-10T12:00:00+00:00",
      "outcome_id": 456
    }
  ]
}
```

**Data source**: `storage.database.db.get_open_trades_with_signals()` → joins `SignalOutcome` (status=OPEN) with `Signal` table.

## REST API Endpoints

### `GET /api/filters`

Returns all active filter toggles (excluding hidden ones: `ema_slope`, `macd_slope`, `tp_path`).

```json
{
  "filters": [
    {"key": "context", "label": "Context", "enabled": true},
    {"key": "confidence_v2", "label": "Confidence V2", "enabled": false},
    ...
  ]
}
```

**Data source**: Iterates `FILTER_TOGGLE_KEYS` dict, reads from `config` singleton via `_get_nested_config`.

**Active filter keys** (shown in UI):

| Key | Label | Config path |
|-----|-------|-------------|
| `context` | Context | `context_enabled` |
| `confidence_v2` | Confidence V2 | `scoring.confidence_v2_enabled` |
| `signal_block` | Block Notify | `signal_block_notify` |
| `dynamic_risk` | Dyn Risk | `risk.dynamic_risk_enabled` |
| `require_entry_zone` | — | `require_entry_zone` |
| `reversal_require_displacement` | — | `reversal_require_displacement` |
| `htf_hard_gate` | — | `htf_hard_gate` |

### `POST /api/filters`

Toggle a filter on/off. Persists to DB.

```json
// Request
{"key": "context", "enabled": true}

// Response
{"ok": true, "key": "context", "enabled": true}
```

**Data source**: Writes to `config` singleton + `storage.database.db.set_setting("filter:toggle:{key}", "true")`.

### `GET /api/open-trades`

Same data as the WebSocket `open_trades` message. REST fallback for initial load.

### `GET /` and `GET /{path:.*}`

Serves `web/public/index.html` (SPA catch-all). Static files served from `web/public/`.

## Frontend Rendering (app.js)

### Init flow
1. `connect()` → opens WebSocket to `ws://{host}/ws`
2. `loadFilters()` → `GET /api/filters` → `renderFilters()`
3. `fetchOpenTrades()` → `GET /api/open-trades` → `renderOpenTrades()`
4. On WS `message`:
   - `type === "update"` → `renderDashboard(data)`
   - `type === "open_trades"` → `renderOpenTrades(data.trades)`

### `renderDashboard(data)` pipeline
1. Status bar update: `"Анализ активен · BTC $61,234"`
2. `renderIndicators(indicators)` — 6 cards: RSI, MACD, EMA, ADX, Supertrend, Volume
3. `renderSignal(signal)` — Signal card: type, score, entry/SL/TP, reasons
4. `renderLevelsData(levels)` — Resistance/support lists
5. `renderSMC(structure, liquidity)` — Smart Money items: BOS, OBs, FVG, sweep, trend
6. `updatePriceChart(priceHistory)` — Chart.js line chart (20 candles)
7. `renderVerdictFromSignal(signal, indicators)` — Verdict row: confidence, regime, trend strength
8. Optional (if data present): `renderOpenInterest()`, `renderVolumeProfile()`, `renderBookAnomalies()`

### UI Sections (HTML layout)

| Section | HTML ID | Data Source |
|---------|---------|-------------|
| Header/Status | `#statusText` | WS connection state + price |
| Token picker | `#tokenInput`, `.qtok` buttons | User input → `subscribe` WS msg |
| Signal card | `#signalCard` | `signal` object |
| 6 indicator cards | `#card-rsi`, `#card-macd`, `#card-ema`, `#card-adx`, `#card-st`, `#card-vol` | `indicators` object |
| Levels | `#resistance-list`, `#support-list` | `levels` object |
| Market Mind (AI) | `#verdict-main`, `#verdict-conf`, `#verdict-regime`, `#verdict-trend` | `signal` + `indicators` |
| Price chart | `#priceChart` (canvas) | `priceHistory` array |
| Smart Money | `#smc-list` | `structure` + `liquidity` |
| Filter toggles | `#filterList` | `GET /api/filters` |
| Open trades | `#tradesBody` | `GET /api/open-trades` or WS `open_trades` |

## Key Modules for Reproduction

| Module | Purpose |
|--------|---------|
| `data/exchange_client.py` | Fetches OHLCV candles from Binance (via ccxt) |
| `indicators/engine.py` | Calculates RSI, MACD, EMA, ADX, Supertrend, Volume |
| `market_structure/structure.py` | BOS detection, swing points, trend |
| `liquidity/order_blocks.py` | Order Block detection |
| `liquidity/fvg.py` | Fair Value Gap detection |
| `liquidity/sweep.py` | Liquidity sweep detection |
| `strategy/levels.py` | Support/Resistance calculation |
| `storage/database.py` | SQLite/async — open trades query |
| `config/settings.py` | All config, filter toggle registry |

## CSS Design Tokens

```css
/* Colors */
--bg:       #0d0d0d
--card-bg:  #1a1a1a
--text:     #e0e0e0
--muted:    #555
--bull:     #a3e635
--bear:     #f87171
--neutral:  #facc15

/* Fonts */
font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif
```

## Responsive Breakpoints

- `≤900px`: single-column main row, 2-col indicator grid
- `≤560px`: 2-col indicator grid, token search stacked, signal details single-col

## Broadcast Loop Flow

```
Every WEB_UPDATE_INTERVAL (5s):
  1. Collect unique symbols from connected clients
  2. For each symbol:
     a. Fetch 200 candles (primary TF, default 1h)
     b. Compute indicators, structure, liquidity, S/R levels, signal
     c. Build priceHistory (last 20 candles)
     d. Send JSON to all subscribed clients
  3. Fetch open trades from DB
  4. Broadcast to ALL clients
```
