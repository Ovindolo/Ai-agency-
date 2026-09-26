"""Market context that the MCP list points at, as data the tournament can TEST instead of trust.

  funding (Binance perpetuals, public)  -> crowding: very positive funding = longs paying a lot to stay in
  Fear & Greed (alternative.me, public) -> sentiment extremes

Each becomes an entry filter (a boolean mask on 15m bars) that only REMOVES trades, built causally:
a funding print is known after its settlement time; the Fear & Greed value for day D is used from the
end of day D. Whether any of them helps is decided out-of-sample, like every other candidate.
"""
from __future__ import annotations

import json
import urllib.request

import pandas as pd


def fetch_fear_greed() -> pd.Series:
    """Daily index 0-100 since 2018 (https://api.alternative.me/fng/, free, no key)."""
    with urllib.request.urlopen("https://api.alternative.me/fng/?limit=0&format=json", timeout=20) as r:
        data = json.loads(r.read())["data"]
    s = pd.Series({pd.Timestamp(int(x["timestamp"]), unit="s", tz="UTC"): int(x["value"]) for x in data})
    return s.sort_index()


def _asof(index15: pd.DatetimeIndex, series: pd.Series, available_after: pd.Timedelta) -> pd.Series:
    """Value known at the CLOSE of each 15m bar: the latest point whose time + delay <= bar close."""
    s = series.sort_index()
    known = pd.Series(s.to_numpy(), index=s.index + available_after)
    closes = index15 + pd.Timedelta("15min")
    pos = known.index.searchsorted(closes, side="right") - 1
    vals = pd.Series(float("nan"), index=index15)
    ok = pos >= 0
    vals[ok] = known.to_numpy()[pos[ok]]
    return vals


def crowding_ok(index15: pd.DatetimeIndex, funding: pd.Series, max_bp: float = 3.0) -> pd.Series:
    """True unless the last settled funding exceeds max_bp per interval (crowded longs)."""
    f = _asof(index15, funding, pd.Timedelta(0)) * 1e4
    return (f <= max_bp) | f.isna()


def fear_greed_ok(index15: pd.DatetimeIndex, fng: pd.Series, lo: int = 0, hi: int = 80) -> pd.Series:
    """True while yesterday's Fear & Greed is inside [lo, hi] (hi=80 skips 'extreme greed')."""
    v = _asof(index15, fng, pd.Timedelta("1D"))
    return ((v >= lo) & (v <= hi)) | v.isna()
