"""Quick check: does sell_no_sweep exist in JSONL?"""
import json

with open("reports/abn/raw_results_r6.jsonl", "r") as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")
for line in lines:
    r = json.loads(line.strip())
    if "sweep" in r.get("preset", ""):
        sym = r["symbol"]
        pre = r["preset"]
        trades = r["total_trades"]
        wr = r["winrate"]
        print(f"  {sym}|{pre}: trades={trades} wr={wr}%")
        
# Count unique presets
presets = set()
for line in lines:
    r = json.loads(line.strip())
    presets.add(r["preset"])
print(f"Presets in JSONL: {sorted(presets)}")
