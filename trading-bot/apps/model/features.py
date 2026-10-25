"""Panel of features per (day, coin), all known at 00:00 UTC of that day, plus forward-return labels.

Coin features are ranked across coins on each day (0..1), so the model learns "which coin" rather than
"what regime"; market features (BTC trend, stablecoin supply, Fear & Greed) stay raw and are the same for
every coin that day. The classic strategies already in the bot (Ichimoku, Fibonacci, Supertrend) enter
as "fired on the 4h chart in the last day" flags: what they say becomes one input among many.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from apps.model.data import load, load_macro
from apps.strategy.classic import CLASSIC, entries

BARS_PER_DAY = 6                                   # 4h bars
COIN_FEATURES = ["r_1d", "r_3d", "r_7d", "r_14d", "r_30d", "r_84d", "vol_7d", "vol_30d", "off_high_30d",
                 "volume_z", "taker_share_1d", "funding_1d", "funding_7d", "oi_chg_1d", "oi_chg_7d",
                 "top_ls", "acct_ls", "taker_ls_1d", *[f"sig_{n}" for n in CLASSIC]]
MARKET_FEATURES = ["btc_r_30d", "btc_r_84d", "btc_vol_30d", "stable_chg_7d", "stable_chg_30d", "fng"]


def coin_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Causal features on 4h bars stamped at their close."""
    d = BARS_PER_DAY
    c = df["close"]
    lr = np.log(c).diff()
    out = pd.DataFrame(index=df.index)
    for days in (1, 3, 7, 14, 30, 84):
        out[f"r_{days}d"] = c / c.shift(days * d) - 1
    out["vol_7d"] = lr.rolling(7 * d).std() * np.sqrt(d)
    out["vol_30d"] = lr.rolling(30 * d).std() * np.sqrt(d)
    out["off_high_30d"] = c / df["high"].rolling(30 * d).max() - 1
    qv = df["quote_volume"]
    out["volume_z"] = np.log(qv.rolling(d).sum() / (qv.rolling(30 * d).mean() * d))
    out["taker_share_1d"] = df["taker_buy_quote"].rolling(d).sum() / qv.rolling(d).sum()
    out["funding_1d"] = df["funding"].rolling(d, min_periods=1).mean()
    out["funding_7d"] = df["funding"].rolling(7 * d, min_periods=d).mean()
    oi = df["oi_usd"].ffill(limit=2)
    out["oi_chg_1d"] = oi / oi.shift(d) - 1
    out["oi_chg_7d"] = oi / oi.shift(7 * d) - 1
    out["top_ls"] = df["top_ls"]
    out["acct_ls"] = df["acct_ls"]
    out["taker_ls_1d"] = df["taker_ls"].rolling(d, min_periods=1).mean()
    for name in CLASSIC:
        fired = entries(name, df).astype(float)
        out[f"sig_{name}"] = fired.rolling(d, min_periods=1).max()
    return out


def market_frame(btc: pd.DataFrame, macro: pd.DataFrame, days: pd.DatetimeIndex) -> pd.DataFrame:
    d = BARS_PER_DAY
    c = btc["close"]
    m = pd.DataFrame(index=btc.index)
    m["btc_r_30d"] = c / c.shift(30 * d) - 1
    m["btc_r_84d"] = c / c.shift(84 * d) - 1
    m["btc_vol_30d"] = np.log(c).diff().rolling(30 * d).std() * np.sqrt(d)
    m = m.reindex(days)
    mac = macro.reindex(macro.index.union(days)).sort_index().ffill().reindex(days)   # last value known
    s = mac["stable_usd"]
    m["stable_chg_7d"] = s / s.shift(7) - 1
    m["stable_chg_30d"] = s / s.shift(30) - 1
    m["fng"] = mac["fng"]
    return m


def build_panel(coins: list[str], horizon_days: int) -> pd.DataFrame:
    """Rows (day, coin): ranked coin features, raw market features, fwd_ret, label (rank of fwd_ret)."""
    frames = []
    raw = {c: load(c) for c in coins}
    for coin, df in raw.items():
        f = coin_frame(df)
        f = f[f.index.hour == 0]                                   # one decision per day, 00:00 UTC
        close = df["close"]
        fwd = close.shift(-horizon_days * BARS_PER_DAY) / close - 1
        f["fwd_ret"] = fwd.reindex(f.index)
        f["ret_1d_next"] = (close.shift(-BARS_PER_DAY) / close - 1).reindex(f.index)
        f["coin"] = coin
        frames.append(f)
    panel = pd.concat(frames).rename_axis("day").reset_index()
    panel = panel[panel["r_30d"].notna()]                           # a coin enters after 30 days of history
    days = pd.DatetimeIndex(sorted(panel["day"].unique()))
    mk = market_frame(raw["BTC"], load_macro(), days)
    for col in COIN_FEATURES:
        panel[col] = panel.groupby("day")[col].rank(pct=True)
    panel = panel.merge(mk, left_on="day", right_index=True, how="left")
    panel["label"] = panel.groupby("day")["fwd_ret"].rank(pct=True)
    return panel.sort_values(["day", "coin"]).reset_index(drop=True)
