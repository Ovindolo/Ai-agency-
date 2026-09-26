import numpy as np
import pandas as pd
import pytest

from apps.research.carry import CarryParams, run_carry
from apps.research.leverage import SimParams, day_moves, kelly_leverage, simulate


def fake_daily(n=1500, mu=0.002, sigma=0.035, seed=3):
    rng = np.random.default_rng(seed)
    r = mu + sigma * rng.standard_normal(n)
    o = 30000 * np.exp(np.concatenate([[0], np.cumsum(r)[:-1]]))
    c = o * (1 + r)
    low = np.minimum(o, c) * (1 - np.abs(0.02 * rng.standard_normal(n)))
    high = np.maximum(o, c) * (1 + np.abs(0.02 * rng.standard_normal(n)))
    return pd.DataFrame({"open": o, "high": high, "low": low, "close": c},
                        index=pd.date_range("2020-01-01", periods=n, freq="1D", tz="UTC"))


P = SimParams(paths=1500, days=365)


def test_kelly_formula():
    ret = np.array([0.02, -0.01] * 50)
    assert kelly_leverage(ret) == pytest.approx(ret.mean() / ret.var())


def test_more_leverage_past_kelly_lowers_the_median():
    ret, worst = day_moves(fake_daily())
    k = kelly_leverage(ret)
    assert 0 < k < 5
    med = {lev: np.median(simulate(ret, worst, lev, P)) for lev in (1, 3, 10, 20)}
    assert med[20] < med[3] and med[10] < med[3]


def test_high_leverage_gets_liquidated():
    ret, worst = day_moves(fake_daily())
    assert np.mean(simulate(ret, worst, 50, P) == 0) > 0.9
    assert np.mean(simulate(ret, worst, 1, P) == 0) == 0


def test_short_mirrors_long():
    d = fake_daily()
    r_long, _ = day_moves(d)
    r_short, w_short = day_moves(d, short=True)
    assert np.allclose(r_short, -r_long)
    assert (w_short <= 0).all()


def funding_series(values, freq="8h"):
    return pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq=freq, tz="UTC"))


def test_carry_collects_funding_minus_fees():
    f = funding_series([0.0003] * (3 * 365))                 # 3 bp every 8h ~ 33%/yr on notional
    r = run_carry(f, CarryParams(fee_pct=0.0))
    share = 1 / (1 + 1 / 3)
    assert r.trades == 1
    assert r.equity.iloc[-1] / 500 == pytest.approx((1 + share * 0.0003) ** (3 * 365 - 3), rel=1e-6)


def test_carry_stays_out_when_funding_is_low_or_negative():
    r = run_carry(funding_series([0.00002, -0.0001] * 500))
    assert r.trades == 0 and r.equity.iloc[-1] == 500


def test_carry_exits_when_funding_drops():
    f = funding_series([0.0003] * 30 + [-0.0002] * 30)
    r = run_carry(f)
    assert r.trades == 1 and r.fees > 0
    assert r.equity.iloc[-1] == r.equity.iloc[-5]           # flat after exit


def test_context_masks_are_causal():
    from apps.features.market_context import crowding_ok, fear_greed_ok
    idx = pd.date_range("2024-01-01", periods=96 * 3, freq="15min", tz="UTC")
    funding = pd.Series([0.0001, 0.0010, 0.0001], index=pd.to_datetime(
        ["2024-01-01 08:00", "2024-01-01 16:00", "2024-01-02 00:00"], utc=True))
    ok = crowding_ok(idx, funding, max_bp=3)
    # the 10 bp print settles at 16:00: bars CLOSING at/after 16:00 see it, earlier ones do not
    assert ok[pd.Timestamp("2024-01-01 15:30", tz="UTC")]
    assert not ok[pd.Timestamp("2024-01-01 15:45", tz="UTC")]
    assert ok[pd.Timestamp("2024-01-01 23:45", tz="UTC")]            # next print (1 bp) known at 00:00 close
    fng = pd.Series([90, 50], index=pd.to_datetime(["2024-01-01", "2024-01-02"], utc=True))
    g = fear_greed_ok(idx, fng, hi=80)
    assert g[pd.Timestamp("2024-01-01 12:00", tz="UTC")]              # day-1 value not known during day 1
    assert not g[pd.Timestamp("2024-01-02 12:00", tz="UTC")]          # extreme greed of day 1 used on day 2
    assert g[pd.Timestamp("2024-01-03 12:00", tz="UTC")]
