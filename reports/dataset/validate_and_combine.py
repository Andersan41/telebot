"""
validate_and_combine.py — Step 4: Validate and save combined dataset.
signals.db is empty, so combined = backtest only.
"""
import pandas as pd
import numpy as np
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

# Load backtest features
df = pd.read_parquet(OUT_DIR / "backtest_features.parquet")

print("=== VALIDATION ===")

# 1. No duplicates
dupes = df["signal_id"].duplicated().sum()
print(f"Duplicate signal_ids: {dupes}")
assert dupes == 0, "Found duplicate signal_ids!"

# 2. result filled for all rows
open_trades = df["result"].isin(["OPEN", ""]).sum()
print(f"Open trades (no result): {open_trades}")

# 3. win = True iff result == TP
mismatch = ((df["result"] == "TP") != df["win"]).sum()
print(f"win/result mismatch: {mismatch}")

# 4. Distribution
print(f"\n=== DISTRIBUTION ===")
print(f"\nBy source:")
print(df["source"].value_counts().to_string())
print(f"\nBy direction:")
print(df["direction"].value_counts().to_string())
print(f"\nBy regime:")
print(df["regime"].value_counts().dropna().to_string())
print(f"\nBy result:")
print(df["result"].value_counts().to_string())
print(f"\nBy score_verdict:")
print(df["score_verdict"].value_counts().to_string())
print(f"\nBy sl_source:")
print(df["sl_source"].value_counts().to_string())

# 5. NaN summary
print(f"\n=== NaN SUMMARY ===")
total_cells = df.shape[0] * df.shape[1]
total_nan = df.isnull().sum().sum()
print(f"Total cells: {total_cells}")
print(f"Total NaN: {total_nan} ({total_nan/total_cells*100:.2f}%)")
nan = df.isnull().sum()
nan = nan[nan > 0].sort_values(ascending=False)
if len(nan) > 0:
    print(f"\nColumns with NaN:")
    for c, n in nan.items():
        print(f"  {c}: {n} ({n/len(df)*100:.1f}%)")
else:
    print("No NaN columns!")

# 6. Feature columns
print(f"\n=== COLUMNS ({df.shape[1]}) ===")
for i, col in enumerate(df.columns):
    dtype = df[col].dtype
    non_null = df[col].notna().sum()
    print(f"  {i+1:2d}. {col:30s} {str(dtype):10s} {non_null}/{len(df)}")

# Save combined (same as backtest since no live data)
combined_parquet = OUT_DIR / "features_combined.parquet"
combined_csv = OUT_DIR / "features_combined.csv"
df.to_parquet(combined_parquet, index=False)
df.to_csv(combined_csv, index=False)
print(f"\nSaved: {combined_parquet} ({combined_parquet.stat().st_size // 1024}KB)")
print(f"Saved: {combined_csv} ({combined_csv.stat().st_size // 1024}KB)")
