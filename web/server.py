"""
web/server.py — WebSocket-сервер для дашборда в браузере

aiohttp: раздача статики + WebSocket хэндлеры.
Периодически рассчитывает индикаторы и broadcast updates всем клиентам.
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Set, Dict, Any, Optional

from aiohttp import web
from loguru import logger

import numpy as np

from config.settings import config

STATIC_DIR = Path(__file__).parent / "public"

# Глобальное состояние
_clients: Set[web.WebSocketResponse] = set()
_client_symbols: Dict[web.WebSocketResponse, str] = {}
_client_tfs: Dict[web.WebSocketResponse, str] = {}
_broadcast_task: Optional[asyncio.Task] = None

# Cache for OI/Funding (updated every 60s in background)
_deriv_cache: Dict[str, Dict[str, Any]] = {}  # {symbol: {"oi": ..., "fr": ..., "ts": ...}}


async def _fetch_candles(symbol: str, timeframe: str, limit: int = 200):
    """Получить свечи через exchange_client (sync в executor)."""
    from data.exchange_client import exchange_client
    if exchange_client._exchange is None:
        return None
    return await exchange_client.fetch_ohlcv(symbol, timeframe, limit=limit)


def _compute_indicators(df, symbol: str, timeframe: str) -> Optional[Dict[str, Any]]:
    """Рассчитать индикаторы и вернуть dict для JSON."""
    from indicators.engine import indicator_engine
    iv = indicator_engine.calculate(df, symbol, timeframe)
    if iv is None:
        return None
    return {
        "value": round(iv.close, 2),
        "rsi": round(iv.rsi, 1),
        "macd": round(iv.macd, 4),
        "macd_signal": round(iv.macd_signal, 4),
        "macd_hist": round(iv.macd_hist, 4),
        "ema_fast": round(iv.ema_fast, 2),
        "ema_slow": round(iv.ema_slow, 2),
        "ema_trend": round(iv.ema_trend, 2),
        "adx": round(iv.adx, 1),
        "dmi_plus": round(iv.dmi_plus, 1),
        "dmi_minus": round(iv.dmi_minus, 1),
        "atr": round(iv.atr, 4),
        "supertrend": round(iv.supertrend, 2),
        "supertrend_direction": iv.supertrend_direction,
        "volume": round(iv.volume, 2),
        "volume_sma": round(iv.volume_sma, 2),
        "volume_delta_pct": round(iv.volume_delta_pct, 1) if iv.volume_delta_pct is not None else None,
        "ema_bullish_cross": iv.ema_bullish_cross,
        "ema_bearish_cross": iv.ema_bearish_cross,
        "ema_bullish_alignment": iv.ema_bullish_alignment,
        "ema_bearish_alignment": iv.ema_bearish_alignment,
        "macd_bullish_cross": iv.macd_bullish_cross,
        "macd_bearish_cross": iv.macd_bearish_cross,
        "volume_above_avg": iv.volume_above_avg,
        "trend_is_strong": iv.trend_is_strong,
        "supertrend_bullish": iv.supertrend_bullish,
    }


def _compute_structure(df, symbol: str, timeframe: str) -> Dict[str, Any]:
    """Рассчитать рыночную структуру (BOS, swing points)."""
    from market_structure.structure import analyze_structure
    state = analyze_structure(df)
    return {
        "trend": state.trend if hasattr(state, "trend") else "unknown",
        "bos": {
            "type": state.last_bos.direction if state.last_bos and hasattr(state.last_bos, "direction") else "none",
            "level": round(state.last_bos.level, 2) if state.last_bos and hasattr(state.last_bos, "level") else None,
        } if state.last_bos else {"type": "none", "level": None},
        "swing_highs": [
            round(sp.price, 2)
            for sp in (state.swing_points[-5:] if state.swing_points else [])
            if hasattr(sp, "price") and hasattr(sp, "type") and sp.type == "high"
        ],
        "swing_lows": [
            round(sp.price, 2)
            for sp in (state.swing_points[-5:] if state.swing_points else [])
            if hasattr(sp, "price") and hasattr(sp, "type") and sp.type == "low"
        ],
    }


def _compute_liquidity(df, symbol: str, timeframe: str) -> Dict[str, Any]:
    """Рассчитать ликвидность (sweeps, OB, FVG, breakout quality)."""
    from liquidity.order_blocks import detect_order_blocks
    from liquidity.fvg import detect_fvg
    from liquidity.sweep import detect_sweeps

    obs = detect_order_blocks(df)
    fvgs = detect_fvg(df)
    sweeps = detect_sweeps(df)

    result = {
        "order_blocks": [
            {"type": getattr(ob, "type", ""), "price": round(getattr(ob, "midpoint", 0), 2)}
            for ob in (obs[-3:] if obs else [])
        ],
        "fvg": [
            {"type": getattr(f, "type", ""), "top": round(getattr(f, "top", 0), 2), "bottom": round(getattr(f, "bottom", 0), 2)}
            for f in (fvgs[-3:] if fvgs else [])
        ],
        "sweep": {
            "detected": len(sweeps) > 0 if sweeps else False,
            "type": getattr(sweeps[-1], "type", "") if sweeps else "",
        } if sweeps else {"detected": False, "type": ""},
    }

    return result


def _compute_sr_levels(df, symbol: str, timeframe: str) -> Dict[str, Any]:
    """Рассчитать уровни поддержки/сопротивления."""
    from strategy.levels import get_support_resistance
    last_price = float(df["close"].iloc[-1]) if len(df) > 0 else 0
    levels = get_support_resistance(df, last_price)
    if not levels:
        return {"resistance": [], "support": []}

    resistance = [{"price": round(p, 4), "strength": "medium"} for p in levels.get("resistance", [])]
    support = [{"price": round(p, 4), "strength": "medium"} for p in levels.get("support", [])]

    return {
        "resistance": sorted(resistance, key=lambda x: x["price"])[:3],
        "support": sorted(support, key=lambda x: -x["price"])[:3],
    }


async def _compute_footprint(symbol: str) -> Optional[Dict[str, Any]]:
    """Построить footprint chart из реального стакана биржи.

    Берём стакан (order book), группируем уровни по tick size,
    считаем объём bid/ask на каждом уровне.
    """
    from data.exchange_client import exchange_client

    book = await exchange_client.fetch_order_book(symbol, limit=50)
    if not book:
        return None

    bids = book.get("bids", [])
    asks = book.get("asks", [])
    if not bids and not asks:
        return None

    tick_size = exchange_client.get_tick_size(symbol) or 0.01

    def round_price(price):
        return round(round(price / tick_size) * tick_size, 10)

    levels: Dict[float, Dict[str, float]] = {}

    for price, qty in bids:
        rp = round_price(price)
        if rp not in levels:
            levels[rp] = {"bid": 0, "ask": 0}
        levels[rp]["bid"] += float(qty)

    for price, qty in asks:
        rp = round_price(price)
        if rp not in levels:
            levels[rp] = {"bid": 0, "ask": 0}
        levels[rp]["ask"] += float(qty)

    if not levels:
        return None

    sorted_prices = sorted(levels.keys())

    level_list = []
    for p in sorted_prices:
        level_list.append({
            "price": round(p, 6),
            "bid": round(levels[p]["bid"], 4),
            "ask": round(levels[p]["ask"], 4),
        })

    return {
        "levels": level_list,
        "tickSize": tick_size,
        "lastPrice": level_list[-1]["price"] if level_list else 0,
    }


async def _build_payload(symbol: str, timeframe: str = None) -> Dict[str, Any]:
    """Собрать полный payload для отправки клиенту."""
    try:
        from config.settings import config as cfg
        tf = timeframe or cfg.trading.primary_timeframes[0] if cfg.trading.primary_timeframes else "1h"

        df = await _fetch_candles(symbol, tf, limit=200)
        if df is None or df.empty:
            return {
                "type": "update",
                "symbol": symbol,
                "timestamp": int(time.time() * 1000),
                "error": "No data",
            }

        indicators = _compute_indicators(df, symbol, tf) or {}
        structure = _compute_structure(df, symbol, tf)
        liquidity = _compute_liquidity(df, symbol, tf)
        sr_levels = _compute_sr_levels(df, symbol, tf)
        signal_info = _compute_signal_light(df, symbol, tf)

        # Footprint removed — scan engine tab replaced it
        footprint = None

        # Open Interest + Funding Rate (from cache, non-blocking)
        oi_data = None
        funding_rate = None
        cached = _deriv_cache.get(symbol)
        if cached:
            oi_data = cached.get("oi")
            funding_rate = cached.get("fr")

        # Wave analysis (soft feature)
        wave_data = None
        if config.wave.enabled:
            try:
                from elliott_wave.analysis import analyze_waves
                from elliott_wave.wave_types import WaveDegree
                wave_analysis = analyze_waves(df, symbol, tf, degree=WaveDegree.MINOR)
                wave_data = wave_analysis.to_dict()
            except Exception as e:
                logger.debug(f"Wave analysis failed for {symbol}/{tf}: {e}")

        # CVD (Cumulative Volume Delta) — approximation from OHLCV
        cvd_data = None
        try:
            if len(df) > 1:
                closes = df["close"].values
                opens = df["open"].values
                volumes = df["volume"].values
                # Bullish candle: close > open → +volume
                # Bearish candle: close < open → -volume
                deltas = np.where(closes > opens, volumes,
                         np.where(closes < opens, -volumes, 0.0))
                cumulative = np.cumsum(deltas)
                # Last 50 candles for chart
                lookback = min(50, len(df))
                timestamps = []
                for idx in df.index[-lookback:]:
                    if hasattr(idx, 'timestamp'):
                        timestamps.append(int(idx.timestamp() * 1000))
                    else:
                        ts = int(idx)
                        timestamps.append(ts * 1000 if ts < 1e12 else ts)
                cvd_values = [round(float(v), 2) for v in cumulative[-lookback:]]
                cvd_deltas = [round(float(d), 2) for d in deltas[-lookback:]]
                current_cvd = round(float(cumulative[-1]), 2)
                # Determine CVD trend (last 10 candles)
                recent = cumulative[-min(10, len(cumulative)):]
                cvd_trend = "bullish" if len(recent) >= 2 and recent[-1] > recent[0] else \
                            "bearish" if len(recent) >= 2 and recent[-1] < recent[0] else "neutral"
                cvd_data = {
                    "timestamps": timestamps,
                    "cumulative": cvd_values,
                    "deltas": cvd_deltas,
                    "current": current_cvd,
                    "trend": cvd_trend,
                }
        except Exception as e:
            logger.debug(f"CVD failed for {symbol}/{tf}: {e}")

        # Volume Profile (POC/VAH/VAL)
        volume_profile = None
        try:
            from liquidity.volume_profile import compute_volume_profile
            vp = compute_volume_profile(df, bins=50, lookback=100)
            if vp and vp.is_valid:
                current_price = float(df["close"].iloc[-1]) if len(df) > 0 else 0
                profile = []
                if vp.volume_at_price:
                    max_vol = max(vp.volume_at_price.values()) if vp.volume_at_price else 1
                    for price, vol in sorted(vp.volume_at_price.items()):
                        profile.append({
                            "price": round(price, 2),
                            "volume": round(vol, 2),
                            "pct": round(vol / max_vol * 100, 1),
                        })
                volume_profile = {
                    "poc": round(vp.poc, 2),
                    "vah": round(vp.vah, 2),
                    "val": round(vp.val, 2),
                    "price_in_va": vp.price_in_value_area(current_price),
                    "price_range_pct": round(vp.price_range_pct, 2),
                    "profile": profile,
                }
        except Exception as e:
            logger.debug(f"Volume profile failed for {symbol}/{tf}: {e}")

        # Breakout Quality (AMD vs real)
        breakout_quality = None
        try:
            from liquidity.breakout_quality import classify_breakout
            bq = classify_breakout(df, lookback=40)
            if bq:
                breakout_quality = {
                    "verdict": bq.verdict,
                    "direction": bq.direction,
                    "score": bq.score,
                    "body_pct": round(bq.body_pct, 2),
                    "retention_pct": round(bq.retention_pct, 2),
                    "volume_ratio": round(bq.volume_ratio, 2),
                }
        except Exception as e:
            logger.debug(f"Breakout quality failed for {symbol}/{tf}: {e}")

        # Price history for chart (последние 20 свечей)
        price_history = []
        for _, row in df.tail(20).iterrows():
            ts = row.name  # timestamp — это индекс DataFrame
            if hasattr(ts, 'timestamp'):
                ts_ms = int(ts.timestamp() * 1000)
            else:
                ts_ms = int(ts)
            price_history.append({"time": ts_ms, "close": round(float(row["close"]), 2)})

        # Candle history for wave chart (все свечи из df, OHLC)
        candle_history = []
        for _, row in df.iterrows():
            ts = row.name
            if hasattr(ts, 'timestamp'):
                ts_sec = int(ts.timestamp())
            else:
                ts_sec = int(ts) // 1000 if int(ts) > 1e12 else int(ts)
            candle_history.append({
                "time": ts_sec,
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
            })

        # Wave overlay — segments с timestamp для отрисовки линий на графике
        wave_overlay = []
        if wave_data and wave_data.get("primary") and wave_data["primary"].get("segments"):
            for seg in wave_data["primary"]["segments"]:
                si = seg.get("start_index")
                ei = seg.get("end_index")
                if si is None or ei is None:
                    continue
                if si >= len(df) or ei >= len(df):
                    continue
                try:
                    start_ts = df.index[si]
                    end_ts = df.index[ei]
                    start_sec = int(start_ts.timestamp()) if hasattr(start_ts, 'timestamp') else int(start_ts) // 1000
                    end_sec = int(end_ts.timestamp()) if hasattr(end_ts, 'timestamp') else int(end_ts) // 1000
                    if start_sec > 0 and end_sec > 0:
                        wave_overlay.append({
                            "start_time": start_sec,
                            "start_price": seg.get("start_price", 0),
                            "end_time": end_sec,
                            "end_price": seg.get("end_price", 0),
                            "label": seg.get("label", ""),
                            "direction": seg.get("direction", "impulse"),
                        })
                except Exception:
                    pass

        return {
            "type": "update",
            "symbol": symbol,
            "timestamp": int(time.time() * 1000),
            "price": indicators.get("value", 0),
            "indicators": indicators,
            "structure": structure,
            "liquidity": liquidity,
            "levels": sr_levels,
            "signal": signal_info,
            "priceHistory": price_history,
            "candleHistory": candle_history,
            "waveOverlay": wave_overlay,
            "cvd": cvd_data,
            "openInterest": oi_data,
            "fundingRate": funding_rate,
            "volumeProfile": volume_profile,
            "breakoutQuality": breakout_quality,
        }
    except Exception as e:
        import traceback
        logger.error(f"Web payload error for {symbol}: {e}\n{traceback.format_exc()}")
        return {
            "type": "update",
            "symbol": symbol,
            "timestamp": int(time.time() * 1000),
            "error": str(e),
        }


def _compute_signal_light(df, symbol: str, timeframe: str) -> Dict[str, Any]:
    """Упрощённый сигнал для дашборда (indicator-only heuristic)."""
    from indicators.engine import indicator_engine
    iv = indicator_engine.calculate(df, symbol, timeframe)
    if iv is None:
        return {"signal": "NO_SIGNAL", "score": 0, "reasons": []}

    reasons = []
    score = 0

    if iv.ema_fast > iv.ema_slow:
        score += 1
        reasons.append("EMA fast > slow")
    elif iv.ema_fast < iv.ema_slow:
        score -= 1

    if iv.rsi > 55:
        score += 1
        reasons.append(f"RSI {iv.rsi:.0f} > 55")
    elif iv.rsi < 45:
        score -= 1

    if iv.macd_hist > 0:
        score += 1
        reasons.append("MACD hist > 0")
    elif iv.macd_hist < 0:
        score -= 1

    if iv.adx > 20:
        if iv.dmi_plus > iv.dmi_minus:
            score += 1
            reasons.append("ADX+ > ADX-")
        else:
            score -= 1

    if score >= 2:
        signal = "BUY"
    elif score <= -2:
        signal = "SELL"
    else:
        signal = "NO_SIGNAL"

    return {
        "signal": signal,
        "score": score,
        "verdict": "СИЛЬНЫЙ" if abs(score) >= 3 else "УМЕРЕННЫЙ" if abs(score) == 2 else "СЛАБЫЙ",
        "confidence": round(abs(score) / 4 * 100, 1),
        "reasons": reasons[:5],
        "entry": round(iv.close, 2),
        "sl": None,
        "tp": None,
        "regime": None,
    }


async def _broadcast_loop():
    """Фоновая задача: рассылает обновления каждые N секунд."""
    from storage.database import db
    while True:
        try:
            if _clients:
                # Группируем клиентов по (symbol, timeframe)
                groups: dict[tuple, list] = {}
                for ws in _clients:
                    sym = _client_symbols.get(ws, "BTC/USDT")
                    tf = _client_tfs.get(ws, "1h")
                    key = (sym, tf)
                    if key not in groups:
                        groups[key] = []
                    groups[key].append(ws)

                for (sym, tf), clients in groups.items():
                    payload = await _build_payload(sym, tf)
                    message = json.dumps(payload, default=str)
                    stale = set()
                    for ws in clients:
                        try:
                            await ws.send_str(message)
                        except Exception:
                            stale.add(ws)
                    _clients.difference_update(stale)

                # Рассылка открытых сделок всем клиентам
                try:
                    trades = await db.get_open_trades_with_signals()
                    trades_msg = json.dumps({"type": "open_trades", "trades": trades}, default=str)
                    stale = set()
                    for ws in _clients:
                        try:
                            await ws.send_str(trades_msg)
                        except Exception:
                            stale.add(ws)
                    _clients.difference_update(stale)
                except Exception as e:
                    logger.warning(f"Open trades broadcast error: {e}")

            await asyncio.sleep(config.web.update_interval)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Broadcast loop error: {e}")
            await asyncio.sleep(5)


async def _deriv_cache_updater():
    """Background task: update OI/funding cache every 60s."""
    while True:
        try:
            from data.exchange_client import exchange_client
            ex = exchange_client._exchange
            if ex is not None:
                # Update for all subscribed symbols
                symbols = set(_client_symbols.values())
                for symbol in symbols:
                    try:
                        ccxt_symbol = exchange_client._resolve_symbol(symbol)
                        fr, oi = None, None
                        if ex.has.get("fetchFundingRate"):
                            try:
                                r = await asyncio.get_event_loop().run_in_executor(
                                    None, ex.fetch_funding_rate, ccxt_symbol)
                                if r and r.get("fundingRate") is not None:
                                    fr = round(float(r["fundingRate"]) * 100, 4)
                            except Exception:
                                pass
                        if ex.has.get("fetchOpenInterest"):
                            try:
                                r = await asyncio.get_event_loop().run_in_executor(
                                    None, ex.fetch_open_interest, ccxt_symbol)
                                if r:
                                    val = r.get("openInterestAmount") or r.get("openInterestValue") or 0
                                    oi = {"value": float(val), "delta_pct": 0}
                            except Exception:
                                pass
                        _deriv_cache[symbol] = {"oi": oi, "fr": fr}
                    except Exception:
                        pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"Deriv cache update error: {e}")
        await asyncio.sleep(60)


# ─── HTTP handlers ──────────────────────────────────────────────────────

async def index_handler(request):
    """Отдаём index.html."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return web.FileResponse(index_path)
    return web.Response(text="Dashboard not built yet", status=404)


# ─── WebSocket handler ──────────────────────────────────────────────────

async def ws_handler(request):
    """Обработка WebSocket подключений."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Подписываем на символ и таймфрейм по умолчанию
    default_symbol = config.trading.symbols[0] if config.trading.symbols else "BTC/USDT"
    default_tf = config.trading.primary_timeframes[0] if config.trading.primary_timeframes else "1h"
    _clients.add(ws)
    _client_symbols[ws] = default_symbol
    _client_tfs[ws] = default_tf

    logger.info(f"WS client connected ({len(_clients)} total), default: {default_symbol} {default_tf}")

    try:
        # Отправить init с доступными таймфреймами
        await ws.send_json({
            "type": "init",
            "timeframes": config.trading.primary_timeframes,
            "currentTimeframe": default_tf,
        })

        # Отправить текущее состояние
        payload = await _build_payload(default_symbol, default_tf)
        await ws.send_json(payload)

        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    if data.get("type") == "subscribe" and data.get("symbol"):
                        new_symbol = data["symbol"].upper()
                        if "/" not in new_symbol:
                            new_symbol = new_symbol + "/USDT"
                        _client_symbols[ws] = new_symbol
                        logger.info(f"WS client subscribed to {new_symbol}")
                        tf = _client_tfs.get(ws, default_tf)
                        payload = await _build_payload(new_symbol, tf)
                        await ws.send_json(payload)
                    elif data.get("type") == "set_timeframe" and data.get("timeframe"):
                        new_tf = data["timeframe"]
                        _client_tfs[ws] = new_tf
                        logger.info(f"WS client timeframe → {new_tf}")
                        symbol = _client_symbols.get(ws, default_symbol)
                        payload = await _build_payload(symbol, new_tf)
                        await ws.send_json(payload)
                except json.JSONDecodeError:
                    pass
            elif msg.type == web.WSMsgType.ERROR:
                logger.warning(f"WS error: {ws.exception()}")
    finally:
        _clients.discard(ws)
        _client_symbols.pop(ws, None)
        _client_tfs.pop(ws, None)
        logger.info(f"WS client disconnected ({len(_clients)} remaining)")

    return ws


async def api_open_trades(request):
    """GET /api/open-trades — вернуть список открытых сделок."""
    from storage.database import db
    try:
        trades = await db.get_open_trades_with_signals()
        return web.json_response({"trades": trades})
    except Exception as e:
        logger.error(f"api_open_trades error: {e}")
        return web.json_response({"trades": [], "error": str(e)})


async def api_waves(request):
    """GET /api/waves/{symbol}/{timeframe} — Elliott Wave analysis."""
    symbol = request.match_info.get("symbol", "BTC/USDT").upper()
    timeframe = request.match_info.get("timeframe", "1h")
    if "/" not in symbol:
        symbol = symbol + "/USDT"
    try:
        df = await _fetch_candles(symbol, timeframe, limit=200)
        if df is None or df.empty:
            return web.json_response({"error": "No data"}, status=404)
        from elliott_wave.analysis import analyze_waves
        from elliott_wave.wave_types import WaveDegree
        result = analyze_waves(df, symbol, timeframe, degree=WaveDegree.MINOR)
        return web.json_response(result.to_dict())
    except Exception as e:
        logger.error(f"api_waves error: {e}")
        return web.json_response({"error": str(e)}, status=500)


# ─── Sandbox API ──────────────────────────────────────────────────────

async def api_sandbox_signals(request):
    """GET /api/sandbox/signals?symbol=BTC/USDT&timeframe=1h&limit=20

    Returns only ACCEPTED signals (from the `signals` table).
    """
    from storage.database import db
    symbol = request.query.get("symbol", None)
    timeframe = request.query.get("timeframe", None)
    limit = int(request.query.get("limit", "20"))
    try:
        signals = await db.get_recent_signals_for_sandbox(symbol=symbol, timeframe=timeframe, limit=limit)
        return web.json_response({"signals": signals})
    except Exception as e:
        logger.error(f"api_sandbox_signals error: {e}")
        return web.json_response({"signals": [], "error": str(e)})


async def api_sandbox_symbols(request):
    """GET /api/sandbox/symbols — distinct symbols with accepted signals."""
    from storage.database import db
    try:
        symbols = await db.get_signal_symbols()
        return web.json_response({"symbols": symbols})
    except Exception as e:
        logger.error(f"api_sandbox_symbols error: {e}")
        return web.json_response({"symbols": [], "error": str(e)})


async def api_sandbox_trace(request):
    """GET /api/sandbox/trace/{signal_id}"""
    from storage.database import db
    signal_id = int(request.match_info["signal_id"])
    try:
        trace = await db.get_visual_trace(signal_id)
        if not trace:
            return web.json_response({"error": "Signal not found"}, status=404)

        # Fetch OHLCV candles for the chart (with timeout)
        sig = trace["signal"]
        symbol = sig["symbol"]
        timeframe = sig["timeframe"]
        try:
            df = await asyncio.wait_for(_fetch_candles(symbol, timeframe, limit=200), timeout=10)
        except asyncio.TimeoutError:
            logger.warning(f"Timeout fetching candles for {symbol} {timeframe} in trace {signal_id}")
            df = None
        candles = []
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                ts = row.name
                ts_sec = int(ts.timestamp()) if hasattr(ts, "timestamp") else int(ts)
                candles.append({
                    "time": ts_sec,
                    "open": round(float(row["open"]), 2),
                    "high": round(float(row["high"]), 2),
                    "low": round(float(row["low"]), 2),
                    "close": round(float(row["close"]), 2),
                })

        # Convert visual timestamps to int (UNIX seconds)
        visual = trace.get("visual", {})
        for key in ("sweep", "mss", "bos"):
            if visual.get(key) and visual[key].get("time"):
                visual[key]["time"] = int(visual[key]["time"])
        for key in ("ob", "fvg"):
            if visual.get(key) and visual[key].get("time"):
                visual[key]["time"] = int(visual[key]["time"])

        return web.json_response({
            "signal": sig,
            "candles": candles,
            "visual": visual,
        })
    except Exception as e:
        logger.error(f"api_sandbox_trace error: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def api_sandbox_candles(request):
    """GET /api/sandbox/candles?symbol=BTC/USDT&timeframe=1h&limit=200"""
    symbol = request.query.get("symbol", "BTC/USDT")
    timeframe = request.query.get("timeframe", "1h")
    limit = int(request.query.get("limit", "200"))
    try:
        df = await _fetch_candles(symbol, timeframe, limit=limit)
        if df is None or df.empty:
            return web.json_response({"candles": [], "error": "No data"})
        candles = []
        for _, row in df.iterrows():
            ts = row.name
            ts_sec = int(ts.timestamp()) if hasattr(ts, "timestamp") else int(ts)
            candles.append({
                "time": ts_sec,
                "open": round(float(row["open"]), 2),
                "high": round(float(row["high"]), 2),
                "low": round(float(row["low"]), 2),
                "close": round(float(row["close"]), 2),
            })
        return web.json_response({"candles": candles})
    except Exception as e:
        logger.error(f"api_sandbox_candles error: {e}")
        return web.json_response({"candles": [], "error": str(e)})


# ─── Scan Stats API ──────────────────────────────────────────────────

async def api_scan_stats(request):
    """GET /api/scan-stats?hours=24 — funnel statistics from audit_log.

    Lightweight: aggregated counts only, no raw rows.
    """
    from storage.database import db
    hours = int(request.query.get("hours", "24"))
    hours = min(hours, 168)  # max 7 days
    try:
        stats = await db.get_scan_stats(hours=hours)
        return web.json_response(stats)
    except Exception as e:
        logger.error(f"api_scan_stats error: {e}")
        return web.json_response({"total_entries": 0, "stages": {}, "top_rejection_reasons": [], "error": str(e)})


# ─── App factory ────────────────────────────────────────────────────────

def create_app() -> web.Application:
    """Создаём aiohttp приложение."""

    @web.middleware
    async def no_cache_middleware(request, handler):
        response = await handler(request)
        if not request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response

    app = web.Application(middlewares=[no_cache_middleware])

    # API
    app.router.add_get("/api/open-trades", api_open_trades)
    app.router.add_get("/api/waves/{symbol}/{timeframe}", api_waves)
    app.router.add_get("/api/sandbox/signals", api_sandbox_signals)
    app.router.add_get("/api/sandbox/symbols", api_sandbox_symbols)
    app.router.add_get("/api/sandbox/trace/{signal_id}", api_sandbox_trace)
    app.router.add_get("/api/sandbox/candles", api_sandbox_candles)
    app.router.add_get("/api/scan-stats", api_scan_stats)

    # WebSocket
    app.router.add_get("/ws", ws_handler)

    # Статика
    if STATIC_DIR.exists():
        app.router.add_static("/css/", STATIC_DIR / "css", show_index=False)
        app.router.add_static("/js/", STATIC_DIR / "js", show_index=False)

    # Index
    app.router.add_get("/", index_handler)
    app.router.add_get("/{path:.*}", index_handler)

    return app


async def start_web_server():
    """Запуск веб-сервера (вызывается из main.py)."""
    global _broadcast_task

    if not config.web.enabled:
        logger.info("Web server disabled (WEB_ENABLED=false)")
        return

    app = create_app()

    # Запускаем broadcast loop + deriv cache updater
    _broadcast_task = asyncio.create_task(_broadcast_loop())
    asyncio.create_task(_deriv_cache_updater())

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, config.web.host, config.web.port)
    await site.start()

    logger.info(f"Web dashboard: http://{config.web.host}:{config.web.port}")

    # Не блокируем — возвращаем runner для shutdown
    return runner
