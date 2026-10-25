"""USDT-M futures 1h candles for the price-action backtest (data.binance.vision, public, cached per month).

Bars are indexed by their OPEN time here (unlike apps/model): the simulator walks bars in order and only
acts on a bar after it has closed, so open-time indexing is the natural convention for intrabar fills.
"""
from __future__ import annotations

import pandas as pd

from apps.model.data import ARCHIVE, OUT, START, UNIVERSE, _cached_months, _get, _to_utc, _zip_csv


def _futures_1h_month(coin: str, m: str) -> pd.DataFrame | None:
    blob = _get(f"{ARCHIVE}/futures/um/monthly/klines/{coin}USDT/1h/{coin}USDT-1h-{m}.zip")
    if blob is None:
        return _futures_1h_daily(coin, m)                    # running month: daily archives
    raw = _zip_csv(blob, header=None)
    if not str(raw.iat[0, 0]).isdigit():                     # newer archives carry a header row
        raw = raw.iloc[1:]
    return _frame(raw)


def _futures_1h_daily(coin: str, m: str) -> pd.DataFrame | None:
    first = pd.Timestamp(f"{m}-01")
    parts = []
    for d in pd.date_range(first, min(first + pd.offsets.MonthEnd(0), pd.Timestamp.now().normalize() - pd.Timedelta("1D"))):
        blob = _get(f"{ARCHIVE}/futures/um/daily/klines/{coin}USDT/1h/{coin}USDT-1h-{d:%Y-%m-%d}.zip")
        if blob is not None:
            raw = _zip_csv(blob, header=None)
            if not str(raw.iat[0, 0]).isdigit():
                raw = raw.iloc[1:]
            parts.append(_frame(raw))
    return pd.concat(parts) if parts else None


def _frame(raw: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({"open": raw[1], "high": raw[2], "low": raw[3], "close": raw[4], "volume": raw[5]}).astype(float)
    out.index = _to_utc(raw[0])
    return out


def load_1h(coin: str, refresh: bool = False) -> pd.DataFrame:
    now = pd.Timestamp.now(tz="UTC")
    df = _cached_months("futures_1h", coin, _futures_1h_month, now, START)
    return df[~df.index.duplicated()].sort_index()


def to_4h(df1h: pd.DataFrame) -> pd.DataFrame:
    """4h bars from 1h, open-time indexed; an incomplete last 4h bar is dropped."""
    g = df1h.resample("4h", origin="epoch")
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum(), "n": g["close"].count()})
    return out[out["n"] == 4].drop(columns="n")


def funding(coin: str) -> pd.Series:
    """Settled funding rates (index = settlement time); empty where no archive exists."""
    from apps.model.data import _funding_month
    f = _cached_months("funding", coin, _funding_month, pd.Timestamp.now(tz="UTC"), START)
    return f["funding"] if not f.empty else pd.Series(dtype=float)


__all__ = ["UNIVERSE", "OUT", "load_1h", "to_4h", "funding"]
