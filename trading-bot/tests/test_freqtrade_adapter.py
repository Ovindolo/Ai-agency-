import numpy as np
import pandas as pd
import pytest

pytest.importorskip("freqtrade")
talib = pytest.importorskip("talib.abstract")
from freqtrade.strategy import IStrategy  # noqa: E402

from apps.backtest.engine import run_backtest  # noqa: E402
from apps.strategy.freqtrade_adapter import entry_signals, has_lookahead, signal_frame  # noqa: E402
from tests.helpers import synthetic_15m  # noqa: E402

DF = synthetic_15m(n=3000, drift=0.0003, seed=4)


class Clean(IStrategy):
    timeframe = "15m"
    stoploss = -0.34549          # hyperopt-style value that must be ignored
    minimal_roi = {"0": 0.01}

    def populate_indicators(self, df, meta):
        df["rsi"] = talib.RSI(df, timeperiod=14)
        df["ema"] = talib.EMA(df, timeperiod=50)
        return df

    def populate_entry_trend(self, df, meta):
        df.loc[(df["rsi"] < 40) & (df["close"] > df["ema"]), "enter_long"] = 1
        return df

    def populate_exit_trend(self, df, meta):
        return df


class LeakyMinMax(Clean):
    def populate_indicators(self, df, meta):
        df = super().populate_indicators(df, meta)
        df["norm"] = (df["close"] - df["close"].min()) / (df["close"].max() - df["close"].min())
        return df


class LeakyNeverFires(Clean):
    """Leaks the future into an indicator but never emits an entry: signals alone cannot catch it."""
    def populate_indicators(self, df, meta):
        df = super().populate_indicators(df, meta)
        df["future"] = df["close"].shift(-3)
        return df

    def populate_entry_trend(self, df, meta):
        df["enter_long"] = 0
        return df


class HourlyClean(Clean):
    timeframe = "1h"


def test_clean_strategy_passes():
    assert has_lookahead(Clean, DF) == (False, "")


@pytest.mark.parametrize("cls,col", [(LeakyMinMax, "norm"), (LeakyNeverFires, "future")])
def test_lookahead_is_caught_even_without_signals(cls, col):
    leak, why = has_lookahead(cls, DF)
    assert leak and col in why


def test_higher_timeframe_signals_land_on_the_closing_15m_bar():
    sig = entry_signals(HourlyClean, DF)
    fired = sig[sig].index
    assert len(fired) > 0
    assert all(t.minute == 45 for t in fired)           # 1h candle [H:00, H+1:00) closes on the H:45 bar


def test_imported_exits_are_ours_not_theirs():
    sf = signal_frame(entry_signals(Clean, DF), DF)
    s = sf[sf["signal"]]
    assert len(s) > 0
    assert (s["stop_pct"] <= 0.025 + 1e-12).all() and (s["stop_pct"] >= 0.015 - 1e-12).all()   # not 34.5%
    rep = run_backtest(DF, "BTC/USDT", label="imported", signal_frame=sf)
    assert rep.signals > 0
