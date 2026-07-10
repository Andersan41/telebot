#!/usr/bin/env python3
"""Analyze v2 expanded backtest results (20 symbols, 3000 candles)."""
import json
from collections import defaultdict

results = []
with open('reports/abn/raw_results.jsonl') as f:
    for line in f:
        results.append(json.loads(line.strip()))

print(f"Total runs: {len(results)}")

# --- Aggregate by preset ---
preset_order = ['baseline','task1_only','task2_only','task3_only','task4_only','task5_only','task6_only','full']
preset_agg = {}
for p in preset_order:
    preset_agg[p] = {'trades': 0, 'wins': 0, 'losses': 0, 'pnl_list': [], 'net_pnl_list': [], 'wr_list': [], 'sharpe_list': [], 'pf_list': [], 'n': 0}

for r in results:
    p = r['preset']
    preset_agg[p]['trades'] += r['total_trades']
    preset_agg[p]['wins'] += r['wins']
    preset_agg[p]['losses'] += r['losses']
    preset_agg[p]['pnl_list'].append(r['total_pnl_pct'])
    preset_agg[p]['net_pnl_list'].append(r['total_net_pnl_pct'])
    preset_agg[p]['wr_list'].append(r['winrate'])
    preset_agg[p]['sharpe_list'].append(r['sharpe_ratio'])
    preset_agg[p]['pf_list'].append(r['profit_factor'])
    preset_agg[p]['n'] += 1

print("\n=== AGGREGATE BY PRESET (20 symbols, ~3000 candles each) ===")
header = f"{'Preset':<16} {'Sym#':<5} {'Trades':<7} {'Win%':<6} {'AvgPnL':<8} {'AvgNet':<8} {'Sharpe':<7} {'PF':<5} {'SumPnL':<8} {'SumNet':<8}"
print(header)
print("-" * len(header))
for p in preset_order:
    d = preset_agg[p]
    n = d['n']
    wr = d['wins'] / d['trades'] * 100 if d['trades'] > 0 else 0
    avg_pnl = sum(d['pnl_list']) / n
    avg_net = sum(d['net_pnl_list']) / n
    avg_sharpe = sum(d['sharpe_list']) / n
    avg_pf = sum(d['pf_list']) / n
    sum_pnl = sum(d['pnl_list'])
    sum_net = sum(d['net_pnl_list'])
    print(f"{p:<16} {n:<5} {d['trades']:<7} {wr:<6.1f} {avg_pnl:<8.2f} {avg_net:<8.2f} {avg_sharpe:<7.2f} {avg_pf:<5.2f} {sum_pnl:<8.2f} {sum_net:<8.2f}")

# --- Per-symbol: baseline vs full ---
print("\n=== PER-SYMBOL: BASELINE vs FULL (Net PnL) ===")
symbols_order = []
for r in results:
    if r['symbol'] not in symbols_order:
        symbols_order.append(r['symbol'])

print(f"{'Symbol':<14} {'BL_Trades':>9} {'BL_WR%':>7} {'BL_Net%':>8} {'FL_Trades':>9} {'FL_WR%':>7} {'FL_Net%':>8} {'Delta':>8}")
print("-" * 78)
bl_total_trades = 0
fl_total_trades = 0
bl_total_net = 0
fl_total_net = 0
profitable_before = 0
profitable_after = 0
for sym in symbols_order:
    bl = next((r for r in results if r['symbol'] == sym and r['preset'] == 'baseline'), None)
    fl = next((r for r in results if r['symbol'] == sym and r['preset'] == 'full'), None)
    if bl and fl:
        delta = fl['total_net_pnl_pct'] - bl['total_net_pnl_pct']
        bl_total_trades += bl['total_trades']
        fl_total_trades += fl['total_trades']
        bl_total_net += bl['total_net_pnl_pct']
        fl_total_net += fl['total_net_pnl_pct']
        if bl['total_net_pnl_pct'] > 0:
            profitable_before += 1
        if fl['total_net_pnl_pct'] > 0:
            profitable_after += 1
        sign = "+" if delta >= 0 else ""
        print(f"{sym:<14} {bl['total_trades']:>9} {bl['winrate']:>6.1f}% {bl['total_net_pnl_pct']:>7.2f}% {fl['total_trades']:>9} {fl['winrate']:>6.1f}% {fl['total_net_pnl_pct']:>7.2f}% {sign}{delta:>7.2f}%")

print(f"\n{'TOTALS':<14} {bl_total_trades:>9} {'':>7} {bl_total_net:>7.2f}% {fl_total_trades:>9} {'':>7} {fl_total_net:>7.2f}% {'+' if fl_total_net - bl_total_net >= 0 else ''}{fl_total_net - bl_total_net:>7.2f}%")
print(f"\nProfitable symbols: {profitable_before}/20 baseline -> {profitable_after}/20 full")

# --- Per-task contribution ---
print("\n=== PER-TASK CONTRIBUTION (vs BASELINE) ===")
bl = preset_agg['baseline']
print(f"{'Task':<45} {'PnL_d':>8} {'WR_d':>6} {'PF_d':>6}")
print("-" * 70)
tasks = [
    ('baseline', 'baseline'),
    ('task1_only', 'Unified Entry (confirm TF)'),
    ('task2_only', 'Structural SL'),
    ('task3_only', 'SL Distance Guard'),
    ('task4_only', 'RR Filter'),
    ('task5_only', 'News Filter (stub)'),
    ('task6_only', 'Stop Hunt Buffer'),
    ('full', 'ALL TASKS COMBINED'),
]
bl_wr = sum(bl['wr_list']) / len(bl['wr_list'])
bl_pf = sum(bl['pf_list']) / len(bl['pf_list'])
bl_net = sum(bl['net_pnl_list']) / len(bl['net_pnl_list'])

for preset_key, name in tasks:
    d = preset_agg[preset_key]
    avg_wr = sum(d['wr_list']) / len(d['wr_list'])
    avg_pf = sum(d['pf_list']) / len(d['pf_list'])
    avg_net = sum(d['net_pnl_list']) / len(d['net_pnl_list'])
    net_d = avg_net - bl_net
    wr_d = avg_wr - bl_wr
    pf_d = avg_pf - bl_pf
    print(f"{name:<45} {net_d:>+7.2f}% {wr_d:>+5.1f}% {pf_d:>+5.2f}")

# --- Reject analysis ---
print("\n=== SIGNAL REJECT ANALYSIS ===")
for p in preset_order:
    total_rej = sum(r.get('signals_rejected', 0) for r in results if r['preset'] == p)
    total_gen = sum(r.get('signals_generated', 0) for r in results if r['preset'] == p)
    rr_rej = sum(r.get('reject_rr', 0) for r in results if r['preset'] == p)
    sl_rej = sum(r.get('reject_sl_dist', 0) for r in results if r['preset'] == p)
    tf_rej = sum(r.get('reject_confirm_tf', 0) for r in results if r['preset'] == p)
    print(f"{p:<16} Gen={total_gen:>6}  Rej={total_rej:>5}  RR={rr_rej:>5}  SLdist={sl_rej:>5}  ConfTF={tf_rej:>5}")
