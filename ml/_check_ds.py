import pandas as pd, os, sys
sys.path.insert(0, 'E:/Projects/tgbot')
path = 'E:/Projects/tgbot/data/training/dataset.parquet'
if os.path.exists(path):
    mtime = os.path.getmtime(path)
    from datetime import datetime
    dt = datetime.fromtimestamp(mtime)
    print("Dataset last modified:", dt)
    df = pd.read_parquet(path)
    print("Rows:", len(df))
    print("Labels:", df["label"].value_counts().to_dict())
    print("Symbols:", df["symbol"].value_counts().to_dict())
else:
    print("Dataset not found")
