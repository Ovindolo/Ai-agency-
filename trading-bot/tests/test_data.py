import pandas as pd
import pytest

from apps.backtest import data
from apps.backtest.data import BadData, to_ms, validate_15m
from tests.helpers import synthetic_15m


def roundtrip(tmp_path, monkeypatch, df, ts):
    monkeypatch.setattr(data, "DATA_DIR", tmp_path)
    out = df.reset_index(drop=True)
    out.insert(0, "ts", ts.to_numpy())
    out.to_csv(data.csv_path("BTC/USDT"), index=False)
    return data.load("BTC/USDT")


def test_ms_roundtrip_is_exact(tmp_path, monkeypatch):
    df = synthetic_15m(n=500)
    back = roundtrip(tmp_path, monkeypatch, df, to_ms(df.index))
    assert (back.index == df.index).all()


def test_seconds_instead_of_ms_is_rejected_loudly(tmp_path, monkeypatch):
    df = synthetic_15m(n=500)
    with pytest.raises(BadData, match="wrong unit"):
        roundtrip(tmp_path, monkeypatch, df, to_ms(df.index) // 1000)


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d.iloc[::2], "spacing"),
    (lambda d: pd.concat([d, d.iloc[:3]]), "unique"),
    (lambda d: d.assign(high=d["low"] - 1), "impossible"),
    (lambda d: d.drop(columns="volume"), "missing"),
])
def test_bad_candles_rejected(mutate, msg):
    with pytest.raises(BadData, match=msg):
        validate_15m(mutate(synthetic_15m(n=300)))
