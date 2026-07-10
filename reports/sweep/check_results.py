import json
p = "reports/sweep/sweep_ab_raw.json"
try:
    data = json.load(open(p))
    print(f"Records: {len(data)}")
    for r in data:
        s = r["symbol"]
        t = r["total_trades"]
        w = r["winrate"]
        n = r["total_net_pnl_pct"]
        print(f"  {s}: trades={t} wr={w}% net_pnl={n:+.2f}%")
except Exception as e:
    print(f"No results: {e}")
