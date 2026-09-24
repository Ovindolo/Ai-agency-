import numpy as np
import pandas as pd


def synthetic_15m(n: int = 800, drift: float = 0.0004, vol: float = 0.004, seed: int = 7, start: float = 100.0) -> pd.DataFrame:
    """Random-walk OHLCV on a UTC 15m index. drift>0 gives an uptrend. Deterministic per seed."""
    rng = np.random.default_rng(seed)
    rets = drift + vol * rng.standard_normal(n)
    close = start * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start], close[:-1]])
    spread = np.abs(vol * rng.standard_normal(n)) * close
    high = np.maximum(open_, close) + spread / 2
    low = np.minimum(open_, close) - spread / 2
    volume = 1000 * (1 + 0.3 * rng.standard_normal(n)).clip(0.2)
    idx = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume,
                         "taker_buy_volume": volume * 0.5}, index=idx)
