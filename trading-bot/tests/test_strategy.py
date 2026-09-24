import pandas as pd

from apps.risk.engine import RiskLimits
from apps.strategy.trend_pullback import StrategyParams, indicators, long_signal
from tests.helpers import synthetic_15m


def test_stop_band_matches_risk_config():
    p, r = StrategyParams(), RiskLimits.load()
    assert (p.stop_min_pct, p.stop_max_pct) == (r.stop_min_pct, r.stop_max_pct)


def test_signals_always_pass_the_risk_rr_gate():
    """Regression: a 15m-ATR stop widened by risk used to push R:R below 1.8 on every signal."""
    df = synthetic_15m(n=6000, drift=0.0004, seed=11)
    ind = indicators(df)
    sig = ind[ind["signal"]]
    assert len(sig) > 0
    rr = (sig["take"] - sig["entry"]) / (sig["entry"] - sig["stop"])
    assert (rr >= RiskLimits().min_reward_risk).all()
    assert (sig["stop_pct"] >= 0.015 - 1e-12).all() and (sig["stop_pct"] <= 0.025 + 1e-12).all()


def test_no_signal_in_downtrend():
    df = synthetic_15m(n=3000, drift=-0.0008, seed=3)
    assert not indicators(df)["signal"].any()


def test_incomplete_hour_never_used():
    """The 1h columns for a bar must equal those computed with all later data removed."""
    df = synthetic_15m(n=3000, drift=0.0004, seed=11)
    full = indicators(df)
    for i in (1203, 1500, 2222, 2999):          # includes bars in the middle of an hour
        prefix = indicators(df.iloc[: i + 1])
        assert bool(full["signal"].iloc[i]) == bool(prefix["signal"].iloc[-1])
        assert abs(full["stop_pct"].iloc[i] - prefix["stop_pct"].iloc[-1]) < 1e-12


def test_future_bars_cannot_change_past_signals():
    df = synthetic_15m(n=3000, drift=0.0004, seed=11)
    a = indicators(df.iloc[:2000])["signal"]
    tampered = df.copy()
    tampered.iloc[2000:, :] = tampered.iloc[2000:, :] * 5          # wreck the future
    b = indicators(tampered).iloc[:2000]["signal"]
    assert a.equals(b)


def test_live_function_matches_vectorized_last_row():
    df = synthetic_15m(n=4000, drift=0.0004, seed=11)
    ind = indicators(df)
    for i in ind.index[ind["signal"]][:5]:
        pos = df.index.get_loc(i)
        assert long_signal(df.iloc[: pos + 1]) is not None
