"""Classic TradingView-style entries, written so they cannot see the future.

Each function returns a frame of numeric columns plus `enter` (1.0 on the closed 15m bar that fires).
Exits are NOT here: every candidate leaves through the same stops/targets/risk engine (exit_frame),
so the tournament compares entries only.

Known traps handled here:
  - Ichimoku's Chikou span is the close plotted 26 bars in the PAST. A backtest that stores it as
    close.shift(-26) reads the future. The honest equivalent is: close now > close 26 bars ago.
  - The cloud (Senkou A/B) is plotted 26 bars AHEAD, so the cloud "under" today's bar was computed
    26 bars ago: shift(+26), which only uses the past.
  - Fibonacci levels need a swing high/low. Pivots that "confirm" later repaint; here the swing is the
    highest high / lowest low of the last N closed bars, known at the time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from apps.features.snapshot import atr, ema


def _mid(df: pd.DataFrame, n: int) -> pd.Series:
    return (df["high"].rolling(n).max() + df["low"].rolling(n).min()) / 2


def ichimoku(df: pd.DataFrame, tenkan: int = 9, kijun: int = 26, senkou_b: int = 52) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["tenkan"] = _mid(df, tenkan)
    out["kijun"] = _mid(df, kijun)
    span_a_now = (out["tenkan"] + out["kijun"]) / 2
    span_b_now = _mid(df, senkou_b)
    out["span_a"] = span_a_now.shift(kijun)             # cloud under today's bar: computed kijun bars ago
    out["span_b"] = span_b_now.shift(kijun)
    out["cloud_top"] = out[["span_a", "span_b"]].max(axis=1, skipna=False)
    close = df["close"]
    chikou_ok = close > close.shift(kijun)               # honest Chikou: no close.shift(-kijun)
    breakout = (close > out["cloud_top"]) & (close.shift(1) <= out["cloud_top"].shift(1))
    out["enter"] = (breakout & (out["tenkan"] > out["kijun"]) & chikou_ok & (span_a_now > span_b_now)).astype(float)
    return out


def _bars_since_extreme(values: np.ndarray, n: int, fn) -> np.ndarray:
    out = np.full(len(values), np.nan)
    if len(values) >= n:
        w = sliding_window_view(values, n)
        out[n - 1:] = n - 1 - fn(w, axis=1)
    return out


def fib_pullback(df: pd.DataFrame, lookback: int = 96, trend: int = 200, min_leg: float = 0.03) -> pd.DataFrame:
    """Up-leg over the last `lookback` bars (low first, then high), price retraces into the 0.5-0.618
    zone and closes back above 0.5, while above EMA(trend)."""
    out = pd.DataFrame(index=df.index)
    hh = df["high"].rolling(lookback).max()
    ll = df["low"].rolling(lookback).min()
    out["since_high"] = _bars_since_extreme(df["high"].to_numpy(), lookback, np.argmax)
    out["since_low"] = _bars_since_extreme(df["low"].to_numpy(), lookback, np.argmin)
    out["fib_50"] = hh - 0.5 * (hh - ll)
    out["fib_618"] = hh - 0.618 * (hh - ll)
    out["ema_trend"] = ema(df["close"], trend)
    up_leg = (out["since_high"] < out["since_low"]) & ((hh - ll) / ll >= min_leg) & (out["since_high"] >= 2)
    touched = (df["low"] <= out["fib_50"]) & (df["low"] >= out["fib_618"])
    out["enter"] = (up_leg & touched & (df["close"] > out["fib_50"]) & (df["close"] > out["ema_trend"])).astype(float)
    return out


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> pd.DataFrame:
    """Standard Supertrend; entry on the bar it flips from down to up."""
    a = atr(df, n).to_numpy()
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy()
    close = df["close"].to_numpy()
    upper, lower = hl2 + mult * a, hl2 - mult * a
    fu, fl = upper.copy(), lower.copy()
    up = np.ones(len(df), dtype=bool)
    for i in range(1, len(df)):
        fu[i] = upper[i] if (upper[i] < fu[i - 1] or close[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lower[i] if (lower[i] > fl[i - 1] or close[i - 1] < fl[i - 1]) else fl[i - 1]
        up[i] = close[i] > fu[i - 1] if not up[i - 1] else close[i] >= fl[i - 1]
    out = pd.DataFrame({"st_upper": fu, "st_lower": fl, "st_up": up.astype(float)}, index=df.index)
    flip = up & ~np.concatenate([[True], up[:-1]])
    flip[:n] = False                                   # ATR not warmed up yet
    out["enter"] = flip.astype(float)
    return out


CLASSIC = {"ichimoku_breakout": ichimoku, "fib_618_pullback": fib_pullback, "supertrend_flip": supertrend}


def entries(name: str, df15: pd.DataFrame) -> pd.Series:
    return CLASSIC[name](df15)["enter"].fillna(0).astype(bool)
