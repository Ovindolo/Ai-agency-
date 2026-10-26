"""Kronos plumbing, tested with a stand-in forecaster: the real model needs torch and Hugging Face.
These prove the wiring is honest (no lookahead, cache resumes, since respected), not that Kronos works."""
import numpy as np
import pandas as pd

from apps.backtest.engine import run_backtest
from apps.research.kronos_eval import evaluate
from apps.strategy.freqtrade_adapter import frame_leaks, signal_frame
from apps.strategy.kronos import KronosParams, entries, forecast_frame, skill, vol_skill
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
    assert "Forecast skill" in md and "Volatility skill" in md and "## Verdict" in md and "kronos ret>" in md


def test_vol_skill_rewards_a_forecaster_that_knows_the_coming_move_size():
    fc = forecast_frame(DF, momentum_stub, P)
    oracle = fc.copy()
    move = (DF["close"].shift(-P.horizon) / DF["close"] - 1).abs()
    oracle["pred_std"] = move.where(fc["pred_std"].notna())
    assert vol_skill(oracle, DF, P.horizon)["ic_kronos"] > 0.99


def test_old_cache_layout_is_ignored(tmp_path):
    cache = tmp_path / "fc.csv"
    pd.DataFrame({"pred_ret": [0.1], "up_frac": [1.0]}, index=[DF.index[100]]).to_csv(cache)
    fc = forecast_frame(DF.iloc[:400], momentum_stub, P, cache=cache)
    assert fc["pred_std"].notna().any() and fc.loc[DF.index[100], "pred_ret"] != 0.1


def test_decision_grid_does_not_shift_when_history_starts_later():
    """Re-downloading candles with a different start must not move the decision bars (the cache is keyed on time)."""
    a = forecast_frame(DF, momentum_stub, P).dropna().index
    b = forecast_frame(DF.iloc[3:], momentum_stub, P).dropna().index
    common = a.intersection(b)
    assert len(common) > 0.9 * min(len(a), len(b))
