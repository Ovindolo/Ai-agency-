"""Own-model pipeline: features must not see the future; the book must charge fees on turnover."""
import numpy as np
import pandas as pd

from apps.model.features import coin_frame
from apps.model.walkforward import book
from apps.strategy.freqtrade_adapter import frame_leaks
from tests.helpers import synthetic_15m


def _coin_4h(seed: int) -> pd.DataFrame:
    df = synthetic_15m(n=3000, seed=seed).rename(columns={"taker_buy_volume": "taker_buy_quote"})
    df.index = pd.date_range("2024-01-01 04:00", periods=len(df), freq="4h", tz="UTC")
    rng = np.random.default_rng(seed)
    df["quote_volume"] = df["volume"] * df["close"]
    df["funding"] = np.where(np.arange(len(df)) % 2 == 0, 1e-4 * rng.standard_normal(len(df)), np.nan)
    df["oi_usd"] = 1e9 * np.exp(np.cumsum(0.01 * rng.standard_normal(len(df))))
    df["top_ls"] = df["acct_ls"] = df["taker_ls"] = 1 + 0.1 * rng.standard_normal(len(df))
    return df


def test_coin_features_do_not_see_the_future():
    leaks, why = frame_leaks(coin_frame, _coin_4h(3))
    assert not leaks, why


def test_book_charges_fees_on_turnover_only():
    days = pd.date_range("2025-01-01", periods=6, freq="D", tz="UTC")
    rows = [(d, c, sc, 0.01, 1.0) for i, d in enumerate(days)
            for c, sc in (("A", 1.0 if i % 2 else 0.0), ("B", 0.5))]
    panel = pd.DataFrame(rows, columns=["day", "coin", "score", "ret_1d_next", "btc_r_84d"])
    flips = book(panel, panel["score"], "flip", horizon=1, k=1, fee=0.001)
    steady = book(panel, pd.Series(1.0, index=panel.index).where(panel["coin"] == "A", 0.0), "steady", 1, 1, 0.001)
    assert steady.daily.iloc[1:].eq(0.01).all()                      # no turnover after day 1, no fee
    assert (flips.daily.iloc[1:] < 0.01).all()                       # switching every day pays both sides


def test_15m_features_do_not_see_the_future():
    from apps.m15.features import coin_features
    df = _coin_4h(5)
    df.index = pd.date_range("2025-01-01", periods=len(df), freq="15min", tz="UTC")
    fund = df["funding"].dropna()
    leaks, why = frame_leaks(lambda d: coin_features(d, fund), df.drop(columns=["funding", "oi_usd", "top_ls", "acct_ls", "taker_ls"]))
    assert not leaks, why
