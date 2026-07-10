"""
reports/sweep/run_focused_ab.py — Efficient A/B: pre-compute snapshots once, evaluate 2 presets.

full_new vs sell_sweep_disabled for 4 symbols.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from loguru import logger as _loguru_logger
_loguru_logger.disable("strategy.signal_engine")
_loguru_logger.disable("indicators.engine")
import logging
logging.getLogger("strategy.signal_engine").setLevel(logging.WARNING)
logging.getLogger("indicators.engine").setLevel(logging.WARNING)

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

from backtest.engine import (
    BacktestConfig, BacktestResult, BacktestTrade, RejectStats,
    _compute_regime, _normalize_symbol,
)
from indicators.engine import IndicatorEngine
from strategy.signal_engine import signal_engine, SignalType
from risk.dynamic_risk import calculate_structural_sl, calculate_structural_tp
from liquidity.sweep import detect_sweeps
from liquidity.order_blocks import detect_order_blocks
from liquidity.fvg import detect_fvg
from market_structure.structure import analyze_structure
from config.settings import config

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "APT/USDT"]
TIMEFRAME = "1h"
CANDLES = 3900
CONFIRM_TF = "15m"
CONFIRM_CANDLES = 15552
WARMUP = 80

FULL_NEW_FLAGS = {
    "enable_unified_entry": True, "enable_confirm_tf_gate": False,
    "enable_structural_sl": True, "enable_sl_distance_guard": True,
    "enable_rr_filter": True, "enable_news_filter": True,
    "enable_stop_hunt_buffer": False,
}

RESULTS_DIR = Path(__file__).parent


@dataclass
class Snap:
    i: int; ind: object; regime: object; structure: object
    all_sweeps: list; valid_sweeps: list; all_obs: list; valid_obs: list
    fvgs: list; entry_base: float; confirm_entry: Optional[float]; confirm_ok: bool


@dataclass
class St:
    in_trade: bool = False; ct: object = None; trades: list = field(default_factory=list)
    rs: object = field(default_factory=RejectStats); sigs: int = 0


def eval_preset(snaps, df, symbol, tf, cfg_flags, strip_sweep_sell=False):
    cfg = BacktestConfig(**cfg_flags)
    st = St()
    fee = config.trading.exchange_fee_pct / 100.0
    slip = config.trading.slippage_pct / 100.0

    for snap in snaps:
        # Exit
        if st.in_trade and st.ct is not None:
            hi, lo = float(snap.ind.high), float(snap.ind.low)
            ct = st.ct; ex = False
            if ct.direction == "BUY":
                if lo <= ct.sl: ct.exit_price=ct.sl; ct.exit_index=snap.i; ct.exit_timestamp=str(df.index[snap.i]); ct.exit_reason="sl"; ex=True
                elif hi >= ct.tp: ct.exit_price=ct.tp; ct.exit_index=snap.i; ct.exit_timestamp=str(df.index[snap.i]); ct.exit_reason="tp"; ex=True
            else:
                if hi >= ct.sl: ct.exit_price=ct.sl; ct.exit_index=snap.i; ct.exit_timestamp=str(df.index[snap.i]); ct.exit_reason="sl"; ex=True
                elif lo <= ct.tp: ct.exit_price=ct.tp; ct.exit_index=snap.i; ct.exit_timestamp=str(df.index[snap.i]); ct.exit_reason="tp"; ex=True
            if ex:
                g = ((ct.exit_price-ct.entry_price)/ct.entry_price*100) if ct.direction=="BUY" else ((ct.entry_price-ct.exit_price)/ct.entry_price*100)
                ct.pnl_pct=round(g,4); ct.net_pnl_pct=round(g-(fee*2+slip*2)*100,4)
                r=abs(ct.entry_price-ct.sl); ct.rr=round(abs(ct.exit_price-ct.entry_price)/r,2) if r>0 else 0.0
                st.trades.append(ct); st.in_trade=False; st.ct=None

        if not st.in_trade:
            st.sigs += 1
            ep = snap.confirm_entry if (cfg.enable_unified_entry and snap.confirm_entry is not None) else snap.entry_base
            if not snap.confirm_ok and cfg.enable_confirm_tf_gate:
                st.rs.confirm_tf_rejected+=1; st.rs.total_rejected+=1; continue

            # KEY: strip sweep for SELL
            sw = snap.valid_sweeps
            if strip_sweep_sell:
                qd = "buy" if snap.ind.ema_fast > snap.ind.ema_slow else "sell"
                if snap.structure and hasattr(snap.structure,'last_bos') and snap.structure.last_bos:
                    qd = "buy" if snap.structure.last_bos.type=="bullish" else "sell"
                if qd == "sell": sw = []

            res = signal_engine.evaluate(snap.ind, regime=snap.regime, structure=snap.structure,
                                         sweeps=sw, order_blocks=snap.valid_obs, entry_price=ep)
            if not (res.is_actionable and res.sl is not None and res.tp is not None): continue
            ib = res.signal == SignalType.BUY

            # FVG TP
            if snap.fvgs and res.tp is not None:
                try:
                    av=float(snap.ind.atr) if snap.ind.atr else 0.0
                    if av<=0: av=float(snap.ind.close)*0.02 if snap.ind.close else 0.02
                    nt=calculate_structural_tp(direction=res.signal.value,entry=ep,sl=res.sl,
                        sweeps=snap.all_sweeps,order_blocks=snap.all_obs,structure=snap.structure,
                        fvgs=snap.fvgs,atr=av,close=float(snap.ind.close) if snap.ind.close else 0.0)
                    if nt: res.tp=nt[0].price
                except: pass

            # Structural SL
            if res.sl is not None and cfg.enable_structural_sl:
                try:
                    av=float(snap.ind.atr) if snap.ind.atr else 0.0
                    if av<=0: av=float(snap.ind.close)*0.02 if snap.ind.close else 0.02
                    if res._sl_source!="bos":
                        ns=calculate_structural_sl(direction=res.signal.value,entry=ep,
                            sweeps=snap.all_sweeps,order_blocks=snap.all_obs,structure=snap.structure,
                            atr=av,close=float(snap.ind.close) if snap.ind.close else 0.0)
                        cd=abs(ep-res.sl); sd=abs(ep-ns)
                        if sd<=cd and ns!=res.sl: res.sl=ns; res._sl_source="structural"
                except: pass

            # SL guard
            if cfg.enable_sl_distance_guard:
                d=abs(ep-res.sl)/ep*100; mn=config.trading.min_sl_distance_pct; mx=config.trading.max_sl_distance_pct
                if d<mn:
                    res.sl=round(ep*(1-mn/100),8) if ib else round(ep*(1+mn/100),8)
                elif d>mx: st.rs.sl_distance_rejected+=1; st.rs.total_rejected+=1; continue

            # RR
            if cfg.enable_rr_filter:
                r=abs(ep-res.sl); rw=abs(res.tp-ep); rr=rw/r if r>0 else 0
                if rr<config.trading.min_rr_threshold: st.rs.rr_rejected+=1; st.rs.total_rejected+=1; continue

            st.ct = BacktestTrade(symbol=symbol, timeframe=tf, direction=res.signal.value,
                entry_price=ep, entry_index=snap.i, entry_timestamp=str(df.index[snap.i]),
                sl=res.sl, tp=res.tp, sl_source=res._sl_source or "atr",
                regime=snap.regime.regime if hasattr(snap.regime,'regime') else "",
                signal_score=res.score, confidence=res.confidence, reasons=list(res.reasons))
            st.in_trade = True

    if st.in_trade and st.ct is not None:
        ct=st.ct; ct.exit_price=float(df.iloc[-1]["close"]); ct.exit_index=len(df)-1
        ct.exit_timestamp=str(df.index[-1]); ct.exit_reason="eob"
        g=((ct.exit_price-ct.entry_price)/ct.entry_price*100) if ct.direction=="BUY" else ((ct.entry_price-ct.exit_price)/ct.entry_price*100)
        ct.pnl_pct=round(g,4); ct.net_pnl_pct=round(g-(fee*2+slip*2)*100,4)
        r=abs(ct.entry_price-ct.sl); ct.rr=round(abs(ct.exit_price-ct.entry_price)/r,2) if r>0 else 0.0
        st.trades.append(ct)

    return build_rec(symbol, tf, st, len(df))


def build_rec(symbol, tf, st, n_candles):
    trades=st.trades; rs=st.rs; total=len(trades)
    if total==0:
        return {"symbol":symbol,"total_trades":0,"wins":0,"winrate":0,"avg_pnl":0,
                "total_pnl_pct":0,"total_net_pnl_pct":0,"profit_factor":0,"expectancy":0,
                "max_drawdown":0,"sharpe_ratio":0,"avg_rr":0,
                "signals_generated":st.sigs,"signals_rejected":rs.total_rejected,
                "long_stats":{},"short_stats":{},"regime_stats":{},"trades":[]}

    w=[t for t in trades if t.pnl_pct>0]; l=[t for t in trades if t.pnl_pct<=0]
    wc=len(w); pnl=[t.pnl_pct for t in trades]; net=[t.net_pnl_pct for t in trades]
    tp=sum(pnl); tn=sum(net); gp=sum(t.pnl_pct for t in w) if w else 0.0
    gl=abs(sum(t.pnl_pct for t in l)) if l else 1.0; pf=gp/gl if gl>0 else float("inf")
    wr=wc/total; aw=gp/wc if wc else 0.0; al=gl/len(l) if l else 0.0
    exp=wr*aw-(1-wr)*al
    std=float(np.std(pnl,ddof=1)) if len(pnl)>1 else 1.0
    sh=(tp/total/std) if std>0 else 0.0
    cum=np.cumsum(pnl); pk=np.maximum.accumulate(cum); mdd=float(np.max(pk-cum)) if len(cum)>0 else 0.0

    ls={}; ss={}
    for d in ["BUY","SELL"]:
        dt=[t for t in trades if t.direction==d]
        if not dt: continue
        dw=sum(1 for t in dt if t.pnl_pct>0)
        dp=sum(t.pnl_pct for t in dt); dn=sum(t.net_pnl_pct for t in dt)
        dwr=dw/len(dt)*100
        gpn=sum(t.pnl_pct for t in dt if t.pnl_pct>0)
        gln=abs(sum(t.pnl_pct for t in dt if t.pnl_pct<=0))
        dpf=gpn/gln if gln>0 else float("inf")
        s={"trades":len(dt),"winrate":round(dwr,1),"pnl":round(dp,4),"net_pnl":round(dn,4),"pf":round(dpf,2)}
        if d=="BUY": ls=s
        else: ss=s

    rm={}
    for t in trades: rm.setdefault(t.regime or "unknown",[]).append(t)
    rg={}
    for reg,rt in rm.items():
        rw=sum(1 for t in rt if t.pnl_pct>0)
        rg[reg]={"trades":len(rt),"winrate":round(rw/len(rt)*100,1),
                 "pnl":round(sum(t.pnl_pct for t in rt),4),"net_pnl":round(sum(t.net_pnl_pct for t in rt),4)}

    td=[{"symbol":t.symbol,"direction":t.direction,"entry_price":t.entry_price,"exit_price":t.exit_price,
         "exit_reason":t.exit_reason,"pnl_pct":t.pnl_pct,"net_pnl_pct":t.net_pnl_pct,"rr":t.rr,
         "sl_source":t.sl_source,"regime":t.regime,"entry_timestamp":str(t.entry_timestamp),
         "signal_score":t.signal_score,"reasons":t.reasons,"sl":t.sl,"tp":t.tp} for t in trades]

    return {"symbol":symbol,"total_trades":total,"wins":wc,"losses":len(l),
            "winrate":round(wr*100,1),"avg_pnl":round(tp/total,4),"avg_net_pnl":round(tn/total,4),
            "total_pnl_pct":round(tp,4),"total_net_pnl_pct":round(tn,4),
            "profit_factor":round(pf,2),"expectancy":round(exp,4),
            "sharpe_ratio":round(sh,2),"max_drawdown":round(mdd,4),
            "avg_rr":round(sum(t.rr for t in trades)/total,2),
            "signals_generated":st.sigs,"signals_rejected":rs.total_rejected,
            "long_stats":ls,"short_stats":ss,"regime_stats":rg,"trades":td}


async def main():
    from backtest.cache_ohlcv import load_cached
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ie = IndicatorEngine()

    print("=" * 70)
    print("  SWEEP DIRECTIONAL A/B — EFFICIENT RUN")
    print("  full_new vs sell_sweep_disabled (4 symbols)")
    print("  Snapshots computed ONCE, evaluated TWICE")
    print("=" * 70)

    all_results = []

    for si, sym in enumerate(SYMBOLS, 1):
        print(f"\n[{si}/{len(SYMBOLS)}] {sym}", end=" ", flush=True)
        t0 = time.time()

        c1h = load_cached(sym, TIMEFRAME, CANDLES)
        c15m = load_cached(sym, CONFIRM_TF, CONFIRM_CANDLES)
        if c1h is None: print("NO CACHE"); continue
        df = c1h.copy()
        cdf = c15m.copy() if c15m is not None else None
        print(f"({len(df)}c)", end=" ", flush=True)

        # Phase 1: pre-compute snapshots (expensive, done once)
        t_snap = time.time()
        snaps = []
        ah, esh, vh = [], [], []
        for i in range(WARMUP, len(df)):
            w = df.iloc[:i+1].copy()
            ind = ie.calculate(w, sym, TIMEFRAME)
            if ind is None: continue
            ah.append(float(ind.atr))
            esh.append(abs(float(ind.ema_fast)-float(ind.ema_slow))/float(ind.ema_slow)*100 if float(ind.ema_slow)>0 else 0.0)
            vh.append(float(ind.volume))
            ro = _compute_regime(ind, ah, esh, vh)
            try: st = analyze_structure(w.tail(100))
            except: st = None
            try: asw = detect_sweeps(w.tail(100), swing_window=5)
            except: asw = []
            try: ao = detect_order_blocks(w.tail(100)) or []
            except: ao = []
            vsw = [s for s in asw if getattr(s,"is_valid",False)]
            vo = [o for o in ao if getattr(o,"is_valid",False)]
            fv = []
            try:
                dc = w.dropna(subset=["open","high","low","close","volume"])
                if len(dc)>=10: fv = detect_fvg(dc, lookback=100)
            except: pass

            epb = float(ind.close); cep = None; cok = True
            ca = config.trading.confirm_tf_enabled and cdf is not None and CONFIRM_TF != TIMEFRAME
            if ca:
                try:
                    pt = df.index[i]
                    ci = cdf.index.get_indexer([pt], method="nearest")[0]
                    if 0 <= ci < len(cdf):
                        ci2 = ie.calculate(cdf.iloc[:ci+1].copy(), sym, CONFIRM_TF)
                        if ci2 is not None:
                            ds = "buy" if ind.ema_fast > ind.ema_slow else "sell"
                            cok = signal_engine.evaluate_confirm(ci2, ds)
                            cep = float(ci2.close)
                except: pass

            snaps.append(Snap(i=i, ind=ind, regime=ro, structure=st, all_sweeps=asw,
                valid_sweeps=vsw, all_obs=ao, valid_obs=vo, fvgs=fv,
                entry_base=epb, confirm_entry=cep, confirm_ok=cok))

        t_snap_done = time.time()
        print(f"snapshots={len(snaps)} ({t_snap_done-t_snap:.0f}s)", end=" ", flush=True)

        # Phase 2: evaluate preset A (full_new)
        t_a = time.time()
        r_full = eval_preset(snaps, df, sym, TIMEFRAME, FULL_NEW_FLAGS, strip_sweep_sell=False)
        all_results.append(r_full)

        # Phase 3: evaluate preset B (sell_sweep_disabled)
        r_exp = eval_preset(snaps, df, sym, TIMEFRAME, FULL_NEW_FLAGS, strip_sweep_sell=True)
        all_results.append(r_exp)

        elapsed = time.time() - t0
        print(f"full={r_full['total_trades']}T/{r_full['winrate']}% exp={r_exp['total_trades']}T/{r_exp['winrate']}% ({elapsed:.0f}s)")

        # Incremental save
        out = RESULTS_DIR / "sweep_ab_raw.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)

    # Save after each symbol (incremental)
    out = RESULTS_DIR / "sweep_ab_raw.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nSaved {len(all_results)} records to {out}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
