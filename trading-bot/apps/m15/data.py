"""USDT-M futures 15m candles (with taker-buy volume) from data.binance.vision, cached per month."""
from __future__ import annotations

import pandas as pd

from apps.model.data import ARCHIVE, START, _cached_months, _get, _to_utc, _zip_csv

COINS = ["NEAR", "SUI", "SEI", "ETH", "ENA", "INJ", "XMR", "TIA", "LINK", "SOL", "UNI", "ASTER", "QNT", "VVV",
         "BTC", "BNB", "XRP", "DOGE", "AVAX", "AAVE"]


def _parse(raw: pd.DataFrame) -> pd.DataFrame:
    if not str(raw.iat[0, 0]).isdigit():                     # newer archives carry a header row
        raw = raw.iloc[1:]
    out = pd.DataFrame({"open": raw[1], "high": raw[2], "low": raw[3], "close": raw[4], "volume": raw[5],
                        "quote_volume": raw[7], "taker_buy_quote": raw[10]}).astype(float)
    out.index = _to_utc(raw[0])                              # open time
    return out


def _month(coin: str, m: str) -> pd.DataFrame | None:
    blob = _get(f"{ARCHIVE}/futures/um/monthly/klines/{coin}USDT/15m/{coin}USDT-15m-{m}.zip")
    if blob is not None:
        return _parse(_zip_csv(blob, header=None))
    first = pd.Timestamp(f"{m}-01")                          # running month: daily archives
    last = min(first + pd.offsets.MonthEnd(0), pd.Timestamp.now().normalize() - pd.Timedelta("1D"))
    parts = []
    for d in pd.date_range(first, last):
        b = _get(f"{ARCHIVE}/futures/um/daily/klines/{coin}USDT/15m/{coin}USDT-15m-{d:%Y-%m-%d}.zip")
        if b is not None:
            parts.append(_parse(_zip_csv(b, header=None)))
    return pd.concat(parts) if parts else None


def load_15m(coin: str) -> pd.DataFrame:
    df = _cached_months("futures_15m", coin, _month, pd.Timestamp.now(tz="UTC"), START)
    return df[~df.index.duplicated()].sort_index()
