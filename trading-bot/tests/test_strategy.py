from apps.strategy.trend_pullback import long_signal
from tests.helpers import synthetic_15m


def test_no_signal_in_downtrend():
    df = synthetic_15m(n=1200, drift=-0.0008, seed=3)
    hits = [long_signal(df.iloc[:i]) for i in range(400, 1200, 5)]
    assert not any(hits)

def test_signals_are_well_formed_when_they_fire():
    df = synthetic_15m(n=2000, drift=0.0006, seed=11)
    sigs = [s for i in range(300, 2000, 3) if (s := long_signal(df.iloc[:i]))]
    assert sigs, "expected at least one signal in a persistent uptrend"
    for s in sigs:
        assert s["side"] == "long" and s["stop"] < s["entry"] < s["take"]
        assert abs(s["rr"] - 2.0) < 1e-9
