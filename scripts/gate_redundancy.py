"""Gate Redundancy Validation — quantitative analysis of gate overlaps."""
import sqlite3
import math
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "signals.db"

GATES = [
    'gate_cooldown', 'gate_portfolio_risk', 'gate_btc_global_trend',
    'gate_indicators', 'gate_confirm_tf', 'gate_signal_engine',
    'gate_distance_filter', 'gate_tp_path', 'gate_mtf_alignment',
    'gate_btc_correlation', 'gate_eth_correlation', 'gate_volatility',
    'gate_context_timeout', 'gate_context_block', 'gate_context_min_verdict',
    'gate_news', 'gate_sl_distance', 'gate_rr_guard', 'gate_no_trade_zones',
    'gate_dynamic_risk', 'gate_confidence_v2', 'gate_dedup', 'gate_compression_block',
]


def phi_coefficient(a, b):
    n11 = sum(1 for x, y in zip(a, b) if x == 0 and y == 0)
    n10 = sum(1 for x, y in zip(a, b) if x == 0 and y != 0)
    n01 = sum(1 for x, y in zip(a, b) if x != 0 and y == 0)
    n00 = sum(1 for x, y in zip(a, b) if x != 0 and y != 0)
    n1_ = n11 + n10
    n0_ = n01 + n00
    n_1 = n11 + n01
    n_0 = n10 + n00
    denom = math.sqrt(max(n1_ * n0_ * n_1 * n_0, 1))
    if denom == 0:
        return 0.0
    return (n11 * n00 - n10 * n01) / denom


def jaccard_blocked(a, b):
    a_b = set(i for i, x in enumerate(a) if x == 0)
    b_b = set(i for i, x in enumerate(b) if x == 0)
    if not a_b and not b_b:
        return 0.0
    return len(a_b & b_b) / max(len(a_b | b_b), 1)


def conditional_entropy(a, b):
    n = len(a)
    h_a_given_b = 0.0
    for val in set(b):
        b_idx = [i for i, x in enumerate(b) if x == val]
        if not b_idx:
            continue
        p_b = len(b_idx) / n
        blocked_in_b = sum(1 for i in b_idx if a[i] == 0)
        p_a1 = blocked_in_b / len(b_idx)
        p_a0 = 1 - p_a1
        h = 0
        if p_a1 > 0:
            h -= p_a1 * math.log2(p_a1)
        if p_a0 > 0:
            h -= p_a0 * math.log2(p_a0)
        h_a_given_b += p_b * h
    return h_a_given_b


def entropy(a):
    n = len(a)
    p1 = sum(1 for x in a if x == 0) / n
    p0 = 1 - p1
    h = 0
    if p1 > 0:
        h -= p1 * math.log2(p1)
    if p0 > 0:
        h -= p0 * math.log2(p0)
    return h


def mutual_information(a, b):
    return entropy(a) - conditional_entropy(a, b)


def unique_blocks(a, b):
    a_b = sum(1 for x, y in zip(a, b) if x == 0 and y != 0)
    b_a = sum(1 for x, y in zip(a, b) if x != 0 and y == 0)
    return a_b, b_a


def main():
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    c.execute('SELECT COUNT(*) FROM decision_traces')
    total = c.fetchone()[0]

    c.execute('SELECT COUNT(*) FROM decision_traces WHERE signal_generated = 1')
    signals = c.fetchone()[0]

    c.execute('SELECT COUNT(*) FROM decision_traces WHERE outcome IS NOT NULL')
    with_outcome = c.fetchone()[0]

    cols = ','.join(GATES)
    c.execute(f'SELECT {cols}, final_stage, blocked_reason, signal_generated, outcome, pnl_pct FROM decision_traces')
    rows = c.fetchall()

    print("=" * 100)
    print("GATE REDUNDANCY VALIDATION")
    print("=" * 100)
    print(f"Total traces:      {total}")
    print(f"Signals generated: {signals}")
    print(f"With outcome:      {with_outcome}")
    print()

    # ── Section 1: Per-gate block stats ──
    print("=" * 100)
    print("1. PER-GATE BLOCK STATISTICS")
    print("=" * 100)
    gate_stats = {}
    for i, gate in enumerate(GATES):
        blocked = sum(1 for r in rows if r[i] == 0)
        passed = sum(1 for r in rows if r[i] == 1)
        not_run = sum(1 for r in rows if r[i] is None)
        entered = blocked + passed
        block_rate = blocked / max(entered, 1) * 100
        gate_stats[gate] = {'blocked': blocked, 'passed': passed, 'not_run': not_run,
                            'entered': entered, 'block_rate': block_rate, 'idx': i}
        print(f"  {gate:30s}  entered={entered:5d}  blocked={blocked:5d}  passed={passed:5d}  "
              f"not_run={not_run:5d}  block_rate={block_rate:5.1f}%")

    # ── Section 2: Pairwise overlap ──
    print()
    print("=" * 100)
    print("2. PAIRWISE OVERLAP ANALYSIS")
    print("=" * 100)

    pairs = [
        ('gate_btc_global_trend', 'gate_btc_correlation', 'BTC trend vs BTC correlation'),
        ('gate_btc_correlation', 'gate_no_trade_zones', 'BTC correlation vs no_trade_zones'),
        ('gate_btc_global_trend', 'gate_no_trade_zones', 'BTC global trend vs no_trade_zones'),
        ('gate_context_block', 'gate_context_min_verdict', 'context_block vs context_min_verdict'),
        ('gate_volatility', 'gate_no_trade_zones', 'volatility vs no_trade_zones'),
        ('gate_compression_block', 'gate_signal_engine', 'compression_block vs signal_engine'),
        ('gate_dynamic_risk', 'gate_signal_engine', 'dynamic_risk vs signal_engine'),
        ('gate_cooldown', 'gate_dedup', 'cooldown vs dedup'),
        ('gate_confirm_tf', 'gate_mtf_alignment', 'confirm_tf vs mtf_alignment'),
        ('gate_sl_distance', 'gate_rr_guard', 'sl_distance vs rr_guard'),
        ('gate_distance_filter', 'gate_tp_path', 'distance_filter vs tp_path'),
    ]

    for g1, g2, label in pairs:
        i1 = gate_stats[g1]['idx']
        i2 = gate_stats[g2]['idx']
        a = [r[i1] for r in rows]
        b = [r[i2] for r in rows]

        j = jaccard_blocked(a, b)
        phi = phi_coefficient(a, b)
        mi = mutual_information(a, b)

        a_blocks = gate_stats[g1]['blocked']
        b_blocks = gate_stats[g2]['blocked']
        both = sum(1 for x, y in zip(a, b) if x == 0 and y == 0)
        a_only, b_only = unique_blocks(a, b)

        print(f"\n  --- {label} ---")
        print(f"  {g1:35s} blocks: {a_blocks:5d}  (unique: {a_only:5d})")
        print(f"  {g2:35s} blocks: {b_blocks:5d}  (unique: {b_only:5d})")
        print(f"  Both block:                     {both:5d}")
        print(f"  Jaccard:  {j:.4f}   Phi: {phi:+.4f}   MI: {mi:.4f} bits")
        if a_blocks > 0:
            print(f"  {g1} covers {both}/{a_blocks} = {both/a_blocks*100:.1f}% of {g2} blocks")
        if b_blocks > 0:
            print(f"  {g2} covers {both}/{b_blocks} = {both/b_blocks*100:.1f}% of {g1} blocks")

    # ── Section 3: Counterfactual analysis ──
    print()
    print("=" * 100)
    print("3. COUNTERFACTUAL ANALYSIS (virtual — no outcomes yet)")
    print("=" * 100)
    print("  What if we remove each gate? How many more signals would pass?")
    print()

    for gate in GATES:
        i = gate_stats[gate]['idx']
        currently_blocked = gate_stats[gate]['blocked']
        if currently_blocked == 0:
            continue

        # How many traces are blocked ONLY by this gate?
        # (this gate is False, and no earlier gate is False)
        only_this = 0
        would_pass = 0
        for r in rows:
            if r[i] != 0:
                continue
            # Check if any earlier gate also blocked
            earlier_blocked = False
            for j in range(i):
                if r[j] == 0:
                    earlier_blocked = True
                    break
            if not earlier_blocked:
                only_this += 1
                # Check if any later gate would also block
                later_blocked = False
                for j in range(i + 1, len(GATES)):
                    if r[j] == 0:
                        later_blocked = True
                        break
                if not later_blocked:
                    would_pass += 1

        # Gate is the FINAL blocker (removing it would let signal through)
        final_blocker = 0
        for r in rows:
            if r[i] != 0:
                continue
            # This gate blocked, check if any later gate also blocked
            later_blocked = False
            for j in range(i + 1, len(GATES)):
                if r[j] == 0:
                    later_blocked = True
                    break
            if not later_blocked:
                final_blocker += 1

        print(f"  {gate:30s}  blocks={currently_blocked:5d}  "
              f"unique_first={only_this:5d}  final_blocker={final_blocker:5d}  "
              f"would_release={would_pass:5d}")

    # ── Section 4: Subsumption analysis ──
    print()
    print("=" * 100)
    print("4. SUBSUMPTION ANALYSIS (A subset B?)")
    print("=" * 100)

    subsumption_pairs = [
        ('gate_context_block', 'gate_context_min_verdict'),
        ('gate_volatility', 'gate_no_trade_zones'),
        ('gate_btc_correlation', 'gate_no_trade_zones'),
    ]

    for a_gate, b_gate in subsumption_pairs:
        ai = gate_stats[a_gate]['idx']
        bi = gate_stats[b_gate]['idx']
        a = [r[ai] for r in rows]
        b = [r[bi] for r in rows]

        a_blocks = sum(1 for x in a if x == 0)
        b_blocks = sum(1 for x in b if x == 0)
        both = sum(1 for x, y in zip(a, b) if x == 0 and y == 0)
        a_only = sum(1 for x, y in zip(a, b) if x == 0 and y != 0)
        b_only = sum(1 for x, y in zip(a, b) if x != 0 and y == 0)

        print(f"\n  --- {a_gate} vs {b_gate} ---")
        print(f"  {a_gate:35s} blocks: {a_blocks:5d}")
        print(f"  {b_gate:35s} blocks: {b_blocks:5d}")
        print(f"  Both block:     {both:5d}")
        print(f"  Only {a_gate}: {a_only:5d}")
        print(f"  Only {b_gate}: {b_only:5d}")

        if a_blocks > 0 and both == a_blocks:
            print(f"  ** {a_gate} SUBSET {b_gate} -- ALL blocks of A are also blocks of B")
            print(f"     {a_gate} is REDUNDANT when {b_gate} is enabled")
        elif b_blocks > 0 and both == b_blocks:
            print(f"  ** {b_gate} SUBSET {a_gate} -- ALL blocks of B are also blocks of A")
            print(f"     {b_gate} is REDUNDANT when {a_gate} is enabled")
        else:
            if a_blocks > 0:
                print(f"  Coverage: {a_gate} covers {both/a_blocks*100:.1f}% of {b_gate}")
            if b_blocks > 0:
                print(f"  Coverage: {b_gate} covers {both/b_blocks*100:.1f}% of {a_gate}")
            if a_only > 0:
                print(f"  {a_gate} has {a_only} UNIQUE blocks not in {b_gate}")
            if b_only > 0:
                print(f"  {b_gate} has {b_only} UNIQUE blocks not in {a_gate}")

    # ── Section 5: Compression dead code analysis ──
    print()
    print("=" * 100)
    print("5. COMPRESSION DEAD CODE ANALYSIS")
    print("=" * 100)

    cb_idx = gate_stats['gate_compression_block']['idx']
    se_idx = gate_stats['gate_signal_engine']['idx']

    # How many traces reached compression_block?
    reached_cb = sum(1 for r in rows if r[cb_idx] is not None)
    cb_blocked = sum(1 for r in rows if r[cb_idx] == 0)
    cb_passed = sum(1 for r in rows if r[cb_idx] == 1)

    # Of those that passed compression_block, how many reached signal_engine?
    passed_cb_then_se = 0
    se_blocked_after_cb = 0
    se_passed_after_cb = 0
    for r in rows:
        if r[cb_idx] == 1:
            passed_cb_then_se += 1
            if r[se_idx] == 0:
                se_blocked_after_cb += 1
            elif r[se_idx] == 1:
                se_passed_after_cb += 1

    # How many are in compression regime?
    compression_regime = sum(1 for r in rows if r[GATES.index('gate_compression_block')] is not None)

    print(f"  Traces reaching compression_block: {reached_cb}")
    print(f"  compression_block blocked:          {cb_blocked}")
    print(f"  compression_block passed:           {cb_passed}")
    print(f"  Passed CB → reached signal_engine:  {passed_cb_then_se}")
    print(f"  Passed CB → signal_engine blocked:  {se_blocked_after_cb}")
    print(f"  Passed CB → signal_engine passed:   {se_passed_after_cb}")

    if cb_blocked > 0:
        # Check if compression_block is the FINAL blocker for any trace
        cb_final = 0
        for r in rows:
            if r[cb_idx] != 0:
                continue
            later_blocked = False
            for j in range(cb_idx + 1, len(GATES)):
                if r[j] == 0:
                    later_blocked = True
                    break
            if not later_blocked:
                cb_final += 1
        print(f"  compression_block as FINAL blocker: {cb_final}")
        print(f"  If compression_block removed:       {cb_final} more candidates reach signal_engine")

    # ── Section 6: Final summary table ──
    print()
    print("=" * 100)
    print("6. FINAL GATE SUMMARY")
    print("=" * 100)
    print(f"  {'Gate':35s}  {'Blocks':>6s}  {'Unique':>6s}  {'Final':>6s}  {'Block%':>6s}  {'Status'}")
    print(f"  {'-'*35}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*6}  {'-'*20}")

    for gate in GATES:
        i = gate_stats[gate]['idx']
        blocks = gate_stats[gate]['blocked']
        entered = gate_stats[gate]['entered']
        block_pct = gate_stats[gate]['block_rate']

        # Unique blocks (this gate blocks but no earlier gate does)
        unique = 0
        for r in rows:
            if r[i] != 0:
                continue
            earlier_blocked = False
            for j in range(i):
                if r[j] == 0:
                    earlier_blocked = True
                    break
            if not earlier_blocked:
                unique += 1

        # Final blocker
        final = 0
        for r in rows:
            if r[i] != 0:
                continue
            later_blocked = False
            for j in range(i + 1, len(GATES)):
                if r[j] == 0:
                    later_blocked = True
                    break
            if not later_blocked:
                final += 1

        status = "NEEDS_DATA" if with_outcome == 0 else "KEEP"
        if blocks == 0:
            status = "NO_BLOCKS"
        elif unique == 0 and blocks > 0:
            status = "CANDIDATE_REMOVE"
        elif final == 0 and blocks > 0:
            status = "ALWAYS_EARLIER"

        print(f"  {gate:35s}  {blocks:6d}  {unique:6d}  {final:6d}  {block_pct:5.1f}%  {status}")

    conn.close()

    print()
    print("=" * 100)
    print("CONCLUSIONS")
    print("=" * 100)
    print("  NOTE: No outcomes available yet (0 signals generated, 0 with outcome).")
    print("  Downstream WR/PF analysis requires real trade outcomes.")
    print("  Recommendations marked NEEDS_DATA until outcome data is populated.")
    print()
    print("  Overlap metrics (Jaccard, Phi, MI) are computed on gate block patterns.")
    print("  High Jaccard (>0.7) + high Phi (>0.5) = strong statistical duplicate.")


if __name__ == "__main__":
    main()
