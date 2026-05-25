"""
scripts/analyze_gate_stats.py — Aggregate GATE_STATS from bot logs.

Usage:
    python -m scripts.analyze_gate_stats logs/bot.log
    python -m scripts.analyze_gate_stats logs/bot.log --min-samples 10

Parses GATE_STATS entries, computes pass rates per gate, top rejection
reasons, and gate_fail_chain frequency analysis.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def parse_gate_stats(line: str) -> dict | None:
    m = re.search(
        r"GATE_STATS\s+(?P<outcome>pass|reject)\s+"
        r"symbol=(?P<symbol>\S+)\s+tf=(?P<tf>\S+)\s+"
        r"(?:(?:failed=(?P<failed>\S+))?\s*)?"
        r"(?:passed=(?P<passed>\S+))?",
        line,
    )
    if not m:
        return None
    return m.groupdict()


def analyze(path: str, min_samples: int = 5):
    total = 0
    passes = 0
    rejects = 0
    gate_counts: dict[str, list[bool]] = defaultdict(list)
    fail_chain_counter: Counter[str] = Counter()
    per_filter_rejects: Counter[str] = Counter()
    symbol_tf_fails: dict[str, Counter] = defaultdict(Counter)

    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        parsed = parse_gate_stats(line)
        if not parsed:
            continue
        total += 1
        if parsed["outcome"] == "pass":
            passes += 1
            gates_str = parsed.get("passed", "")
            for part in gates_str.split("|"):
                if "=" in part:
                    name, val = part.split("=", 1)
                    gate_counts[name].append(val == "1")
        else:
            rejects += 1
            failed_str = parsed.get("failed", "")
            if not failed_str:
                continue
            gates = failed_str.split("|")
            fail_chain_counter["|".join(gates)] += 1
            for g in gates:
                per_filter_rejects[g] += 1
                key = f"{parsed['symbol']}|{parsed['tf']}"
                symbol_tf_fails[key][g] += 1
            for g in gates:
                gate_counts[g].append(False)

    print(f"\n{'='*60}")
    print(f"  GATE STATS ANALYSIS — {path}")
    print(f"{'='*60}")
    print(f"\nTotal evaluations: {total}")
    print(f"Passes:            {passes} ({passes/total*100:.1f}%)" if total else "0")
    print(f"Rejects:           {rejects} ({rejects/total*100:.1f}%)" if total else "0")

    if total == 0:
        print("\nNo GATE_STATS found. Is DEBUG logging enabled?")
        return

    # Pass rate per gate (sorted by pass rate ascending)
    print(f"\n  --- Pass rate per gate (min {min_samples} samples) ---")
    print(f"  {'Gate':20s} {'Passes':>8s} {'Total':>8s} {'Rate':>8s}")
    print(f"  {'-'*46}")
    sorted_gates = sorted(
        gate_counts.items(),
        key=lambda x: sum(x[1]) / len(x[1]) if x[1] else 0,
    )
    for gate, outcomes in sorted_gates:
        n = len(outcomes)
        if n < min_samples:
            continue
        passed = sum(outcomes)
        rate = passed / n * 100
        print(f"  {gate:20s} {passed:8d} {n:8d} {rate:7.1f}%")

    # Top rejection filters
    print(f"\n  --- Top reject filters ---")
    print(f"  {'Filter':20s} {'Rejects':>8s} {'% of rejects':>12s}")
    print(f"  {'-'*42}")
    for filter_name, count in per_filter_rejects.most_common(10):
        print(f"  {filter_name:20s} {count:8d} {count/rejects*100:11.1f}%")

    # Fail chain frequency
    print(f"\n  --- Gate fail chain frequency (top 15) ---")
    print(f"  {'Chain':40s} {'Count':>6s} {'%':>8s}")
    print(f"  {'-'*56}")
    for chain, count in fail_chain_counter.most_common(15):
        print(f"  {chain:40s} {count:6d} {count/total*100:7.1f}%")

    # Correlation suggestion: gates that always appear together
    print(f"\n  --- Potential correlated gate pairs (fail in same rejection) ---")
    pair_counts: Counter[str] = Counter()
    for chain, count in fail_chain_counter.items():
        gates = chain.split("|")
        if len(gates) >= 2:
            for i in range(len(gates)):
                for j in range(i + 1, len(gates)):
                    pair = f"{gates[i]} + {gates[j]}"
                    pair_counts[pair] += count
    for pair, count in pair_counts.most_common(10):
        print(f"  {pair:40s} {count:6d} co-rejections")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "logs/bot.log"
    min_samples = 5
    if "--min-samples" in sys.argv:
        idx = sys.argv.index("--min-samples")
        min_samples = int(sys.argv[idx + 1])
    analyze(path, min_samples=min_samples)
