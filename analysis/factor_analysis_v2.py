"""
factor_analysis_v2.py — Data-driven factor analysis pipeline.

Pipeline:
  1. Logistic Regression: coefficients, p-values, Odds Ratio, VIF
  2. Permutation Importance (honest, no multicollinearity bias)
  3. SHAP on XGBoost (per-trade explainability)
  4. Feature Clustering (eliminate triple-counted factors)
  5. Interaction Analysis: Regime x Direction x ADX x Score
  6. Empirical scoring model proposal

Usage:
  python analysis/factor_analysis_v2.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

from scipy.cluster.hierarchy import linkage, fcluster, dendrogram
from scipy.spatial.distance import squareform
from scipy.stats import chi2_contingency

from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.linear_model import LogisticRegression
from sklearn.inspection import permutation_importance as sk_permutation_importance
from sklearn.metrics import classification_report, roc_auc_score

import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor

import xgboost as xgb
import shap

REPORT_DIR = Path(__file__).resolve().parent.parent / "reports" / "analysis" / "v2"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 0. Load & prepare data
# ---------------------------------------------------------------------------

def load_data() -> pd.DataFrame:
    csv = Path(__file__).resolve().parent.parent / "reports" / "dataset" / "features_combined.csv"
    df = pd.read_csv(csv)
    print(f"Loaded: {len(df)} rows x {len(df.columns)} columns")
    return df


def prepare_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """Select numeric features suitable for modeling."""
    # Target
    y = df["win"].astype(int)

    # Features: numeric columns only, exclude identifiers/targets/metadata
    exclude = {
        "signal_id", "symbol", "timeframe", "direction", "created_at",
        "source", "result", "win", "pnl_pct", "net_pnl_pct", "hours_in_trade",
        "sl_source", "entry_price", "exit_price",
        # Raw price data — not features
        "close", "high", "low", "volume",
        "ema_fast", "ema_slow", "ema_trend", "ema_fast_prev", "ema_slow_prev",
        "rsi", "macd", "macd_signal", "macd_hist", "macd_hist_prev",
        "adx", "dmi_plus", "dmi_minus", "atr", "supertrend", "volume_sma",
        # Derived duplicates (keep normalized versions)
        "adx_value",  # same as adx
        "ema_strength",  # derived from ema_fast/slow/trend
        # TARGET LEAKAGE — rr is realized risk/reward, known only after exit
        "rr",
        # Post-trade labels derived from outcome
        "signal_score",  # count-based score, use raw factors instead
        "score_verdict",  # derived from signal_score
    }

    # Encode categoricals
    cat_cols = ["regime", "structure_trend", "ema_spread_trend", "score_verdict", "direction"]
    X = df.copy()
    for col in cat_cols:
        if col in X.columns:
            le = LabelEncoder()
            X[col] = le.fit_transform(X[col].astype(str))

    # Bool → int
    bool_cols = X.select_dtypes(include=["bool"]).columns
    for col in bool_cols:
        X[col] = X[col].astype(int)

    # Select feature columns
    feature_cols = []
    for c in X.columns:
        if c in exclude:
            continue
        if X[c].dtype in ["float64", "float32", "int64", "int32", "int"]:
            if X[c].nunique() > 1:  # drop constant columns
                feature_cols.append(c)

    X = X[feature_cols].copy()

    # Fill NaN with median
    for col in X.columns:
        if X[col].isna().sum() > 0:
            X[col] = X[col].fillna(X[col].median())

    print(f"Features: {len(feature_cols)} | Target balance: {y.mean()*100:.1f}% wins")
    return X, y, feature_cols


# ---------------------------------------------------------------------------
# 1. Logistic Regression — coefficients, p-values, Odds Ratio, VIF
# ---------------------------------------------------------------------------

def run_logistic_regression(X: pd.DataFrame, y: pd.Series) -> pd.DataFrame:
    print("\n" + "=" * 70)
    print("1. LOGISTIC REGRESSION")
    print("=" * 70)

    scaler = StandardScaler()
    X_scaled = pd.DataFrame(scaler.fit_transform(X), columns=X.columns, index=X.index)

    # Drop highly correlated features to avoid singular matrix
    corr_matrix = X_scaled.corr().abs()
    upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))
    to_drop = [col for col in upper.columns if any(upper[col] > 0.95)]
    if to_drop:
        print(f"Dropping {len(to_drop)} highly correlated features for LR stability: {to_drop}")
        X_lr = X_scaled.drop(columns=to_drop)
    else:
        X_lr = X_scaled

    # Statsmodels for p-values and Odds Ratio (with regularization for stability)
    X_const = sm.add_constant(X_lr)
    try:
        model = sm.Logit(y, X_const).fit(disp=0, method="bfgs", maxiter=200)
    except np.linalg.LinAlgError:
        print("BFGS failed, trying Newton with regularization...")
        model = sm.Logit(y, X_const).fit(disp=0, method="newton", maxiter=200)

    print(model.summary2())

    # Build results table (using X_lr which matches model coefficients)
    results = pd.DataFrame({
        "feature": X_lr.columns,
        "coefficient": model.params[1:].values,
        "std_err": model.bse[1:].values,
        "z_value": model.tvalues[1:].values,
        "p_value": model.pvalues[1:].values,
        "odds_ratio": np.exp(model.params[1:].values),
        "ci_lower_95": np.exp(model.conf_int().iloc[1:, 0].values),
        "ci_upper_95": np.exp(model.conf_int().iloc[1:, 1].values),
        "significant_005": model.pvalues[1:].values < 0.05,
        "significant_001": model.pvalues[1:].values < 0.01,
    })
    results = results.sort_values("p_value")

    # VIF (on full feature set)
    print("\n--- Variance Inflation Factors (VIF) ---")
    vif_data = []
    for i, col in enumerate(X.columns):
        vif = variance_inflation_factor(X_scaled.values, i)
        vif_data.append({"feature": col, "VIF": vif})
    vif_df = pd.DataFrame(vif_data).sort_values("VIF", ascending=False)
    print(vif_df.to_string(index=False))

    # Merge VIF into results (left join, some may be NaN if dropped)
    results = results.merge(vif_df, on="feature", how="left")

    # Classification report
    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=0.2, random_state=42, stratify=y
    )
    lr = LogisticRegression(max_iter=1000, random_state=42)
    lr.fit(X_train, y_train)
    y_pred = lr.predict(X_test)
    y_prob = lr.predict_proba(X_test)[:, 1]

    print(f"\n--- Out-of-sample (20%) ---")
    print(classification_report(y_test, y_pred, target_names=["SL", "TP"]))
    print(f"ROC AUC: {roc_auc_score(y_test, y_prob):.4f}")

    # Cross-validation
    cv_scores = cross_val_score(lr, X_scaled, y, cv=5, scoring="roc_auc")
    print(f"5-fold CV AUC: {cv_scores.mean():.4f} +/- {cv_scores.std():.4f}")

    # Save
    results.to_csv(REPORT_DIR / "01_logistic_regression.csv", index=False)
    vif_df.to_csv(REPORT_DIR / "01_vif.csv", index=False)

    # Summary
    sig = results[results["significant_005"]]
    print(f"\n--- Significant features (p<0.05): {len(sig)} ---")
    for _, row in sig.iterrows():
        direction = "+" if row["coefficient"] > 0 else "-"
        print(f"  {row['feature']:30s}  coef={row['coefficient']:+.4f}  "
              f"OR={row['odds_ratio']:.3f}  p={row['p_value']:.4f}  "
              f"VIF={row['VIF']:.1f}  [{direction}]")

    high_vif = results[results["VIF"] > 5]
    if len(high_vif) > 0:
        print(f"\n--- High VIF (>5) — multicollinearity candidates ---")
        for _, row in high_vif.iterrows():
            print(f"  {row['feature']:30s}  VIF={row['VIF']:.1f}")

    return results


# ---------------------------------------------------------------------------
# 2. Permutation Importance
# ---------------------------------------------------------------------------

def run_permutation_importance(X: pd.DataFrame, y: pd.Series) -> pd.DataFrame:
    print("\n" + "=" * 70)
    print("2. PERMUTATION IMPORTANCE")
    print("=" * 70)

    scaler = StandardScaler()
    X_scaled = pd.DataFrame(scaler.fit_transform(X), columns=X.columns, index=X.index)

    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=0.2, random_state=42, stratify=y
    )

    # Use XGBoost for permutation importance (better than LR for non-linear)
    model = xgb.XGBClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.1,
        random_state=42, eval_metric="logloss", use_label_encoder=False,
    )
    model.fit(X_train, y_train, verbose=False)

    result = sk_permutation_importance(
        model, X_test, y_test, n_repeats=30, random_state=42, scoring="roc_auc",
    )

    imp_df = pd.DataFrame({
        "feature": X.columns,
        "importance_mean": result.importances_mean,
        "importance_std": result.importances_std,
    }).sort_values("importance_mean", ascending=False)

    print("\nTop 20 features by permutation importance:")
    for _, row in imp_df.head(20).iterrows():
        bar = "#" * max(0, int(row["importance_mean"] * 200))
        print(f"  {row['feature']:30s}  {row['importance_mean']:+.4f} +/- {row['importance_std']:.4f}  {bar}")

    imp_df.to_csv(REPORT_DIR / "02_permutation_importance.csv", index=False)
    return imp_df


# ---------------------------------------------------------------------------
# 3. SHAP on XGBoost
# ---------------------------------------------------------------------------

def run_shap_analysis(X: pd.DataFrame, y: pd.Series) -> pd.DataFrame:
    print("\n" + "=" * 70)
    print("3. SHAP ANALYSIS (XGBoost)")
    print("=" * 70)

    scaler = StandardScaler()
    X_scaled = pd.DataFrame(scaler.fit_transform(X), columns=X.columns, index=X.index)

    X_train, X_test, y_train, y_test = train_test_split(
        X_scaled, y, test_size=0.2, random_state=42, stratify=y
    )

    model = xgb.XGBClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.1,
        random_state=42, eval_metric="logloss", use_label_encoder=False,
    )
    model.fit(X_train, y_train, verbose=False)

    # SHAP values
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test)

    # Mean |SHAP| per feature
    shap_importance = pd.DataFrame({
        "feature": X.columns,
        "mean_abs_shap": np.abs(shap_values).mean(axis=0),
        "mean_shap": shap_values.mean(axis=0),
        "std_shap": shap_values.std(axis=0),
    }).sort_values("mean_abs_shap", ascending=False)

    print("\nTop 20 features by mean |SHAP|:")
    for _, row in shap_importance.head(20).iterrows():
        bar = "#" * max(0, int(row["mean_abs_shap"] * 100))
        direction = "+" if row["mean_shap"] > 0 else "-"
        print(f"  {row['feature']:30s}  |SHAP|={row['mean_abs_shap']:.4f}  "
              f"mean={row['mean_shap']:+.4f}  [{direction}]  {bar}")

    shap_importance.to_csv(REPORT_DIR / "03_shap_importance.csv", index=False)

    # SHAP summary plot (bar) saved as CSV — plot requires display
    # For detailed per-trade analysis, save SHAP values
    shap_df = pd.DataFrame(shap_values, columns=X.columns, index=X_test.index)
    shap_df.to_csv(REPORT_DIR / "03_shap_values_test.csv", index=False)

    # SHAP interaction values (sample for speed)
    sample_size = min(200, len(X_test))
    X_sample = X_test.iloc[:sample_size]
    print(f"\nComputing SHAP interaction values for {sample_size} samples (this may take a moment)...")
    shap_interaction = explainer.shap_interaction_values(X_sample)

    # Mean |interaction| per feature pair
    n_features = len(X.columns)
    interaction_matrix = np.abs(shap_interaction).mean(axis=0)
    interaction_df = pd.DataFrame(interaction_matrix, index=X.columns, columns=X.columns)

    # Top interactions (off-diagonal)
    interactions = []
    for i in range(n_features):
        for j in range(i + 1, n_features):
            interactions.append({
                "feature_1": X.columns[i],
                "feature_2": X.columns[j],
                "interaction_strength": interaction_matrix[i, j],
            })
    interactions_df = pd.DataFrame(interactions).sort_values("interaction_strength", ascending=False)

    print("\nTop 15 feature interactions:")
    for _, row in interactions_df.head(15).iterrows():
        print(f"  {row['feature_1']:20s} x {row['feature_2']:20s}  "
              f"strength={row['interaction_strength']:.4f}")

    interactions_df.to_csv(REPORT_DIR / "03_shap_interactions.csv", index=False)

    return shap_importance


# ---------------------------------------------------------------------------
# 4. Feature Clustering (correlation-based)
# ---------------------------------------------------------------------------

def run_feature_clustering(X: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 70)
    print("4. FEATURE CLUSTERING (Correlation-based)")
    print("=" * 70)

    corr = X.corr(method="spearman")
    corr_abs = corr.abs()

    # Convert to distance matrix (work with numpy to avoid read-only issues)
    dist_arr = (1 - corr_abs.values).copy()
    np.fill_diagonal(dist_arr, 0)

    # Ensure symmetric
    dist_arr = (dist_arr + dist_arr.T) / 2

    # Hierarchical clustering
    condensed = squareform(dist_arr, checks=False)
    Z = linkage(condensed, method="ward")

    # Cut into clusters (target ~5-7 clusters)
    max_clusters = 7
    clusters = fcluster(Z, t=max_clusters, criterion="maxclust")

    cluster_df = pd.DataFrame({
        "feature": X.columns,
        "cluster": clusters,
    }).sort_values("cluster")

    # Print clusters
    print("\nFeature clusters:")
    for c in sorted(cluster_df["cluster"].unique()):
        members = cluster_df[cluster_df["cluster"] == c]["feature"].tolist()
        print(f"\n  Cluster {c} ({len(members)} features):")
        for m in members:
            print(f"    - {m}")

    # Identify redundant features within each cluster (correlation > 0.8)
    print("\n--- Redundancy within clusters (r > 0.8) ---")
    for c in sorted(cluster_df["cluster"].unique()):
        members = cluster_df[cluster_df["cluster"] == c]["feature"].tolist()
        if len(members) < 2:
            continue
        sub_corr = corr_abs.loc[members, members]
        redundant = []
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                if sub_corr.iloc[i, j] > 0.8:
                    redundant.append((members[i], members[j], sub_corr.iloc[i, j]))
        if redundant:
            print(f"\n  Cluster {c} — redundant pairs:")
            for f1, f2, r in redundant:
                    print(f"    {f1} <-> {f2}: r={r:.3f}")

    cluster_df.to_csv(REPORT_DIR / "04_feature_clusters.csv", index=False)

    # Save correlation matrix
    corr.to_csv(REPORT_DIR / "04_correlation_matrix.csv")

    return cluster_df


# ---------------------------------------------------------------------------
# 5. Interaction Analysis: Regime x Direction x ADX x Score
# ---------------------------------------------------------------------------

def run_interaction_analysis(df: pd.DataFrame) -> pd.DataFrame:
    print("\n" + "=" * 70)
    print("5. INTERACTION ANALYSIS: Regime x Direction x ADX x Score")
    print("=" * 70)

    # ADX buckets
    df = df.copy()
    df["adx_bucket"] = pd.cut(
        df["adx_value"],
        bins=[0, 20, 30, 40, 100],
        labels=["flat_<20", "weak_20-30", "moderate_30-40", "strong_40+"],
    )

    # Score buckets
    df["score_bucket"] = pd.cut(
        df["signal_score"],
        bins=[0, 2, 3, 4, 5, 10],
        labels=["score_1-2", "score_3", "score_4", "score_5", "score_6+"],
    )

    # 5-way interaction
    groups = df.groupby(["regime", "direction", "adx_bucket", "score_bucket"], observed=True).agg(
        N=("win", "count"),
        WR=("win", "mean"),
        avg_pnl=("net_pnl_pct", "mean"),
    ).reset_index()

    # Filter meaningful groups (N >= 5)
    groups_filtered = groups[groups["N"] >= 5].copy()
    groups_filtered = groups_filtered.sort_values("WR", ascending=False)

    print("\nTop combinations (N>=5, sorted by WR):")
    print(f"{'Regime':15s} {'Dir':5s} {'ADX':15s} {'Score':12s} {'N':>4s} {'WR':>7s} {'AvgPnL':>8s}")
    print("-" * 75)
    for _, row in groups_filtered.head(25).iterrows():
        print(f"{str(row['regime']):15s} {str(row['direction']):5s} "
              f"{str(row['adx_bucket']):15s} {str(row['score_bucket']):12s} "
              f"{row['N']:4d} {row['WR']:6.1%} {row['avg_pnl']:+7.2f}%")

    # Worst combinations
    print("\nWorst combinations (N>=5, sorted by WR):")
    for _, row in groups_filtered.tail(10).iterrows():
        print(f"{str(row['regime']):15s} {str(row['direction']):5s} "
              f"{str(row['adx_bucket']):15s} {str(row['score_bucket']):12s} "
              f"{row['N']:4d} {row['WR']:6.1%} {row['avg_pnl']:+7.2f}%")

    groups_filtered.to_csv(REPORT_DIR / "05_interaction_analysis.csv", index=False)

    # Chi-square test: is regime × direction independent of win?
    print("\n--- Chi-square tests ---")
    for factor in ["regime", "direction", "adx_bucket", "score_bucket"]:
        ct = pd.crosstab(df[factor], df["win"])
        chi2, p, dof, expected = chi2_contingency(ct)
        sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
        print(f"  {factor:20s}  chi2={chi2:8.2f}  p={p:.4f}  dof={dof}  {sig}")

    return groups_filtered


# ---------------------------------------------------------------------------
# 6. Empirical Scoring Model Proposal
# ---------------------------------------------------------------------------

def build_empirical_model(
    lr_results: pd.DataFrame,
    perm_results: pd.DataFrame,
    shap_results: pd.DataFrame,
    cluster_df: pd.DataFrame,
    feature_cols: list[str],
) -> str:
    print("\n" + "=" * 70)
    print("6. EMPIRICAL SCORING MODEL PROPOSAL")
    print("=" * 70)

    # Build a composite ranking
    lr_rank = lr_results.set_index("feature")["coefficient"].abs().rank(ascending=False)
    perm_rank = perm_results.set_index("feature")["importance_mean"].rank(ascending=False)
    shap_rank = shap_results.set_index("feature")["mean_abs_shap"].rank(ascending=False)

    combined = pd.DataFrame({
        "lr_coef": lr_results.set_index("feature")["coefficient"],
        "lr_pvalue": lr_results.set_index("feature")["p_value"],
        "lr_or": lr_results.set_index("feature")["odds_ratio"],
        "lr_rank": lr_rank,
        "perm_importance": perm_results.set_index("feature")["importance_mean"],
        "perm_rank": perm_rank,
        "shap_abs": shap_results.set_index("feature")["mean_abs_shap"],
        "shap_rank": shap_rank,
        "cluster": cluster_df.set_index("feature")["cluster"],
    })

    combined["avg_rank"] = (combined["lr_rank"] + combined["perm_rank"] + combined["shap_rank"]) / 3
    combined = combined.sort_values("avg_rank")

    print("\n--- Composite ranking (avg of 3 methods) ---")
    print(f"{'Feature':30s} {'LR_coef':>8s} {'p':>6s} {'OR':>6s} "
          f"{'Perm':>8s} {'SHAP':>8s} {'Cluster':>8s} {'AvgRank':>7s}")
    print("-" * 95)
    for feat, row in combined.iterrows():
        sig = "***" if row["lr_pvalue"] < 0.001 else "**" if row["lr_pvalue"] < 0.01 else "*" if row["lr_pvalue"] < 0.05 else ""
        print(f"{feat:30s} {row['lr_coef']:+8.4f} {row['lr_pvalue']:5.3f}{sig} "
              f"{row['lr_or']:6.3f} {row['perm_importance']:+8.4f} "
              f"{row['shap_abs']:8.4f} C{int(row['cluster']):7d} {row['avg_rank']:7.1f}")

    combined.to_csv(REPORT_DIR / "06_composite_ranking.csv")

    # --- Proposal: one representative per cluster ---
    print("\n--- Proposed feature selection (one per cluster, highest composite rank) ---")
    proposal = []
    for c in sorted(combined["cluster"].unique()):
        cluster_features = combined[combined["cluster"] == c]
        best = cluster_features["avg_rank"].idxmin()
        proposal.append({
            "cluster": c,
            "representative": best,
            "avg_rank": cluster_features.loc[best, "avg_rank"],
            "cluster_members": ", ".join(cluster_features.index.tolist()),
            "lr_coef": cluster_features.loc[best, "lr_coef"],
            "shap_abs": cluster_features.loc[best, "shap_abs"],
        })

    proposal_df = pd.DataFrame(proposal).sort_values("avg_rank")
    for _, row in proposal_df.iterrows():
        print(f"\n  Cluster {row['cluster']}: {row['representative']}")
        print(f"    LR coef: {row['lr_coef']:+.4f} | SHAP: {row['shap_abs']:.4f} | Rank: {row['avg_rank']:.1f}")
        print(f"    Members: {row['cluster_members']}")

    proposal_df.to_csv(REPORT_DIR / "06_proposed_features.csv", index=False)

    # Build text report
    report = []
    report.append("# Factor Analysis V2 — Empirical Scoring Model")
    report.append(f"\n## Key Findings")
    report.append(f"\n### Logistic Regression")
    report.append(f"- Significant features (p<0.05): {len(combined[combined['lr_pvalue'] < 0.05])}")
    report.append(f"- Significant features (p<0.01): {len(combined[combined['lr_pvalue'] < 0.01])}")

    high_vif = lr_results[lr_results["VIF"] > 5]
    report.append(f"- High VIF features (>5): {len(high_vif)} — multicollinearity detected")

    report.append(f"\n### Composite Ranking (Top 10)")
    for feat, row in combined.head(10).iterrows():
        report.append(f"1. **{feat}** — LR coef: {row['lr_coef']:+.4f}, "
                      f"SHAP: {row['shap_abs']:.4f}, Cluster: {int(row['cluster'])}")

    report.append(f"\n### Feature Clusters")
    for c in sorted(cluster_df["cluster"].unique()):
        members = cluster_df[cluster_df["cluster"] == c]["feature"].tolist()
        report.append(f"- Cluster {c}: {', '.join(members)}")

    report.append(f"\n### Proposed Scoring Model")
    report.append("Based on cluster representatives (one per cluster, highest composite rank):")
    for _, row in proposal_df.iterrows():
        coef = row["lr_coef"]
        weight = round(abs(coef) * 20)  # Scale to 0-20 range
        direction = "supports" if coef > 0 else "penalizes"
        report.append(f"- **{row['representative']}** (Cluster {row['cluster']}): "
                      f"weight={weight}, {direction} TP (OR={row['lr_coef']:.3f})")

    report_text = "\n".join(report)
    (REPORT_DIR / "06_empirical_model_proposal.md").write_text(report_text)
    print(f"\n{'=' * 70}")
    print("REPORTS SAVED TO:", REPORT_DIR)
    print(f"{'=' * 70}")

    return report_text


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    df = load_data()
    X, y, feature_cols = prepare_features(df)

    lr_results = run_logistic_regression(X, y)
    perm_results = run_permutation_importance(X, y)
    shap_results = run_shap_analysis(X, y)
    cluster_df = run_feature_clustering(X)
    interaction_results = run_interaction_analysis(df)

    report = build_empirical_model(lr_results, perm_results, shap_results, cluster_df, feature_cols)
    print("\nDONE.")


if __name__ == "__main__":
    main()
