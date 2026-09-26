import numpy as np
import pandas as pd
import pytest

from apps.features.snapshot import resample_1d
from apps.strategy.daily_trend import (DailyTrendParams, buy_and_hold, compare, run_daily_trend, target_weights,
                                      weekly_dca)
from apps.strategy.freqtrade_adapter import frame_leaks
from tests.helpers import synthetic_15m


def daily(drift=0.0, n_days=400, seed=3):
    return resample_1d(synthetic_15m(n=96 * n_days, drift=drift, vol=0.003, seed=seed, start=30000))


def test_weights_do_not_see_the_future():
    d = daily(0.00005)
    leaks, why = frame_leaks(lambda x: target_weights(x, DailyTrendParams()).to_frame("w"), d)
    assert not leaks, why


def test_weights_are_spot_only():
    w = target_weights(daily(0.0002), DailyTrendParams())
    assert w.min() >= 0 and w.max() <= 1.0


def test_downtrend_stays_mostly_in_cash_and_loses_less():
    d = daily(-0.0001, seed=5)
    t, bh = run_daily_trend(d), buy_and_hold(d)
    assert bh.total_return < -0.3
    assert t.total_return > bh.total_return and t.max_dd < bh.max_dd


def test_money_is_conserved_when_flat():
    d = daily(-0.0003, n_days=60, seed=1)
    r = run_daily_trend(d, DailyTrendParams(lookback=5))
    flat = target_weights(d, DailyTrendParams(lookback=5)).shift(1).fillna(0) == 0
    # on days after going flat equity only changes through fees/slippage of the exit, never price
    e = r.equity[flat].diff().dropna()
    assert (e.abs() < 5).all()


def test_dca_invests_everything_by_the_end():
    d = daily(0.0, n_days=70)
    r = weekly_dca(d)
    assert r.trades == 10 and r.fees == pytest.approx(0.5)


def test_compare_has_benchmarks():
    names = [r.label for r in compare(daily(0.0001))]
    assert "buy & hold" in names and "DCA săptămânal" in names
