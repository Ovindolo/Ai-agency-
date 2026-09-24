"""Deterministic feature snapshot. Code only.

Every value uses only candles CLOSED before the decision time. The caller passes frames that end
at the last closed candle; nothing here looks at an open candle or the future.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Snapshot:
    symbol: str
    ts: str                      # ISO time of the last CLOSED 15m candle
    # PRICE
    mid: float
    return_15m: float
    return_1h: float
    return_4h: float
    ema20_1h: float
    ema50_1h: float
    ema_gap: float               # (ema20-ema50)/ema50
    adx_1h: float
    # BOOK
    spread_bps: float
    depth_usd_l1: float
    imbalance: float
    # FLOW
    volume_vs_avg: float
    taker_buy_ratio: float       # 0.5 when unavailable
    # VOL
    atr_pct: float               # 15m ATR(14) / close
    realized_vol_5h: float
    vol_vs_24h: float
    # POS
    inventory_usd: float
    unrealized_pnl_pct: float
    position_age_min: float
    daily_pnl_pct: float
    drawdown_pct: float
    # HEALTH
    data_age_sec: float
    # SIGNAL
    strategy_side: str           # "long" | "none"
    strategy_rr: float
    stop_pct: float
    take_pct: float

    def as_dict(self) -> dict:
        return asdict(self)


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def adx(df: pd.DataFrame, n: int = 14) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = atr(df, 1)
    atr_n = tr.ewm(alpha=1 / n, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr_n
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr_n
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean().fillna(0)


def resample_1h(df15: pd.DataFrame) -> pd.DataFrame:
    """1h candles built only from complete hours of 15m data."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "taker_buy_volume" in df15:
        agg["taker_buy_volume"] = "sum"
    h = df15.resample("1h", label="left", closed="left").agg(agg).dropna()
    counts = df15["close"].resample("1h", label="left", closed="left").count()
    return h[counts.reindex(h.index) == 4]


def build_snapshot(
    symbol: str,
    df15: pd.DataFrame,
    *,
    book: dict | None = None,
    position: dict | None = None,
    account: dict | None = None,
    signal: dict | None = None,
    data_age_sec: float = 0.0,
) -> Snapshot:
    """df15: DatetimeIndex (UTC), columns open/high/low/close/volume[/taker_buy_volume], closed candles only."""
    if len(df15) < 24 * 4 + 1:
        raise ValueError("need at least 24h + 1 of closed 15m candles")
    book = book or {}
    position = position or {}
    account = account or {}
    signal = signal or {}

    close = df15["close"]
    last = float(close.iloc[-1])
    h1 = resample_1h(df15)
    e20, e50 = ema(h1["close"], 20), ema(h1["close"], 50)
    a15 = atr(df15)
    rets = close.pct_change()

    vol_avg = df15["volume"].iloc[-97:-1].mean()
    if "taker_buy_volume" in df15 and df15["volume"].iloc[-1] > 0:
        tbr = float(df15["taker_buy_volume"].iloc[-1] / df15["volume"].iloc[-1])
    else:
        tbr = 0.5
    rv5 = float(rets.iloc[-20:].std() * np.sqrt(20))
    rv24 = float(rets.iloc[-96:].std() * np.sqrt(20))

    return Snapshot(
        symbol=symbol,
        ts=df15.index[-1].isoformat(),
        mid=float(book.get("mid", last)),
        return_15m=float(close.iloc[-1] / close.iloc[-2] - 1),
        return_1h=float(close.iloc[-1] / close.iloc[-5] - 1),
        return_4h=float(close.iloc[-1] / close.iloc[-17] - 1),
        ema20_1h=float(e20.iloc[-1]),
        ema50_1h=float(e50.iloc[-1]),
        ema_gap=float((e20.iloc[-1] - e50.iloc[-1]) / e50.iloc[-1]),
        adx_1h=float(adx(h1).iloc[-1]),
        spread_bps=float(book.get("spread_bps", 1.0)),
        depth_usd_l1=float(book.get("depth_usd_l1", 1e6)),
        imbalance=float(book.get("imbalance", 0.0)),
        volume_vs_avg=float(df15["volume"].iloc[-1] / vol_avg) if vol_avg > 0 else 1.0,
        taker_buy_ratio=tbr,
        atr_pct=float(a15.iloc[-1] / last),
        realized_vol_5h=rv5,
        vol_vs_24h=rv5 / rv24 if rv24 > 0 else 1.0,
        inventory_usd=float(position.get("inventory_usd", 0.0)),
        unrealized_pnl_pct=float(position.get("unrealized_pnl_pct", 0.0)),
        position_age_min=float(position.get("age_min", 0.0)),
        daily_pnl_pct=float(account.get("daily_pnl_pct", 0.0)),
        drawdown_pct=float(account.get("drawdown_pct", 0.0)),
        data_age_sec=float(data_age_sec),
        strategy_side=str(signal.get("side", "none")),
        strategy_rr=float(signal.get("rr", 0.0)),
        stop_pct=float(signal.get("stop_pct", 0.0)),
        take_pct=float(signal.get("take_pct", 0.0)),
    )
