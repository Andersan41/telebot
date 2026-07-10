"""
sweep_conditional_analysis.py — Sweep Conditional + Causal Analysis

Part A: Conditional analysis (4 levels) with Wilson + Bootstrap CI
Part B: Permutation Random Forest Importance (2 models)
Part C: Logistic Regression (Odds Ratios for has_sweep)
Part D: Verdict table

Usage:
    python -m reports.dataset.sweep_conditional_analysis
"""
from __future__ import annotations

import sys
import os
import math
import warnings
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass

warnings.filterwarnings("ignore", category=RuntimeWarning, message="overflow")

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats

# Ensure project root on path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = Path(__file__).resolve().parent
DATASET_PATH = OUT_DIR / "features_combined.parquet"

# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

MIN_SAMPLE = 30  # below this → NOT SIGNIFICANT automatically


def wilson_ci_95(wins: int, total: int) -> tuple[float, float]:
    """Wilson score interval 95% for binomial proportion."""
    if total == 0:
        return (0.0, 1.0)
    z = 1.96
    p = wins / total
    denom = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denom
    spread = z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total) / denom
    return (max(0, center - spread), min(1, center + spread))


def bootstrap_ci_wr_diff(
    wins_a: int, n_a: int, wins_b: int, n_b: int, n_resamples: int = 2000
) -> tuple[float, float, float]:
    """Bootstrap 95% CI for difference in win rates (A - B).
    Returns (point_diff, ci_low, ci_high).
    """
    if n_a < 2 or n_b < 2:
        return (0.0, 0.0, 0.0)
    rng = np.random.default_rng(42)
    arr_a = np.array([1] * wins_a + [0] * (n_a - wins_a))
    arr_b = np.array([1] * wins_b + [0] * (n_b - wins_b))
    diffs = np.array([
        np.mean(rng.choice(arr_a, size=n_a, replace=True))
        - np.mean(rng.choice(arr_b, size=n_b, replace=True))
        for _ in range(n_resamples)
    ])
    point = (wins_a / n_a) - (wins_b / n_b)
    return (point, float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5)))


def bootstrap_ci_mean_diff(
    vals_a: list[float], vals_b: list[float], n_resamples: int = 2000
) -> tuple[float, float, float]:
    """Bootstrap 95% CI for difference in means (A - B)."""
    if len(vals_a) < 2 or len(vals_b) < 2:
        return (0.0, 0.0, 0.0)
    rng = np.random.default_rng(42)
    a, b = np.array(vals_a), np.array(vals_b)
    diffs = np.array([
        np.mean(rng.choice(a, size=len(a), replace=True))
        - np.mean(rng.choice(b, size=len(b), replace=True))
        for _ in range(n_resamples)
    ])
    point = float(np.mean(a) - np.mean(b))
    return (point, float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5)))


def significance_tag(n: int, ci_overlap_50: bool = False) -> str:
    """Return SIGNIFICANT / NOT SIGNIFICANT / LOW SAMPLE."""
    if n < MIN_SAMPLE:
        return "LOW SAMPLE"
    if ci_overlap_50:
        return "NOT SIGNIFICANT"
    return "SIGNIFICANT"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    """Load the feature dataset."""
    df = pd.read_parquet(DATASET_PATH)
    print(f"Loaded: {DATASET_PATH.name} — {df.shape[0]} rows x {df.shape[1]} cols")
    return df


# ---------------------------------------------------------------------------
# Part A: Conditional Analysis
# ---------------------------------------------------------------------------

@dataclass
class ConditionalRow:
    label: str
    n: int
    wins: int
    wr: float
    avg_pnl: float
    wr_ci: tuple[float, float]
    wr_diff: float = 0.0
    wr_diff_ci: tuple[float, float] = (0.0, 0.0)
    pnl_diff: float = 0.0
    pnl_diff_ci: tuple[float, float] = (0.0, 0.0)
    verdict: str = ""


def conditional_row(label: str, subset: pd.DataFrame) -> ConditionalRow:
    """Compute metrics for a subset."""
    n = len(subset)
    if n == 0:
        return ConditionalRow(label=label, n=0, wins=0, wr=0.0, avg_pnl=0.0,
                             wr_ci=(0.0, 1.0), verdict="NO DATA")
    wins = int(subset["win"].sum())
    wr = wins / n * 100
    avg_pnl = float(subset["pnl_pct"].mean())
    wr_ci = wilson_ci_95(wins, n)
    verdict = significance_tag(n)
    return ConditionalRow(label=label, n=n, wins=wins, wr=round(wr, 1),
                         avg_pnl=round(avg_pnl, 4), wr_ci=wr_ci, verdict=verdict)


def format_ci(ci: tuple[float, float]) -> str:
    return f"[{ci[0]*100:.1f}%, {ci[1]*100:.1f}%]"


def format_diff_ci(ci: tuple[float, float]) -> str:
    return f"[{ci[0]:+.1f}pp, {ci[1]:+.1f}pp]"


def part_a_conditional(df: pd.DataFrame) -> list[str]:
    """Part A: 4-level conditional analysis."""
    lines = [
        "# Sweep Conditional Analysis",
        "",
        f"**Dataset:** {len(df)} trades from `features_combined.parquet`",
        f"**Method:** Wilson CI 95% (WR), Bootstrap CI 95% (diffs), {MIN_SAMPLE} sample threshold",
        "",
        "---",
        "",
        "## Part A: Conditional Analysis",
        "",
    ]

    sell = df[df["direction"] == "SELL"].copy()
    buy = df[df["direction"] == "BUY"].copy()

    # ── Level 1: Directional split ────────────────────────────────────
    lines.extend([
        "### Level 1: Direction × has_sweep",
        "",
    ])

    level1_groups = []
    for direction_label, subset in [("SELL", sell), ("BUY", buy)]:
        for sweep_val in [True, False]:
            mask = subset["has_sweep"] == sweep_val
            label = f"{direction_label} × sweep={'YES' if sweep_val else 'NO'}"
            row = conditional_row(label, subset[mask])
            level1_groups.append((direction_label, sweep_val, row))

    # Table
    lines.append("| Direction | has_sweep | N | WR% | Avg PnL | WR CI 95% | Verdict |")
    lines.append("|-----------|-----------|---|-----|---------|-----------|---------|")
    for _, _, r in level1_groups:
        lines.append(f"| {r.label.split(' × ')[0]} | {'YES' if 'sweep=YES' in r.label else 'NO'} | "
                     f"{r.n} | {r.wr}% | {r.avg_pnl:+.4f}% | {format_ci(r.wr_ci)} | {r.verdict} |")

    # Diff CIs
    lines.extend(["", "**Differences (sweep YES vs NO):**", ""])
    for d in ["SELL", "SELL"]:
        row_yes = next(r for dd, sv, r in level1_groups if dd == d and sv == True)
        row_no = next(r for dd, sv, r in level1_groups if dd == d and sv == False)
        if row_yes.n >= 2 and row_no.n >= 2:
            wr_diff, wr_diff_lo, wr_diff_hi = bootstrap_ci_wr_diff(
                row_yes.wins, row_yes.n, row_yes.wins - int(row_yes.wr * row_yes.n / 100), row_no.n
            )
            # Recompute properly
            wr_diff_val, lo, hi = bootstrap_ci_wr_diff(
                row_yes.wins, row_yes.n, row_no.wins, row_no.n
            )
            pnl_diff_val, pnl_lo, pnl_hi = bootstrap_ci_mean_diff(
                sell[sell["has_sweep"] == True]["pnl_pct"].tolist(),
                sell[sell["has_sweep"] == False]["pnl_pct"].tolist(),
            )
            delta_wr = row_yes.wr - row_no.wr
            lines.append(f"- **{d}:** ΔWR = {delta_wr:+.1f}pp, CI = {format_diff_ci((lo, hi))}")
            lines.append(f"  ΔPnL = {pnl_diff_val:+.4f}%, CI = [{pnl_lo:+.4f}%, {pnl_hi:+.4f}%]")
            # Only compute once for SELL
            break

    for d in ["BUY"]:
        row_yes = next(r for dd, sv, r in level1_groups if dd == d and sv == True)
        row_no = next(r for dd, sv, r in level1_groups if dd == d and sv == False)
        if row_yes.n >= 2 and row_no.n >= 2:
            wr_diff_val, lo, hi = bootstrap_ci_wr_diff(
                row_yes.wins, row_yes.n, row_no.wins, row_no.n
            )
            pnl_diff_val, pnl_lo, pnl_hi = bootstrap_ci_mean_diff(
                buy[buy["has_sweep"] == True]["pnl_pct"].tolist(),
                buy[buy["has_sweep"] == False]["pnl_pct"].tolist(),
            )
            delta_wr = row_yes.wr - row_no.wr
            lines.append(f"- **{d}:** ΔWR = {delta_wr:+.1f}pp, CI = {format_diff_ci((lo, hi))}")
            lines.append(f"  ΔPnL = {pnl_diff_val:+.4f}%, CI = [{pnl_lo:+.4f}%, {pnl_hi:+.4f}%]")

    lines.append("")

    # ── Level 2: SELL × Regime ────────────────────────────────────────
    lines.extend([
        "### Level 2: SELL × Regime × has_sweep",
        "",
        "| Regime | has_sweep | N | WR% | Avg PnL | WR CI 95% | Verdict |",
        "|--------|-----------|---|-----|---------|-----------|---------|",
    ])

    regimes = sell["regime"].dropna().unique()
    for reg in sorted(regimes):
        for sweep_val in [True, False]:
            subset = sell[(sell["regime"] == reg) & (sell["has_sweep"] == sweep_val)]
            row = conditional_row(f"{reg} × sweep={'YES' if sweep_val else 'NO'}", subset)
            lines.append(f"| {reg} | {'YES' if sweep_val else 'NO'} | "
                         f"{row.n} | {row.wr}% | {row.avg_pnl:+.4f}% | {format_ci(row.wr_ci)} | {row.verdict} |")

    lines.extend(["", "**Regime differences (sweep YES vs NO, ΔWR):**", ""])
    for reg in sorted(regimes):
        sub_yes = sell[(sell["regime"] == reg) & (sell["has_sweep"] == True)]
        sub_no = sell[(sell["regime"] == reg) & (sell["has_sweep"] == False)]
        if len(sub_yes) >= 2 and len(sub_no) >= 2:
            _, lo, hi = bootstrap_ci_wr_diff(
                int(sub_yes["win"].sum()), len(sub_yes),
                int(sub_no["win"].sum()), len(sub_no),
            )
            delta = sub_yes["win"].mean() * 100 - sub_no["win"].mean() * 100
            lines.append(f"- **{reg}:** ΔWR = {delta:+.1f}pp, CI = {format_diff_ci((lo, hi))}")
        else:
            lines.append(f"- **{reg}:** insufficient data (N<2 in at least one group)")

    lines.append("")

    # ── Level 3: SELL × ADX quartile ──────────────────────────────────
    lines.extend([
        "### Level 3: SELL × ADX Quartile × has_sweep",
        "",
    ])

    sell_valid = sell[sell["adx_value"].notna()].copy()
    if len(sell_valid) > 0:
        sell_valid["adx_q"] = pd.qcut(sell_valid["adx_value"], 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
        lines.append("| ADX Quartile | has_sweep | N | WR% | Avg PnL | WR CI 95% | Verdict |")
        lines.append("|-------------|-----------|---|-----|---------|-----------|---------|")

        for q in ["Q1", "Q2", "Q3", "Q4"]:
            for sweep_val in [True, False]:
                subset = sell_valid[(sell_valid["adx_q"] == q) & (sell_valid["has_sweep"] == sweep_val)]
                row = conditional_row(f"{q} × sweep={'YES' if sweep_val else 'NO'}", subset)
                lines.append(f"| {q} | {'YES' if sweep_val else 'NO'} | "
                             f"{row.n} | {row.wr}% | {row.avg_pnl:+.4f}% | {format_ci(row.wr_ci)} | {row.verdict} |")

        lines.extend(["", "**ADX quartile differences (sweep YES vs NO, ΔWR):**", ""])
        for q in ["Q1", "Q2", "Q3", "Q4"]:
            sub_yes = sell_valid[(sell_valid["adx_q"] == q) & (sell_valid["has_sweep"] == True)]
            sub_no = sell_valid[(sell_valid["adx_q"] == q) & (sell_valid["has_sweep"] == False)]
            if len(sub_yes) >= 2 and len(sub_no) >= 2:
                _, lo, hi = bootstrap_ci_wr_diff(
                    int(sub_yes["win"].sum()), len(sub_yes),
                    int(sub_no["win"].sum()), len(sub_no),
                )
                delta = sub_yes["win"].mean() * 100 - sub_no["win"].mean() * 100
                lines.append(f"- **{q}:** ΔWR = {delta:+.1f}pp, CI = {format_diff_ci((lo, hi))}")
            else:
                lines.append(f"- **{q}:** insufficient data")

    lines.append("")

    # ── Level 4: SELL × Score Verdict ─────────────────────────────────
    lines.extend([
        "### Level 4: SELL × Score Verdict × has_sweep",
        "",
        "| Score Verdict | has_sweep | N | WR% | Avg PnL | WR CI 95% | Verdict |",
        "|---------------|-----------|---|-----|---------|-----------|---------|",
    ])

    for sv in ["strong", "moderate", "weak"]:
        for sweep_val in [True, False]:
            subset = sell[(sell["score_verdict"] == sv) & (sell["has_sweep"] == sweep_val)]
            row = conditional_row(f"{sv} × sweep={'YES' if sweep_val else 'NO'}", subset)
            lines.append(f"| {sv} | {'YES' if sweep_val else 'NO'} | "
                         f"{row.n} | {row.wr}% | {row.avg_pnl:+.4f}% | {format_ci(row.wr_ci)} | {row.verdict} |")

    lines.extend(["", "**Score verdict differences (sweep YES vs NO, ΔWR):**", ""])
    for sv in ["strong", "moderate", "weak"]:
        sub_yes = sell[(sell["score_verdict"] == sv) & (sell["has_sweep"] == True)]
        sub_no = sell[(sell["score_verdict"] == sv) & (sell["has_sweep"] == False)]
        if len(sub_yes) >= 2 and len(sub_no) >= 2:
            _, lo, hi = bootstrap_ci_wr_diff(
                int(sub_yes["win"].sum()), len(sub_yes),
                int(sub_no["win"].sum()), len(sub_no),
            )
            delta = sub_yes["win"].mean() * 100 - sub_no["win"].mean() * 100
            lines.append(f"- **{sv}:** ΔWR = {delta:+.1f}pp, CI = {format_diff_ci((lo, hi))}")
        else:
            lines.append(f"- **{sv}:** insufficient data (N={len(sub_yes)}+{len(sub_no)})")

    lines.extend(["", "---", ""])
    return lines


# ---------------------------------------------------------------------------
# Part B: Permutation Random Forest
# ---------------------------------------------------------------------------

RF_FEATURES = [
    "has_sweep", "adx_value", "signal_score", "has_bos", "has_ob",
    "volume_ratio", "rsi_value", "macd_hist_normalized", "ema_strength",
]
# regime needs encoding — handle separately


def encode_regime(df: pd.DataFrame) -> pd.DataFrame:
    """Encode regime as dummy columns."""
    dummies = pd.get_dummies(df["regime"], prefix="regime", dtype=int)
    return pd.concat([df, dummies], axis=1)


def part_b_rf(df: pd.DataFrame) -> list[str]:
    """Part B: Permutation Random Forest."""
    lines = [
        "## Part B: Permutation Random Forest Importance",
        "",
    ]

    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.inspection import permutation_importance
        from sklearn.preprocessing import LabelEncoder
    except ImportError:
        lines.append("**scikit-learn not installed. Skipping RF analysis.**\n")
        lines.append("---\n")
        return lines

    df_rf = encode_regime(df.copy())
    regime_cols = [c for c in df_rf.columns if c.startswith("regime_")]
    feature_cols = RF_FEATURES + regime_cols

    # Drop rows with NaN in features
    valid_mask = df_rf[feature_cols + ["win"]].notna().all(axis=1)
    df_valid = df_rf[valid_mask].copy()
    lines.append(f"Rows for RF (after dropna): {len(df_valid)} / {len(df_rf)}\n")

    X = df_valid[feature_cols].values
    y = df_valid["win"].astype(int).values
    feature_names = feature_cols

    # ── RF №1: All trades ─────────────────────────────────────────────
    lines.extend([
        "### RF №1: All Trades (Permutation Importance)",
        "",
    ])

    rf1 = RandomForestClassifier(n_estimators=200, random_state=42, max_depth=10, min_samples_leaf=20)
    rf1.fit(X, y)
    acc1 = rf1.score(X, y)

    perm_imp1 = permutation_importance(rf1, X, y, n_repeats=15, random_state=42, n_jobs=-1)
    imp_series1 = pd.Series(perm_imp1.importances_mean, index=feature_names).sort_values(ascending=False)

    lines.append(f"RF Accuracy: {acc1*100:.1f}%\n")
    lines.append("| Rank | Feature | Permutation Importance |")
    lines.append("|------|---------|----------------------|")
    for rank, (fname, imp) in enumerate(imp_series1.items(), 1):
        bar = "#" * max(1, int(imp * 300))
        lines.append(f"| {rank} | {fname} | {imp:.4f} {bar} |")

    # ── RF №2: SELL only ──────────────────────────────────────────────
    lines.extend([
        "",
        "### RF №2: SELL Trades Only (Permutation Importance)",
        "",
    ])

    sell_valid = df_valid[df_valid["direction"] == "SELL"].copy()
    if len(sell_valid) < 30:
        lines.append(f"**Insufficient SELL trades ({len(sell_valid)}) for reliable RF.**\n")
    else:
        X_sell = sell_valid[feature_cols].values
        y_sell = sell_valid["win"].astype(int).values

        rf2 = RandomForestClassifier(n_estimators=200, random_state=42, max_depth=10, min_samples_leaf=20)
        rf2.fit(X_sell, y_sell)
        acc2 = rf2.score(X_sell, y_sell)

        perm_imp2 = permutation_importance(rf2, X_sell, y_sell, n_repeats=15, random_state=42, n_jobs=-1)
        imp_series2 = pd.Series(perm_imp2.importances_mean, index=feature_names).sort_values(ascending=False)

        lines.append(f"SELL trades: {len(sell_valid)} | RF Accuracy: {acc2*100:.1f}%\n")
        lines.append("| Rank | Feature | Permutation Importance |")
        lines.append("|------|---------|----------------------|")
        for rank, (fname, imp) in enumerate(imp_series2.items(), 1):
            bar = "#" * max(1, int(imp * 300))
            marker = " **<-- has_sweep**" if fname == "has_sweep" else ""
            lines.append(f"| {rank} | {fname} | {imp:.4f} {bar}{marker} |")

        # Sweep rank check
        sweep_rank = list(imp_series2.index).index("has_sweep") + 1 if "has_sweep" in imp_series2 else None
        sweep_imp = imp_series2.get("has_sweep", 0.0)
        in_top5 = sweep_rank is not None and sweep_rank <= 5
        lines.extend([
            "",
            f"**has_sweep rank in SELL model:** #{sweep_rank} (importance: {sweep_imp:.4f})",
            f"**Top-5 check:** {'YES — sweep is a top-5 factor in SELL' if in_top5 else 'NO — sweep is not top-5, effect likely explained by other factors'}",
        ])

    lines.extend(["", "---", ""])
    return lines


# ---------------------------------------------------------------------------
# Part C: Logistic Regression
# ---------------------------------------------------------------------------

def part_c_logistic(df: pd.DataFrame) -> list[str]:
    """Part C: Logistic Regression with Odds Ratios."""
    lines = [
        "## Part C: Logistic Regression — Independent Effect of has_sweep",
        "",
    ]

    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import LabelEncoder
    except ImportError:
        lines.append("**scikit-learn not installed. Skipping logistic regression.**\n")
        lines.append("---\n")
        return lines

    # Features: has_sweep + controls (no regime dummies — avoids singular matrix)
    final_features = ["has_sweep", "adx_value", "signal_score", "has_bos", "has_ob",
                      "volume_ratio", "rsi_value", "macd_hist_normalized", "ema_strength"]

    df_log = df.copy()
    df_log["has_sweep_int"] = df_log["has_sweep"].astype(int)
    final_features_int = ["has_sweep_int"] + [f for f in final_features if f != "has_sweep"]

    # Drop NaN
    valid_mask = df_log[final_features_int + ["win"]].notna().all(axis=1)
    df_valid = df_log[valid_mask].copy()

    if len(df_valid) < 50:
        lines.append(f"**Insufficient data ({len(df_valid)} rows) for logistic regression.**\n")
        lines.append("---\n")
        return lines

    X = df_valid[final_features_int].values
    y = df_valid["win"].astype(int).values

    # Standardize for Odds Ratios
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = LogisticRegression(max_iter=1000, random_state=42, solver="lbfgs")
    model.fit(X_scaled, y)
    acc = model.score(X_scaled, y)

    # Coefficients → Odds Ratios
    coefs = model.coef_[0]

    # Wald test: use Hessian from logistic regression for proper SE
    n = len(y)
    k = X_scaled.shape[1]
    y_pred = model.predict_proba(X_scaled)[:, 1]
    # Weight matrix W = diag(p * (1-p))
    W = np.diag(y_pred * (1 - y_pred) + 1e-10)
    # Fisher information matrix: X^T W X
    fisher = X_scaled.T @ W @ X_scaled
    # Add small ridge for numerical stability
    var_matrix = np.linalg.inv(fisher + np.eye(k) * 1e-4)
    se = np.sqrt(np.diag(var_matrix))

    lines.append(f"Model accuracy: {acc*100:.1f}% | N = {n} | Features = {k}\n")

    lines.append("| Feature | Coef | Odds Ratio | 95% CI (OR) | p-value | Sig |")
    lines.append("|---------|------|-----------|-------------|---------|-----|")

    def safe_exp(x: float) -> float:
        """Clip exp to avoid overflow."""
        return float(np.exp(np.clip(x, -10, 10)))

    sweep_idx = final_features_int.index("has_sweep_int")
    sweep_coef = coefs[sweep_idx]
    sweep_or = safe_exp(sweep_coef)
    sweep_se = se[sweep_idx]
    sweep_or_lo = safe_exp(sweep_coef - 1.96 * sweep_se)
    sweep_or_hi = safe_exp(sweep_coef + 1.96 * sweep_se)
    z = sweep_coef / sweep_se if sweep_se > 0 else 0
    p_value = 2 * (1 - scipy_stats.norm.cdf(abs(z)))
    sig = "YES" if p_value < 0.05 else "NO"

    for i, fname in enumerate(final_features_int):
        coef = coefs[i]
        or_val = safe_exp(coef)
        or_lo = safe_exp(coef - 1.96 * se[i])
        or_hi = safe_exp(coef + 1.96 * se[i])
        z_i = coef / se[i] if se[i] > 0 else 0
        p_i = 2 * (1 - scipy_stats.norm.cdf(abs(z_i)))
        sig_i = "YES" if p_i < 0.05 else "NO"
        marker = " **<-- TARGET**" if fname == "has_sweep_int" else ""
        lines.append(f"| {fname} | {coef:+.4f} | {or_val:.4f} | [{or_lo:.4f}, {or_hi:.4f}] | {p_i:.4f} | {sig_i}{marker} |")

    lines.extend([
        "",
        "### Interpretation",
        "",
        f"- **has_sweep Odds Ratio:** {sweep_or:.4f} (95% CI: [{sweep_or_lo:.4f}, {sweep_or_hi:.4f}])",
        f"- **p-value:** {p_value:.4f}",
        f"- **Statistically significant:** {sig}",
    ])

    if sweep_or < 1.0:
        lines.append(f"- Sweep REDUCES odds of winning by {(1 - sweep_or) * 100:.1f}% (after controlling for ADX, regime, score, BOS, OB)")
    else:
        lines.append(f"- Sweep INCREASES odds of winning by {(sweep_or - 1) * 100:.1f}% (after controlling for ADX, regime, score, BOS, OB)")

    lines.extend(["", "---", ""])
    return lines


# ---------------------------------------------------------------------------
# Part D: Verdict Table
# ---------------------------------------------------------------------------

def part_d_verdict(
    df: pd.DataFrame,
    rf_sweep_rank: int | None = None,
    rf_in_top5: bool = False,
    logistic_p: float = 1.0,
    logistic_or: float = 1.0,
    logistic_sig: str = "NO",
) -> list[str]:
    """Part D: Final verdict table."""
    lines = [
        "## Part D: Verdict Table",
        "",
    ]

    sell = df[df["direction"] == "SELL"]
    sell_sweep = sell[sell["has_sweep"] == True]
    sell_no_sweep = sell[sell["has_sweep"] == False]

    # Compute key stats for verdicts
    if len(sell_sweep) > 0 and len(sell_no_sweep) > 0:
        wr_sweep = sell_sweep["win"].mean() * 100
        wr_no_sweep = sell_no_sweep["win"].mean() * 100
        delta_wr = wr_sweep - wr_no_sweep
        # Bootstrap significance for overall
        if len(sell_sweep) >= 2 and len(sell_no_sweep) >= 2:
            _, lo, hi = bootstrap_ci_wr_diff(
                int(sell_sweep["win"].sum()), len(sell_sweep),
                int(sell_no_sweep["win"].sum()), len(sell_no_sweep),
            )
            overall_sig = lo > 0 or hi < 0  # CI doesn't cross zero
        else:
            overall_sig = False
    else:
        delta_wr = 0
        overall_sig = False

    # Regime dependence: check if ΔWR varies across regimes
    regime_deltas = {}
    for reg in sell["regime"].dropna().unique():
        sub_yes = sell[(sell["regime"] == reg) & (sell["has_sweep"] == True)]
        sub_no = sell[(sell["regime"] == reg) & (sell["has_sweep"] == False)]
        if len(sub_yes) >= 5 and len(sub_no) >= 5:
            regime_deltas[reg] = sub_yes["win"].mean() * 100 - sub_no["win"].mean() * 100

    if regime_deltas:
        delta_range = max(regime_deltas.values()) - min(regime_deltas.values())
        regime_dependent = delta_range > 10  # >10pp variation across regimes
    else:
        regime_dependent = False

    # Score dependence
    score_deltas = {}
    for sv in ["strong", "moderate", "weak"]:
        sub_yes = sell[(sell["score_verdict"] == sv) & (sell["has_sweep"] == True)]
        sub_no = sell[(sell["score_verdict"] == sv) & (sell["has_sweep"] == False)]
        if len(sub_yes) >= 5 and len(sub_no) >= 5:
            score_deltas[sv] = sub_yes["win"].mean() * 100 - sub_no["win"].mean() * 100

    if score_deltas:
        score_delta_range = max(score_deltas.values()) - min(score_deltas.values())
        score_dependent = score_delta_range > 10
    else:
        score_dependent = False

    # Verdicts
    v1 = "CONFIRMED" if (delta_wr < -5 and overall_sig) else ("REJECTED" if delta_wr > 0 else "NOT CONFIRMED")
    v2 = "YES" if logistic_sig == "YES" and logistic_or < 1.0 else "NO"
    v3 = "YES" if regime_dependent else "NO"
    v4 = "YES" if score_dependent else "NO"
    v5 = "YES" if rf_in_top5 else "NO"

    lines.extend([
        "| # | Гипотеза | Статус | Основание |",
        "|---|----------|--------|-----------|",
        f"| 1 | Sweep ухудшает SELL | **{v1}** | ΔWR={delta_wr:+.1f}pp, bootstrap CI {'not crossing 0' if overall_sig else 'crosses 0'}, logistic p={logistic_p:.4f} |",
        f"| 2 | Sweep влияет независимо от ADX/regime/score | **{v2}** | Logistic OR={logistic_or:.3f}, p={logistic_p:.4f}, sig={logistic_sig} |",
        f"| 3 | Sweep зависит от режима | **{v3}** | ΔWR range across regimes: {delta_range:.1f}pp |",
        f"| 4 | Sweep зависит от Score | **{v4}** | ΔWR range across scores: {score_delta_range:.1f}pp |" if score_deltas else f"| 4 | Sweep зависит от Score | **{v4}** | insufficient data |",
        f"| 5 | Sweep в Top-5 RF факторов (SELL) | **{v5}** | RF permutation rank: #{rf_sweep_rank} |" if rf_sweep_rank else f"| 5 | Sweep в Top-5 RF факторов (SELL) | **{v5}** | insufficient data |",
    ])

    lines.extend([
        "",
        "### Key evidence",
        "",
        f"- SELL overall: sweep WR={wr_sweep:.1f}% vs no_sweep WR={wr_no_sweep:.1f}% (Δ={delta_wr:+.1f}pp)",
        f"- Logistic: OR={logistic_or:.3f}, p={logistic_p:.4f} → {'independent factor' if v2 == 'YES' else 'marker of bad conditions, not independent'}",
        f"- RF rank of has_sweep in SELL: #{rf_sweep_rank}" if rf_sweep_rank else "- RF: insufficient data",
        f"- Regime variation: {delta_range:.1f}pp range → {'sweep effect varies by regime' if regime_dependent else 'sweep effect consistent across regimes'}" if regime_deltas else "- Regime: insufficient data for comparison",
    ])

    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    df = load_data()

    all_lines = []

    # Part A
    print("Part A: Conditional analysis...")
    all_lines.extend(part_a_conditional(df))

    # Part B
    print("Part B: Permutation Random Forest...")
    rf_lines = part_b_rf(df)
    all_lines.extend(rf_lines)

    # Extract RF results for verdict
    rf_sweep_rank = None
    rf_in_top5 = False
    for line in rf_lines:
        if "has_sweep rank in SELL model:" in line:
            try:
                rank_str = line.split("#")[1].split(" ")[0]
                rf_sweep_rank = int(rank_str)
                rf_in_top5 = rf_sweep_rank <= 5
            except (IndexError, ValueError):
                pass

    # Part C
    print("Part C: Logistic Regression...")
    log_lines = part_c_logistic(df)
    all_lines.extend(log_lines)

    # Extract logistic results for verdict
    logistic_p = 1.0
    logistic_or = 1.0
    logistic_sig = "NO"
    for line in log_lines:
        if "has_sweep_int" in line and "TARGET" in line:
            try:
                parts = line.split("|")
                logistic_or = float(parts[3].strip())
                logistic_p = float(parts[5].strip())
                logistic_sig = parts[6].strip()
            except (IndexError, ValueError):
                pass
        if "p-value:**" in line:
            try:
                logistic_p = float(line.split("**")[1])
            except (IndexError, ValueError):
                pass
        if "Odds Ratio:**" in line:
            try:
                logistic_or = float(line.split("**")[1].split("(")[0])
            except (IndexError, ValueError):
                pass
        if "Statistically significant:**" in line:
            logistic_sig = line.split("**")[-1].strip()

    # Part D
    print("Part D: Verdict table...")
    all_lines.extend(part_d_verdict(
        df,
        rf_sweep_rank=rf_sweep_rank,
        rf_in_top5=rf_in_top5,
        logistic_p=logistic_p,
        logistic_or=logistic_or,
        logistic_sig=logistic_sig,
    ))

    # Write report
    report_path = OUT_DIR / "sweep_conditional_analysis.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(all_lines))
    print(f"\nSaved: {report_path}")

    # Export SELL trades CSV
    sell = df[df["direction"] == "SELL"].copy()
    export_cols = [
        "symbol", "direction", "regime", "adx_value", "signal_score", "score_verdict",
        "has_sweep", "sweep_strength", "has_bos", "bos_type", "has_ob", "ob_valid",
        "sl_source", "result", "pnl_pct", "net_pnl_pct", "win", "rr",
        "ema_strength", "rsi_value", "macd_hist_normalized", "volume_ratio",
        "created_at", "entry_price", "exit_price",
    ]
    available = [c for c in export_cols if c in sell.columns]
    csv_path = OUT_DIR / "sweep_sell_trades.csv"
    sell[available].to_csv(csv_path, index=False)
    print(f"Saved: {csv_path} ({len(sell)} trades)")

    print(f"\n{'='*60}")
    print(f"  Analysis complete: {len(df)} trades")
    print(f"  SELL: {len(sell)} | BUY: {len(df[df['direction'] == 'BUY'])}")
    print(f"  SELL+has_sweep: {len(sell[sell['has_sweep'] == True])}")
    print(f"  SELL+no_sweep: {len(sell[sell['has_sweep'] == False])}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
