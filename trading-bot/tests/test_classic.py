import pandas as pd
import pytest

from apps.backtest.engine import run_backtest
from apps.strategy.classic import CLASSIC, entries, ichimoku
from apps.strategy.freqtrade_adapter import frame_leaks, signal_frame
from tests.helpers import synthetic_15m

DF = synthetic_15m(n=2500, drift=0.0003, vol=0.004, seed=5)


@pytest.mark.parametrize("name", sorted(CLASSIC))
def test_classic_indicators_do_not_see_the_future(name):
    leaks, why = frame_leaks(CLASSIC[name], DF)
    assert not leaks, why


def test_naive_chikou_is_caught():
    """The textbook mistake: storing Chikou as close.shift(-26). The detector must reject it."""
    def naive(df):
        out = ichimoku(df)
        out["chikou"] = df["close"].shift(-26)
        return out
    leaks, why = frame_leaks(naive, DF)
    assert leaks and "chikou" in why


@pytest.mark.parametrize("name", sorted(CLASSIC))
def test_classic_fires_and_runs_through_the_same_exits(name):
    e = entries(name, DF)
    assert e.sum() > 0, f"{name} never fired on trending data"
    rep = run_backtest(DF, "BTC/USDT", label=name, signal_frame=signal_frame(e, DF))
    assert rep.signals > 0
    assert all(t.reason for t in rep.trades)
