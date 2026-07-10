"""
reports/confidence_analysis.py — Confidence V2 Bucket & Factor Attribution Analysis.

Reads signals + outcomes + confidence factors from data/signals.db and generates:

1. Confidence Bucket Analysis — WR, PF, Avg PnL per confidence range
2. Confidence Factor Attribution — per-factor contribution analysis
3. Calibration check — does higher confidence = better outcomes?

Usage:
    python -m reports.confidence_analysis
"""
import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "signals.db"

BUCKETS = [
    (0, 20, "0-20"),
    (20, 40, "20-40"),
    (40, 60, "40-60"),
    (60, 80, "60-80"),
    (80, 100, "80-100"),
]


@dataclass
class Trade:
    signal_id: int
    symbol: str
    signal_type: str
    close_price: float
    sl: float
    tp: float
    score: int
    status: str
    pnl_pct: float
    confidence_pct: float
    factors: list  # [{name, weight, raw_score, weighted_score}, ...]
    factor_fingerprint: str
    created_at: str


def load_trades() -> list[Trade]:
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT s.id, s.symbol, s.signal_type, s.close_price, s.sl, s.tp,
               s.score, s.factor_fingerprint, s.confidence_v2_pct,
               s.confidence_v2_factors, s.created_at,
               o.status, o.pnl_pct
        FROM signals s
        JOIN signal_outcomes o ON s.id = o.signal_id
        WHERE s.confidence_v2_pct IS NOT NULL
          AND o.status IN ('HIT_TP', 'HIT_SL')
        ORDER BY s.created_at
    """)

    trades = []
    for row in c.fetchall():
        factors = json.loads(row["confidence_v2_factors"]) if row["confidence_v2_factors"] else []
        trades.append(Trade(
            signal_id=row["id"],
            symbol=row["symbol"],
            signal_type=row["signal_type"],
            close_price=row["close_price"],
            sl=row["sl"],
            tp=row["tp"],
            score=row["score"],
            status=row["status"],
            pnl_pct=row["pnl_pct"] or 0.0,
            confidence_pct=row["confidence_v2_pct"] or 0.0,
            factors=factors,
            factor_fingerprint=row["factor_fingerprint"] or "",
            created_at=row["created_at"],
        ))

    conn.close()
    return trades


def bucket_analysis(trades: list[Trade]) -> str:
    lines = []
    lines.append("=" * 80)
    lines.append("CONFIDENCE BUCKET ANALYSIS")
    lines.append("=" * 80)
    lines.append("")

    bucket_data = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "pnls": []})

    for t in trades:
        conf = min(t.confidence_pct, 99.99)
        for lo, hi, label in BUCKETS:
            if lo <= conf < hi:
                bucket_data[label]["trades"] += 1
                if t.status == "HIT_TP":
                    bucket_data[label]["wins"] += 1
                else:
                    bucket_data[label]["losses"] += 1
                bucket_data[label]["pnls"].append(t.pnl_pct)
                break

    header = f"{'Bucket':<10} {'Trades':>7} {'Wins':>5} {'Losses':>6} {'WR':>7} {'PF':>7} {'Avg PnL':>9} {'Total PnL':>10}"
    lines.append(header)
    lines.append("-" * 80)

    total_trades = 0
    total_wins = 0
    total_pnls = []

    for lo, hi, label in BUCKETS:
        d = bucket_data[label]
        n = d["trades"]
        total_trades += n
        total_wins += d["wins"]
        total_pnls.extend(d["pnls"])

        if n == 0:
            lines.append(f"{label:<10} {'—':>7} {'—':>5} {'—':>6} {'—':>7} {'—':>7} {'—':>9} {'—':>10}")
            continue

        wr = d["wins"] / n * 100
        gross_profit = sum(p for p in d["pnls"] if p > 0)
        gross_loss = abs(sum(p for p in d["pnls"] if p < 0))
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        avg_pnl = sum(d["pnls"]) / n
        total_pnl = sum(d["pnls"])

        lines.append(
            f"{label:<10} {n:>7} {d['wins']:>5} {d['losses']:>6} "
            f"{wr:>6.1f}% {pf:>6.2f} {avg_pnl:>+8.2f}% {total_pnl:>+9.2f}%"
        )

    lines.append("-" * 80)
    overall_wr = total_wins / total_trades * 100 if total_trades else 0
    overall_pnl = sum(total_pnls)
    overall_avg = overall_pnl / total_trades if total_trades else 0
    lines.append(
        f"{'TOTAL':<10} {total_trades:>7} {total_wins:>5} {total_trades - total_wins:>6} "
        f"{overall_wr:>6.1f}% {'—':>7} {overall_avg:>+8.2f}% {overall_pnl:>+9.2f}%"
    )
    lines.append("")

    # Calibration check
    lines.append("CALIBRATION CHECK:")
    lines.append("  Does higher confidence → better outcomes?")
    lines.append("")

    wr_by_bucket = {}
    for lo, hi, label in BUCKETS:
        d = bucket_data[label]
        if d["trades"] > 0:
            wr_by_bucket[label] = d["wins"] / d["trades"] * 100

    if len(wr_by_bucket) >= 2:
        sorted_buckets = sorted(wr_by_bucket.items(), key=lambda x: BUCKETS[[b[2] for b in BUCKETS].index(x[0])][0])
        wrs = [w for _, w in sorted_buckets]
        labels = [l for l, _ in sorted_buckets]

        monotonic_up = all(wrs[i] <= wrs[i + 1] for i in range(len(wrs) - 1))
        monotonic_down = all(wrs[i] >= wrs[i + 1] for i in range(len(wrs) - 1))

        if monotonic_up:
            lines.append("  [OK] Calibration: MONOTONIC INCREASING -- higher confidence = higher WR")
        elif monotonic_down:
            lines.append("  [!!] Calibration: MONOTONIC DECREASING -- higher confidence = LOWER WR (INVERTED)")
        else:
            lines.append("  [!!] Calibration: NON-MONOTONIC -- confidence is NOT well calibrated")
            lines.append(f"    WR sequence: {' -> '.join(f'{l}={w:.1f}%' for l, w in sorted_buckets)}")
    else:
        lines.append("  ⚠ Not enough buckets with data to assess calibration")

    return "\n".join(lines)


def factor_attribution(trades: list[Trade]) -> str:
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("CONFIDENCE FACTOR ATTRIBUTION")
    lines.append("=" * 80)
    lines.append("")

    if not trades:
        lines.append("No trades with factor data.")
        return "\n".join(lines)

    # Collect all factor names
    all_factor_names = []
    seen = set()
    for t in trades:
        for f in t.factors:
            if f["name"] not in seen:
                all_factor_names.append(f["name"])
                seen.add(f["name"])

    # Per-factor breakdown: aligned (raw_score has same sign as signal direction) vs against
    header = f"{'Factor':<18} {'Aligned':>8} {'WR':>7} {'Avg PnL':>9} {'Against':>8} {'WR':>7} {'Avg PnL':>9} {'Neutral':>8} {'WR':>7} {'Avg PnL':>9}"
    lines.append(header)
    lines.append("-" * 120)

    factor_stats = {}

    for fname in all_factor_names:
        aligned = {"trades": 0, "wins": 0, "pnls": []}
        against = {"trades": 0, "wins": 0, "pnls": []}
        neutral = {"trades": 0, "wins": 0, "pnls": []}

        for t in trades:
            factor_val = None
            for f in t.factors:
                if f["name"] == fname:
                    factor_val = f["raw_score"]
                    break
            if factor_val is None:
                continue

            # Determine alignment: factor supports signal direction
            is_buy = t.signal_type == "BUY"
            if abs(factor_val) < 0.1:
                bucket = neutral
            elif (is_buy and factor_val > 0) or (not is_buy and factor_val < 0):
                bucket = aligned
            else:
                bucket = against

            bucket["trades"] += 1
            if t.status == "HIT_TP":
                bucket["wins"] += 1
            bucket["pnls"].append(t.pnl_pct)

        def fmt(d):
            n = d["trades"]
            if n == 0:
                return f"{'—':>8} {'—':>7} {'—':>9}"
            wr = d["wins"] / n * 100
            avg = sum(d["pnls"]) / n
            return f"{n:>8} {wr:>6.1f}% {avg:>+8.2f}%"

        lines.append(f"{fname:<18} {fmt(aligned)} {fmt(against)} {fmt(neutral)}")

        # Store for summary
        total_aligned = aligned["trades"]
        total_against = against["trades"]
        wr_aligned = aligned["wins"] / total_aligned * 100 if total_aligned else 0
        wr_against = against["wins"] / total_against * 100 if total_against else 0
        avg_aligned = sum(aligned["pnls"]) / total_aligned if total_aligned else 0
        avg_against = sum(against["pnls"]) / total_against if total_against else 0
        delta_wr = wr_aligned - wr_against
        delta_pnl = avg_aligned - avg_against
        factor_stats[fname] = {
            "aligned_count": total_aligned,
            "against_count": total_against,
            "delta_wr": delta_wr,
            "delta_pnl": delta_pnl,
            "total": total_aligned + total_against,
        }

    lines.append("")
    lines.append("FACTOR IMPORTANCE RANKING (by WR delta: aligned vs against):")
    lines.append(f"  {'Rank':<5} {'Factor':<18} {'ΔWR':>8} {'ΔAvgPnL':>10} {'N':>5}")
    lines.append("  " + "-" * 50)

    ranked = sorted(factor_stats.items(), key=lambda x: abs(x[1]["delta_wr"]), reverse=True)
    for i, (fname, s) in enumerate(ranked, 1):
        marker = "*" if abs(s["delta_wr"]) > 10 else " "
        lines.append(
            f"  {i:<5} {fname:<18} {s['delta_wr']:>+7.1f}% {s['delta_pnl']:>+9.2f}% {s['total']:>5} {marker}"
        )

    lines.append("")
    lines.append("INTERPRETATION:")
    lines.append("  ΔWR > 0: factor ALIGNED with signal → higher WR than when AGAINST")
    lines.append("  ΔWR ≈ 0: factor is DECORATIVE (no predictive power)")
    lines.append("  ΔWR < 0: factor is INVERTED (conflicting signal)")
    lines.append("  ★ = |ΔWR| > 10% (potentially meaningful)")

    return "\n".join(lines)


def overall_stats(trades: list[Trade]) -> str:
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("OVERALL STATISTICS")
    lines.append("=" * 80)
    lines.append("")

    if not trades:
        lines.append("No completed trades with confidence data.")
        return "\n".join(lines)

    n = len(trades)
    wins = sum(1 for t in trades if t.status == "HIT_TP")
    losses = n - wins
    wr = wins / n * 100
    pnls = [t.pnl_pct for t in trades]
    total_pnl = sum(pnls)
    avg_pnl = total_pnl / n
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    avg_conf = sum(t.confidence_pct for t in trades) / n

    lines.append(f"  Total completed trades:  {n}")
    lines.append(f"  Wins / Losses:           {wins} / {losses}")
    lines.append(f"  Win Rate:                {wr:.1f}%")
    lines.append(f"  Profit Factor:           {pf:.2f}")
    lines.append(f"  Total PnL:               {total_pnl:+.2f}%")
    lines.append(f"  Avg PnL:                 {avg_pnl:+.2f}%")
    lines.append(f"  Best trade:              {max(pnls):+.2f}%")
    lines.append(f"  Worst trade:             {min(pnls):+.2f}%")
    lines.append(f"  Avg confidence:          {avg_conf:.1f}%")
    lines.append("")

    # By signal type
    for stype in ["BUY", "SELL"]:
        subset = [t for t in trades if t.signal_type == stype]
        if not subset:
            continue
        sn = len(subset)
        sw = sum(1 for t in subset if t.status == "HIT_TP")
        swr = sw / sn * 100
        spnl = sum(t.pnl_pct for t in subset) / sn
        sc = sum(t.confidence_pct for t in subset) / sn
        lines.append(f"  {stype}: {sn} trades, WR={swr:.1f}%, AvgPnL={spnl:+.2f}%, AvgConf={sc:.1f}%")

    return "\n".join(lines)


def factor_value_distribution(trades: list[Trade]) -> str:
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("FACTOR VALUE DISTRIBUTION (raw scores)")
    lines.append("=" * 80)
    lines.append("")
    lines.append("Shows how often each factor contributes positively vs negatively")
    lines.append("")

    all_factor_names = []
    seen = set()
    for t in trades:
        for f in t.factors:
            if f["name"] not in seen:
                all_factor_names.append(f["name"])
                seen.add(f["name"])

    header = f"{'Factor':<18} {'N':>4} {'Pos':>5} {'Neg':>5} {'Zero':>5} {'PosWR':>7} {'NegWR':>7} {'PosAvg':>9} {'NegAvg':>9}"
    lines.append(header)
    lines.append("-" * 95)

    for fname in all_factor_names:
        pos = {"trades": 0, "wins": 0, "pnls": []}
        neg = {"trades": 0, "wins": 0, "pnls": []}
        zero = {"trades": 0, "wins": 0, "pnls": []}

        for t in trades:
            for f in t.factors:
                if f["name"] == fname:
                    r = f["raw_score"]
                    if r > 0.1:
                        b = pos
                    elif r < -0.1:
                        b = neg
                    else:
                        b = zero
                    b["trades"] += 1
                    if t.status == "HIT_TP":
                        b["wins"] += 1
                    b["pnls"].append(t.pnl_pct)
                    break

        total = pos["trades"] + neg["trades"] + zero["trades"]

        def wr_pct(d):
            return f"{d['wins']/d['trades']*100:.1f}%" if d["trades"] else "—"

        def avg_pnl(d):
            return f"{sum(d['pnls'])/d['trades']:+.2f}%" if d["trades"] else "—"

        lines.append(
            f"{fname:<18} {total:>4} {pos['trades']:>5} {neg['trades']:>5} {zero['trades']:>5} "
            f"{wr_pct(pos):>7} {wr_pct(neg):>7} {avg_pnl(pos):>9} {avg_pnl(neg):>9}"
        )

    return "\n".join(lines)


def main():
    trades = load_trades()
    print(f"Loaded {len(trades)} completed trades with confidence_v2 data.\n")

    if not trades:
        print("No trades with confidence_v2 data found.")
        print("New signals will have factor data after bot restart.")
        print("\nGenerating analysis from available context_snapshots data instead...\n")
        context_analysis()
        return

    report_parts = [
        overall_stats(trades),
        bucket_analysis(trades),
        factor_attribution(trades),
        factor_value_distribution(trades),
    ]

    report = "\n".join(report_parts)
    print(report)

    # Save to file
    report_path = Path(__file__).resolve().parent / "confidence_report.txt"
    report_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to {report_path}")


def context_analysis():
    """Fallback analysis using context_snapshots data when confidence_v2 factors aren't stored yet."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    c.execute("""
        SELECT s.id, s.symbol, s.signal_type, s.score, s.factor_fingerprint,
               o.status, o.pnl_pct,
               cs.confidence as ctx_confidence, cs.score as ctx_score,
               cs.fear_greed, cs.funding_rate, cs.long_short_ratio,
               cs.open_interest_delta, cs.news_sentiment
        FROM signals s
        JOIN signal_outcomes o ON s.id = o.signal_id
        LEFT JOIN context_snapshots cs ON s.id = cs.signal_id
        WHERE o.status IN ('HIT_TP', 'HIT_SL')
        ORDER BY s.created_at
    """)

    rows = c.fetchall()
    conn.close()

    if not rows:
        print("No completed trades found at all.")
        return

    print("=" * 80)
    print("AVAILABLE DATA (no confidence_v2 factors stored yet)")
    print("=" * 80)
    print()

    # Factor fingerprint analysis
    fp_data = defaultdict(lambda: {"trades": 0, "wins": 0, "pnls": []})
    for r in rows:
        fp = r["factor_fingerprint"] or "unknown"
        fp_data[fp]["trades"] += 1
        if r["status"] == "HIT_TP":
            fp_data[fp]["wins"] += 1
        fp_data[fp]["pnls"].append(r["pnl_pct"] or 0)

    print("FACTOR FINGERPRINT ANALYSIS (qualitative combos):")
    print(f"  {'Fingerprint':<60} {'N':>4} {'WR':>7} {'AvgPnL':>9}")
    print("  " + "-" * 85)

    for fp, d in sorted(fp_data.items(), key=lambda x: -x[1]["trades"]):
        wr = d["wins"] / d["trades"] * 100 if d["trades"] else 0
        avg = sum(d["pnls"]) / d["trades"] if d["pnls"] else 0
        print(f"  {fp:<60} {d['trades']:>4} {wr:>6.1f}% {avg:>+8.2f}%")

    # Context data analysis
    print()
    print("CONTEXT DATA AVAILABILITY:")
    ctx_count = sum(1 for r in rows if r["ctx_confidence"] is not None)
    fg_count = sum(1 for r in rows if r["fear_greed"] is not None)
    fr_count = sum(1 for r in rows if r["funding_rate"] is not None)
    oi_count = sum(1 for r in rows if r["open_interest_delta"] is not None)
    print(f"  Context snapshots linked:  {ctx_count}/{len(rows)}")
    print(f"  Fear & Greed data:         {fg_count}/{len(rows)}")
    print(f"  Funding rate data:         {fr_count}/{len(rows)}")
    print(f"  Open Interest data:        {oi_count}/{len(rows)}")

    # Context confidence vs outcome
    if ctx_count > 0:
        print()
        print("CONTEXT CONFIDENCE vs OUTCOME:")
        print(f"  {'CtxConf':<10} {'N':>4} {'WR':>7} {'AvgPnL':>9}")
        print("  " + "-" * 35)

        ctx_buckets = defaultdict(lambda: {"trades": 0, "wins": 0, "pnls": []})
        for r in rows:
            if r["ctx_confidence"] is not None:
                bucket = int(r["ctx_confidence"] / 20) * 20
                label = f"{bucket}-{bucket+20}"
                ctx_buckets[label]["trades"] += 1
                if r["status"] == "HIT_TP":
                    ctx_buckets[label]["wins"] += 1
                ctx_buckets[label]["pnls"].append(r["pnl_pct"] or 0)

        for label in sorted(ctx_buckets.keys()):
            d = ctx_buckets[label]
            wr = d["wins"] / d["trades"] * 100 if d["trades"] else 0
            avg = sum(d["pnls"]) / d["trades"] if d["pnls"] else 0
            print(f"  {label:<10} {d['trades']:>4} {wr:>6.1f}% {avg:>+8.2f}%")

    # Overall
    print()
    n = len(rows)
    wins = sum(1 for r in rows if r["status"] == "HIT_TP")
    pnls = [r["pnl_pct"] or 0 for r in rows]
    print(f"OVERALL: {n} trades, WR={wins/n*100:.1f}%, AvgPnL={sum(pnls)/n:+.2f}%, TotalPnL={sum(pnls):+.2f}%")
    print()
    print("NOTE: confidence_v2 factor scores will be stored for new signals after bot restart.")
    print("Re-run this script after accumulating ~30+ signals for meaningful bucket analysis.")


if __name__ == "__main__":
    main()
