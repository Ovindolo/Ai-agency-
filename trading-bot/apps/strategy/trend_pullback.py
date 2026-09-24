"""v1 strategy: 1h trend + 15m pullback. Deterministic, vectorized. Replaceable once Trading_Context.md exists.

Long only (spot). Flat in chop. Jev is a gate on top of this, not a replacement for it.

Stop design: 1.5 x ATR(1h), placed INSIDE the risk band [stop_min, stop_max] here, and the target is
computed from the final stop so reward/risk stays at target_rr. (A 15m-ATR stop widened later by the
risk engine collapsed R:R below 1.8 and vetoed every signal - see docs/RISK.md.)

No lookahead: each 15m bar only sees the last COMPLETE hour. A 15m bar opening at T closes at T+15m;
the latest complete hour at that moment is floor(T+15m, 1h) - 1h.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from apps.features.snapshot import adx, atr, ema, resample_1h


@dataclass(frozen=True)
class StrategyParams:
    adx_min: float = 20.0
    pullback_lookback: int = 4        # previous 15m bars in which price must have touched ema20_15m
    touch_tolerance: float = 0.001    # low within 0.1% of ema20 counts as a touch
    stop_atr_mult: float = 1.5        # x ATR(14) on 1h
    stop_min_pct: float = 0.015       # must match config/risk.yaml (tested)
    stop_max_pct: float = 0.025
    target_rr: float = 2.0
    volume_mult: float = 1.0          # 15m volume >= avg(previous 20) * this
    min_hours: int = 55               # EMA50 on 1h needs history


def indicators(df15: pd.DataFrame, p: StrategyParams = StrategyParams()) -> pd.DataFrame:
    h1 = resample_1h(df15)
    e20h, e50h = ema(h1["close"], 20), ema(h1["close"], 50)
    hf = pd.DataFrame({
        "trend_up": (e20h > e50h) & (h1["close"] > e20h),
        "adx_1h": adx(h1),
        "atr_1h": atr(h1),
        "h1_n": np.arange(1, len(h1) + 1),
    }, index=h1.index)
    key = (df15.index + pd.Timedelta("15min")).floor("1h") - pd.Timedelta("1h")
    j = hf.reindex(key)
    j.index = df15.index

    close, low, vol = df15["close"], df15["low"], df15["volume"]
    e20 = ema(close, 20)
    touch = (low <= e20 * (1 + p.touch_tolerance)).astype(float)
    touched = touch.shift(1).rolling(p.pullback_lookback, min_periods=1).max() > 0
    reclaimed = (close > e20) & (close > close.shift(1))
    vol_ok = vol >= vol.shift(1).rolling(20).mean() * p.volume_mult

    raw_stop = p.stop_atr_mult * j["atr_1h"] / close
    stop_pct = raw_stop.clip(lower=p.stop_min_pct)
    ok = (j["trend_up"].fillna(False).astype(bool) & (j["adx_1h"] >= p.adx_min) & (j["h1_n"] >= p.min_hours)
          & touched & reclaimed & vol_ok & (raw_stop <= p.stop_max_pct))

    out = pd.DataFrame(index=df15.index)
    out["signal"] = ok.fillna(False)
    out["entry"] = close
    out["stop_pct"] = stop_pct
    out["stop"] = close * (1 - stop_pct)
    out["take"] = close * (1 + p.target_rr * stop_pct)
    return out


def row_to_signal(row: pd.Series, p: StrategyParams) -> dict:
    return {"side": "long", "entry": float(row["entry"]), "stop": float(row["stop"]), "take": float(row["take"]),
            "rr": p.target_rr, "stop_pct": float(row["stop_pct"]), "take_pct": float(p.target_rr * row["stop_pct"])}


def long_signal(df15: pd.DataFrame, p: StrategyParams = StrategyParams()) -> dict | None:
    """Signal for the LAST closed bar of df15, or None. Used by the live/paper runner."""
    if len(df15) < p.min_hours * 4:
        return None
    row = indicators(df15, p).iloc[-1]
    return row_to_signal(row, p) if bool(row["signal"]) else None
