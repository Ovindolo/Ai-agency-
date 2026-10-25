"""make model-data -> data/model/*.csv: everything the cross-sectional model may learn from.

All public, no key, from sources reachable even where api.binance.com answers 451:
  - 4h spot candles per coin           data.binance.vision monthly archives (+ the API mirror for this month)
  - funding per coin (USDT-M perps)     data.binance.vision monthly archives
  - open interest, top-trader and taker long/short ratios (5m)   data.binance.vision daily "metrics" files,
    folded into 4h bars (last OI, last ratios, mean taker ratio)
  - total USD stablecoin supply         DefiLlama (daily)
  - Fear & Greed                        alternative.me (daily)

Timestamps are when a value became KNOWN (bar close, funding settlement, end of day), so features built
on them cannot see the future. Archives are cached per month: reruns only fetch what is new.
"""
from __future__ import annotations

import argparse
import io
import json
import time
import urllib.error
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from apps.backtest.data import DATA_DIR

OUT = DATA_DIR / "model"
ARCHIVE = "https://data.binance.vision/data"
# Liquid Binance spot pairs that also have USDT-M perpetuals for the whole sample.
UNIVERSE = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT",
            "LTC", "BCH", "TRX", "ATOM", "NEAR", "UNI", "ETC", "FIL", "XLM", "AAVE"]
START = pd.Timestamp("2022-01-01", tz="UTC")


def _get(url: str, tries: int = 4) -> bytes | None:
    for k in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None                                  # not listed yet that month/day
            time.sleep(2 ** k)
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 ** k)
    raise RuntimeError(f"failed: {url}")


def _zip_csv(blob: bytes, **kw) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        return pd.read_csv(z.open(z.namelist()[0]), **kw)


def _to_utc(ts: pd.Series) -> pd.DatetimeIndex:
    """Binance archives switched from ms to us timestamps in 2025; accept both."""
    v = pd.to_numeric(ts)
    v = v.where(v < 1e14, v // 1000)
    return pd.DatetimeIndex(pd.to_datetime(v, unit="ms", utc=True))


def months(start: pd.Timestamp, end: pd.Timestamp) -> list[str]:
    return [p.strftime("%Y-%m") for p in pd.period_range(start.tz_localize(None), end.tz_localize(None), freq="M")]


def _cached_months(kind: str, coin: str, fetch_month, now: pd.Timestamp, start: pd.Timestamp) -> pd.DataFrame:
    """One CSV per finished month under data/model/<kind>/<coin>/; the running month is always refetched."""
    folder = OUT / kind / coin
    folder.mkdir(parents=True, exist_ok=True)
    frames = []
    current = now.strftime("%Y-%m")
    for m in months(start, now):
        f = folder / f"{m}.csv"
        if f.exists() and m != current:
            part = pd.read_csv(f, index_col=0)
        else:
            part = fetch_month(coin, m)
            if part is None:
                continue
            if m != current:
                part.to_csv(f)
        frames.append(part)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames)
    df.index = pd.DatetimeIndex(pd.to_datetime(df.index, utc=True, format="ISO8601"))
    return df[~df.index.duplicated()].sort_index()


def _klines_month(coin: str, m: str) -> pd.DataFrame | None:
    blob = _get(f"{ARCHIVE}/spot/monthly/klines/{coin}USDT/4h/{coin}USDT-4h-{m}.zip")
    if blob is None:
        return _klines_api(coin, m)                          # this month: not archived yet
    raw = _zip_csv(blob, header=None)
    if not str(raw.iat[0, 0]).isdigit():                     # some archives carry a header row
        raw = raw.iloc[1:]
    out = pd.DataFrame({"open": raw[1], "high": raw[2], "low": raw[3], "close": raw[4],
                        "volume": raw[5], "quote_volume": raw[7], "taker_buy_quote": raw[10]}).astype(float)
    out.index = _to_utc(raw[0]) + pd.Timedelta("4h")         # stamped at the CLOSE: known from then on
    return out


def _klines_api(coin: str, m: str) -> pd.DataFrame | None:
    from apps.backtest.data import public_exchange
    ex = public_exchange("binance")
    since = int(pd.Timestamp(f"{m}-01", tz="UTC").timestamp() * 1000)
    rows = ex.publicGetKlines({"symbol": f"{coin}USDT", "interval": "4h", "startTime": since, "limit": 1000})
    if not rows:
        return None
    raw = pd.DataFrame(rows).iloc[:-1]                       # drop the still-open bar
    out = pd.DataFrame({"open": raw[1], "high": raw[2], "low": raw[3], "close": raw[4],
                        "volume": raw[5], "quote_volume": raw[7], "taker_buy_quote": raw[10]}).astype(float)
    out.index = _to_utc(raw[0]) + pd.Timedelta("4h")
    return out


def _funding_month(coin: str, m: str) -> pd.DataFrame | None:
    blob = _get(f"{ARCHIVE}/futures/um/monthly/fundingRate/{coin}USDT/{coin}USDT-fundingRate-{m}.zip")
    if blob is None:
        return None
    raw = _zip_csv(blob)
    return pd.DataFrame({"funding": raw["last_funding_rate"].astype(float).to_numpy()}, index=_to_utc(raw["calc_time"]))


def _metrics_day(coin: str, day: str) -> pd.DataFrame | None:
    blob = _get(f"{ARCHIVE}/futures/um/daily/metrics/{coin}USDT/{coin}USDT-metrics-{day}.zip")
    if blob is None:
        return None
    raw = _zip_csv(blob)
    raw.index = pd.DatetimeIndex(pd.to_datetime(raw["create_time"], utc=True))
    cols = {"sum_open_interest_value": "oi_usd", "sum_toptrader_long_short_ratio": "top_ls",
            "count_long_short_ratio": "acct_ls", "sum_taker_long_short_vol_ratio": "taker_ls"}
    raw = raw[list(cols)].rename(columns=cols).apply(pd.to_numeric, errors="coerce")
    # a 5m snapshot stamped t is known at t; a 4h bar closing at T takes everything with t < T
    grouped = raw.groupby(raw.index.ceil("4h"))
    return pd.DataFrame({"oi_usd": grouped["oi_usd"].last(), "top_ls": grouped["top_ls"].last(),
                         "acct_ls": grouped["acct_ls"].last(), "taker_ls": grouped["taker_ls"].mean()})


def _metrics_month(coin: str, m: str) -> pd.DataFrame | None:
    first = pd.Timestamp(f"{m}-01")
    days = [d.strftime("%Y-%m-%d") for d in pd.date_range(first, first + pd.offsets.MonthEnd(0))
            if d < pd.Timestamp.now().normalize()]
    with ThreadPoolExecutor(8) as pool:
        parts = [p for p in pool.map(lambda d: _metrics_day(coin, d), days) if p is not None]
    return pd.concat(parts).sort_index() if parts else None


def stablecoins() -> pd.Series:
    """Total USD-pegged supply, value for day D known at the end of D."""
    with urllib.request.urlopen("https://stablecoins.llama.fi/stablecoincharts/all", timeout=60) as r:
        rows = json.loads(r.read())
    s = pd.Series({pd.Timestamp(int(x["date"]), unit="s", tz="UTC") + pd.Timedelta("1D"):
                   x["totalCirculatingUSD"]["peggedUSD"] for x in rows})
    return s.sort_index().rename("stable_usd")


def collect(coins: list[str], start: pd.Timestamp = START, workers: int = 4) -> None:
    from apps.features.market_context import fetch_fear_greed
    now = pd.Timestamp.now(tz="UTC")
    OUT.mkdir(parents=True, exist_ok=True)

    def one(coin: str) -> str:
        k = _cached_months("klines", coin, _klines_month, now, start)
        f = _cached_months("funding", coin, _funding_month, now, start)
        mt = _cached_months("metrics", coin, _metrics_month, now, start)
        df = k.join(mt, how="left")
        # funding settles every 8h: carry the last settled rate to each 4h close, but never a stale one
        # (the running month is not archived yet and fapi is geo-blocked: missing, not last month's value)
        if f.empty:
            df["funding"] = float("nan")
        else:
            pos = f.index.searchsorted(df.index, side="right") - 1
            ok = pos >= 0
            val = pd.Series(float("nan"), index=df.index)
            val[ok] = f["funding"].to_numpy()[pos[ok]]
            age = pd.Series(df.index, index=df.index) - pd.Series(f.index[pos.clip(0)], index=df.index)
            df["funding"] = val.where(ok & (age <= pd.Timedelta("12h")))
        df.to_csv(OUT / f"{coin}.csv")
        return f"{coin}: {len(df)} bars {df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d}, " \
               f"funding {df['funding'].notna().mean():.0%}, OI {df['oi_usd'].notna().mean():.0%}"

    with ThreadPoolExecutor(workers) as pool:
        for line in pool.map(one, coins):
            print(line, flush=True)
    fng = fetch_fear_greed().rename("fng")
    fng.index = fng.index + pd.Timedelta("1D")              # day D's value is known at the end of D
    macro = pd.concat([stablecoins(), fng], axis=1).sort_index()
    macro.to_csv(OUT / "macro.csv")
    print(f"macro: {len(macro)} days -> {OUT / 'macro.csv'}")


def load(coin: str) -> pd.DataFrame:
    df = pd.read_csv(OUT / f"{coin}.csv", index_col=0)
    df.index = pd.DatetimeIndex(pd.to_datetime(df.index, utc=True, format="ISO8601"))
    return df


def load_macro() -> pd.DataFrame:
    df = pd.read_csv(OUT / "macro.csv", index_col=0)
    df.index = pd.DatetimeIndex(pd.to_datetime(df.index, utc=True, format="ISO8601"))
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default=",".join(UNIVERSE))
    ap.add_argument("--start", default=str(START.date()))
    a = ap.parse_args()
    collect(a.coins.split(","), start=pd.Timestamp(a.start, tz="UTC"))


if __name__ == "__main__":
    main()
