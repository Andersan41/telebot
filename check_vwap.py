import pandas_ta as ta

# Check for VWAP
print("Checking for VWAP in pandas-ta...")
print(f"Has vwap attribute: {hasattr(ta, 'vwap')}")
print(f"Has VWAP attribute: {hasattr(ta, 'VWAP')}")

# List all attributes containing 'vwap' (case insensitive)
attrs = [attr for attr in dir(ta) if 'vwap' in attr.lower()]
print(f"Attributes with 'vwap': {attrs}")

# List volume-related attributes
volume_attrs = [attr for attr in dir(ta) if 'volume' in attr.lower()]
print(f"Volume-related attributes (first 10): {volume_attrs[:10]}")
print(f"Total volume-related attributes: {len(volume_attrs)}")

# Check for typical volume indicators
typical_vol = ['vwap', 'vwap_d', 'vwap_m', 'volume_sma', 'volume_ema']
for vol in typical_vol:
    print(f"Has {vol}: {hasattr(ta, vol)}")