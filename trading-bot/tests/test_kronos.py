"""Kronos plumbing, tested with a stand-in forecaster: the real model needs torch and Hugging Face.
These prove the wiring is honest (no lookahead, cache resumes, since respected), not that Kronos works."""
import numpy as np
import pandas as pd

from apps.backtest.engine import run_backtest
from apps.research.kronos_eval import evaluate
from apps.strategy.freqtrade_adapter import frame_leaks, signal_frame
from apps.strategy.kronos import KronosParams, entries, forecast_frame, skill
from tests.helpers import synthetic_15m

DF = synthetic_15m(n=2500, drift=0.0003, vol=0.004, seed=5)
P = KronosParams(lookback=64, horizon=8, every=4, paths=8)


def momentum_stub(window, future, paths, seed):
    """Extrapolates the window's last 16-bar drift, plus seeded noise: deterministic per bar, like the real one."""
    c = window["close"].to_numpy()
    drift = np.log(c[-1] / c[-16]) / 16
    noise = np.random.default_rng(seed).normal(0, 0.002, (paths, len(future)))
    return c[-1] * np.exp(np.cumsum(drift + noise, axis=1))


def test_forecasts_do_not_see_the_future():
    leaks, why = frame_leaks(lambda d: forecast_frame(d, momentum_stub, P), DF)
    assert not leaks, why


def test_forecaster_gets_only_closed_bars_up_to_the_decision():
    seen = []
    def spy(window, future, paths, seed):
        seen.append((window.index[-1], future[0], len(window)))
        return momentum_stub(window, future, paths, seed)
    forecast_frame(DF.iloc[:300], spy, P)
    assert all(last < first_future and n == P.lookback for last, first_future, n in seen)


def test_cache_resume_equals_fresh_run(tmp_path):
    cache = tmp_path / "fc.csv"
    forecast_frame(DF.iloc[:1500], momentum_stub, P, cache=cache)
    calls = []
    def counting(*a):
        calls.append(1)
        return momentum_stub(*a)
    resumed = forecast_frame(DF, counting, P, cache=cache)
    fresh = forecast_frame(DF, momentum_stub, P)
    assert len(calls) < len(fresh.dropna())                     # cached bars were not recomputed
    pd.testing.assert_frame_equal(resumed, fresh, check_freq=False, atol=1e-12)


def test_since_skips_earlier_bars():
    since = DF.index[1200]
    fc = forecast_frame(DF, momentum_stub, P, since=since)
    assert fc.loc[:DF.index[1199]].isna().all().all()
    assert fc.loc[since:].notna().any().all()


def test_entries_run_through_the_same_exits_and_skill_is_measured():
    fc = forecast_frame(DF, momentum_stub, P)
    e = entries(fc, P)
    assert e.sum() > 0
    rep = run_backtest(DF, "BTC/USDT", label="kronos", signal_frame=signal_frame(e, DF))
    assert rep.signals > 0 and all(t.reason for t in rep.trades)
    s = skill(fc, DF, P.horizon)
    assert s["n"] > 0 and 0 <= s["hit_rate"] <= 1


def test_report_renders():
    fc = forecast_frame(DF, momentum_stub, P)
    md = evaluate(DF, fc, "BTC/USDT", P, DF.index[500], 800.0, "stub")
    assert "Forecast skill" in md and "## Verdict" in md and "kronos ret>" in md
