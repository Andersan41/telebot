"""Walk-forward validation on new leakage-fixed dataset."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from ml.config import DATASET_PATH
from sklearn.metrics import roc_auc_score, brier_score_loss, precision_score, recall_score, f1_score
from sklearn.model_selection import StratifiedShuffleSplit

df = pd.read_parquet(DATASET_PATH)
print(f"Dataset: {len(df)} rows")
print(f"Symbols: {df['symbol'].nunique()} ({df['symbol'].value_counts().head(5).to_dict()})")
print(f"Labels: {df['label'].value_counts().to_dict()}")
print(f"timestamp range: {df['timestamp'].min()} -> {df['timestamp'].max()}")

# Check for non-numeric columns
exclude = {"label", "entry_price", "sl_price", "tp_price", "symbol", "timestamp", "timeframe", "exit_bar"}
feature_cols = [c for c in df.columns if c not in exclude]
non_numeric = [c for c in feature_cols if not pd.api.types.is_numeric_dtype(df[c])]
if non_numeric:
    print(f"Non-numeric features (will be dropped): {non_numeric}")
    for c in non_numeric:
        feature_cols.remove(c)

print(f"Numeric features: {len(feature_cols)}")

# Sort by time for temporal split
df_sorted = df.sort_values("timestamp").reset_index(drop=True)

# ============================================================
# TEMPORAL SPLIT (last 20%)
# ============================================================
print("\n" + "=" * 70)
print("TEMPORAL SPLIT (last 20% by time)")
print("=" * 70)

split_idx = int(len(df_sorted) * 0.8)
df_train = df_sorted.iloc[:split_idx]
df_test = df_sorted.iloc[split_idx:]

print(f"Train: {len(df_train)} rows ({df_train['timestamp'].min()} -> {df_train['timestamp'].max()})")
print(f"Test:  {len(df_test)} rows ({df_test['timestamp'].min()} -> {df_test['timestamp'].max()})")

# Binary subset (TP vs SL only)
train_bin = df_train[df_train["label"].isin([0, 1])].copy()
test_bin = df_test[df_test["label"].isin([0, 1])].copy()
print(f"Train binary: {len(train_bin)} (TP={(train_bin['label']==1).sum()}, SL={(train_bin['label']==0).sum()})")
print(f"Test binary:  {len(test_bin)} (TP={(test_bin['label']==1).sum()}, SL={(test_bin['label']==0).sum()})")

X_tr = train_bin[feature_cols].fillna(0).values
y_tr = (train_bin["label"] == 1).astype(int).values
X_te = test_bin[feature_cols].fillna(0).values
y_te = (test_bin["label"] == 1).astype(int).values

from xgboost import XGBClassifier
model = XGBClassifier(
    n_estimators=300, max_depth=3, learning_rate=0.05,
    min_child_weight=10, reg_alpha=1.0, reg_lambda=5.0,
    subsample=0.7, colsample_bytree=0.7,
    eval_metric="logloss", random_state=42,
)
model.fit(X_tr, y_tr, verbose=False)

pred_tr = model.predict_proba(X_tr)[:, 1]
pred_te = model.predict_proba(X_te)[:, 1]

print(f"\nTrain AUC: {roc_auc_score(y_tr, pred_tr):.4f}")
print(f"Test  AUC: {roc_auc_score(y_te, pred_te):.4f}")
print(f"Train Brier: {brier_score_loss(y_tr, pred_tr):.4f}")
print(f"Test  Brier: {brier_score_loss(y_te, pred_te):.4f}")

# Per-symbol test AUC
print("\nPer-symbol test AUC:")
for sym in test_bin["symbol"].unique():
    sym_mask = test_bin["symbol"] == sym
    if sym_mask.sum() > 20:
        try:
            auc = roc_auc_score(y_te[sym_mask], pred_te[sym_mask])
            print(f"  {sym:12s}: AUC={auc:.4f} ({sym_mask.sum()} samples)")
        except:
            print(f"  {sym:12s}: N/A ({sym_mask.sum()} samples)")

# Threshold analysis
print(f"\n{'Threshold':>10s} {'Precision':>10s} {'Recall':>10s} {'F1':>8s} {'Trades':>8s} {'Winrate':>10s} {'ExpRet%':>10s}")
print("-" * 70)

test_bin_c = test_bin.copy()
tp_m = test_bin_c["label"] == 1
sl_m = test_bin_c["label"] == 0
test_bin_c["trade_return"] = 0.0
test_bin_c.loc[tp_m, "trade_return"] = (
    abs(test_bin_c.loc[tp_m, "tp_price"] - test_bin_c.loc[tp_m, "entry_price"])
    / test_bin_c.loc[tp_m, "entry_price"].clip(lower=0.001)
)
test_bin_c.loc[sl_m, "trade_return"] = -(
    abs(test_bin_c.loc[sl_m, "entry_price"] - test_bin_c.loc[sl_m, "sl_price"])
    / test_bin_c.loc[sl_m, "entry_price"].clip(lower=0.001)
)

for thresh in [0.0, 0.3, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8]:
    sig = pred_te >= thresh
    n = sig.sum()
    if n == 0:
        continue
    w = (y_te[sig] == 1).sum()
    l = (y_te[sig] == 0).sum()
    wr = w / n * 100
    prec = w / max(w + l, 1)
    rec = w / max(y_te.sum(), 1)
    f1 = 2 * prec * rec / max(prec + rec, 0.001)
    exp = test_bin_c["trade_return"].values[sig].mean() * 100
    print(f"  >= {thresh:.2f}  {prec:10.3f} {rec:10.3f} {f1:8.3f} {n:8d} {wr:9.1f}% {exp:+9.3f}%")

# ============================================================
# WALK-FORWARD (3 folds)
# ============================================================
print("\n" + "=" * 70)
print("WALK-FORWARD (3 folds)")
print("=" * 70)

n = len(df_sorted)
fold_size = n // 3

for i in range(3):
    test_start = i * fold_size
    test_end = min((i + 1) * fold_size, n)
    train_end = test_start

    if train_end < 100:
        print(f"  Fold {i+1}: skipped (no train data)")
        continue

    train_df = df_sorted.iloc[:train_end]
    test_df = df_sorted.iloc[test_start:test_end]

    tr_bin = train_df[train_df["label"].isin([0, 1])].copy()
    te_bin = test_df[test_df["label"].isin([0, 1])].copy()

    if len(tr_bin) < 50 or len(te_bin) < 50:
        print(f"  Fold {i+1}: skipped (train={len(tr_bin)}, test={len(te_bin)})")
        continue

    X_wf = tr_bin[feature_cols].fillna(0).values
    y_wf = (tr_bin["label"] == 1).astype(int).values
    X_wf_te = te_bin[feature_cols].fillna(0).values
    y_wf_te = (te_bin["label"] == 1).astype(int).values

    m = XGBClassifier(
        n_estimators=300, max_depth=3, learning_rate=0.05,
        min_child_weight=10, reg_alpha=1.0, reg_lambda=5.0,
        subsample=0.7, colsample_bytree=0.7,
        eval_metric="logloss", random_state=42,
    )
    m.fit(X_wf, y_wf, verbose=False)
    pred_wf = m.predict_proba(X_wf_te)[:, 1]

    auc = roc_auc_score(y_wf_te, pred_wf)
    brier = brier_score_loss(y_wf_te, pred_wf)

    time_range = f"{test_df['timestamp'].min()} -> {test_df['timestamp'].max()}"
    print(f"  Fold {i+1}: AUC={auc:.4f}, Brier={brier:.4f}, train={len(tr_bin)}, test={len(te_bin)}")
    print(f"    {time_range}")

    # Key thresholds
    te_bin_c = te_bin.copy()
    tp_wf = te_bin_c["label"] == 1
    sl_wf = te_bin_c["label"] == 0
    te_bin_c["trade_return"] = 0.0
    if tp_wf.any():
        te_bin_c.loc[tp_wf, "trade_return"] = (
            abs(te_bin_c.loc[tp_wf, "tp_price"] - te_bin_c.loc[tp_wf, "entry_price"])
            / te_bin_c.loc[tp_wf, "entry_price"].clip(lower=0.001)
        )
    if sl_wf.any():
        te_bin_c.loc[sl_wf, "trade_return"] = -(
            abs(te_bin_c.loc[sl_wf, "entry_price"] - te_bin_c.loc[sl_wf, "sl_price"])
            / te_bin_c.loc[sl_wf, "entry_price"].clip(lower=0.001)
        )

    for thresh in [0.5, 0.65, 0.8]:
        sig = pred_wf >= thresh
        n_s = sig.sum()
        if n_s == 0:
            continue
        w = (y_wf_te[sig] == 1).sum()
        wr = w / n_s * 100
        exp = te_bin_c["trade_return"].values[sig].mean() * 100
        print(f"    thresh>={thresh:.2f}: n={n_s}, winrate={wr:.1f}%, exp_ret={exp:+.3f}%")

# ============================================================
# Feature importance
# ============================================================
print("\n" + "=" * 70)
print("TOP 15 FEATURE IMPORTANCES")
print("=" * 70)
pairs = list(zip(feature_cols, model.feature_importances_))
pairs.sort(key=lambda x: x[1], reverse=True)
for name, imp in pairs[:15]:
    print(f"  {name:35s} {imp:.4f}")
