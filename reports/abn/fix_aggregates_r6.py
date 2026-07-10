"""Recompute aggregates from raw trade data to fix PF=0 bug."""
import json
from pathlib import Path

RESULTS_DIR = Path("reports/abn")
raw = json.load(open(RESULTS_DIR / "raw_results_r6.json"))

PRESETS = [
    "true_baseline", "unified_only", "structural_sl_only", "sl_guard_only",
    "rr_filter_only", "gate_only", "buffer_only", "full_old", "full_new",
    "unified_plus_filters",
]

agg = {}
for preset in PRESETS:
    records = [r for r in raw if r["preset"] == preset]
    total_trades = sum(r["total_trades"] for r in records)
    if total_trades == 0:
        agg[preset] = {"total_trades": 0}
        continue

    total_wins = sum(r["wins"] for r in records)
    total_pnl = sum(r["total_pnl_pct"] for r in records)
    total_net_pnl = sum(r["total_net_pnl_pct"] for r in records)
    total_signals = sum(r["signals_generated"] for r in records)
    total_rejected = sum(r["signals_rejected"] for r in records)

    # Correct PF: sum gross profit and gross loss from all trades across all symbols
    all_trades = []
    for r in records:
        all_trades.extend(r["trades"])

    gross_profit = sum(t["pnl_pct"] for t in all_trades if t["pnl_pct"] > 0)
    gross_loss = abs(sum(t["pnl_pct"] for t in all_trades if t["pnl_pct"] <= 0))
    pf = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0

    # Correct expectancy
    wins = [t for t in all_trades if t["pnl_pct"] > 0]
    losses = [t for t in all_trades if t["pnl_pct"] <= 0]
    winrate = len(wins) / len(all_trades) * 100 if all_trades else 0
    avg_win = gross_profit / len(wins) if wins else 0
    avg_loss = gross_loss / len(losses) if losses else 0
    expectancy = winrate / 100 * avg_win - (1 - winrate / 100) * avg_loss

    # Correct avg_rr
    total_rr = sum(r["avg_rr"] * r["total_trades"] for r in records)
    avg_rr = total_rr / total_trades if total_trades else 0

    # Max drawdown (weighted)
    max_dd = max(r["max_drawdown"] for r in records) if records else 0

    # Exit reasons
    exit_sl = sum(r["exit_sl"] for r in records)
    exit_tp = sum(r["exit_tp"] for r in records)
    exit_eob = sum(r["exit_eob"] for r in records)
    src_atr = sum(r["src_atr"] for r in records)
    src_bos = sum(r["src_bos"] for r in records)
    src_structural = sum(r["src_structural"] for r in records)
    reject_rr = sum(r["reject_rr"] for r in records)
    reject_sl = sum(r["reject_sl_dist"] for r in records)
    reject_ctf = sum(r["reject_confirm_tf"] for r in records)

    agg[preset] = {
        "total_trades": total_trades,
        "symbols": len(records),
        "winrate": round(winrate, 1),
        "avg_pnl": round(sum(r["avg_pnl"] * r["total_trades"] for r in records) / total_trades, 4),
        "avg_net_pnl": round(sum(r["avg_net_pnl"] * r["total_trades"] for r in records) / total_trades, 4),
        "avg_rr": round(avg_rr, 2),
        "profit_factor": pf,
        "expectancy": round(expectancy, 4),
        "max_drawdown": round(max_dd, 4),
        "total_pnl_pct": round(total_pnl, 4),
        "total_net_pnl_pct": round(total_net_pnl, 4),
        "signals_generated": total_signals,
        "signals_rejected": total_rejected,
        "exit_sl": exit_sl,
        "exit_tp": exit_tp,
        "exit_eob": exit_eob,
        "src_atr": src_atr,
        "src_bos": src_bos,
        "src_structural": src_structural,
        "reject_rr": reject_rr,
        "reject_sl_dist": reject_sl,
        "reject_confirm_tf": reject_ctf,
        "gross_profit": round(gross_profit, 4),
        "gross_loss": round(gross_loss, 4),
    }

# Save corrected aggregates
with open(RESULTS_DIR / "aggregates_r6.json", "w") as f:
    json.dump(agg, f, indent=2, ensure_ascii=False)

# Print summary
print(f"{'Preset':28s} {'Trades':>6s} {'WR%':>6s} {'PnL(net)':>10s} {'PF':>6s} {'MaxDD':>8s} {'AvgRR':>6s}")
print(f"{'-'*28} {'-'*6} {'-'*6} {'-'*10} {'-'*6} {'-'*8} {'-'*6}")
for p in PRESETS:
    a = agg[p]
    print(f"{p:28s} {a.get('total_trades',0):6d} {a.get('winrate',0):5.1f}% "
          f"{a.get('total_net_pnl_pct',0):+9.2f}% {a.get('profit_factor',0):5.2f} "
          f"{a.get('max_drawdown',0):7.2f}% {a.get('avg_rr',0):5.2f}")

print(f"\n--- Key comparison: true_baseline | full_new | unified_plus_filters ---")
for p in ["true_baseline", "full_new", "unified_plus_filters"]:
    a = agg[p]
    print(f"  {p:28s} net_pnl={a.get('total_net_pnl_pct',0):+.2f}%  pf={a.get('profit_factor',0):.2f}  "
          f"trades={a.get('total_trades',0)}  wr={a.get('winrate',0):.1f}%  dd={a.get('max_drawdown',0):.2f}%")

print(f"\n--- full_old vs full_new ---")
for p in ["full_old", "full_new"]:
    a = agg[p]
    print(f"  {p:28s} net_pnl={a.get('total_net_pnl_pct',0):+.2f}%  pf={a.get('profit_factor',0):.2f}  "
          f"trades={a.get('total_trades',0)}  wr={a.get('winrate',0):.1f}%  dd={a.get('max_drawdown',0):.2f}%")
