"""
Deep analysis script for Task 2 / Task 6 backtest data.
Reads raw_results.jsonl and produces:
  1. Per-symbol comparison table (baseline / task2_only / task6_only)
  2. Aggregated totals
  3. Isolated structural SL trade analysis
  4. Final verdict
"""
import json
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from pathlib import Path

RESULTS = Path(__file__).parent / "raw_results.jsonl"

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "XRP/USDT", "SOL/USDT", "DOGE/USDT",
    "AVAX/USDT", "LINK/USDT", "ADA/USDT", "DOT/USDT", "UNI/USDT",
    "NEAR/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "SUI/USDT",
    "INJ/USDT", "WIF/USDT", "FLOKI/USDT", "FIL/USDT", "GRT/USDT",
]

def load_data():
    data = {}  # {(symbol, preset): record}
    with open(RESULTS, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            key = (rec["symbol"], rec["preset"])
            data[key] = rec
    return data


def get_trade_level(data, symbol, preset):
    """Extract all trades for a symbol+preset."""
    rec = data.get((symbol, preset))
    if not rec:
        return []
    return rec.get("trades", [])


def section1_per_symbol_table(data):
    """Full comparison table for all 20 symbols."""
    print("=" * 160)
    print("SECTION 1: PER-SYMBOL COMPARISON TABLE")
    print("=" * 160)
    header = (
        f"{'Symbol':<14} | "
        f"{'BL trades':>9} {'BL PnL%':>10} | "
        f"{'T2 trades':>9} {'T2 PnL%':>10} {'T2 Δ PnL%':>11} | "
        f"{'T6 trades':>9} {'T6 PnL%':>10} {'T6 Δ PnL%':>11} | "
        f"{'StructSL#':>9}"
    )
    print(header)
    print("-" * 160)

    totals = {"bl_trades": 0, "bl_pnl": 0, "t2_trades": 0, "t2_pnl": 0, "t6_trades": 0, "t6_pnl": 0, "struct_count": 0}
    symbols_with_struct = 0

    for sym in SYMBOLS:
        bl = data.get((sym, "baseline"), {})
        t2 = data.get((sym, "task2_only"), {})
        t6 = data.get((sym, "task6_only"), {})

        bl_tr = bl.get("total_trades", 0)
        bl_pnl = bl.get("total_net_pnl_pct", 0)
        t2_tr = t2.get("total_trades", 0)
        t2_pnl = t2.get("total_net_pnl_pct", 0)
        t6_tr = t6.get("total_trades", 0)
        t6_pnl = t6.get("total_net_pnl_pct", 0)
        struct_n = t2.get("src_structural", 0)

        t2_delta = t2_pnl - bl_pnl
        t6_delta = t6_pnl - bl_pnl

        totals["bl_trades"] += bl_tr
        totals["bl_pnl"] += bl_pnl
        totals["t2_trades"] += t2_tr
        totals["t2_pnl"] += t2_pnl
        totals["t6_trades"] += t6_tr
        totals["t6_pnl"] += t6_pnl
        totals["struct_count"] += struct_n
        if struct_n > 0:
            symbols_with_struct += 1

        print(
            f"{sym:<14} | "
            f"{bl_tr:>9} {bl_pnl:>+10.2f} | "
            f"{t2_tr:>9} {t2_pnl:>+10.2f} {t2_delta:>+11.2f} | "
            f"{t6_tr:>9} {t6_pnl:>+10.2f} {t6_delta:>+11.2f} | "
            f"{struct_n:>9}"
        )

    print("-" * 160)
    print(
        f"{'TOTAL':<14} | "
        f"{totals['bl_trades']:>9} {totals['bl_pnl']:>+10.2f} | "
        f"{totals['t2_trades']:>9} {totals['t2_pnl']:>+10.2f} {totals['t2_pnl'] - totals['bl_pnl']:>+11.2f} | "
        f"{totals['t6_trades']:>9} {totals['t6_pnl']:>+10.2f} {totals['t6_pnl'] - totals['bl_pnl']:>+11.2f} | "
        f"{totals['struct_count']:>9}"
    )
    print()
    print(f"Symbols with structural SL > 0: {symbols_with_struct}/20 ({symbols_with_struct/20*100:.0f}%)")
    print(f"Total structural SL trades (task2_only): {totals['struct_count']}")
    print()
    return totals


def section2_aggregated(data):
    """Aggregated metrics: PnL, win rate, profit factor."""
    print("=" * 100)
    print("SECTION 2: AGGREGATED TOTALS (all 20 symbols)")
    print("=" * 100)

    presets = ["baseline", "task2_only", "task6_only"]
    agg = {}
    for preset in presets:
        total_trades = 0
        total_wins = 0
        total_gross_pnl = 0
        total_net_pnl = 0
        gross_wins = 0
        gross_losses = 0

        for sym in SYMBOLS:
            rec = data.get((sym, preset), {})
            tr = rec.get("total_trades", 0)
            w = rec.get("wins", 0)
            total_trades += tr
            total_wins += w
            total_gross_pnl += rec.get("total_pnl_pct", 0)
            total_net_pnl += rec.get("total_net_pnl_pct", 0)
            # Profit factor: sum of winning trades / abs(sum of losing trades)
            for t in rec.get("trades", []):
                pnl = t.get("net_pnl_pct", 0)
                if pnl > 0:
                    gross_wins += pnl
                else:
                    gross_losses += abs(pnl)

        winrate = (total_wins / total_trades * 100) if total_trades else 0
        pf = (gross_wins / gross_losses) if gross_losses else 0
        agg[preset] = {
            "trades": total_trades,
            "wins": total_wins,
            "winrate": winrate,
            "gross_pnl": total_gross_pnl,
            "net_pnl": total_net_pnl,
            "pf": pf,
            "gross_wins": gross_wins,
            "gross_losses": gross_losses,
        }

    print(f"\n{'Metric':<25} | {'baseline':>12} | {'task2_only':>12} | {'task6_only':>12}")
    print("-" * 70)
    for label, key, fmt in [
        ("Total trades", "trades", "{:d}"),
        ("Total wins", "wins", "{:d}"),
        ("Win rate %", "winrate", "{:.1f}%"),
        ("Sum gross PnL %", "gross_pnl", "{:+.2f}%"),
        ("Sum net PnL %", "net_pnl", "{:+.2f}%"),
        ("Profit Factor", "pf", "{:.3f}"),
        ("Gross wins sum", "gross_wins", "{:+.2f}%"),
        ("Gross losses sum", "gross_losses", "{:.2f}%"),
    ]:
        vals = []
        for p in presets:
            v = agg[p][key]
            vals.append(fmt.format(v))
        print(f"{label:<25} | {vals[0]:>12} | {vals[1]:>12} | {vals[2]:>12}")

    print()
    print(f"task2_only vs baseline:  PnL Δ = {agg['task2_only']['net_pnl'] - agg['baseline']['net_pnl']:+.2f}%  |  WR Δ = {agg['task2_only']['winrate'] - agg['baseline']['winrate']:+.1f}%  |  PF Δ = {agg['task2_only']['pf'] - agg['baseline']['pf']:+.3f}")
    print(f"task6_only vs baseline:  PnL Δ = {agg['task6_only']['net_pnl'] - agg['baseline']['net_pnl']:+.2f}%  |  WR Δ = {agg['task6_only']['winrate'] - agg['baseline']['winrate']:+.1f}%  |  PF Δ = {agg['task6_only']['pf'] - agg['baseline']['pf']:+.3f}")
    print(f"task6_only vs task2_only: PnL Δ = {agg['task6_only']['net_pnl'] - agg['task2_only']['net_pnl']:+.2f}%  |  WR Δ = {agg['task6_only']['winrate'] - agg['task2_only']['winrate']:+.1f}%  |  PF Δ = {agg['task6_only']['pf'] - agg['task2_only']['pf']:+.3f}")
    print()
    return agg


def section3_structural_sl_isolation(data):
    """Isolated analysis of structural SL trades."""
    print("=" * 120)
    print("SECTION 3: ISOLATED STRUCTURAL SL TRADE ANALYSIS")
    print("=" * 120)

    # Collect all structural SL trades from task2_only
    struct_trades = []
    # Collect all ATR/BOS trades from task2_only for comparison
    non_struct_trades = []

    for sym in SYMBOLS:
        rec = data.get((sym, "task2_only"), {})
        for t in rec.get("trades", []):
            src = t.get("sl_source", "atr")
            if src == "structural":
                struct_trades.append(t)
            else:
                non_struct_trades.append(t)

    print(f"\nTotal structural SL trades: {len(struct_trades)}")
    print(f"Total non-structural trades (ATR/BOS): {len(non_struct_trades)}")

    if struct_trades:
        struct_wins = sum(1 for t in struct_trades if t.get("net_pnl_pct", 0) > 0)
        struct_losses = sum(1 for t in struct_trades if t.get("net_pnl_pct", 0) <= 0)
        struct_avg_pnl = sum(t.get("net_pnl_pct", 0) for t in struct_trades) / len(struct_trades)
        struct_wr = struct_wins / len(struct_trades) * 100

        nonstruct_wins = sum(1 for t in non_struct_trades if t.get("net_pnl_pct", 0) > 0)
        nonstruct_avg_pnl = sum(t.get("net_pnl_pct", 0) for t in non_struct_trades) / len(non_struct_trades) if non_struct_trades else 0
        nonstruct_wr = nonstruct_wins / len(non_struct_trades) * 100 if non_struct_trades else 0

        print(f"\n{'Metric':<30} | {'Structural SL':>15} | {'ATR/BOS (non-struct)':>20} | {'Delta':>10}")
        print("-" * 80)
        print(f"{'Count':<30} | {len(struct_trades):>15} | {len(non_struct_trades):>20} | {len(struct_trades) - len(non_struct_trades):>+10}")
        print(f"{'Win rate %':<30} | {struct_wr:>14.1f}% | {nonstruct_wr:>19.1f}% | {struct_wr - nonstruct_wr:>+9.1f}%")
        print(f"{'Avg net PnL %':<30} | {struct_avg_pnl:>+14.4f}% | {nonstruct_avg_pnl:>+19.4f}% | {struct_avg_pnl - nonstruct_avg_pnl:>+9.4f}%")
        print(f"{'Wins':<30} | {struct_wins:>15} | {nonstruct_wins:>20} | {struct_wins - nonstruct_wins:>+10}")
        print(f"{'Losses':<30} | {len(struct_trades) - struct_wins:>15} | {len(non_struct_trades) - nonstruct_wins:>20} |")

        # Also show per-symbol structural SL breakdown
        print(f"\n--- Per-Symbol Structural SL Trades (task2_only) ---")
        print(f"{'Symbol':<14} | {'#':>3} | {'WR%':>6} | {'Avg PnL%':>10} | {'Trades':>6}")
        print("-" * 50)
        for sym in SYMBOLS:
            rec = data.get((sym, "task2_only"), {})
            sym_struct = [t for t in rec.get("trades", []) if t.get("sl_source") == "structural"]
            if sym_struct:
                sw = sum(1 for t in sym_struct if t.get("net_pnl_pct", 0) > 0)
                swr = sw / len(sym_struct) * 100
                sap = sum(t.get("net_pnl_pct", 0) for t in sym_struct) / len(sym_struct)
                print(f"{sym:<14} | {len(sym_struct):>3} | {swr:>5.1f}% | {sap:>+10.4f}% | {rec.get('total_trades', 0):>6}")

        # Compare structural vs same-symbol ATR trades
        print(f"\n--- Structural SL Trades: Win/Loss by Exit Reason ---")
        struct_sl = [t for t in struct_trades if t.get("exit_reason") == "sl"]
        struct_tp = [t for t in struct_trades if t.get("exit_reason") == "tp"]
        struct_eob = [t for t in struct_trades if t.get("exit_reason") == "eob"]
        print(f"  SL exits: {len(struct_sl)} ({sum(1 for t in struct_sl if t.get('net_pnl_pct',0)>0)} wins)")
        print(f"  TP exits: {len(struct_tp)} ({sum(1 for t in struct_tp if t.get('net_pnl_pct',0)>0)} wins)")
        print(f"  EOB exits: {len(struct_eob)}")

        # Show the actual structural SL trades with details
        print(f"\n--- All Structural SL Trades Detail (task2_only) ---")
        print(f"{'Symbol':<14} | {'Dir':>4} | {'SL PnL%':>9} | {'Exit':>4} | {'Regime':<12} | {'Entry→Exit':>15}")
        print("-" * 80)
        for t in struct_trades:
            entry_p = t.get("entry_price", 0)
            exit_p = t.get("exit_price", 0)
            print(
                f"{t['symbol']:<14} | {t['direction']:>4} | "
                f"{t.get('net_pnl_pct', 0):>+9.4f} | {t.get('exit_reason', '?'):>4} | "
                f"{t.get('regime', '?'):<12} | {entry_p:.4f}→{exit_p:.4f}"
            )
    else:
        print("\nNo structural SL trades found.")

    # Also check task6_only for comparison
    print(f"\n--- task6_only Structural SL Trades ---")
    t6_struct = []
    for sym in SYMBOLS:
        rec = data.get((sym, "task6_only"), {})
        for t in rec.get("trades", []):
            if t.get("sl_source") == "structural":
                t6_struct.append(t)
    print(f"Total structural SL trades (task6_only): {len(t6_struct)}")
    if t6_struct:
        t6_sw = sum(1 for t in t6_struct if t.get("net_pnl_pct", 0) > 0)
        t6_swr = t6_sw / len(t6_struct) * 100
        t6_sap = sum(t.get("net_pnl_pct", 0) for t in t6_struct) / len(t6_struct)
        print(f"Win rate: {t6_swr:.1f}%  |  Avg PnL: {t6_sap:+.4f}%")

    print()
    return struct_trades, non_struct_trades


def main():
    data = load_data()
    print(f"Loaded {len(data)} records from {RESULTS}\n")

    totals = section1_per_symbol_table(data)
    agg = section2_aggregated(data)
    struct_trades, non_struct_trades = section3_structural_sl_isolation(data)

    # Verdict
    print("=" * 100)
    print("SECTION 4: FINAL VERDICT")
    print("=" * 100)
    t2_pnl = agg["task2_only"]["net_pnl"]
    bl_pnl = agg["baseline"]["net_pnl"]
    t6_pnl = agg["task6_only"]["net_pnl"]
    t2_delta = t2_pnl - bl_pnl
    t6_delta = t6_pnl - bl_pnl

    print(f"\nTask 2 (structural SL only): PnL Δ = {t2_delta:+.2f}% vs baseline")
    print(f"Task 6 (buffer + structural): PnL Δ = {t6_delta:+.2f}% vs baseline")
    print(f"Task 6 vs Task 2: PnL Δ = {t6_pnl - t2_pnl:+.2f}%")
    print()

    if struct_trades:
        struct_wins = sum(1 for t in struct_trades if t.get("net_pnl_pct", 0) > 0)
        struct_wr = struct_wins / len(struct_trades) * 100
        struct_avg = sum(t.get("net_pnl_pct", 0) for t in struct_trades) / len(struct_trades)
        print(f"Structural SL trades: {len(struct_trades)} total, {struct_wr:.1f}% WR, {struct_avg:+.4f}% avg PnL")
    print()


if __name__ == "__main__":
    main()
