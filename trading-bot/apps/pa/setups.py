"""The setups of *The Ultimate Price Action Trading Guide* (Atanas Matov, 2019), as exact rules.

Each function reads closed bars only and returns one row per signal: the bar that completed the pattern
(index), side (+1 long / -1 short), how to enter, the stop and the target. The book's wording is kept
where it is precise; where it says "art, not science" (zones, "major" levels) the rule below is the
closest mechanical reading, stated in the docstring so it can be argued with.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from apps.features.snapshot import atr, ema

COLS = ["side", "entry_kind", "entry", "stop", "target"]


def _trend(df: pd.DataFrame) -> pd.Series:
    """+1 uptrend, -1 downtrend, 0 neither: close and EMA50 on the same side of EMA200."""
    c, e50, e200 = df["close"], ema(df["close"], 50), ema(df["close"], 200)
    up = (c > e50) & (e50 > e200)
    down = (c < e50) & (e50 < e200)
    return up.astype(int) - down.astype(int)


def _frame(rows: list[tuple]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=COLS)
    return pd.DataFrame(rows, columns=["t", *COLS]).set_index("t")


def pin_bar(df: pd.DataFrame, rr: float = 2.0, prior: int = 20) -> pd.DataFrame:
    """Tail >= 2x body and >= 2/3 of the range, after a move against it (close below its level `prior`
    bars ago for a bullish pin). Enter on a break of the pin's far end (stop order, valid 3 bars), stop
    at the tail's end, target `rr` x the pin's length beyond the entry (book: "minimum two times")."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    body = np.abs(c - o)
    rng = h - l
    lower = np.minimum(o, c) - l
    upper = h - np.maximum(o, c)
    rows = []
    for i in range(prior, len(df)):
        if rng[i] <= 0:
            continue
        if lower[i] >= 2 * body[i] and lower[i] >= rng[i] * 2 / 3 and c[i] < c[i - prior]:
            rows.append((df.index[i], 1, "stop", h[i], l[i], h[i] + rr * rng[i]))
        elif upper[i] >= 2 * body[i] and upper[i] >= rng[i] * 2 / 3 and c[i] > c[i - prior]:
            rows.append((df.index[i], -1, "stop", l[i], h[i], l[i] - rr * rng[i]))
    return _frame(rows)


def pin_bar_at_level(df: pd.DataFrame, rr: float = 2.0, lookback: int = 50) -> pd.DataFrame:
    """The book's confluence: a pin bar whose tail tests the lowest low (highest high) of the previous
    `lookback` bars, i.e. support (resistance). Same entry, stop and target as pin_bar."""
    pins = pin_bar(df, rr)
    if pins.empty:
        return pins
    lo = df["low"].shift(1).rolling(lookback).min()
    hi = df["high"].shift(1).rolling(lookback).max()
    a = atr(df, 14)
    keep = []
    for t, r in pins.iterrows():
        if r["side"] == 1:
            keep.append(abs(df.at[t, "low"] - lo[t]) <= 0.5 * a[t])
        else:
            keep.append(abs(df.at[t, "high"] - hi[t]) <= 0.5 * a[t])
    return pins[np.array(keep, dtype=bool)]


def engulfing_in_trend(df: pd.DataFrame, rr: float = 2.0) -> pd.DataFrame:
    """In a trend, after a pullback (at least 2 of the last 3 bodies against the trend), a candle whose
    body engulfs the previous body in the trend's direction. Book: continuation only, 'not effective'
    as a reversal. Enter at the next open, stop beyond the last 3 bars' extreme, target rr x risk."""
    tr = _trend(df).to_numpy()
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    rows = []
    for i in range(203, len(df)):
        against = sum((c[j] < o[j]) if tr[i] == 1 else (c[j] > o[j]) for j in range(i - 3, i))
        if tr[i] == 0 or against < 2:
            continue
        lo_b, hi_b = min(o[i - 1], c[i - 1]), max(o[i - 1], c[i - 1])
        if tr[i] == 1 and c[i] > o[i] and o[i] <= lo_b and c[i] >= hi_b:
            rows.append((df.index[i], 1, "open", np.nan, l[i - 2:i + 1].min(), np.nan))
        elif tr[i] == -1 and c[i] < o[i] and o[i] >= hi_b and c[i] <= lo_b:
            rows.append((df.index[i], -1, "open", np.nan, h[i - 2:i + 1].max(), np.nan))
    return _attach_rr(_frame(rows), rr)


def inside_bar_in_trend(df: pd.DataFrame, rr: float = 2.0, room_atr: float = 3.0) -> pd.DataFrame:
    """In a trend, a bar inside the previous one, with no 50-bar high (low) within `room_atr` ATR ahead
    ('no major S/R near'). Enter at the next open, stop beyond the mother bar, target rr x risk."""
    tr = _trend(df).to_numpy()
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    hi50 = df["high"].rolling(50).max().to_numpy()
    lo50 = df["low"].rolling(50).min().to_numpy()
    a = atr(df, 14).to_numpy()
    rows = []
    for i in range(203, len(df)):
        if not (h[i] < h[i - 1] and l[i] > l[i - 1]) or tr[i] == 0:
            continue
        if tr[i] == 1 and hi50[i] - c[i] >= room_atr * a[i]:
            rows.append((df.index[i], 1, "open", np.nan, l[i - 1], np.nan))
        elif tr[i] == -1 and c[i] - lo50[i] >= room_atr * a[i]:
            rows.append((df.index[i], -1, "open", np.nan, h[i - 1], np.nan))
    return _attach_rr(_frame(rows), rr)


def supply_demand_zone(df: pd.DataFrame, rr: float = 3.0, max_wait: int = 100) -> pd.DataFrame:
    """A base of 1-3 small candles (range < 0.8 ATR each) followed by 3 large candles (body > 0.5 ATR,
    same colour) moving > 2 ATR away: the base is a demand (supply) zone. When price first returns to it
    within `max_wait` bars, enter with a limit at the zone's middle, stop 0.1 ATR beyond the zone,
    target rr x risk (book: entry mid-zone, stop just beyond, 1:3). Covers DBU/UBU (and UBD/DBD)."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = atr(df, 14).to_numpy()
    rows = []
    i = 20
    n = len(df)
    while i < n - 4:
        for base_len in (1, 2, 3):
            b0, b1 = i - base_len + 1, i
            if b0 < 1 or not all(h[j] - l[j] < 0.8 * a[j] for j in range(b0, b1 + 1)):
                continue
            imp = range(b1 + 1, b1 + 4)
            if imp[-1] >= n:
                break
            zlo, zhi = l[b0:b1 + 1].min(), h[b0:b1 + 1].max()
            up = all(c[j] > o[j] and c[j] - o[j] > 0.5 * a[j] for j in imp) and c[imp[-1]] - zhi > 2 * a[b1]
            dn = all(c[j] < o[j] and o[j] - c[j] > 0.5 * a[j] for j in imp) and zlo - c[imp[-1]] > 2 * a[b1]
            if up or dn:
                side = 1 if up else -1
                mid = (zlo + zhi) / 2
                stop = zlo - 0.1 * a[b1] if up else zhi + 0.1 * a[b1]
                # the zone is known once the impulse has closed; the signal is stamped there
                rows.append((df.index[imp[-1]], side, f"limit{max_wait}", mid, stop, mid + side * rr * abs(mid - stop)))
                break
        i += 1
    out = _frame(rows)
    return out[~out.index.duplicated()]


def supply_demand_5rules(df: pd.DataFrame, rr: float = 3.0, max_wait: int = 50, before: int = 20,
                         before_atr: float = 3.0) -> pd.DataFrame:
    """The '5 Supply and Demand Rules' variant: (1) strength comes from the move BEFORE the zone, so the
    base must follow a move of > `before_atr` ATR in the opposite direction (drop-base-rally / rally-base-
    drop only, rule 4: no rally-base-rally); (2) first touch only; (5) fresh zones only (`max_wait` bars).
    Rule 3 (trade with the trend of your own time frame) is not applied: right after a drop-base-rally the
    latest swing is still a lower low, so read literally it rejects almost every reversal zone the other
    rules ask for (2 on BTC 1h in 5 years). The book confirms the trend later, by eye."""
    zones = supply_demand_zone(df, rr, max_wait)
    if zones.empty:
        return zones
    c = df["close"]
    a = atr(df, 14)
    pos = {t: i for i, t in enumerate(df.index)}
    keep = []
    for t, z in zones.iterrows():
        i = pos[t] - 3 - 3                                       # roughly where the base starts
        if i - before < 0:
            keep.append(False)
            continue
        move = c.iloc[i] - c.iloc[i - before]
        reversal = move < -before_atr * a.iloc[i] if z["side"] == 1 else move > before_atr * a.iloc[i]
        keep.append(bool(reversal))
    return zones[np.array(keep, dtype=bool)]


def _attach_rr(sig: pd.DataFrame, rr: float) -> pd.DataFrame:
    """For next-open entries the target is set at fill time from the actual entry (target = NaN, rr kept)."""
    sig = sig.copy()
    sig["rr"] = rr
    return sig


SETUPS = {
    "pin_bar": pin_bar,
    "pin_bar_at_level": pin_bar_at_level,
    "engulfing_in_trend": engulfing_in_trend,
    "inside_bar_in_trend": inside_bar_in_trend,
    "supply_demand_zone": supply_demand_zone,
    "supply_demand_5rules": supply_demand_5rules,
}
