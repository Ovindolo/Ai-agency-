import re
from dataclasses import replace

from apps.features.snapshot import build_snapshot, resample_1h
from apps.features.words import state_text, to_words
from tests.helpers import synthetic_15m


def snap(**sig):
    return build_snapshot("BTC/USDT", synthetic_15m(), signal=sig or None)


def test_snapshot_uses_only_closed_candles():
    df = synthetic_15m()
    s1 = build_snapshot("BTC/USDT", df)
    # Appending a future candle must not change a snapshot built on the prefix
    s2 = build_snapshot("BTC/USDT", df.iloc[:-1])
    assert s1.ts == df.index[-1].isoformat()
    assert s2.ts == df.index[-2].isoformat()
    assert s1 != s2


def test_1h_resample_drops_incomplete_hours():
    df = synthetic_15m(n=401)          # 100 hours + one extra 15m bar
    h = resample_1h(df)
    assert len(h) == 100


def test_state_has_no_digits_and_is_short():
    text = state_text(snap(side="long", rr=2.0, stop_pct=0.02, take_pct=0.04))
    assert not re.search(r"\d", text), text          # Jev never sees a number
    assert len(text.split()) == 14


def test_word_thresholds_are_directional():
    s = snap()
    assert "violent" in to_words(replace(s, atr_pct=0.05))
    assert "calm" in to_words(replace(s, atr_pct=0.001))
    assert "wide_spread" in to_words(replace(s, spread_bps=20))
    assert "thin_book" in to_words(replace(s, depth_usd_l1=1000))
    assert "pumping" in to_words(replace(s, return_15m=0.02))
    assert "dumping" in to_words(replace(s, return_15m=-0.02))
    assert "signal_long_pullback" in to_words(replace(s, strategy_side="long", strategy_rr=3.0))
    assert "rr_good" in to_words(replace(s, strategy_side="long", strategy_rr=3.0))
    assert "long_losing" in to_words(replace(s, inventory_usd=50, unrealized_pnl_pct=-0.01))
