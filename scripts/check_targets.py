import json

data = json.load(open("E:/Projects/tgbot/reports/abn/raw_results_r6.json"))
targets = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "APT/USDT"]
presets = ["full_new", "true_baseline", "unified_only", "structural_sl_only", "sl_guard_only", "rr_filter_only", "gate_only", "buffer_only"]

for sym in targets:
    for p in presets:
        matches = [r for r in data if r["symbol"] == sym and r["preset"] == p]
        if matches:
            r = matches[0]
            print(f"{sym:12s} {p:22s} T={r['total_trades']:4d} WR={r['winrate']:5.1f}% PnL={r['total_net_pnl_pct']:+8.2f}% PF={r['profit_factor']:5.2f} Exp={r['expectancy']:+.4f} DD={r['max_drawdown']:6.2f}% rej={r['signals_rejected']:5d} R={r['reject_rr']:3d} S={r['reject_sl_dist']:2d} C={r['reject_confirm_tf']:5d}")
        else:
            print(f"{sym:12s} {p:22s} MISSING")
