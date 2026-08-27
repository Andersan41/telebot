import sys
sys.path.insert(0, '.')

import asyncio
import pandas as pd


def analyze(daily: pd.DataFrame, name: str, window=21):
    n = len(daily)
    close = daily['close']
    high, low, vol = daily['high'], daily['low'], daily['volume']

    hh = high.iloc[-window:].max()
    ll = low.iloc[-window:].min()
    cur = close.iloc[-1]
    range_pct = (hh - ll) / ll * 100
    pos_in_range = (cur - ll) / (hh - ll) * 100 if hh != ll else 50.0

    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(span=14, adjust=False).mean()
    atr_now_pct = atr.iloc[-window:].mean() / cur * 100
    atr_hist = atr.iloc[:n-window].mean() if n > window else atr.iloc[-window:].mean()
    atr_hist_pct = atr_hist / cur * 100
    compression = (1 - atr_now_pct / atr_hist_pct) * 100 if atr_hist_pct else 0

    ma = close.rolling(20).mean()
    sd = close.rolling(20).std()
    bw = ((ma + 2*sd) - (ma - 2*sd)) / ma * 100
    bw_now = bw.iloc[-1]
    bw_pctile = (bw < bw_now).iloc[-200:].mean() * 100

    vol_ma = vol.rolling(20).mean()
    vol_ratio = vol.iloc[-1] / vol_ma.iloc[-1] if vol_ma.iloc[-1] else 1

    mid = len(daily)
    mid_lo = high.iloc[-window:].min()
    mid_hi = low.iloc[-window:].max()

    return {
        'range_pct': range_pct,
        'pos_in_range': pos_in_range,
        'atr_pct': atr_now_pct,
        'atr_hist_pct': atr_hist_pct,
        'compression': compression,
        'bw_now': bw_now,
        'bw_pctile': bw_pctile,
        'vol_ratio': vol_ratio,
    }


def squeeze_probability(r: dict) -> float:
    # Tight BB squeezed toward lows of last 200 => coil
    bw_score = max(0, min(40, (50 - r['bw_pctile']) * 0.9))
    comp_score = max(0, min(30, r['compression'] * 1.2))
    pos_score = 10 if 35 < r['pos_in_range'] < 65 else 3
    vol_score = 15 if r['vol_ratio'] < 1.0 else 5
    struct_score = 8 if r['range_pct'] < 12 else 4
    prob = min(90.0, bw_score + comp_score + pos_score + vol_score + struct_score)
    return prob


async def main():
    from data.exchange_client import exchange_client
    from context.fetcher import context_fetcher
    await exchange_client.connect()

    for symbol in ['BTC/USDT', 'ETH/USDT']:
        print(f"\n########## {symbol} ##########")
        d = await exchange_client.fetch_ohlcv(symbol, '1d', limit=300)
        daily = d.dropna()
        r = analyze(daily, symbol)
        p = squeeze_probability(r)

        print(f"  Daily candles: {len(daily)}  last: {daily.index[-1].date()}  close={daily['close'].iloc[-1]:.2f}")
        print(f"  3-week range: {r['range_pct']:.2f}%  pos-in-range: {r['pos_in_range']:.1f}%")
        print(f"  ATR now {r['atr_pct']:.2f}% vs hist {r['atr_hist_pct']:.2f}%  compression {r['compression']:.0f}%")
        print(f"  BB bandwidth now {r['bw_now']:.2f}%  pctile {r['bw_pctile']:.0f}%  vol ratio {r['vol_ratio']:.2f}")
        print(f"  >>> SQUEEZE PROBABILITY (vol expansion pending): {p:.1f} / 90")

        try:
            fr = await context_fetcher.fetch_funding_rate(symbol)
            oi = await context_fetcher.fetch_open_interest(symbol)
            fr_s = f"{fr*100:.4f}%" if fr is not None else "NA"
            oi_s = f"{oi.get('open_interest_delta'):.2f}%" if oi and oi.get('open_interest_delta') is not None else "NA"
            print(f"  Funding: {fr_s}  |  OI delta: {oi_s}")
        except Exception as e:
            print(f"  derivatives NA ({e})")


asyncio.run(main())