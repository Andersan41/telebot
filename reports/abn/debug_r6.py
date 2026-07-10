import json
data = json.load(open("reports/abn/raw_results_r6.json"))

# Check BTC baseline
for r in data:
    if r["symbol"] == "BTC/USDT" and r["preset"] == "true_baseline":
        print(f"Batch BTC baseline: trades={r['total_trades']} pnl={r['total_net_pnl_pct']:.2f}%")
        for t in r["trades"][:3]:
            print(f"  {t['direction']} entry={t['entry_price']:.2f} exit={t['exit_price']} pnl={t['pnl_pct']:.4f}% reason={t['exit_reason']}")
        print("  ...")
        for t in r["trades"][-3:]:
            print(f"  {t['direction']} entry={t['entry_price']:.2f} exit={t['exit_price']} pnl={t['pnl_pct']:.4f}% reason={t['exit_reason']}")
        break

# Check ARB/USDT full_new (129% seems too high)
for r in data:
    if r["symbol"] == "ARB/USDT" and r["preset"] == "full_new":
        print(f"\nBatch ARB full_new: trades={r['total_trades']} pnl={r['total_net_pnl_pct']:.2f}%")
        # Show trades with highest pnl
        trades_sorted = sorted(r["trades"], key=lambda t: t["pnl_pct"], reverse=True)
        for t in trades_sorted[:5]:
            print(f"  {t['direction']} entry={t['entry_price']:.4f} exit={t['exit_price']} pnl={t['pnl_pct']:.4f}% reason={t['exit_reason']}")
        break
