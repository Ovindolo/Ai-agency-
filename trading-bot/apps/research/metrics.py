"""Performance metrics on daily equity, the Deflated Sharpe Ratio, and market-regime labels.

Deflated Sharpe Ratio (Bailey & Lopez de Prado, 2014): the probability that a strategy's true Sharpe
is above zero AFTER accounting for how many strategies were tried to find it, and for fat tails.
Picking the best of N backtests inflates its Sharpe; the DSR raises the bar to the Sharpe the best of
N random strategies would show by luck. DSR > 0.95 is the usual threshold.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

N = NormalDist()
EULER = 0.5772156649
DAYS = 365          # crypto trades every day


def daily(equity: pd.Series) -> pd.Series:
    return equity.resample("1D").last().dropna()


def perf(eq: pd.Series) -> dict:
    """eq: daily equity. Sharpe/Sortino annualized with 365 days, zero risk-free rate."""
    r = eq.pct_change().dropna()
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1 / 365)
    down = r[r < 0]
    dd = float(((eq.cummax() - eq) / eq.cummax()).max()) if len(eq) else 0.0
    total = float(eq.iloc[-1] / eq.iloc[0] - 1) if len(eq) > 1 else 0.0
    cagr = (1 + total) ** (1 / years) - 1 if total > -1 else -1.0
    sharpe = float(r.mean() / r.std() * math.sqrt(DAYS)) if len(r) > 1 and r.std() > 1e-12 else 0.0
    sortino = float(r.mean() / down.std() * math.sqrt(DAYS)) if len(down) > 1 and down.std() > 1e-12 else 0.0
    return {"total": total, "cagr": cagr, "sharpe": sharpe, "sortino": sortino, "max_dd": dd,
            "calmar": cagr / dd if dd > 0 else 0.0}


def deflated_sharpe(returns: pd.Series, trial_sharpes: list[float]) -> float:
    """returns: the chosen strategy's daily returns. trial_sharpes: DAILY (non-annualized) Sharpe of every
    candidate tried, including this one. Returns P(true Sharpe > 0 | N trials)."""
    r = returns.dropna()
    t = len(r)
    if t < 30 or r.std() < 1e-12:
        return 0.0
    sr = r.mean() / r.std()
    n = max(len(trial_sharpes), 1)
    var = float(np.var(trial_sharpes, ddof=1)) if n > 1 else 0.0
    sr0 = math.sqrt(var) * ((1 - EULER) * N.inv_cdf(1 - 1 / n) + EULER * N.inv_cdf(1 - 1 / (n * math.e))) if n > 1 else 0.0
    skew, kurt = float(r.skew()), float(r.kurt()) + 3.0          # pandas kurt is excess
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if denom <= 0:
        return 0.0
    return float(N.cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(denom)))


def regimes(price: pd.Series, lookback: int = 90, band: float = 0.20) -> pd.Series:
    """Label each day by the asset's trailing `lookback`-day return: bull (> +band), bear (< -band),
    sideways otherwise. Uses only past prices."""
    ret = price / price.shift(lookback) - 1
    lab = pd.Series("sideways", index=price.index)
    lab[ret > band] = "bull"
    lab[ret < -band] = "bear"
    lab[ret.isna()] = "unknown"
    return lab


def by_regime(eq: pd.Series, labels: pd.Series) -> dict[str, tuple[int, float]]:
    """Per regime: (days, annualized COMPOUNDED return of the strategy on those days; never below -100%)."""
    r = eq.pct_change().dropna()
    lab = labels.reindex(r.index).fillna("unknown")
    out = {}
    for k in ("bull", "sideways", "bear"):
        x = r[lab == k]
        if len(x):
            out[k] = (int(len(x)), float(np.exp(np.log1p(x.clip(lower=-0.999)).mean() * DAYS) - 1))
    return out
