"""v1 strategy: 1h trend + 15m pullback. Deterministic. Replaceable once Trading_Context.md exists.

Long only (spot). Flat in chop. Jev is a gate on top of this, not a replacement for it.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from apps.features.snapshot import adx, atr, ema, resample_1h


@dataclass(frozen=True)
class StrategyParams:
    adx_min: float = 20.0
    pullback_lookback: int = 4        # bars (15m) in which price must have touched ema20_15m
    touch_tolerance: float = 0.001    # low within 0.1% of ema20 counts as a touch
    stop_atr_mult: float = 1.5
    target_rr: float = 2.0
    volume_mult: float = 1.0          # current 15m volume >= avg * this


def long_signal(df15: pd.DataFrame, p: StrategyParams = StrategyParams()) -> dict | None:
    """df15 ends at the last CLOSED candle. Returns a candidate dict or None."""
    if len(df15) < 60 * 4:
        return None
    h1 = resample_1h(df15)
    if len(h1) < 55:
        return None
    e20h, e50h = ema(h1["close"], 20), ema(h1["close"], 50)
    trend_up = e20h.iloc[-1] > e50h.iloc[-1] and h1["close"].iloc[-1] > e20h.iloc[-1]
    trending = adx(h1).iloc[-1] >= p.adx_min
    if not (trend_up and trending):
        return None

    close, low, vol = df15["close"], df15["low"], df15["volume"]
    e20 = ema(close, 20)
    recent_low = low.iloc[-p.pullback_lookback - 1:-1]
    recent_ema = e20.iloc[-p.pullback_lookback - 1:-1]
    touched = bool((recent_low <= recent_ema * (1 + p.touch_tolerance)).any())
    reclaimed = close.iloc[-1] > e20.iloc[-1] and close.iloc[-1] > close.iloc[-2]
    volume_ok = vol.iloc[-1] >= vol.iloc[-21:-1].mean() * p.volume_mult
    if not (touched and reclaimed and volume_ok):
        return None

    entry = float(close.iloc[-1])
    stop = entry - p.stop_atr_mult * float(atr(df15).iloc[-1])
    if stop <= 0 or stop >= entry:
        return None
    take = entry + p.target_rr * (entry - stop)
    return {"side": "long", "entry": entry, "stop": stop, "take": take, "rr": p.target_rr,
            "stop_pct": (entry - stop) / entry, "take_pct": (take - entry) / entry}
