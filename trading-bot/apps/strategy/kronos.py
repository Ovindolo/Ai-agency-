"""Kronos (shiyu-coder/Kronos, AAAI 2026) as a tournament candidate.

Kronos forecasts the next candles from the last `lookback` closed ones. Here it only proposes entries:
it fires when most sampled paths end above the current close by more than the round-trip cost. Exits
go through the same stops/targets/risk engine as every other candidate (signal_frame).

Honesty rules this file enforces:
  - A forecast made at bar i sees bars <= i only, and its sampling seed comes from bar i's timestamp,
    so the frame is identical whether built on a slice or on full history (frame_leaks checks it).
  - Kronos was pre-trained on 45 exchanges up to June 2024 (paper, appendix D). Any period it has seen is
    worthless as a test, so the evaluation starts at `since`: 2025-09 by default, 2024-07 at the earliest.
  - The model call is slow on CPU, so forecasts are cached per decision bar and a rerun resumes.
"""
from __future__ import annotations

import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "vendor" / "Kronos"

# window (lookback rows of OHLCV), future 15m stamps, number of paths, seed -> closes, shape (paths, horizon)
Forecaster = Callable[[pd.DataFrame, pd.DatetimeIndex, int, int], np.ndarray]
COLS = ["pred_ret", "up_frac", "pred_std"]


@dataclass(frozen=True)
class KronosParams:
    lookback: int = 400          # Kronos-small/base context is 512 tokens
    horizon: int = 8             # 2h ahead on 15m bars; the operator holds a few hours
    every: int = 4               # decide once per hour, hold the flag off in between
    paths: int = 8               # sampled futures per decision
    min_ret: float = 0.004       # mean predicted move must beat ~0.25% round trip plus margin
    min_up: float = 0.75         # share of paths that must end higher

    def key(self) -> str:
        return f"lb{self.lookback}_h{self.horizon}_e{self.every}_p{self.paths}"


def seed_for(ts: pd.Timestamp) -> int:
    return zlib.crc32(ts.isoformat().encode())


def forecast_frame(df15: pd.DataFrame, forecaster: Forecaster, p: KronosParams = KronosParams(),
                   cache: Path | None = None, since: pd.Timestamp | None = None,
                   progress: bool = False) -> pd.DataFrame:
    """On decision bars (NaN elsewhere): pred_ret, the mean predicted return to the horizon; up_frac, the
    share of paths ending higher; pred_std, the spread of path returns (Kronos' own volatility forecast)."""
    done = pd.DataFrame(columns=COLS, dtype=float)
    if cache and cache.exists():
        old = pd.read_csv(cache, index_col=0)
        if list(old.columns) == COLS:                       # a cache from an older layout is ignored
            done = old
            done.index = pd.DatetimeIndex(pd.to_datetime(done.index, utc=True))
    step = pd.Timedelta("15min")
    todo = [i for i in range(p.lookback - 1, len(df15), p.every)
            if (since is None or df15.index[i] >= since) and df15.index[i] not in done.index]
    rows = []
    for n, i in enumerate(todo):
        t = df15.index[i]
        window = df15.iloc[i - p.lookback + 1:i + 1]
        future = pd.date_range(t + step, periods=p.horizon, freq=step)
        closes = np.asarray(forecaster(window, future, p.paths, seed_for(t)), dtype=float)
        rets = closes[:, -1] / df15["close"].iat[i] - 1
        rows.append((t, float(rets.mean()), float((rets > 0).mean()), float(rets.std())))
        if cache and (len(rows) % 50 == 0 or n == len(todo) - 1):
            done = pd.concat([done, pd.DataFrame(rows, columns=["t", *COLS]).set_index("t")])
            rows = []
            cache.parent.mkdir(exist_ok=True)
            done.sort_index().to_csv(cache)
        if progress and n % 50 == 0:
            print(f"  kronos {n + 1}/{len(todo)}  {t:%Y-%m-%d %H:%M}", flush=True)
    if rows:
        done = pd.concat([done, pd.DataFrame(rows, columns=["t", *COLS]).set_index("t")])
    return done.sort_index().reindex(df15.index)


def entries(fc: pd.DataFrame, p: KronosParams = KronosParams()) -> pd.Series:
    return ((fc["pred_ret"] > p.min_ret) & (fc["up_frac"] >= p.min_up)).fillna(False).astype(bool)


def skill(fc: pd.DataFrame, df15: pd.DataFrame, horizon: int) -> dict[str, float]:
    """Forecast quality before any trading rule: does the predicted direction match what happened?"""
    realized = df15["close"].shift(-horizon) / df15["close"] - 1
    both = pd.DataFrame({"pred": fc["pred_ret"], "real": realized}).dropna()
    if both.empty:
        return {"n": 0, "hit_rate": float("nan"), "ic": float("nan"), "base_up": float("nan")}
    return {
        "n": len(both),
        "hit_rate": float((np.sign(both["pred"]) == np.sign(both["real"])).mean()),
        "ic": float(both["pred"].rank().corr(both["real"].rank())),       # Spearman without scipy; 0 = no skill
        "base_up": float((both["real"] > 0).mean()),                      # hit rate of "always up"
    }


def vol_skill(fc: pd.DataFrame, df15: pd.DataFrame, horizon: int, trailing: int = 96) -> dict[str, float]:
    """Does Kronos' path spread rank the size of the coming move better than plain trailing volatility?
    Rank IC against |realized return|; the baseline is the std of the last `trailing` 15m returns."""
    move = (df15["close"].shift(-horizon) / df15["close"] - 1).abs()
    base = np.log(df15["close"]).diff().rolling(trailing).std()
    both = pd.DataFrame({"kronos": fc["pred_std"], "trailing": base, "move": move}).dropna()
    if both.empty:
        return {"n": 0, "ic_kronos": float("nan"), "ic_trailing": float("nan"), "ic_blend": float("nan")}
    r = both.rank()
    return {
        "n": len(both),
        "ic_kronos": float(r["kronos"].corr(r["move"])),
        "ic_trailing": float(r["trailing"].corr(r["move"])),
        "ic_blend": float(((r["kronos"] + r["trailing"]) / 2).corr(r["move"])),   # equal-weight, as in the TSFM vol study
    }


def kronos_forecaster(model: str = "NeoQuasar/Kronos-small", tokenizer: str = "NeoQuasar/Kronos-Tokenizer-base",
                      device: str | None = None, max_context: int = 512) -> Forecaster:
    """The real model. Needs `make kronos-setup` (clones the repo into vendor/, installs torch)."""
    if not VENDOR.exists():
        raise SystemExit("vendor/Kronos missing: run `make kronos-setup` first")
    sys.path.insert(0, str(VENDOR))
    import torch
    from model import Kronos, KronosPredictor, KronosTokenizer

    pred = KronosPredictor(Kronos.from_pretrained(model), KronosTokenizer.from_pretrained(tokenizer),
                           device=device, max_context=max_context)     # None: cuda, then mps, then cpu

    def forecast(window: pd.DataFrame, future: pd.DatetimeIndex, paths: int, seed: int) -> np.ndarray:
        torch.manual_seed(seed)
        x = window[["open", "high", "low", "close", "volume"]].reset_index(drop=True)
        xt = pd.Series(window.index.tz_convert(None))
        yt = pd.Series(future.tz_convert(None))
        # predict_batch keeps every path separate; predict() would average them into one
        out = pred.predict_batch([x] * paths, [xt] * paths, [yt] * paths, pred_len=len(future),
                                 T=1.0, top_p=0.9, sample_count=1, verbose=False)
        return np.stack([o["close"].to_numpy() for o in out])

    return forecast
