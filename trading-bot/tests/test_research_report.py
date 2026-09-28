import numpy as np
import pandas as pd
import pytest

from apps.research.metrics import by_regime, deflated_sharpe, perf, regimes
from apps.research.report import apply_checks, evaluate_symbol, markdown, walk_forward
from apps.features.snapshot import resample_1d
from tests.helpers import synthetic_15m


def eq_from_returns(r, start="2024-01-01"):
    idx = pd.date_range(start, periods=len(r) + 1, freq="1D", tz="UTC")
    return pd.Series(500 * np.concatenate([[1], np.cumprod(1 + np.asarray(r))]), index=idx)


def test_perf_basic():
    eq = eq_from_returns([0.01] * 365)
    p = perf(eq)
    assert p["total"] == pytest.approx(1.01 ** 365 - 1)
    assert p["max_dd"] == 0 and p["sharpe"] == 0          # zero variance -> no Sharpe claimed


def test_deflated_sharpe_punishes_many_trials():
    rng = np.random.default_rng(1)
    r = pd.Series(0.001 + 0.02 * rng.standard_normal(700))
    few = deflated_sharpe(r, [r.mean() / r.std(), 0.0])
    trials = list(rng.normal(0, 0.05, 200)) + [r.mean() / r.std()]
    many = deflated_sharpe(r, trials)
    assert 0 <= many < few <= 1


def test_regimes_are_causal_and_bounded():
    px = pd.Series(100 * 1.01 ** np.arange(200), index=pd.date_range("2024-01-01", periods=200, freq="1D", tz="UTC"))
    lab = regimes(px, lookback=30)
    assert (lab.iloc[:30] == "unknown").all() and lab.iloc[-1] == "bull"
    crash = eq_from_returns([-0.5] * 10)
    g = by_regime(crash, pd.Series("bear", index=crash.index))
    assert g["bear"][1] >= -1.0                              # compounded: never below -100%


def test_walk_forward_only_uses_the_past():
    good_early = eq_from_returns([0.01] * 100 + [-0.01] * 100)
    good_late = eq_from_returns([-0.001] * 100 + [0.01] * 100)
    eq, picks = walk_forward({"early": good_early, "late": good_late}, folds=4)
    assert picks[0] == "early"                               # it cannot know "late" will win later
    assert len(eq) > 0


def test_report_end_to_end_small():
    df = synthetic_15m(n=96 * 120, drift=0.0001, vol=0.003, seed=4, start=30000)
    daily_long = resample_1d(synthetic_15m(n=96 * 400, drift=0.00005, vol=0.003, seed=5, start=30000))
    res = evaluate_symbol("BTC/USDT", df, daily_long)
    apply_checks([res])
    md = markdown([res], simulated=True)
    for section in ("## 1. Rezumat", "## 4. Rezultate", "Walk-forward", "Sensibilitate", "## 5. Clasament",
                    "## 6. Recomandare", "DATE SIMULATE", "Deflated Sharpe"):
        assert section in md
    assert all(len(r.checks) == 7 for r in res["rows"])
