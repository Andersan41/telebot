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
    """Рассчитать ликвидность (sweeps, OB, FVG) с таймстампами для аннотаций на графике."""
    from liquidity.order_blocks import detect_order_blocks
    from liquidity.fvg import detect_fvg
    from liquidity.sweep import detect_sweeps

    obs = detect_order_blocks(df)
    fvgs = detect_fvg(df)
    sweeps = detect_sweeps(df)

    def _ts(candle_idx):
        """Convert candle index to UNIX timestamp seconds."""
        if candle_idx is None or candle_idx < 0 or candle_idx >= len(df):
            return None
        ts = df.index[candle_idx]
        if hasattr(ts, 'timestamp'):
            return int(ts.timestamp())
        try:
            v = int(ts)
            return v // 1000 if v > 1e12 else v
        except Exception:
            return None

    result = {
        "order_blocks": [
            {
                "type": getattr(ob, "type", ""),
                "price": round(getattr(ob, "midpoint", 0), 2),
                "high": round(getattr(ob, "high", 0), 2),
                "low": round(getattr(ob, "low", 0), 2),
                "time": _ts(getattr(ob, "candle_index", None)),
            }
            for ob in (obs[-3:] if obs else [])
        ],
        "fvg": [
            {
                "type": getattr(f, "type", ""),
                "top": round(getattr(f, "top", 0), 2),
                "bottom": round(getattr(f, "bottom", 0), 2),
                "time": _ts(getattr(f, "index", None)),
            }
            for f in (fvgs[-3:] if fvgs else [])
        ],
        "sweep": {
            "detected": len(sweeps) > 0 if sweeps else False,
            "type": getattr(sweeps[-1], "type", "") if sweeps else "",
            "time": _ts(getattr(sweeps[-1], "candle_index", None)) if sweeps else None,
            "swept_level": round(getattr(sweeps[-1], "swept_level", 0), 2) if sweeps else None,
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
            _last = df.iloc[-1]
            _bq_dir = "buy" if float(_last['close']) >= float(_last['open']) else "sell"
            _atr_val = float(df['high'].tail(14).sub(df['low'].tail(14)).mean()) if len(df) >= 14 else 0.0
            bq = classify_breakout(df, direction=_bq_dir, atr=_atr_val, lookback=40)
            if bq:
                breakout_quality = {
                    "verdict": bq.verdict,
                    "direction": bq.direction,
                    "score": bq.score,
                    "body_pct": round(bq.body_pct, 2),
                    "retention": bq.retention,
                    "volume_ratio": round(bq.volume_ratio, 2),
                }
        except Exception as e:
            logger.debug(f"Breakout quality failed for {symbol}/{tf}: {e}")

        # HTF structure (4H bias for Market Context)
        htf_structure = None
        try:
            from market_structure.structure import analyze_structure as analyze_htf
            htf_df = await _fetch_candles(symbol, "4h", limit=100)
            if htf_df is not None and not htf_df.empty:
                htf_state = analyze_htf(htf_df)
                htf_structure = {
                    "trend": htf_state.trend if hasattr(htf_state, "trend") else "unknown",
                    "bos_type": htf_state.last_bos.type if htf_state.last_bos and hasattr(htf_state.last_bos, "type") else None,
                    "mss_type": htf_state.last_mss.type if htf_state.last_mss and hasattr(htf_state.last_mss, "type") else None,
                }
        except Exception as e:
            logger.debug(f"HTF structure failed for {symbol}: {e}")

        # Dynamic decimals based on price magnitude
        def _price_decimals(price: float) -> int:
            if price >= 1000:
                return 2
            if price >= 1:
                return 4
            if price >= 0.01:
                return 6
            if price >= 0.001:
                return 8
            return 10

        _ref_price = float(df.iloc[-1]["close"]) if len(df) > 0 else 1.0
        _dec = _price_decimals(_ref_price)

        # Price history for chart (последние 20 свечей)
        price_history = []
        for _, row in df.tail(20).iterrows():
            ts = row.name
            if hasattr(ts, 'timestamp'):
                ts_ms = int(ts.timestamp() * 1000)
            else:
                ts_ms = int(ts)
            price_history.append({"time": ts_ms, "close": round(float(row["close"]), _dec)})

        # Candle history (OHLC)
        candle_history = []
        for _, row in df.iterrows():
            ts = row.name
            if hasattr(ts, 'timestamp'):
                ts_sec = int(ts.timestamp())
            else:
                ts_sec = int(ts) // 1000 if int(ts) > 1e12 else int(ts)
            candle_history.append({
                "time": ts_sec,
                "open": round(float(row["open"]), _dec),
                "high": round(float(row["high"]), _dec),
                "low": round(float(row["low"]), _dec),
                "close": round(float(row["close"]), _dec),
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

        # Fibonacci / Premium-Discount zones
        fib_zone = None
        try:
            from market_structure.premium_discount import classify_zone
            _swing_highs = structure.get("swing_highs", []) if structure else []
            _swing_lows = structure.get("swing_lows", []) if structure else []
            if _swing_highs and _swing_lows:
                _sh = max(_swing_highs)
                _sl = min(_swing_lows)
                _price = float(df["close"].iloc[-1]) if len(df) > 0 else 0
                if _sh > _sl and _price > 0:
                    zone = classify_zone(df, "bullish", _sh, _sl)
                    fib_zone = {
                        "zone_type": zone.zone_type.value,
                        "fib_level": round(zone.fib_level, 3),
                        "zone_low": round(zone.zone_price_low, 2),
                        "zone_high": round(zone.zone_price_high, 2),
                        "swing_high": round(_sh, 2),
                        "swing_low": round(_sl, 2),
                        "distance_to_premium_pct": round(zone.distance_to_premium_pct, 2),
                        "distance_to_discount_pct": round(zone.distance_to_discount_pct, 2),
                    }
        except Exception as e:
            logger.debug(f"Fib zone failed for {symbol}/{tf}: {e}")

        # Enrich S/R levels with distance from current price
        _current_price = float(df.iloc[-1]["close"]) if len(df) > 0 else 0
        if sr_levels and _current_price > 0:
            for r in sr_levels.get("resistance", []):
                if r.get("price") and r["price"] > 0:
                    r["distance_pct"] = round((r["price"] - _current_price) / _current_price * 100, 2)
            for s in sr_levels.get("support", []):
                if s.get("price") and s["price"] > 0:
                    s["distance_pct"] = round((_current_price - s["price"]) / _current_price * 100, 2)

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
            "fibZone": fib_zone,
            "htfStructure": htf_structure,
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
    """Упрощённый сигнал для дашборда (indicator-only heuristic) с обогащёнными данными."""
    from indicators.engine import indicator_engine
    iv = indicator_engine.calculate(df, symbol, timeframe)
    if iv is None:
        return {"signal": "NO_SIGNAL", "score": 0, "reasons": []}

    reasons = []
    score = 0
    factors_for = []    # factors pushing score positive (BUY)
    factors_against = [] # factors pushing score negative (SELL)

    # ── EMA ──
    if iv.ema_fast > iv.ema_slow:
        score += 1
        reasons.append("EMA fast > slow")
        factors_for.append({"factor": "EMA бычья", "weight": 1})
    elif iv.ema_fast < iv.ema_slow:
        score -= 1
        reasons.append("EMA fast < slow")
        factors_against.append({"factor": "EMA медвежья", "weight": -1})

    # ── RSI ──
    if iv.rsi > 55:
        score += 1
        reasons.append(f"RSI {iv.rsi:.0f} > 55")
        factors_for.append({"factor": f"RSI бычий ({iv.rsi:.0f})", "weight": 1})
    elif iv.rsi < 45:
        score -= 1
        reasons.append(f"RSI {iv.rsi:.0f} < 45")
        factors_against.append({"factor": f"RSI медвежий ({iv.rsi:.0f})", "weight": -1})

    # ── MACD ──
    if iv.macd_hist > 0:
        score += 1
        reasons.append("MACD hist > 0")
        factors_for.append({"factor": "MACD бычий", "weight": 1})
    elif iv.macd_hist < 0:
        score -= 1
        reasons.append("MACD hist < 0")
        factors_against.append({"factor": "MACD медвежий", "weight": -1})

    # ── ADX / DMI ──
    if iv.adx > 20:
        if iv.dmi_plus > iv.dmi_minus:
            score += 1
            reasons.append("ADX+ > ADX-")
            factors_for.append({"factor": f"DMI бычий ({iv.dmi_plus:.1f}/{iv.dmi_minus:.1f})", "weight": 1})
        else:
            score -= 1
            reasons.append("ADX- > ADX+")
            factors_against.append({"factor": f"DMI медвежий ({iv.dmi_plus:.1f}/{iv.dmi_minus:.1f})", "weight": -1})

    # ── Supertrend ──
    if iv.supertrend_bullish:
        factors_for.append({"factor": "Supertrend бычий", "weight": 1})
    elif iv.supertrend_bearish:
        factors_against.append({"factor": "Supertrend медвежий", "weight": -1})

    # ── Market Structure (BOS/MSS) ──
    try:
        from market_structure.structure import analyze_structure
        structure = analyze_structure(df)
        if structure.last_mss:
            mss_dir = structure.last_mss.type
            if mss_dir == "bearish":
                factors_against.append({"factor": "MSS медвежий", "weight": -1})
            elif mss_dir == "bullish":
                factors_for.append({"factor": "MSS бычий", "weight": 1})
        elif structure.last_bos:
            bos_dir = structure.last_bos.type
            if bos_dir == "bearish":
                factors_against.append({"factor": "BOS медвежий", "weight": -1})
            elif bos_dir == "bullish":
                factors_for.append({"factor": "BOS бычий", "weight": 1})
    except Exception:
        pass

    # ── Liquidity (Sweep) ──
    try:
        from liquidity.sweep import detect_sweeps
        sweeps = detect_sweeps(df, lookback=30, swing_window=2)
        if sweeps and sweeps[-1].is_valid:
            sw = sweeps[-1]
            if sw.type == "bullish":
                factors_for.append({"factor": "Liquidity Sweep бычий", "weight": 1})
            else:
                factors_against.append({"factor": "Liquidity Sweep медвежий", "weight": -1})
    except Exception:
        pass

    # ── Order Blocks ──
    try:
        from liquidity.order_blocks import detect_order_blocks
        obs = detect_order_blocks(df, lookback=50)
        valid_obs = [ob for ob in obs if ob.is_valid][-2:]
        for ob in valid_obs:
            if ob.type == "bullish":
                factors_for.append({"factor": f"Order Block бычий @ ${ob.midpoint:.4f}", "weight": 1})
            else:
                factors_against.append({"factor": f"Order Block медвежий @ ${ob.midpoint:.4f}", "weight": -1})
    except Exception:
        pass

    # ── FVG ──
    try:
        from liquidity.fvg import detect_fvg
        fvgs = detect_fvg(df, lookback=50)
        active_fvgs = [f for f in fvgs if f.is_active][-1:]
        for f in active_fvgs:
            if f.type == "bullish":
                factors_for.append({"factor": f"FVG бычий ${f.bottom:.4f}–${f.top:.4f}", "weight": 1})
            else:
                factors_against.append({"factor": f"FVG медвежий ${f.bottom:.4f}–${f.top:.4f}", "weight": -1})
    except Exception:
        pass

    # ── Premium/Discount zone ──
    try:
        from market_structure.premium_discount import classify_zone
        swing_highs = []
        swing_lows = []
        for sp in (structure.swing_points[-10:] if structure and hasattr(structure, 'swing_points') else []):
            if hasattr(sp, 'type') and sp.type == 'high':
                swing_highs.append(sp.price)
            elif hasattr(sp, 'type') and sp.type == 'low':
                swing_lows.append(sp.price)
        if swing_highs and swing_lows:
            sh, sl = max(swing_highs), min(swing_lows)
            if sh > sl:
                zone = classify_zone(df, "bullish", sh, sl)
                if zone.zone_type.value == "premium":
                    factors_against.append({"factor": f"Fib Premium ({zone.fib_level*100:.0f}%)", "weight": -1})
                elif zone.zone_type.value == "discount":
                    factors_for.append({"factor": f"Fib Discount ({zone.fib_level*100:.0f}%)", "weight": 1})
    except Exception:
        pass

    if score >= 2:
        signal = "BUY"
    elif score <= -2:
        signal = "SELL"
    else:
        signal = "NO_SIGNAL"

    # ── Regime detection ──
    regime = None
    if iv.adx >= 25:
        regime = "trending"
    elif iv.adx < 15:
        atr_pct = (iv.atr / iv.close * 100) if iv.close > 0 else 0
        if atr_pct > 3:
            regime = "volatile"
        else:
            regime = "range"
    else:
        regime = "range"

    # ── SL / TP calculation ──
    sl = None
    tp = None
    rr_ratio = None
    atr = iv.atr
    entry = round(iv.close, 4)

    try:
        from strategy.levels import get_support_resistance
        levels = get_support_resistance(df, entry)
        sr_list = levels.get("resistance", []) + levels.get("support", [])
    except Exception:
        sr_list = []

    if signal == "BUY" and atr > 0:
        sl = round(entry - atr * 1.5, 4)
        tp = round(entry + atr * 3.0, 4)
        risk = entry - sl
        reward = tp - entry
        rr_ratio = round(reward / risk, 2) if risk > 0 else None
    elif signal == "SELL" and atr > 0:
        sl = round(entry + atr * 1.5, 4)
        tp = round(entry - atr * 3.0, 4)
        risk = sl - entry
        reward = entry - tp
        rr_ratio = round(reward / risk, 2) if risk > 0 else None

    # ── HTF Bias (4H if available) ──
    htf_bias = None
    trend_strength = "Слабый" if iv.adx < 20 else "Умеренный" if iv.adx < 30 else "Сильный"
    trend_strength_text = f"{trend_strength} (ADX {iv.adx:.1f}, {timeframe.upper()})"

    try:
        from market_structure.structure import get_htf_directional_bias
        if len(df) >= 200:
            htf_bias = get_htf_directional_bias(df, df)
    except Exception:
        pass

    # ── Conflict explanation ──
    conflict_explanation = None
    st_bullish = iv.supertrend_bullish
    structure_bearish = False
    try:
        if structure and structure.trend == "bearish":
            structure_bearish = True
        if structure and structure.last_mss and structure.last_mss.type == "bearish":
            structure_bearish = True
    except Exception:
        pass

    if signal == "SELL" and st_bullish and not structure_bearish:
        conflict_explanation = (
            f"Краткосрочный тренд ({timeframe.upper()} Supertrend) бычий, "
            f"но индикаторы (RSI, MACD, DMI) медвежьи → сигнал идёт против локального тренда, риск повышен"
        )
    elif signal == "SELL" and st_bullish and structure_bearish:
        conflict_explanation = (
            f"Supertrend бычий, но структура рынка (MSS/BOS) медвежья → "
            f"сигнал следует за структурой, но против индикатора тренда"
        )
    elif signal == "BUY" and iv.supertrend_bearish:
        conflict_explanation = (
            f"Supertrend медвежий, но индикаторы бычьи → "
            f"сигнал идёт против тренда индикатора"
        )

    # ── Confidence ──
    total_factors = len(factors_for) + len(factors_against)
    if total_factors > 0:
        dominant = max(len(factors_for), len(factors_against))
        confidence = round(dominant / total_factors * 100, 1)
    else:
        confidence = 0

    verdict = "СИЛЬНЫЙ" if abs(score) >= 3 else "УМЕРЕННЫЙ" if abs(score) == 2 else "СЛАБЫЙ"

    return {
        "signal": signal,
        "score": score,
        "verdict": verdict,
        "confidence": confidence,
        "reasons": reasons[:5],
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "rr_ratio": rr_ratio,
        "regime": regime,
        "htf_bias": htf_bias,
        "trend_strength": trend_strength_text,
        "conflict_explanation": conflict_explanation,
        "score_factors_for": factors_for,
        "score_factors_against": factors_against,
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
        try:
            await ws.send_json({
                "type": "init",
                "timeframes": config.trading.primary_timeframes,
                "currentTimeframe": default_tf,
            })
        except ConnectionResetError:
            _clients.discard(ws)
            return ws

        # Отправить текущее состояние
        try:
            payload = await _build_payload(default_symbol, default_tf)
            await ws.send_json(payload)
        except ConnectionResetError:
            _clients.discard(ws)
            return ws

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
                        try:
                            await ws.send_json(payload)
                        except ConnectionResetError:
                            break
                    elif data.get("type") == "set_timeframe" and data.get("timeframe"):
                        new_tf = data["timeframe"]
                        _client_tfs[ws] = new_tf
                        logger.info(f"WS client timeframe → {new_tf}")
                        symbol = _client_symbols.get(ws, default_symbol)
                        payload = await _build_payload(symbol, new_tf)
                        try:
                            await ws.send_json(payload)
                        except ConnectionResetError:
                            break
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
            _ref = float(df.iloc[-1]["close"])
            _dec = 2 if _ref >= 1000 else 4 if _ref >= 1 else 6 if _ref >= 0.01 else 8 if _ref >= 0.001 else 10
            for _, row in df.iterrows():
                ts = row.name
                ts_sec = int(ts.timestamp()) if hasattr(ts, "timestamp") else int(ts)
                candles.append({
                    "time": ts_sec,
                    "open": round(float(row["open"]), _dec),
                    "high": round(float(row["high"]), _dec),
                    "low": round(float(row["low"]), _dec),
                    "close": round(float(row["close"]), _dec),
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


# ─── Token Report API ──────────────────────────────────────────────

_TOKEN_REPORT_CACHE: Dict[str, tuple] = {}  # symbol -> (monotonic_ts, data)
_TOKEN_REPORT_CACHE_TTL = 60  # seconds

async def api_token_report(request):
    """GET /api/token-report/{symbol} — detailed token analysis report."""
    from analytics.token_report import generate_token_report
    from analytics.token_formatter import format_token_report
    from data.exchange_client import exchange_client
    from indicators.engine import indicator_engine
    from context.fetcher import context_fetcher

    symbol = request.match_info.get("symbol", "").upper()
    if "/" not in symbol:
        symbol = f"{symbol}/USDT"

    cached = _TOKEN_REPORT_CACHE.get(symbol)
    if cached and time.monotonic() - cached[0] < _TOKEN_REPORT_CACHE_TTL:
        return web.json_response(cached[1])

    try:
        report = await generate_token_report(
            symbol=symbol,
            exchange_client=exchange_client,
            indicator_engine=indicator_engine,
            context_fetcher=context_fetcher,
        )

        if report is None:
            return web.json_response(
                {"error": f"Failed to generate report for {symbol}"},
                status=404,
            )

        # Convert report to dict for JSON serialization
        data = {
            "symbol": report.symbol,
            "price": report.price,
            "market_cap_rank": report.market_cap_rank,
            "volume_24h": report.volume_24h,
            "change_24h": report.change_24h,
            "change_7d": report.change_7d,
            "change_30d": report.change_30d,
            "indicators_1h": {
                "rsi": report.indicators_1h.rsi if report.indicators_1h else None,
                "rsi_signal": report.indicators_1h.rsi_signal if report.indicators_1h else None,
                "macd": report.indicators_1h.macd if report.indicators_1h else None,
                "macd_signal": report.indicators_1h.macd_signal if report.indicators_1h else None,
                "ema_fast": report.indicators_1h.ema_fast if report.indicators_1h else None,
                "ema_slow": report.indicators_1h.ema_slow if report.indicators_1h else None,
                "ema_signal": report.indicators_1h.ema_signal if report.indicators_1h else None,
                "adx": report.indicators_1h.adx if report.indicators_1h else None,
                "adx_signal": report.indicators_1h.adx_signal if report.indicators_1h else None,
                "supertrend": report.indicators_1h.supertrend if report.indicators_1h else None,
                "supertrend_signal": report.indicators_1h.supertrend_signal if report.indicators_1h else None,
                "volume_signal": report.indicators_1h.volume_signal if report.indicators_1h else None,
            } if report.indicators_1h else None,
            "indicators_4h": {
                "rsi": report.indicators_4h.rsi if report.indicators_4h else None,
                "rsi_signal": report.indicators_4h.rsi_signal if report.indicators_4h else None,
                "macd": report.indicators_4h.macd if report.indicators_4h else None,
                "macd_signal": report.indicators_4h.macd_signal if report.indicators_4h else None,
                "ema_fast": report.indicators_4h.ema_fast if report.indicators_4h else None,
                "ema_slow": report.indicators_4h.ema_slow if report.indicators_4h else None,
                "ema_signal": report.indicators_4h.ema_signal if report.indicators_4h else None,
                "adx": report.indicators_4h.adx if report.indicators_4h else None,
                "adx_signal": report.indicators_4h.adx_signal if report.indicators_4h else None,
                "supertrend": report.indicators_4h.supertrend if report.indicators_4h else None,
                "supertrend_signal": report.indicators_4h.supertrend_signal if report.indicators_4h else None,
                "volume_signal": report.indicators_4h.volume_signal if report.indicators_4h else None,
            } if report.indicators_4h else None,
            "fear_greed": report.fear_greed,
            "fear_greed_label": report.fear_greed_label,
            "funding_rate": report.funding_rate,
            "long_short_ratio": report.long_short_ratio,
            "open_interest": report.open_interest,
            "oi_delta": report.oi_delta,
            "resistance_1h": report.resistance_1h,
            "support_1h": report.support_1h,
            "resistance_4h": report.resistance_4h,
            "support_4h": report.support_4h,
            "strategies": [
                {
                    "type": s.type,
                    "direction": s.direction,
                    "entry": s.entry,
                    "stop_loss": s.stop_loss,
                    "tp1": s.tp1,
                    "tp2": s.tp2,
                    "tp3": s.tp3,
                    "rr_ratio": s.rr_ratio,
                    "reason": s.reason,
                    "confidence": s.confidence,
                    "entry_price": s.entry_price,
                    "sl_price": s.sl_price,
                    "tp1_price": s.tp1_price,
                    "tp2_price": s.tp2_price,
                    "tp3_price": s.tp3_price,
                    "rr1": s.rr1,
                    "rr2": s.rr2,
                }
                for s in report.strategies
            ],
            "observations": report.observations,
            "recommendation": report.recommendation,
            "recommendation_reason": report.recommendation_reason,
            "rec_votes": report.recommendation_votes,
            "formatted": format_token_report(report),
        }

        _TOKEN_REPORT_CACHE[symbol] = (time.monotonic(), data)
        return web.json_response(data)

    except Exception as e:
        logger.error(f"api_token_report error for {symbol}: {e}", exc_info=True)
        return web.json_response({"error": str(e)}, status=500)


# ─── Price Alerts API (вкладка Alerts) ────────────────────────────────────

def _normalize_alert_symbol(text) -> str:
    """BTCUSDT / BTC / btc/usdt -> BTC/USDT (как bot/menu.py::_normalize_symbol)."""
    s = str(text or "").upper().strip()
    if "/USDT" in s:
        return s.split("/")[0] + "/USDT"
    if s.endswith("USDT"):
        return s[:-4] + "/USDT"
    return s + "/USDT"


def _alert_to_dict(alert) -> dict:
    return {
        "id": alert.id,
        "symbol": alert.symbol,
        "price": alert.price,
        "direction": alert.direction,
        "active": alert.active,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "triggered_at": alert.triggered_at.isoformat() if alert.triggered_at else None,
        "triggered_price": alert.triggered_price,
    }


async def api_price_alerts(request):
    """GET /api/price-alerts - все алерты (активные и сработавшие)."""
    from storage.database import db
    try:
        alerts = await db.get_price_alerts(active_only=False)
        return web.json_response({"alerts": [_alert_to_dict(a) for a in alerts]})
    except Exception as e:
        logger.error(f"api_price_alerts error: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def api_price_alerts_create(request):
    """POST /api/price-alerts - {symbol, price, direction} -> 201 | 400/503.

    Первый POST-роут проекта: валидация символа/цены на стороне биржи,
    уровень должен лежать на несработавшей стороне (иначе алерт сработал
    бы мгновенно).
    """
    from data.exchange_client import exchange_client
    from storage.database import db

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    direction = str(body.get("direction", "")).upper().strip()
    if direction not in ("ABOVE", "BELOW", "ANY"):
        return web.json_response(
            {"error": "direction must be ABOVE, BELOW or ANY"}, status=400
        )

    symbol = _normalize_alert_symbol(body.get("symbol"))
    if not symbol or symbol == "/USDT":
        return web.json_response({"error": "symbol is required"}, status=400)

    try:
        price = float(body.get("price"))
    except (TypeError, ValueError):
        return web.json_response({"error": "price must be a number"}, status=400)
    if not price > 0:  # NaN/inf тоже отсекаются
        return web.json_response({"error": "price must be > 0"}, status=400)

    if not await exchange_client.is_symbol_available(symbol):
        return web.json_response(
            {"error": f"symbol {symbol} not available on exchange"}, status=400
        )

    current = await exchange_client.fetch_ticker_price(symbol)
    if current is None:
        return web.json_response(
            {"error": f"cannot fetch current price for {symbol}"}, status=503
        )

    if direction == "ABOVE" and current >= price:
        return web.json_response(
            {"error": f"current price {current} is already at/above target {price}"},
            status=400,
        )
    if direction == "BELOW" and current <= price:
        return web.json_response(
            {"error": f"current price {current} is already at/below target {price}"},
            status=400,
        )
    if direction == "ANY" and current == price:
        return web.json_response(
            {"error": "current price equals target"}, status=400
        )

    try:
        alert_id = await db.add_price_alert(
            symbol, price, direction, prev_price=current
        )
    except Exception as e:
        logger.error(f"api_price_alerts_create error: {e}")
        return web.json_response({"error": str(e)}, status=500)

    return web.json_response(
        {
            "id": alert_id,
            "symbol": symbol,
            "price": price,
            "direction": direction,
            "active": True,
            "current_price": current,
        },
        status=201,
    )


async def api_price_alerts_delete(request):
    """DELETE /api/price-alerts/{id}."""
    from storage.database import db
    try:
        alert_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "invalid id"}, status=400)
    try:
        deleted = await db.delete_price_alert(alert_id)
    except Exception as e:
        logger.error(f"api_price_alerts_delete error: {e}")
        return web.json_response({"error": str(e)}, status=500)
    if not deleted:
        return web.json_response({"error": f"alert {alert_id} not found"}, status=404)
    return web.json_response({"deleted": alert_id})


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
    # {symbol:.*} so "ETH/USDT" (with slash) also matches — plain {symbol} 404s
    app.router.add_get("/api/token-report/{symbol:.*}", api_token_report)

    # Price Alerts (вкладка Alerts)
    app.router.add_get("/api/price-alerts", api_price_alerts)
    app.router.add_post("/api/price-alerts", api_price_alerts_create)
    app.router.add_delete("/api/price-alerts/{id}", api_price_alerts_delete)

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
