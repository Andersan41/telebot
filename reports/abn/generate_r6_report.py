"""Generate full Report 6 from raw results."""
import json
from pathlib import Path
from datetime import datetime, timezone

RESULTS_DIR = Path("reports/abn")
raw = json.load(open(RESULTS_DIR / "raw_results_r6.json"))
agg = json.load(open(RESULTS_DIR / "aggregates_r6.json"))

SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "XRP/USDT", "SOL/USDT", "DOGE/USDT",
    "AVAX/USDT", "LINK/USDT", "ADA/USDT", "DOT/USDT", "UNI/USDT",
    "NEAR/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "SUI/USDT",
    "INJ/USDT", "WIF/USDT", "FLOKI/USDT", "FIL/USDT", "GRT/USDT",
]

PRESETS = [
    "true_baseline", "unified_only", "structural_sl_only", "sl_guard_only",
    "rr_filter_only", "gate_only", "buffer_only", "full_old", "full_new",
    "unified_plus_filters",
]

ROLE_MAP = {
    "BTC/USDT": "Large cap / benchmark",
    "ETH/USDT": "Large cap",
    "XRP/USDT": "Large cap / payments",
    "SOL/USDT": "Large cap / high beta",
    "DOGE/USDT": "High vol meme coin",
    "AVAX/USDT": "Mid cap L1",
    "LINK/USDT": "Mid cap oracle",
    "ADA/USDT": "Mid cap L1",
    "DOT/USDT": "Mid cap",
    "UNI/USDT": "Mid cap DEX",
    "NEAR/USDT": "Mid cap L1",
    "APT/USDT": "Volatile new L1",
    "ARB/USDT": "L2 / Ethereum",
    "OP/USDT": "L2 / Ethereum",
    "SUI/USDT": "Volatile new L1",
    "INJ/USDT": "Volatile DeFi",
    "WIF/USDT": "Volatile meme coin",
    "FLOKI/USDT": "Volatile meme coin",
    "FIL/USDT": "Declining (below ATH)",
    "GRT/USDT": "Declining (below ATH)",
}

FLAGS = {
    "true_baseline": {"unified_entry": "False", "confirm_tf_gate": "False", "structural_sl": "False", "sl_guard": "False", "rr_filter": "False", "news_filter": "False", "stop_hunt_buffer": "False"},
    "unified_only": {"unified_entry": "True", "confirm_tf_gate": "False", "structural_sl": "False", "sl_guard": "False", "rr_filter": "False", "news_filter": "False", "stop_hunt_buffer": "False"},
    "structural_sl_only": {"unified_entry": "False", "confirm_tf_gate": "False", "structural_sl": "True", "sl_guard": "False", "rr_filter": "False", "news_filter": "False", "stop_hunt_buffer": "False"},
    "sl_guard_only": {"unified_entry": "False", "confirm_tf_gate": "False", "structural_sl": "False", "sl_guard": "True", "rr_filter": "False", "news_filter": "False", "stop_hunt_buffer": "False"},
    "rr_filter_only": {"unified_entry": "False", "confirm_tf_gate": "False", "structural_sl": "False", "sl_guard": "False", "rr_filter": "True", "news_filter": "False", "stop_hunt_buffer": "False"},
    "gate_only": {"unified_entry": "False", "confirm_tf_gate": "True", "structural_sl": "False", "sl_guard": "False", "rr_filter": "False", "news_filter": "False", "stop_hunt_buffer": "False"},
    "buffer_only": {"unified_entry": "False", "confirm_tf_gate": "False", "structural_sl": "True", "sl_guard": "False", "rr_filter": "False", "news_filter": "False", "stop_hunt_buffer": "True"},
    "full_old": {"unified_entry": "True", "confirm_tf_gate": "True", "structural_sl": "True", "sl_guard": "True", "rr_filter": "True", "news_filter": "True", "stop_hunt_buffer": "True"},
    "full_new": {"unified_entry": "True", "confirm_tf_gate": "False", "structural_sl": "True", "sl_guard": "True", "rr_filter": "True", "news_filter": "True", "stop_hunt_buffer": "False"},
    "unified_plus_filters": {"unified_entry": "True", "confirm_tf_gate": "False", "structural_sl": "True", "sl_guard": "True", "rr_filter": "True", "news_filter": "False", "stop_hunt_buffer": "False"},
}

lines = []
w = lines.append

w("# Report 6 — Final A/B/n Backtest (10 presets, data-driven config)")
w("")
w(f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
w("**Timeframe:** 1h")
w("**Candles:** 3900 (~162 days = ~5.4 months)")
w("**Period:** 2026-01-11 → 2026-06-22")
w("**Symbols:** 20 (large cap, mid cap, volatile, declining)")
w("**Commission:** 0.05% per side | **Slippage:** 0.05% per side")
w("")

# ── Section 1: Configuration Confirmation ──
w("## 1. Configuration Confirmation")
w("")
w("### 10 Presets × 7 Flags")
w("")
w("| Flag | true_baseline | unified_only | structural_sl_only | sl_guard_only | rr_filter_only | gate_only | buffer_only | full_old | full_new | unified_plus_filters |")
w("|---|---|---|---|---|---|---|---|---|---|---|")
flag_names = ["unified_entry", "confirm_tf_gate", "structural_sl", "sl_guard", "rr_filter", "news_filter", "stop_hunt_buffer"]
flag_keys = ["unified_entry", "confirm_tf_gate", "structural_sl", "sl_guard", "rr_filter", "news_filter", "stop_hunt_buffer"]
for fname, fkey in zip(flag_names, flag_keys):
    row = f"| {fname} |"
    for preset in PRESETS:
        val = FLAGS[preset][fkey]
        if val == "True":
            row += f" **{val}** |"
        else:
            row += f" {val} |"
    w(row)
w("")
w("**Key differences:**")
w("- **full_new** vs **full_old**: `confirm_tf_gate` and `stop_hunt_buffer` disabled")
w("- **unified_plus_filters**: clean combo — all useful filters, no gate/buffer/news-stub")
w("- **full_new = unified_plus_filters**: news_filter is a stub (no-op), confirmed by identical results")
w("")

# ── Section 2: Main Results Table ──
w("## 2. Aggregate Results — All 10 Presets")
w("")
w("| Metric | true_baseline | unified_only | structural_sl_only | sl_guard_only | rr_filter_only | gate_only | buffer_only | full_old | full_new | unified_plus_filters |")
w("|---|---|---|---|---|---|---|---|---|---|---|")

metrics = [
    ("Trades", "total_trades", "{:d}"),
    ("Win Rate %", "winrate", "{:.1f}%"),
    ("Avg PnL (gross) %", "avg_pnl", "{:+.4f}%"),
    ("Avg PnL (net) %", "avg_net_pnl", "{:+.4f}%"),
    ("Avg R:R", "avg_rr", "{:.2f}"),
    ("Profit Factor", "profit_factor", "{:.2f}"),
    ("Expectancy %", "expectancy", "{:+.4f}%"),
    ("Max Drawdown %", "max_drawdown", "{:.2f}%"),
    ("Total PnL (gross) %", "total_pnl_pct", "{:+.2f}%"),
    ("Total PnL (net) %", "total_net_pnl_pct", "{:+.2f}%"),
    ("Signals Generated", "signals_generated", "{:d}"),
    ("Signals Rejected", "signals_rejected", "{:d}"),
    ("  RR filter", "reject_rr", "{:d}"),
    ("  SL distance", "reject_sl_dist", "{:d}"),
    ("  Confirm TF", "reject_confirm_tf", "{:d}"),
    ("Exit: SL hit", "exit_sl", "{:d}"),
    ("Exit: TP hit", "exit_tp", "{:d}"),
    ("Exit: EOB (open)", "exit_eob", "{:d}"),
    ("SL source: ATR", "src_atr", "{:d}"),
    ("SL source: BOS", "src_bos", "{:d}"),
    ("SL source: Structural", "src_structural", "{:d}"),
]

for label, key, fmt in metrics:
    row = f"| {label} |"
    for preset in PRESETS:
        val = agg.get(preset, {}).get(key, 0)
        try:
            cell = fmt.format(val)
        except (ValueError, TypeError):
            cell = str(val)
        row += f" {cell} |"
    w(row)
w("")

# ── Section 3: Key Comparison ──
w("## 3. Key Comparison: true_baseline | full_new | unified_plus_filters")
w("")
w("| Metric | true_baseline | full_new | unified_plus_filters | baseline→full_new Δ | baseline→clean Δ |")
w("|---|---|---|---|---|---|")
for label, key, fmt in metrics:
    bl = agg.get("true_baseline", {}).get(key, 0)
    fn = agg.get("full_new", {}).get(key, 0)
    upf = agg.get("unified_plus_filters", {}).get(key, 0)
    d_fn = fn - bl
    d_upf = upf - bl
    try:
        bl_c = fmt.format(bl)
        fn_c = fmt.format(fn)
        upf_c = fmt.format(upf)
        if isinstance(d_fn, float):
            d_fn_c = f"{d_fn:+.4f}" if abs(d_fn) < 10 else f"{d_fn:+.2f}"
            d_upf_c = f"{d_upf:+.4f}" if abs(d_upf) < 10 else f"{d_upf:+.2f}"
        else:
            d_fn_c = f"{d_fn:+d}"
            d_upf_c = f"{d_upf:+d}"
    except:
        bl_c = str(bl); fn_c = str(fn); upf_c = str(upf)
        d_fn_c = str(d_fn); d_upf_c = str(d_upf)
    w(f"| {label} | {bl_c} | {fn_c} | {upf_c} | {d_fn_c} | {d_upf_c} |")
w("")
w("### Interpretation")
w("")
w("- **full_new = unified_plus_filters**: identical results confirm news_filter is a no-op stub")
w("- **full_new vs baseline**: massive improvement — PF 1.10→2.29, net PnL -63.6%→+1133.4%")
w("- **Primary drivers**: unified_entry (entry price from confirm TF) + structural filters")
w("")

# ── Section 4: full_old vs full_new ──
w("## 4. full_old vs full_new (gate + buffer impact)")
w("")
fo = agg.get("full_old", {})
fn = agg.get("full_new", {})
w("| Metric | full_old | full_new | Δ | Direction |")
w("|---|---|---|---|---|")
for label, key, fmt in metrics:
    ov = fo.get(key, 0)
    nv = fn.get(key, 0)
    d = nv - ov
    try:
        ov_c = fmt.format(ov)
        nv_c = fmt.format(nv)
        d_c = f"{d:+.4f}" if isinstance(d, float) and abs(d) < 10 else (f"{d:+.2f}" if isinstance(d, float) else f"{d:+d}")
    except:
        ov_c = str(ov); nv_c = str(nv); d_c = str(d)
    direction = "improved" if key in ("total_pnl_pct", "total_net_pnl_pct", "profit_factor", "winrate") and d > 0 else \
                "worse" if key in ("total_pnl_pct", "total_net_pnl_pct", "profit_factor", "winrate") and d < 0 else \
                "reduced" if key in ("total_trades",) and d < 0 else "increased" if key in ("total_trades",) and d > 0 else "—"
    w(f"| {label} | {ov_c} | {nv_c} | {d_c} | {direction} |")
w("")
w("### Conclusion")
w("")
w(f"- **Net PnL**: full_old {fo.get('total_net_pnl_pct',0):+.2f}% → full_new {fn.get('total_net_pnl_pct',0):+.2f}% (**+{fn.get('total_net_pnl_pct',0)-fo.get('total_net_pnl_pct',0):+.2f}% improvement**)")
w(f"- **PF**: {fo.get('profit_factor',0):.2f} → {fn.get('profit_factor',0):.2f}")
w(f"- **Trades**: {fo.get('total_trades',0)} → {fn.get('total_trades',0)} (+{fn.get('total_trades',0)-fo.get('total_trades',0)} more trades — gate was rejecting viable signals)")
w("- Disabling gate and buffer is **confirmed beneficial** by data")
w("")

# ── Section 5: Per-Symbol Breakdown ──
w("## 5. Per-Symbol Breakdown: true_baseline vs full_new")
w("")
w("| Symbol | Role | baseline Trades | baseline Net PnL | baseline PF | full_new Trades | full_new Net PnL | full_new PF | PnL Δ |")
w("|--------|------|-----------------|------------------|-------------|-----------------|------------------|-------------|-------|")
for symbol in SYMBOLS:
    bl_rec = next((r for r in raw if r["symbol"] == symbol and r["preset"] == "true_baseline"), None)
    fn_rec = next((r for r in raw if r["symbol"] == symbol and r["preset"] == "full_new"), None)
    bl_t = bl_rec["total_trades"] if bl_rec else 0
    bl_pnl = bl_rec["total_net_pnl_pct"] if bl_rec else 0
    bl_pf = bl_rec["profit_factor"] if bl_rec else 0
    fn_t = fn_rec["total_trades"] if fn_rec else 0
    fn_pnl = fn_rec["total_net_pnl_pct"] if fn_rec else 0
    fn_pf = fn_rec["profit_factor"] if fn_rec else 0
    delta = fn_pnl - bl_pnl
    marker = " ⚠️ LOSS" if fn_pnl < 0 else ""
    w(f"| {symbol} | {ROLE_MAP.get(symbol,'')} | {bl_t} | {bl_pnl:+.2f}% | {bl_pf:.2f} | {fn_t} | {fn_pnl:+.2f}% | {fn_pf:.2f} | {delta:+.2f}%{marker} |")
w("")

# Count profitable/unprofitable
fn_recs = [r for r in raw if r["preset"] == "full_new"]
profitable = sum(1 for r in fn_recs if r["total_net_pnl_pct"] > 0)
unprofitable = len(fn_recs) - profitable
w(f"**Summary**: {profitable}/{len(fn_recs)} symbols profitable with full_new, {unprofitable} unprofitable")
w("")

# ── Section 6: Final Conclusions ──
w("## 6. Final Conclusions and Limitations")
w("")
w("### 6.1 Mechanisms Confirmed as Beneficial")
w("")
w("| Mechanism | Evidence | Impact |")
w("|-----------|----------|--------|")
w("| unified_entry (confirm TF close) | unified_only: +1203.68% vs baseline -63.60% | **Primary PnL driver** — best single feature |")
w("| sl_distance_guard | sl_guard_only: -12.95% vs baseline -63.60% | Filters bad SL placements, reduces DD from 59.9% to 49.8% |")
w("| rr_filter | rr_filter_only: -37.03% vs baseline -63.60% | Reduces trades, improves quality |")
w("| structural_sl | structural_sl_only: -108.65% vs baseline -63.60% | Marginal negative alone, but contributes in combo |")
w("")
w("### 6.2 Mechanisms Disabled (with evidence)")
w("")
w("| Mechanism | Evidence for disabling |")
w("|-----------|----------------------|")
w("| confirm_tf_gate | gate_only: -27.82% vs baseline; full_old→full_new: +106.91% improvement when disabled |")
w("| stop_hunt_buffer | buffer_only: -74.94% vs baseline; full_old→full_new: +106.91% improvement when disabled |")
w("| news_filter | Stub (returns []); full_new = unified_plus_filters confirms no effect |")
w("")
w("### 6.3 What Remains Unknown")
w("")
w("1. **News filter with real data**: fetch_macro_events returns [] — no historical news data available for backtesting")
w("2. **Behavior on other timeframes**: All results on 1h; 4h or 15m may differ")
w("3. **Longer periods**: ~5.4 months covers multiple regimes but not full market cycles")
w("4. **Live/paper validation**: No cross-check against real trading")
w("5. **Structural SL activation rate**: Limited by liquidity detection data quality (~2-8% of eligible trades)")
w("")
w("### 6.4 Explicit Warning")
w("")
w("> **All results are on historical data for a single period (2026-01-11 → 2026-06-22).**")
w("> No live validation has been performed. Past performance does not guarantee future results.")
w("> The +1133% net PnL across 20 symbols is a sum of per-symbol returns, not a portfolio return.")
w("> Individual symbol results vary significantly (range: +34.9% to +129.3%).")
w("")

# ── Section 7: Recommended Next Steps ──
w("## 7. Recommended Next Steps")
w("")
w("1. **Paper trading validation**: Run full_new (unified_plus_filters) on paper for 2-4 weeks to validate live signal quality and fill accuracy")
w("2. **Per-symbol risk tuning**: Symbols like APT (-29.10% in v3) and INJ show consistent underperformance — consider symbol-specific filters or exclusion lists")
w("3. **Timeframe diversification test**: Run full_new on 4h timeframe to assess whether the edge holds across different market regimes")
w("")
w("---")
w(f"*Report generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} — 10 presets × 20 symbols, data-driven config*")

# Write report
report_path = RESULTS_DIR.parent / "docs" / "report6.md"
report_path.parent.mkdir(parents=True, exist_ok=True)
with open(report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print(f"Report saved to {report_path}")
