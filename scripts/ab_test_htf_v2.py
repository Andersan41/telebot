#!/usr/bin/env python3
"""
scripts/ab_test_htf_v2.py — A/B test comparing HTF bias approaches.

Compares three variants:
  v1:        htf_bias_v2=False, premium_discount=False (legacy HTF from backtest pipeline)
  v2:        htf_bias_v2=True,  premium_discount=False (get_htf_bias_v2 gate)
  v2+zones:  htf_bias_v2=True,  premium_discount=True  (v2 gate + zone quality multiplier)

Usage:
    python scripts/ab_test_htf_v2.py --days 90 --timeframe 4h
    python scripts/ab_test_htf_v2.py --symbols BTC/USDT,ETH/USDT --days 60
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Literal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loguru import logger
logger.disable("strategy.signal_engine")
logger.disable("indicators.engine")
logger.disable("strategy.pattern_engine")
logger.disable("risk.engine")
logger.disable("strategy.probability_engine")
logger.disable("strategy.trade_engine")

import numpy as np
import pandas as pd

from data.exchange_client import exchange_client
from indicators.engine import IndicatorEngine, IndicatorValues
from strategy.pattern_engine import pattern_engine, ICTSetup
from strategy.feature_builder import feature_builder
from strategy.probability_engine import probability_engine, TradeProbability
from risk.engine import risk_engine, PortfolioState, RiskDecision
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from liquidity.candle_quality import analyze_last_candle
from liquidity.ob_state import get_ob_tracker, get_ob_multiplier, OBState
from market_structure.structure import analyze_structure, calc_premium_discount_score, _detect_trend_from_df
from market_structure.htf_bias import get_htf_bias, HTFBias, extract_structure_dict
from market_structure.htf_bias_v2 import get_htf_bias_v2, HTFBiasResult
from market_structure.premium_discount import classify_zone, get_entry_zone_quality, ZoneResult
from config.settings import config

# ── Constants (mirror backtest/run_new_pipeline.py) ────────────────────
WARMUP = 80
COOLDOWN_BARS = 3
COMMISSION_PCT = 0.06
SLIPPAGE_PCT = 0.02
MAX_TRADE_DURATION = 72

ASSET_TYPES = {
    "BTC/USDT": "major",
    "ETH/USDT": "major",
    "ZRO/USDT": "L1",
}


# ── Dataclasses (mirror) ───────────────────────────────────────────────
@dataclass
class Trade:
    symbol: str
    direction: str
    entry_price: float
    entry_index: int
    entry_timestamp: str
    sl: float
    tp: float
    exit_price: float = 0.0
    exit_index: int = 0
    exit_timestamp: str = ""
    exit_reason: str = ""
    pnl_pct: float = 0.0
    net_pnl_pct: float = 0.0
    setup_type: str = ""
    p_tp: float = 0.0
    rr: float = 0.0
    mss_score: float = 0.0
    regime: str = ""


@dataclass
class SymbolResult:
    symbol: str
    timeframe: str
    trades: list[Trade] = field(default_factory=list)
    signals_generated: int = 0
    signals_rejected: int = 0
    rejection_reasons: dict = field(default_factory=dict)


# ── Trade simulation (mirror) ──────────────────────────────────────────
def simulate_trade(
    direction: str,
    entry_price: float,
    sl: float,
    tp: float,
    df: pd.DataFrame,
    entry_idx: int,
    symbol: str,
    setup_type: str = "",
    p_tp: float = 0.0,
    mss_score: float = 0.0,
    regime: str = "",
) -> Trade:
    trade = Trade(
        symbol=symbol,
        direction=direction,
        entry_price=entry_price,
        entry_index=entry_idx,
        entry_timestamp=str(df.index[entry_idx]),
        sl=sl,
        tp=tp,
        setup_type=setup_type,
        p_tp=p_tp,
        mss_score=mss_score,
        regime=regime,
    )
    for i in range(entry_idx + 1, min(entry_idx + MAX_TRADE_DURATION + 1, len(df))):
        high = float(df["high"].iloc[i])
        low = float(df["low"].iloc[i])
        if direction == "BUY":
            if low <= sl:
                trade.exit_price = sl
                trade.exit_index = i
                trade.exit_timestamp = str(df.index[i])
                trade.exit_reason = "sl"
                break
            elif high >= tp:
                trade.exit_price = tp
                trade.exit_index = i
                trade.exit_timestamp = str(df.index[i])
                trade.exit_reason = "tp"
                break
        else:
            if high >= sl:
                trade.exit_price = sl
                trade.exit_index = i
                trade.exit_timestamp = str(df.index[i])
                trade.exit_reason = "sl"
                break
            elif low <= tp:
                trade.exit_price = tp
                trade.exit_index = i
                trade.exit_timestamp = str(df.index[i])
                trade.exit_reason = "tp"
                break
    if not trade.exit_price:
        last_idx = min(entry_idx + MAX_TRADE_DURATION, len(df) - 1)
        trade.exit_price = float(df["close"].iloc[last_idx])
        trade.exit_index = last_idx
        trade.exit_timestamp = str(df.index[last_idx])
        trade.exit_reason = "timeout"
    if direction == "BUY":
        trade.pnl_pct = (trade.exit_price / entry_price - 1) * 100
    else:
        trade.pnl_pct = (1 - trade.exit_price / entry_price) * 100
    cost = COMMISSION_PCT * 2 + SLIPPAGE_PCT * 2
    trade.net_pnl_pct = trade.pnl_pct - cost
    risk = abs(entry_price - sl)
    if risk > 0:
        if direction == "BUY":
            reward = trade.exit_price - entry_price
        else:
            reward = entry_price - trade.exit_price
        trade.rr = reward / risk
    return trade


# ── HTF score from cache (mirror) ──────────────────────────────────────
def _calc_htf_score_from_cache(htf_data: dict, direction: str) -> float:
    if not htf_data:
        return 0.5
    bull = "bullish" if direction in ("buy", "bullish") else "bearish"
    same = 0
    opp = 0
    for tf, df_ in htf_data.items():
        trend = _detect_trend_from_df(df_)
        if trend == bull:
            same += 1
        elif trend != "ranging":
            opp += 1
    total = len(htf_data)
    if same == total:
        return 1.0
    if same == total - 1 and opp == 1:
        return 0.8
    if same >= 1 and opp <= 1:
        return 0.5
    if opp >= same and same >= 1:
        return 0.2
    return 0.5


# ── Parameterised backtest runner ──────────────────────────────────────
async def run_symbol_variant(
    symbol: str,
    timeframe: str,
    candles: int,
    use_htf_bias_v2: bool,
    use_premium_discount: bool,
) -> SymbolResult:
    """Run new pipeline backtest for one symbol, respecting feature flags."""
    result = SymbolResult(symbol=symbol, timeframe=timeframe)

    logger.info(f"Fetching {candles} candles for {symbol} {timeframe}...")
    raw = None
    for attempt in range(3):
        try:
            raw = await exchange_client.fetch_ohlcv_paginated(
                symbol, timeframe, total_limit=candles, page_size=998,
            )
            break
        except Exception as e:
            logger.warning(f"  Fetch attempt {attempt+1}/3 failed for {symbol}: {e}")
            if attempt < 2:
                await asyncio.sleep(5 * (attempt + 1))

    if raw is None or len(raw) < WARMUP + 20:
        logger.warning(f"Not enough data for {symbol}: {len(raw) if raw is not None else 0}")
        return result

    df = raw.copy()
    logger.info(f"{symbol}: {len(df)} candles, {df.index[0]} → {df.index[-1]}")

    # Pre-fetch HTF data (always fetch all TFs needed by either v1 or v2)
    htf_data = {}
    df_1w_full, df_1d_full, df_4h_full, df_1h_full = None, None, None, None
    for htf, limit in [("1w", 60), ("1d", 200), ("4h", 300), ("1h", 500)]:
        try:
            _df = await exchange_client.fetch_ohlcv(symbol, htf, limit=limit)
            if _df is not None and len(_df) >= 20:
                htf_data[htf] = _df
                if htf == "1w":
                    df_1w_full = _df
                elif htf == "1d":
                    df_1d_full = _df
                elif htf == "4h":
                    df_4h_full = _df
                elif htf == "1h":
                    df_1h_full = _df
        except Exception:
            pass

    # Pre-compute indicators
    ind_engine = IndicatorEngine()
    atr_history = []
    cooldown = 0

    for i in range(WARMUP, len(df)):
        window = df.iloc[:i + 1].copy()
        candle_time = df.index[i]

        # Slice HTF data to only include candles up to current time
        df_1w = df_1w_full[df_1w_full.index <= candle_time] if df_1w_full is not None else None
        df_1d = df_1d_full[df_1d_full.index <= candle_time] if df_1d_full is not None else None
        df_4h = df_4h_full[df_4h_full.index <= candle_time] if df_4h_full is not None else None
        df_1h = df_1h_full[df_1h_full.index <= candle_time] if df_1h_full is not None else None

        if cooldown > 0:
            cooldown -= 1
            continue

        try:
            ind = ind_engine.calculate(window, symbol, timeframe)
        except Exception:
            continue

        if ind is None or ind.atr is None or ind.atr <= 0:
            continue

        atr_history.append(ind.atr)
        if len(atr_history) > 100:
            atr_history.pop(0)

        current_price = float(ind.close)

        # ── Phase 1: Liquidity + Structure ──
        try:
            sweeps = detect_sweeps(window, lookback=50)
        except Exception:
            sweeps = []
        try:
            order_blocks = detect_order_blocks(window, lookback=100)
        except Exception:
            order_blocks = []
        try:
            fvgs = detect_fvg(window, lookback=100)
        except Exception:
            fvgs = []
        try:
            candle_quality = analyze_last_candle(window, atr_value=ind.atr)
        except Exception:
            candle_quality = None

        _disp_atr = 0.0
        if candle_quality and ind.atr and ind.atr > 0:
            _disp_atr = candle_quality.body_atr_ratio if hasattr(candle_quality, 'body_atr_ratio') else 0.0

        try:
            structure = analyze_structure(
                window, lookback=50,
                sweeps=sweeps,
                displacement_atr=_disp_atr,
                atr_value=ind.atr if ind.atr else 0.0,
            )
        except Exception:
            structure = None

        # ── Phase 2: Pattern Engine ──
        setup = pattern_engine.detect(
            sweeps=sweeps,
            order_blocks=order_blocks,
            structure=structure,
            fvgs=fvgs,
            candle_quality=candle_quality,
            current_price=current_price,
            atr=ind.atr,
        )

        if not setup.detected:
            result.signals_rejected += 1
            reason = setup.rejection_reason or "no_setup"
            result.rejection_reasons[reason] = result.rejection_reasons.get(reason, 0) + 1
            continue

        result.signals_generated += 1

        # ═══ PHASE 1.45: HTF BIAS GATE ═══
        _htf_bias_penalty = 1.0
        _htf_direction: Optional[str] = None  # 'bullish'/'bearish'/'neutral' for downstream zone logic

        if use_htf_bias_v2:
            # ── V2: get_htf_bias_v2 (W1→D1→H4→H1, EMA + BOS) ──
            try:
                _htf_result = get_htf_bias_v2(df_1w, df_1d, df_4h, df_1h)
                htf_bias_str = _htf_result.direction
                if htf_bias_str == 'bullish':
                    _bias_enum = HTFBias.BULLISH
                elif htf_bias_str == 'bearish':
                    _bias_enum = HTFBias.BEARISH
                else:
                    _bias_enum = HTFBias.NEUTRAL
                _htf_direction = htf_bias_str

                if _bias_enum != HTFBias.NEUTRAL:
                    direction_map = {"buy": HTFBias.BULLISH, "sell": HTFBias.BEARISH}
                    setup_bias = direction_map.get(setup.direction)

                    if setup.setup_type == "continuation":
                        if setup_bias != _bias_enum:
                            result.signals_rejected += 1
                            result.rejection_reasons[f"htf_bias_v2_{setup.direction}_vs_{htf_bias_str}"] = \
                                result.rejection_reasons.get(f"htf_bias_v2_{setup.direction}_vs_{htf_bias_str}", 0) + 1
                            continue
                    elif setup.setup_type == "reversal":
                        if setup_bias != _bias_enum:
                            _htf_bias_penalty = 0.85
            except Exception:
                pass

        else:
            # ── V1: legacy get_htf_bias (structure-based) ──
            try:
                _struct_1d = extract_structure_dict(structure) if structure else None
                htf_bias = get_htf_bias(
                    df_1d=None, df_4h=None,
                    structure_1d=_struct_1d, structure_4h=None,
                )
                _htf_direction = htf_bias.value

                if htf_bias != HTFBias.NEUTRAL:
                    direction_map = {"buy": HTFBias.BULLISH, "sell": HTFBias.BEARISH}
                    setup_bias = direction_map.get(setup.direction)
                    if setup_bias != htf_bias:
                        if setup.setup_type == "continuation":
                            result.signals_rejected += 1
                            result.rejection_reasons[f"htf_bias_{setup.direction}_vs_{htf_bias.value}"] = \
                                result.rejection_reasons.get(f"htf_bias_{setup.direction}_vs_{htf_bias.value}", 0) + 1
                            continue
                        elif setup.setup_type == "reversal":
                            _htf_bias_penalty = 0.85
            except Exception:
                pass

        # ── Asset-type directional filter: block SHORT on L1 tokens ──
        if setup.direction.lower() == "sell" and ASSET_TYPES.get(symbol) == "L1":
            result.signals_rejected += 1
            result.rejection_reasons["l1_short_blocked"] = \
                result.rejection_reasons.get("l1_short_blocked", 0) + 1
            continue

        # ── Phase 1.5: Build Trade Plan (SL/TP) ──
        try:
            from strategy.trade_engine import trade_engine
            trade_plan = trade_engine.build_trade_plan(
                ind=ind,
                direction=setup.direction,
                structure=structure,
                order_blocks=order_blocks,
                sweeps=sweeps,
                fvgs=fvgs,
                df=window,
                timeframe=timeframe,
            )
            sl = trade_plan.sl
            tp = trade_plan.tp
        except Exception as e:
            logger.debug(f"Trade plan failed: {e}")
            result.signals_rejected += 1
            result.rejection_reasons["trade_plan_failed"] = result.rejection_reasons.get("trade_plan_failed", 0) + 1
            continue

        if sl is None or tp is None:
            result.signals_rejected += 1
            result.rejection_reasons["sl_tp_failed"] = result.rejection_reasons.get("sl_tp_failed", 0) + 1
            continue

        # ── Phase 3: HTF Alignment + Premium/Discount scores ──
        htf_score = None
        pd_score = None
        try:
            htf_score = _calc_htf_score_from_cache(htf_data, setup.direction)
        except Exception:
            pass
        try:
            pd_score = calc_premium_discount_score(window, setup.direction)
        except Exception:
            pass

        # ── Phase 3.5: Feature Builder ──
        try:
            features = feature_builder.build(
                setup=setup,
                ind=ind,
                structure=structure,
                regime=None,
                vol_regime=None,
                mtf_aligned=False,
                mtf_count=0,
                context_score=0.0,
                fear_greed=None,
                funding_rate=None,
                sl=sl,
                tp=tp,
                entry_price=current_price,
                candle_quality=candle_quality,
                htf_alignment_score=htf_score,
                premium_discount_score=pd_score,
                htf_bias_penalty=_htf_bias_penalty,
            )
        except Exception as e:
            logger.debug(f"Feature builder failed: {e}")
            continue

        # ── Phase 4: Probability Engine ──
        try:
            probability = probability_engine.predict(features)
        except Exception as e:
            logger.debug(f"Probability engine failed: {e}")
            continue

        # ═══ Premium/Discount Zone Quality Multiplier ═══
        if use_premium_discount and _htf_direction is not None:
            try:
                _swing_high = None
                _swing_low = None
                if structure and structure.recent_highs and structure.recent_lows:
                    _swing_high = max(structure.recent_highs)
                    _swing_low = min(structure.recent_lows)
                if _swing_high is None or _swing_low is None or _swing_high <= _swing_low:
                    _lookback = min(50, len(df))
                    _swing_high = float(df['high'].tail(_lookback).max())
                    _swing_low = float(df['low'].tail(_lookback).min())

                zone_result = classify_zone(df, _htf_direction, _swing_high, _swing_low)
                _zone_quality_multiplier = get_entry_zone_quality(
                    zone_result, _htf_direction, setup.setup_type,
                )
                if _zone_quality_multiplier != 1.0:
                    probability.p_tp = min(probability.p_tp * _zone_quality_multiplier, 1.0)
            except Exception:
                pass

        if probability.p_tp < 0.40:
            result.signals_rejected += 1
            result.rejection_reasons["low_p_tp"] = result.rejection_reasons.get("low_p_tp", 0) + 1
            continue

        # ── Phase 5: Risk Engine ──
        try:
            portfolio = PortfolioState(
                active_count=0,
                total_risk_pct=0.0,
            )
            decision = risk_engine.evaluate(
                features=features,
                probability=probability,
                portfolio=portfolio,
                entry_price=current_price,
                sl=sl,
                tp=tp,
                mss_quality=setup.mss_score if setup.has_mss else 0.0,
            )
        except Exception as e:
            logger.debug(f"Risk engine failed: {e}")
            continue

        if not decision.should_trade:
            result.signals_rejected += 1
            reason = decision.rejection_reason or "risk_blocked"
            result.rejection_reasons[reason] = result.rejection_reasons.get(reason, 0) + 1
            continue

        final_sl = decision.sl_price if decision.sl_price else sl
        final_tp = decision.tp_price if decision.tp_price else tp

        trade = simulate_trade(
            direction=setup.direction.upper(),
            entry_price=current_price,
            sl=final_sl,
            tp=final_tp,
            df=df,
            entry_idx=i,
            symbol=symbol,
            setup_type=setup.setup_type or "unknown",
            p_tp=probability.p_tp,
            mss_score=setup.mss_score if setup.has_mss else 0.0,
            regime=structure.trend if structure else "unknown",
        )

        result.trades.append(trade)
        cooldown = COOLDOWN_BARS

    return result


# ── Statistics ─────────────────────────────────────────────────────────
def compute_stats(result: SymbolResult) -> dict:
    trades = result.trades
    if not trades:
        return {"symbol": result.symbol, "total": 0}

    pnls = [t.net_pnl_pct for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total = len(trades)
    win_count = len(wins)
    wr = win_count / total * 100 if total else 0
    avg_pnl = np.mean(pnls) if pnls else 0
    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float("inf")

    if len(pnls) > 1:
        sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(8760) if np.std(pnls) > 0 else 0
    else:
        sharpe = 0

    cumulative = np.cumsum(pnls)
    peak = np.maximum.accumulate(cumulative)
    dd = peak - cumulative
    max_dd = np.max(dd) if len(dd) > 0 else 0

    total_bars_in_trade = sum(t.exit_index - t.entry_index for t in trades)
    total_bars = len(trades) * (trades[-1].entry_index - trades[0].entry_index + 1) if len(trades) > 1 else 1
    exposure = total_bars_in_trade / max(total_bars, 1) * 100

    avg_duration = np.mean([t.exit_index - t.entry_index for t in trades])

    buys = [t for t in trades if t.direction == "BUY"]
    sells = [t for t in trades if t.direction == "SELL"]
    buy_wr = len([t for t in buys if t.net_pnl_pct > 0]) / len(buys) * 100 if buys else 0
    sell_wr = len([t for t in sells if t.net_pnl_pct > 0]) / len(sells) * 100 if sells else 0

    reversals = [t for t in trades if t.setup_type == "reversal"]
    continuations = [t for t in trades if t.setup_type == "continuation"]
    rev_wr = len([t for t in reversals if t.net_pnl_pct > 0]) / len(reversals) * 100 if reversals else 0
    cont_wr = len([t for t in continuations if t.net_pnl_pct > 0]) / len(continuations) * 100 if continuations else 0

    return {
        "symbol": result.symbol,
        "total": total,
        "wins": win_count,
        "losses": total - win_count,
        "winrate": round(wr, 1),
        "avg_pnl": round(avg_pnl, 3),
        "avg_win": round(avg_win, 3),
        "avg_loss": round(avg_loss, 3),
        "profit_factor": round(pf, 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_dd, 2),
        "total_pnl": round(sum(pnls), 2),
        "avg_rr": round(np.mean([t.rr for t in trades]), 2),
        "exposure_pct": round(exposure, 1),
        "avg_duration_bars": round(avg_duration, 1),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "buy_wr": round(buy_wr, 1),
        "sell_wr": round(sell_wr, 1),
        "reversal_count": len(reversals),
        "continuation_count": len(continuations),
        "reversal_wr": round(rev_wr, 1),
        "continuation_wr": round(cont_wr, 1),
        "signals_generated": result.signals_generated,
        "signals_rejected": result.signals_rejected,
        "rejection_reasons": result.rejection_reasons,
    }


# ── Main ───────────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(
        description="A/B test: compare v1 vs v2 vs v2+zones HTF bias approaches",
    )
    parser.add_argument("--days", type=int, default=90, help="Days of history")
    parser.add_argument("--timeframe", default="4h", help="Primary timeframe")
    parser.add_argument("--symbols", default="BTC/USDT,ETH/USDT,ZRO/USDT",
                        help="Comma-separated symbols")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",")]
    timeframe = args.timeframe
    days = args.days
    candles = days * 24 + WARMUP + 50

    variants = [
        {"name": "v1", "use_htf_bias_v2": False, "use_premium_discount": False},
        {"name": "v2", "use_htf_bias_v2": True, "use_premium_discount": False},
        {"name": "v2+zones", "use_htf_bias_v2": True, "use_premium_discount": True},
    ]

    out_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "reports", "ab_test_htf_v2",
    )
    os.makedirs(out_dir, exist_ok=True)

    await exchange_client.connect()
    logger.info("Exchange connected.\n")

    all_variant_results = {}

    for variant in variants:
        label = variant["name"]
        use_v2 = variant["use_htf_bias_v2"]
        use_zones = variant["use_premium_discount"]

        logger.info(f"{'='*60}")
        logger.info(f"  VARIANT: {label}  (htf_bias_v2={use_v2}, premium_discount={use_zones})")
        logger.info(f"{'='*60}\n")

        # Set config flags (so any downstream code that checks them sees the right values)
        config.htf_bias_v2 = use_v2
        config.premium_discount = use_zones

        variant_start = time.time()
        results = []
        all_trades = []

        for idx, symbol in enumerate(symbols):
            if idx > 0:
                await asyncio.sleep(3)
            t0 = time.time()
            res = await run_symbol_variant(symbol, timeframe, candles, use_v2, use_zones)
            elapsed = time.time() - t0
            stats = compute_stats(res)
            results.append(stats)
            all_trades.extend(res.trades)

            logger.info(
                f"  {symbol}: {stats['total']} trades | "
                f"WR={stats.get('winrate', 0)}% | "
                f"PF={stats.get('profit_factor', 0)} | "
                f"PnL={stats.get('total_pnl', 0):+.2f}% | "
                f"({elapsed:.1f}s)"
            )

        variant_elapsed = time.time() - variant_start

        # Aggregate
        total_trades = sum(s["total"] for s in results)
        total_wins = sum(s.get("wins", 0) for s in results)
        total_losses = sum(s.get("losses", 0) for s in results)
        overall_wr = total_wins / total_trades * 100 if total_trades else 0
        all_pnls = [t.net_pnl_pct for t in all_trades]
        total_pnl = sum(all_pnls)
        wins_pnl = [p for p in all_pnls if p > 0]
        losses_pnl = [p for p in all_pnls if p <= 0]
        overall_pf = (sum(wins_pnl) / abs(sum(losses_pnl))) if losses_pnl and sum(losses_pnl) != 0 else float("inf")
        if len(all_pnls) > 1 and np.std(all_pnls) > 0:
            overall_sharpe = np.mean(all_pnls) / np.std(all_pnls) * np.sqrt(8760)
        else:
            overall_sharpe = 0

        # Aggregate rejection reasons
        agg_reasons = {}
        for s in results:
            for reason, count in s.get("rejection_reasons", {}).items():
                agg_reasons[reason] = agg_reasons.get(reason, 0) + count

        agg = {
            "total_trades": total_trades,
            "wins": total_wins,
            "losses": total_losses,
            "winrate": round(overall_wr, 1),
            "profit_factor": round(overall_pf, 2),
            "sharpe": round(overall_sharpe, 2),
            "total_pnl": round(total_pnl, 2),
            "avg_pnl": round(np.mean(all_pnls), 3) if all_pnls else 0,
            "elapsed_sec": round(variant_elapsed, 1),
            "rejection_reasons": dict(sorted(agg_reasons.items(), key=lambda x: -x[1])),
        }

        all_variant_results[label] = {"aggregate": agg, "per_symbol": results}

        logger.info(f"\n  [{label}] Aggregate: "
                     f"{total_trades} trades | "
                     f"WR={overall_wr:.1f}% | "
                     f"PF={overall_pf:.2f} | "
                     f"Sharpe={overall_sharpe:.2f} | "
                     f"PnL={total_pnl:+.2f}% | "
                     f"({variant_elapsed:.1f}s)\n")

        # Save per-variant detail
        variant_path = os.path.join(out_dir, f"{label}.json")
        with open(variant_path, "w", encoding="utf-8") as f:
            json.dump(all_variant_results[label], f, indent=2, default=str)
        logger.info(f"  Saved: {variant_path}")

    # ── Comparison table ────────────────────────────────────────────────
    logger.info(f"\n{'='*70}")
    logger.info(f"  A/B COMPARISON — {args.timeframe} / {args.days}d")
    logger.info(f"{'='*70}\n")

    header = f"{'Variant':<12} {'Trades':>7} {'WR%':>6} {'PF':>7} {'Sharpe':>7} {'PnL%':>9} {'Time':>7}"
    sep = "─" * len(header)
    logger.info(header)
    logger.info(sep)

    for variant in variants:
        label = variant["name"]
        a = all_variant_results[label]["aggregate"]
        logger.info(
            f"{label:<12} {a['total_trades']:>7} {a['winrate']:>5.1f}% "
            f"{a['profit_factor']:>7.2f} {a['sharpe']:>7.2f} "
            f"{a['total_pnl']:>+8.2f}% {a['elapsed_sec']:>6.1f}s"
        )

    # ── Per-symbol comparison ──
    logger.info(f"\n{'='*70}")
    logger.info(f"  PER-SYMBOL COMPARISON")
    logger.info(f"{'='*70}\n")

    for symbol in symbols:
        short = symbol.replace("/", "")
        logger.info(f"  {symbol}:")
        hdr = f"{'Variant':<12} {'Trades':>6} {'WR%':>6} {'PF':>7} {'PnL%':>9} {'Rev':>5} {'Cont':>5}"
        logger.info(f"    {hdr}")
        logger.info(f"    {'─'*len(hdr)}")
        for variant in variants:
            label = variant["name"]
            sym_stats = None
            for s in all_variant_results[label]["per_symbol"]:
                if s["symbol"] == symbol:
                    sym_stats = s
                    break
            if sym_stats:
                logger.info(
                    f"    {label:<12} {sym_stats['total']:>6} {sym_stats.get('winrate', 0):>5.1f}% "
                    f"{sym_stats.get('profit_factor', 0):>7.2f} "
                    f"{sym_stats.get('total_pnl', 0):>+8.2f}% "
                    f"{sym_stats.get('reversal_count', 0):>5} "
                    f"{sym_stats.get('continuation_count', 0):>5}"
                )
        logger.info("")

    # ── Comparison Delta (v2 vs v1, v2+zones vs v1) ──
    logger.info(f"{'='*70}")
    logger.info(f"  DELTA vs v1 (baseline)")
    logger.info(f"{'='*70}\n")

    v1_agg = all_variant_results["v1"]["aggregate"]
    for label in ["v2", "v2+zones"]:
        agg = all_variant_results[label]["aggregate"]
        delta_trades = agg["total_trades"] - v1_agg["total_trades"]
        delta_wr = agg["winrate"] - v1_agg["winrate"]
        delta_pf = agg["profit_factor"] - v1_agg["profit_factor"]
        delta_sharpe = agg["sharpe"] - v1_agg["sharpe"]
        delta_pnl = agg["total_pnl"] - v1_agg["total_pnl"]
        logger.info(
            f"  {label:<12} Trades:{delta_trades:+6d}  "
            f"WR:{delta_wr:+6.1f}%  PF:{delta_pf:+7.2f}  "
            f"Sharpe:{delta_sharpe:+7.2f}  PnL:{delta_pnl:+9.2f}%"
        )

    # ── Save master comparison ──
    master = {
        "meta": {
            "timeframe": timeframe,
            "days": days,
            "symbols": symbols,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "variants": all_variant_results,
    }
    master_path = os.path.join(out_dir, "comparison.json")
    with open(master_path, "w", encoding="utf-8") as f:
        json.dump(master, f, indent=2, default=str)
    logger.info(f"\nMaster comparison saved: {master_path}")

    await exchange_client.close()


if __name__ == "__main__":
    asyncio.run(main())
