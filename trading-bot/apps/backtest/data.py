"""Historical data: download via ccxt (public endpoints, no key) and load from CSV."""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def csv_path(symbol: str, tf: str = "15m") -> Path:
    return DATA_DIR / f"{symbol.replace('/', '')}_{tf}.csv"


def download(symbol: str, exchange: str = "binance", tf: str = "15m", days: int = 400) -> Path:
    import ccxt
    ex = getattr(ccxt, exchange)({"enableRateLimit": True})
    since = ex.milliseconds() - days * 86_400_000
    rows: list[list] = []
    while True:
        batch = ex.fetch_ohlcv(symbol, tf, since=since, limit=1000)
        if not batch:
            break
        rows += batch
        since = batch[-1][0] + 1
        if len(batch) < 1000:
            break
        time.sleep(ex.rateLimit / 1000)
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).drop_duplicates("ts")
    df = df.iloc[:-1]                                    # drop the still-open candle
    DATA_DIR.mkdir(exist_ok=True)
    out = csv_path(symbol, tf)
    df.to_csv(out, index=False)
    return out


class BadData(ValueError):
    """Raised instead of silently producing zero signals from malformed candles."""


def validate_15m(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        raise BadData("no candles")
    if not isinstance(df.index, pd.DatetimeIndex) or df.index.tz is None:
        raise BadData("index must be a UTC DatetimeIndex")
    if df.index[0] < pd.Timestamp("2017-01-01", tz="UTC"):
        raise BadData(f"first candle is {df.index[0]} - timestamps are probably in the wrong unit (need ms)")
    if df.index.has_duplicates or not df.index.is_monotonic_increasing:
        raise BadData("timestamps must be unique and increasing")
    step = df.index.to_series().diff().median()
    if step != pd.Timedelta("15min"):
        raise BadData(f"median candle spacing is {step}, expected 15min")
    missing = {"open", "high", "low", "close", "volume"} - set(df.columns)
    if missing:
        raise BadData(f"missing columns: {sorted(missing)}")
    if (df["high"] < df["low"]).any() or (df[["open", "high", "low", "close"]] <= 0).any().any():
        raise BadData("impossible OHLC values")
    return df


def to_ms(index: pd.DatetimeIndex) -> pd.Series:
    """Epoch milliseconds, independent of pandas' internal datetime resolution (ns in 2.x, us in 3.x)."""
    return pd.Series((index - pd.Timestamp("1970-01-01", tz="UTC")) // pd.Timedelta("1ms"), index=index)


def load(symbol: str, tf: str = "15m") -> pd.DataFrame:
    df = pd.read_csv(csv_path(symbol, tf))
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("ts"), unit="ms", utc=True))
    return validate_15m(df.sort_index())
