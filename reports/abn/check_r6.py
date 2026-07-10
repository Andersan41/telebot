import json

data = json.load(open("reports/abn/raw_results_r6.json"))

# Check BTC full_new
for r in data:
    if r["symbol"] == "BTC/USDT" and r["preset"] == "full_new":
        print(f"trades={r['total_trades']} wins={r['wins']} losses={r['losses']} pnl={r['total_net_pnl_pct']:.2f}% pf={r['profit_factor']:.2f}")
        for t in r["trades"][:5]:
            print(f"  {t['direction']} entry={t['entry_price']:.4f} exit={t['exit_price']} pnl={t['pnl_pct']:.4f}% reason={t['exit_reason']}")
        for t in r["trades"][-3:]:
            print(f"  {t['direction']} entry={t['entry_price']:.4f} exit={t['exit_price']} pnl={r['total_pnl_pct']:.4f}% reason={t['exit_reason']}")
        break

# Check BTC true_baseline
for r in data:
    if r["symbol"] == "BTC/USDT" and r["preset"] == "true_baseline":
        print(f"\nBASELINE: trades={r['total_trades']} wins={r['wins']} losses={r['losses']} pnl={r['total_net_pnl_pct']:.2f}% pf={r['profit_factor']:.2f}")
        for t in r["trades"][:3]:
            print(f"  {t['direction']} entry={t['entry_price']:.4f} exit={t['exit_price']} pnl={t['pnl_pct']:.4f}% reason={t['exit_reason']}")
        break

# Check per-symbol for full_new
print("\n--- Per-symbol full_new ---")
for r in data:
    if r["preset"] == "full_new":
        print(f"  {r['symbol']:12s} trades={r['total_trades']:3d} pnl={r['total_net_pnl_pct']:+8.2f}% pf={r['profit_factor']:.2f} wr={r['winrate']:.1f}%")
