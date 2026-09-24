"""Market data for the runner. Live: ccxt public endpoints (no API key). Replay: a CSV/DataFrame, bar by bar."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from apps.backtest.data import validate_15m

BARS = 1000


class CcxtSource:
    def __init__(self, exchange: str = "binance"):
        import ccxt
        self.ex = getattr(ccxt, exchange)({"enableRateLimit": True})

    def candles(self, symbol: str, now: datetime) -> pd.DataFrame:
        rows = self.ex.fetch_ohlcv(symbol, "15m", limit=BARS + 1)
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("ts"), unit="ms", utc=True))
        closed = df[df.index + pd.Timedelta("15min") <= pd.Timestamp(now)]     # drop the open candle
        return validate_15m(closed)

    def book(self, symbol: str, now: datetime | None = None) -> dict:
        ob = self.ex.fetch_order_book(symbol, limit=5)
        bid, ask = ob["bids"][0][0], ob["asks"][0][0]
        mid = (bid + ask) / 2
        return {"mid": mid, "bid": bid, "ask": ask, "spread_bps": (ask - bid) / mid * 1e4,
                "depth_usd_l1": min(ob["bids"][0][0] * ob["bids"][0][1], ob["asks"][0][0] * ob["asks"][0][1])}


class ReplaySource:
    """Serves history as if it were live: at time t only candles closed by t exist; price = next open."""

    def __init__(self, frames: dict[str, pd.DataFrame]):
        self.frames = {s: validate_15m(df) for s, df in frames.items()}

    def times(self, symbol: str, start: int, end: int | None = None) -> list[datetime]:
        idx = self.frames[symbol].index
        return [(t + pd.Timedelta("15min")).to_pydatetime() for t in idx[start:end]]

    def candles(self, symbol: str, now: datetime) -> pd.DataFrame:
        df = self.frames[symbol]
        closed = df[df.index + pd.Timedelta("15min") <= pd.Timestamp(now)]
        return closed.iloc[-BARS:]

    def book(self, symbol: str, now: datetime | None = None) -> dict:
        df = self.frames[symbol]
        nxt = df[df.index >= pd.Timestamp(now)] if now is not None else df.iloc[-1:]
        px = float(nxt["open"].iloc[0]) if len(nxt) else float(df["close"].iloc[-1])
        return {"mid": px, "bid": px * 0.99995, "ask": px * 1.00005, "spread_bps": 1.0, "depth_usd_l1": 1e6}
