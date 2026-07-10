import json

results = {}
with open("E:/Projects/tgbot/reports/abn/raw_results.jsonl", "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        key = f"{rec['symbol']}|{rec['preset']}"
        results[key] = rec

print(f"Total unique combos: {len(results)}")
symbols = sorted(set(r["symbol"] for r in results.values()))
presets = sorted(set(r["preset"] for r in results.values()))
print(f"Symbols: {len(symbols)} - {symbols}")
print(f"Presets: {len(presets)} - {presets}")

all_symbols = [
    "BTC/USDT", "ETH/USDT", "XRP/USDT", "SOL/USDT", "DOGE/USDT",
    "AVAX/USDT", "LINK/USDT", "ADA/USDT", "DOT/USDT", "UNI/USDT",
    "NEAR/USDT", "APT/USDT", "ARB/USDT", "OP/USDT", "SUI/USDT",
    "INJ/USDT", "WIF/USDT", "FLOKI/USDT", "FIL/USDT", "GRT/USDT",
]
all_presets = [
    "baseline", "task1_only", "confirm_tf_only", "task2_only",
    "task3_only", "task4_only", "task5_only", "task6_only", "full",
]

missing = []
for s in all_symbols:
    for p in all_presets:
        if f"{s}|{p}" not in results:
            missing.append(f"{s}|{p}")

print(f"Missing: {len(missing)} combos")
for m in missing:
    print(f"  {m}")
