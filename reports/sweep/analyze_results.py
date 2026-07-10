"""
Complete analysis of sweep A/B experiment.
Run after all 4 symbols are saved in sweep_ab_raw.json.
"""
import json
import numpy as np
from pathlib import Path

RESULTS_DIR = Path(__file__).parent


def wilson_ci(wins, n, z=1.96):
    if n == 0: return (0.0, 0.0)
    p = wins / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    spread = z * np.sqrt((p * (1 - p) + z**2 / (4 * n)) / n) / denom
    return (round((center - spread) * 100, 2), round((center + spread) * 100, 2))


def bootstrap_wr_ci(wins_a, n_a, wins_b, n_b, n_boot=10000):
    if n_a < 5 or n_b < 5:
        return None
    rng = np.random.default_rng(42)
    a = np.array([1.0]*wins_a + [0.0]*(n_a - wins_a))
    b = np.array([1.0]*wins_b + [0.0]*(n_b - wins_b))
    diffs = []
    for _ in range(n_boot):
        sa = rng.choice(a, size=len(a), replace=True)
        sb = rng.choice(b, size=len(b), replace=True)
        diffs.append(np.mean(sa) - np.mean(sb))
    diffs = np.array(diffs)
    lo = float(np.percentile(diffs, 2.5))
    hi = float(np.percentile(diffs, 97.5))
    return {"mean_pp": round(float(np.mean(diffs))*100, 2),
            "ci_lo_pp": round(lo*100, 2), "ci_hi_pp": round(hi*100, 2),
            "sig": lo > 0 or hi < 0}


def bootstrap_pnl_ci(pnl_a, pnl_b, n_boot=10000):
    if len(pnl_a) < 5 or len(pnl_b) < 5:
        return None
    rng = np.random.default_rng(42)
    diffs = []
    for _ in range(n_boot):
        sa = rng.choice(pnl_a, size=len(pnl_a), replace=True)
        sb = rng.choice(pnl_b, size=len(pnl_b), replace=True)
        diffs.append(np.mean(sa) - np.mean(sb))
    diffs = np.array(diffs)
    lo = float(np.percentile(diffs, 2.5))
    hi = float(np.percentile(diffs, 97.5))
    return {"mean": round(float(np.mean(diffs)), 4),
            "ci_lo": round(lo, 4), "ci_hi": round(hi, 4),
            "sig": lo > 0 or hi < 0}


def main():
    data = json.load(open(RESULTS_DIR / "sweep_ab_raw.json", encoding="utf-8"))

    # Organize by symbol
    by_sym = {}
    for r in data:
        by_sym.setdefault(r["symbol"], {})[
            "exp" if r["total_trades"] > 0 and "sell_sweep" in str(r.get("regime_stats", "")) else "full"
        ] = r

    # Actually, identify by position: odd = full_new, even = sell_sweep_disabled
    by_sym = {}
    for i in range(0, len(data), 2):
        sym = data[i]["symbol"]
        by_sym[sym] = {"full": data[i], "exp": data[i+1]}

    print("=" * 90)
    print("  SWEEP DIRECTIONAL A/B — COMPLETE RESULTS")
    print("=" * 90)

    # ── Stage 4: Statistics ────────────────────────────────────────────
    print("\n  STAGE 4: STATISTICS")
    print("  " + "-" * 86)
    print(f"  {'Symbol':10s} {'Preset':20s} {'Trades':>6s} {'WR%':>6s} {'BUY_T':>5s} {'BUY_WR':>7s} {'SELL_T':>6s} {'SELL_WR':>7s} {'NetPnL%':>9s}")
    print("  " + "-" * 86)

    all_full_pnls = []
    all_exp_pnls = []

    for sym in sorted(by_sym.keys()):
        f = by_sym[sym]["full"]
        e = by_sym[sym]["exp"]
        fl = f.get("long_stats", {}); fs = f.get("short_stats", {})
        el = e.get("long_stats", {}); es = e.get("short_stats", {})

        print(f"  {sym:10s} {'full_new':20s} {f['total_trades']:6d} {f['winrate']:5.1f}% "
              f"{fl.get('trades',0):5d} {fl.get('winrate',0):6.1f}% "
              f"{fs.get('trades',0):6d} {fs.get('winrate',0):6.1f}% "
              f"{f['total_net_pnl_pct']:+8.2f}%")
        print(f"  {'':10s} {'sell_sweep_disabled':20s} {e['total_trades']:6d} {e['winrate']:5.1f}% "
              f"{el.get('trades',0):5d} {el.get('winrate',0):6.1f}% "
              f"{es.get('trades',0):6d} {es.get('winrate',0):6.1f}% "
              f"{e['total_net_pnl_pct']:+8.2f}%")

        d_wr = e["winrate"] - f["winrate"]
        d_swr = es.get("winrate", 0) - fs.get("winrate", 0)
        d_ntrades = e["total_trades"] - f["total_trades"]
        d_net = e["total_net_pnl_pct"] - f["total_net_pnl_pct"]
        print(f"  {'':10s} {'DELTA':20s} {d_ntrades:+6d} {d_wr:+5.1f}% "
              f"{'':5s} {'':7s} {'':6s} {d_swr:+6.1f}% "
              f"{d_net:+8.2f}%")
        print()

        # Collect for aggregation
        for t in f.get("trades", []):
            all_full_pnls.append(t["pnl_pct"])
        for t in e.get("trades", []):
            all_exp_pnls.append(t["pnl_pct"])

    # Aggregate
    total_full = sum(by_sym[s]["full"]["total_trades"] for s in by_sym)
    total_exp = sum(by_sym[s]["exp"]["total_trades"] for s in by_sym)
    total_full_wins = sum(by_sym[s]["full"]["wins"] for s in by_sym)
    total_exp_wins = sum(by_sym[s]["exp"]["wins"] for s in by_sym)
    total_full_net = sum(by_sym[s]["full"]["total_net_pnl_pct"] for s in by_sym)
    total_exp_net = sum(by_sym[s]["exp"]["total_net_pnl_pct"] for s in by_sym)

    agg_wr_full = total_full_wins / total_full * 100 if total_full else 0
    agg_wr_exp = total_exp_wins / total_exp * 100 if total_full else 0

    # Aggregate BUY/SELL
    total_full_buy_t = sum(by_sym[s]["full"].get("long_stats", {}).get("trades", 0) for s in by_sym)
    total_exp_buy_t = sum(by_sym[s]["exp"].get("long_stats", {}).get("trades", 0) for s in by_sym)
    total_full_sell_t = sum(by_sym[s]["full"].get("short_stats", {}).get("trades", 0) for s in by_sym)
    total_exp_sell_t = sum(by_sym[s]["exp"].get("short_stats", {}).get("trades", 0) for s in by_sym)

    # Estimate wins from WR * trades
    total_full_buy_w = sum(int(by_sym[s]["full"].get("long_stats", {}).get("winrate", 0) * by_sym[s]["full"].get("long_stats", {}).get("trades", 0) / 100) for s in by_sym)
    total_exp_buy_w = sum(int(by_sym[s]["exp"].get("long_stats", {}).get("winrate", 0) * by_sym[s]["exp"].get("long_stats", {}).get("trades", 0) / 100) for s in by_sym)
    total_full_sell_w = sum(int(by_sym[s]["full"].get("short_stats", {}).get("winrate", 0) * by_sym[s]["full"].get("short_stats", {}).get("trades", 0) / 100) for s in by_sym)
    total_exp_sell_w = sum(int(by_sym[s]["exp"].get("short_stats", {}).get("winrate", 0) * by_sym[s]["exp"].get("short_stats", {}).get("trades", 0) / 100) for s in by_sym)

    print("  " + "=" * 86)
    print(f"  {'AGGREGATE':10s} {'full_new':20s} {total_full:6d} {agg_wr_full:5.1f}% "
          f"{total_full_buy_t:5d} {total_full_buy_w/total_full_buy_t*100 if total_full_buy_t else 0:6.1f}% "
          f"{total_full_sell_t:6d} {total_full_sell_w/total_full_sell_t*100 if total_full_sell_t else 0:6.1f}% "
          f"{total_full_net:+8.2f}%")
    print(f"  {'':10s} {'sell_sweep_disabled':20s} {total_exp:6d} {agg_wr_exp:5.1f}% "
          f"{total_exp_buy_t:5d} {total_exp_buy_w/total_exp_buy_t*100 if total_exp_buy_t else 0:6.1f}% "
          f"{total_exp_sell_t:6d} {total_exp_sell_w/total_exp_sell_t*100 if total_exp_sell_t else 0:6.1f}% "
          f"{total_exp_net:+8.2f}%")

    # ── Stage 5: Significance ──────────────────────────────────────────
    print(f"\n\n  STAGE 5: SIGNIFICANCE TESTING")
    print("  " + "-" * 86)

    # Overall WR
    overall = bootstrap_wr_ci(total_full_wins, total_full, total_exp_wins, total_exp)
    print(f"\n  Overall WR: {agg_wr_full:.1f}% vs {agg_wr_exp:.1f}% (delta={agg_wr_exp-agg_wr_full:+.1f}pp)")
    if overall:
        print(f"    Bootstrap CI: mean={overall['mean_pp']:+.2f}pp, CI=[{overall['ci_lo_pp']:+.2f}, {overall['ci_hi_pp']:+.2f}]")
        print(f"    Verdict: {'SIGNIFICANT' if overall['sig'] else 'NOT SIGNIFICANT'}")
    else:
        print(f"    Low statistical confidence (N<30)")

    # Per-symbol SELL WR
    print(f"\n  SELL Winrate by Symbol:")
    print(f"  {'Symbol':10s} {'full_new':>10s} {'exp':>10s} {'Delta':>8s} {'Wilson CI (full)':>20s} {'Wilson CI (exp)':>20s} {'Bootstrap':>12s} {'Verdict':>16s}")

    for sym in sorted(by_sym.keys()):
        f = by_sym[sym]["full"]
        e = by_sym[sym]["exp"]
        fs = f.get("short_stats", {})
        es = e.get("short_stats", {})
        fn = fs.get("trades", 0)
        en = es.get("trades", 0)
        fw = fs.get("winrate", 0)
        ew = es.get("winrate", 0)
        fw_n = int(fw * fn / 100) if fn else 0
        ew_n = int(ew * en / 100) if en else 0

        wf = wilson_ci(fw_n, fn)
        we = wilson_ci(ew_n, en)
        b = bootstrap_wr_ci(fw_n, fn, ew_n, en)

        delta = ew - fw
        verdict = ""
        if b:
            verdict = "SIGNIFICANT" if b["sig"] else "NOT SIGNIFICANT"
        elif fn < 30 or en < 30:
            verdict = "Low N"

        print(f"  {sym:10s} {fw:9.1f}% {ew:9.1f}% {delta:+7.1f}pp "
              f"[{wf[0]:.1f},{wf[1]:.1f}]".rjust(21) + " "
              f"[{we[0]:.1f},{we[1]:.1f}]".rjust(21) + " "
              f"{b['mean_pp']:+.2f}pp".rjust(12) if b else " " * 12 + " "
              f"{verdict:>16s}")

    # BUY WR (should be identical)
    print(f"\n  BUY Winrate (should be identical — no changes to BUY logic):")
    for sym in sorted(by_sym.keys()):
        fl = by_sym[sym]["full"].get("long_stats", {})
        el = by_sym[sym]["exp"].get("long_stats", {})
        print(f"  {sym}: full={fl.get('winrate',0):.1f}% exp={el.get('winrate',0):.1f}% delta={el.get('winrate',0)-fl.get('winrate',0):+.1f}pp")

    # Per-symbol PnL
    print(f"\n  Net PnL by Symbol:")
    print(f"  {'Symbol':10s} {'full_new':>10s} {'exp':>10s} {'Delta':>10s} {'Bootstrap':>16s} {'Verdict':>16s}")
    for sym in sorted(by_sym.keys()):
        f = by_sym[sym]["full"]
        e = by_sym[sym]["exp"]
        fp = [t["pnl_pct"] for t in f.get("trades", [])]
        ep = [t["pnl_pct"] for t in e.get("trades", [])]
        b = bootstrap_pnl_ci(fp, ep)
        delta = e["total_net_pnl_pct"] - f["total_net_pnl_pct"]
        verdict = ""
        if b:
            verdict = "SIGNIFICANT" if b["sig"] else "NOT SIGNIFICANT"
        bstr = f"{b['mean']:+.2f},[{b['ci_lo']:+.2f},{b['ci_hi']:+.2f}]" if b else "N/A"
        print(f"  {sym:10s} {f['total_net_pnl_pct']:+9.2f}% {e['total_net_pnl_pct']:+9.2f}% {delta:+9.2f}% {bstr:>16s} {verdict:>16s}")

    # ── Stage 6: Unintended consequences ───────────────────────────────
    print(f"\n\n  STAGE 6: UNINTENDED CONSEQUENCES")
    print("  " + "-" * 86)

    print(f"\n  Signal count change: {total_exp - total_full:+d} trades")
    print(f"  BUY trades unchanged: {total_full_buy_t} → {total_exp_buy_t} (delta={total_exp_buy_t-total_full_buy_t:+d})")
    print(f"  SELL trades reduced: {total_full_sell_t} → {total_exp_sell_t} (delta={total_exp_sell_t-total_full_sell_t:+d})")

    # Regime mix
    print(f"\n  Regime mix change:")
    all_regimes = set()
    for s in by_sym.values():
        all_regimes.update(s["full"].get("regime_stats", {}).keys())
        all_regimes.update(s["exp"].get("regime_stats", {}).keys())

    for reg in sorted(all_regimes):
        ft = sum(s["full"].get("regime_stats", {}).get(reg, {}).get("trades", 0) for s in by_sym.values())
        et = sum(s["exp"].get("regime_stats", {}).get(reg, {}).get("trades", 0) for s in by_sym.values())
        print(f"  {reg:15s}: full={ft:3d} exp={et:3d} delta={et-ft:+d}")

    # ── Stage 7/8: Trade diff ──────────────────────────────────────────
    print(f"\n\n  STAGE 7: DISAPPEARED SELL TRADES")
    print("  " + "-" * 86)

    for sym in sorted(by_sym.keys()):
        ft = {(t["symbol"], t["entry_timestamp"]): t for t in by_sym[sym]["full"].get("trades", []) if t["direction"] == "SELL"}
        et = {(t["symbol"], t["entry_timestamp"]): t for t in by_sym[sym]["exp"].get("trades", []) if t["direction"] == "SELL"}
        disappeared = [ft[k] for k in ft if k not in et]
        if disappeared:
            print(f"\n  {sym}: {len(disappeared)} SELL trades disappeared")
            for t in disappeared[:5]:
                print(f"    {t['entry_timestamp'][:16]} score={t['signal_score']} regime={t['regime']} pnl={t['pnl_pct']:+.2f}% reasons={t['reasons'][:2]}")

    print(f"\n\n  STAGE 8: NEW SELL TRADES")
    print("  " + "-" * 86)

    for sym in sorted(by_sym.keys()):
        ft = {(t["symbol"], t["entry_timestamp"]): t for t in by_sym[sym]["full"].get("trades", []) if t["direction"] == "SELL"}
        et = {(t["symbol"], t["entry_timestamp"]): t for t in by_sym[sym]["exp"].get("trades", []) if t["direction"] == "SELL"}
        new_t = [et[k] for k in et if k not in ft]
        if new_t:
            print(f"\n  {sym}: {len(new_t)} new SELL trades appeared")
            for t in new_t[:5]:
                print(f"    {t['entry_timestamp'][:16]} score={t['signal_score']} regime={t['regime']} pnl={t['pnl_pct']:+.2f}%")
        else:
            print(f"\n  {sym}: 0 new SELL trades")

    # ── Stage 9: Proxy analysis ────────────────────────────────────────
    print(f"\n\n  STAGE 9: PROXY ANALYSIS")
    print("  " + "-" * 86)

    # Collect all sweep-related trades from full_new
    all_full_trades = []
    for s in by_sym.values():
        all_full_trades.extend(s["full"].get("trades", []))

    sweep_trades = [t for t in all_full_trades if any("sweep" in r.lower() for r in t.get("reasons", []))]
    no_sweep_trades = [t for t in all_full_trades if not any("sweep" in r.lower() for r in t.get("reasons", []))]

    print(f"\n  Total trades with sweep in reasons: {len(sweep_trades)} / {len(all_full_trades)}")
    if sweep_trades:
        print(f"  Sweep trades WR: {sum(1 for t in sweep_trades if t['pnl_pct']>0)/len(sweep_trades)*100:.1f}%")
        print(f"  No-sweep trades WR: {sum(1 for t in no_sweep_trades if t['pnl_pct']>0)/len(no_sweep_trades)*100:.1f}%")

        # Regime distribution
        print(f"\n  Regime distribution:")
        for reg in ["expansion", "trend", "range", "compression"]:
            sw_pct = sum(1 for t in sweep_trades if t.get("regime") == reg) / len(sweep_trades) * 100
            nsw_pct = sum(1 for t in no_sweep_trades if t.get("regime") == reg) / len(no_sweep_trades) * 100
            print(f"  {reg:15s}: sweep={sw_pct:5.1f}% no-sweep={nsw_pct:5.1f}% delta={sw_pct-nsw_pct:+.1f}pp")

    # ── Stage 10: Feature importance ───────────────────────────────────
    print(f"\n\n  STAGE 10: FEATURE IMPORTANCE")
    print("  " + "-" * 86)

    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.inspection import permutation_importance

        features = ["score", "regime_trend", "regime_range", "regime_expansion", "regime_compression"]
        for label, trades in [("full_new", all_full_trades), ("sell_sweep_disabled",
                              [t for s in by_sym.values() for t in s["exp"].get("trades", [])])]:
            if len(trades) < 50:
                print(f"\n  {label}: N={len(trades)} < 50, skipping")
                continue
            X, y = [], []
            for t in trades:
                regime = t.get("regime", "range")
                row = [t.get("signal_score", 0),
                       1 if regime == "trend" else 0,
                       1 if regime == "range" else 0,
                       1 if regime == "expansion" else 0,
                       1 if regime == "compression" else 0]
                X.append(row)
                y.append(1 if t.get("pnl_pct", 0) > 0 else 0)
            X, y = np.array(X), np.array(y)
            clf = RandomForestClassifier(n_estimators=100, random_state=42, max_depth=5)
            clf.fit(X, y)
            pi = permutation_importance(clf, X, y, n_repeats=10, random_state=42)
            print(f"\n  {label} (N={len(trades)}):")
            for i, name in enumerate(features):
                imp = pi.importances_mean[i]
                print(f"    {name:25s}: {imp:+.4f} (std={pi.importances_std[i]:.4f})")
    except Exception as ex:
        print(f"  Feature importance failed: {ex}")

    print(f"\n{'='*90}")
    print("  ANALYSIS COMPLETE")
    print(f"{'='*90}")


if __name__ == "__main__":
    main()
