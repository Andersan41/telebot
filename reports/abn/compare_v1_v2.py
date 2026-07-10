#!/usr/bin/env python3
"""Compare v1 (8 symbols, 1340 candles) vs v2 (20 symbols, 3000 candles)."""
import json

# Load v1
v1 = []
with open('reports/abn/raw_results_v1_1340candles.jsonl') as f:
    for line in f:
        v1.append(json.loads(line.strip()))

# Load v2
v2 = []
with open('reports/abn/raw_results.jsonl') as f:
    for line in f:
        v2.append(json.loads(line.strip()))

preset_order = ['baseline','task1_only','task2_only','task3_only','task4_only','task5_only','task6_only','full']

# Aggregate v1
def agg_by_preset(data):
    d = {}
    for p in preset_order:
        runs = [r for r in data if r['preset'] == p]
        d[p] = {
            'n': len(runs),
            'trades': sum(r['total_trades'] for r in runs),
            'avg_net': sum(r['total_net_pnl_pct'] for r in runs) / len(runs),
            'sum_net': sum(r['total_net_pnl_pct'] for r in runs),
            'avg_wr': sum(r['winrate'] for r in runs) / len(runs),
            'avg_pf': sum(r['profit_factor'] for r in runs) / len(runs),
        }
    return d

v1_agg = agg_by_preset(v1)
v2_agg = agg_by_preset(v2)

print("=== V1 (8 sym, 1340 candles) vs V2 (20 sym, 3000 candles) ===")
print(f"\n{'Preset':<16} {'V1_AvgNet':>10} {'V2_AvgNet':>10} {'V1_SumNet':>10} {'V2_SumNet':>10} {'V1_WR':>7} {'V2_WR':>7} {'V1_PF':>6} {'V2_PF':>6}")
print("-" * 90)
for p in preset_order:
    v1d = v1_agg[p]
    v2d = v2_agg[p]
    print(f"{p:<16} {v1d['avg_net']:>+9.2f}% {v2d['avg_net']:>+9.2f}% {v1d['sum_net']:>+9.2f}% {v2d['sum_net']:>+9.2f}% {v1d['avg_wr']:>6.1f}% {v2d['avg_wr']:>6.1f}% {v1d['avg_pf']:>5.2f} {v2d['avg_pf']:>5.2f}")

# Compare common symbols
common_symbols = ['BTC/USDT','ETH/USDT','XRP/USDT','SOL/USDT','DOGE/USDT','AVAX/USDT','LINK/USDT','ADA/USDT']
print("\n=== COMMON 8 SYMBOLS: V1 vs V2 ===")
print(f"{'Symbol':<14} {'V1_BL_Net':>10} {'V2_BL_Net':>10} {'V1_FL_Net':>10} {'V2_FL_Net':>10} {'V1_Delta':>9} {'V2_Delta':>9}")
print("-" * 72)
for sym in common_symbols:
    v1_bl = next((r for r in v1 if r['symbol'] == sym and r['preset'] == 'baseline'), None)
    v1_fl = next((r for r in v1 if r['symbol'] == sym and r['preset'] == 'full'), None)
    v2_bl = next((r for r in v2 if r['symbol'] == sym and r['preset'] == 'baseline'), None)
    v2_fl = next((r for r in v2 if r['symbol'] == sym and r['preset'] == 'full'), None)
    if all([v1_bl, v1_fl, v2_bl, v2_fl]):
        v1d = v1_fl['total_net_pnl_pct'] - v1_bl['total_net_pnl_pct']
        v2d = v2_fl['total_net_pnl_pct'] - v2_bl['total_net_pnl_pct']
        print(f"{sym:<14} {v1_bl['total_net_pnl_pct']:>+9.2f}% {v2_bl['total_net_pnl_pct']:>+9.2f}% {v1_fl['total_net_pnl_pct']:>+9.2f}% {v2_fl['total_net_pnl_pct']:>+9.2f}% {v1d:>+8.2f}% {v2d:>+8.2f}%")
