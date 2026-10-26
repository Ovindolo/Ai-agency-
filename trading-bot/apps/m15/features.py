"""Everything the bot 'sees' on a 15m chart, as numbers known at the close of each bar.

Indicators (returns, volatility, ATR, RSI, MACD, EMAs, Bollinger), volume and order flow (volume vs its
day average, cumulative delta of aggressive buyers minus sellers, price/delta divergence, VWAP, OBV,
volume on breakouts, up- vs down-candle volume), structure (distance
to the 1-day high/low, breakouts, higher highs/lows), candle patterns from the books (pin bar, engulfing,
inside bar), the classic strategies already in the bot (Ichimoku, Fibonacci 0.618, Supertrend), funding,
time of day, and BTC's own moves as the market backdrop. Rows are indexed by bar OPEN time; a row's values
use that bar and earlier ones only, so a decision taken on it is executed at the NEXT bar's open.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from apps.features.snapshot import atr, ema
from apps.strategy.classic import CLASSIC, entries


def _rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def candles(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = (c - o).abs()
    rng = (h - l).replace(0, np.nan)
    lower = np.minimum(o, c) - l
    upper = h - np.maximum(o, c)
    po, pc = o.shift(1), c.shift(1)
    out = pd.DataFrame(index=df.index)
    out["pin_bull"] = ((lower >= 2 * body) & (lower >= rng * 2 / 3)).astype(float)
    out["pin_bear"] = ((upper >= 2 * body) & (upper >= rng * 2 / 3)).astype(float)
    out["engulf_bull"] = ((c > o) & (pc < po) & (o <= pc) & (c >= po)).astype(float)
    out["engulf_bear"] = ((c < o) & (pc > po) & (o >= pc) & (c <= po)).astype(float)
    out["inside"] = ((h < h.shift(1)) & (l > l.shift(1))).astype(float)
    out["body_frac"] = (c - o) / rng
    return out


def coin_features(df: pd.DataFrame, funding: pd.Series) -> pd.DataFrame:
    c, h, l = df["close"], df["high"], df["low"]
    lr = np.log(c).diff()
    a = atr(df, 14)
    f = pd.DataFrame(index=df.index)
    for n in (1, 4, 16, 96):
        f[f"r{n}"] = np.log(c / c.shift(n))
    f["vol16"] = lr.rolling(16).std()
    f["vol96"] = lr.rolling(96).std()
    f["vol_ratio"] = f["vol16"] / f["vol96"]
    f["atr_pct"] = a / c
    f["rsi14"] = _rsi(c, 14)
    macd = ema(c, 12) - ema(c, 26)
    f["macd_hist"] = (macd - ema(macd, 9)) / c
    for n in (20, 50, 200):
        f[f"ema{n}_dist"] = c / ema(c, n) - 1
    ma, sd = c.rolling(20).mean(), c.rolling(20).std()
    f["bb_pctb"] = (c - (ma - 2 * sd)) / (4 * sd)
    hi96, lo96 = h.rolling(96).max(), l.rolling(96).min()
    f["from_high_atr"] = (c - hi96) / a
    f["from_low_atr"] = (c - lo96) / a
    f["breakout_up"] = (c > h.shift(1).rolling(96).max()).astype(float)
    f["breakout_dn"] = (c < l.shift(1).rolling(96).min()).astype(float)
    f["hh"] = np.sign(h.rolling(48).max() - h.shift(48).rolling(48).max())        # structure: higher highs
    f["hl"] = np.sign(l.rolling(48).min() - l.shift(48).rolling(48).min())        # and higher lows
    qv = df["quote_volume"]
    f["volume_z"] = np.log(qv / qv.rolling(96).mean())
    f["taker_share4"] = df["taker_buy_quote"].rolling(4).sum() / qv.rolling(4).sum()
    # order flow: aggressive buyers minus aggressive sellers (delta), as a share of volume traded
    delta = 2 * df["taker_buy_quote"] - qv
    for n in (4, 16, 96):
        f[f"cvd{n}"] = delta.rolling(n).sum() / qv.rolling(n).sum()
    f["price_delta_div16"] = np.sign(f["r16"]) - np.sign(f["cvd16"])               # price up, sellers lead
    vwap = qv.rolling(96).sum() / df["volume"].rolling(96).sum()
    f["vwap96_dist"] = c / vwap - 1
    obv = (np.sign(c.diff()).fillna(0) * qv).cumsum()
    f["obv_slope16"] = (obv - obv.shift(16)) / qv.rolling(16).sum()
    up_v = qv.where(c > df["open"], 0).rolling(16).sum()
    f["up_volume_share16"] = up_v / qv.rolling(16).sum()
    f["breakout_volume"] = (f["breakout_up"] - f["breakout_dn"]) * f["volume_z"]   # breakout on high or low volume
    f = f.join(candles(df))
    for name in CLASSIC:
        f[f"sig_{name}"] = entries(name, df).astype(float).rolling(4, min_periods=1).max()
    close_t = df.index + pd.Timedelta("15min")                                    # known at bar close
    if len(funding):
        fs = funding.sort_index()
        pos = fs.index.searchsorted(close_t, side="right") - 1
        vals = np.where(pos >= 0, fs.to_numpy()[np.clip(pos, 0, None)], np.nan)
        age = np.where(pos >= 0, (close_t - fs.index[np.clip(pos, 0, None)]) / pd.Timedelta("1h"), np.nan)
        f["funding"] = np.where(age <= 12, vals, np.nan)                          # never a stale rate
    else:
        f["funding"] = np.nan
    f["hour"] = df.index.hour
    f["weekday"] = df.index.weekday
    return f


def labels(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Enter at the next bar's open, leave at the open `horizon` bars later."""
    o = df["open"]
    entry, exit_ = o.shift(-1), o.shift(-1 - horizon)
    out = pd.DataFrame(index=df.index)
    out["fwd"] = np.log(exit_ / entry)
    return out


MARKET = ["btc_r4", "btc_r16", "btc_r96", "btc_vol96"]


def market(btc: pd.DataFrame) -> pd.DataFrame:
    lr = np.log(btc["close"]).diff()
    m = pd.DataFrame(index=btc.index)
    for n in (4, 16, 96):
        m[f"btc_r{n}"] = np.log(btc["close"] / btc["close"].shift(n))
    m["btc_vol96"] = lr.rolling(96).std()
    return m
