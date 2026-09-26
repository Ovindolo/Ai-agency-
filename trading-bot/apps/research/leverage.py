"""How much leverage actually multiplies money? Monte Carlo on REAL daily candles.

Leverage multiplies the average return by L but the variance by L^2, and compounding punishes variance:
long-run growth ~ L*mu - (L*sigma)^2 / 2. Past the growth-optimal (Kelly) leverage L* = mu / sigma^2,
more leverage makes the MEDIAN outcome worse, long before liquidation risk is even counted.

Simulation (constant leverage, rebalanced daily, like a leveraged ETF or a trader who keeps size in
proportion to the account):
  - one year paths built by block-bootstrapping real days (blocks keep crashes and streaks together)
  - each day: if the intraday low moves against the position by (1/L - maintenance margin), the account
    is liquidated (0); otherwise equity *= 1 + L * (close/open - 1) - costs
  - costs: funding 0.01%/8h on the leveraged notional, taker fee on the rebalancing turnover

  python -m apps.research.leverage --symbol BTC/USDT            # uses data/BTCUSDT_1d.csv (make daily)
  python -m apps.research.leverage --symbol BTC/USDT --short     # the same for shorts
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd

LEVERAGES = (1, 2, 3, 5, 10, 20, 50)


@dataclass(frozen=True)
class SimParams:
    days: int = 365
    paths: int = 4000
    block: int = 10
    mmr: float = 0.005
    funding_8h: float = 0.0001
    fee_pct: float = 0.0005
    seed: int = 7


def day_moves(daily: pd.DataFrame, short: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """(close/open - 1, worst intraday move against the position) for each real day."""
    o, h, l, c = (daily[k].to_numpy(dtype=float) for k in ("open", "high", "low", "close"))
    ret = c / o - 1
    worst = (h / o - 1) if short else (l / o - 1)
    return (-ret, -worst) if short else (ret, worst)


def kelly_leverage(ret: np.ndarray) -> float:
    return float(np.mean(ret) / np.var(ret)) if np.var(ret) > 0 else 0.0


def simulate(ret: np.ndarray, worst: np.ndarray, lev: float, p: SimParams = SimParams()) -> np.ndarray:
    """Final equity multiple for each path (0 = liquidated)."""
    rng = np.random.default_rng(p.seed)
    n = len(ret)
    starts = rng.integers(0, n - p.block, size=(p.paths, p.days // p.block + 1))
    idx = (starts[:, :, None] + np.arange(p.block)).reshape(p.paths, -1)[:, :p.days]
    r, w = ret[idx], worst[idx]
    liq = lev * np.abs(np.minimum(w, 0)) >= (1 - lev * p.mmr)       # adverse move ate the margin
    daily = 1 + lev * r - lev * 3 * p.funding_8h - lev * np.abs(r) * p.fee_pct
    daily = np.where(liq, 0.0, np.maximum(daily, 0.0))
    return np.prod(daily, axis=1)


def table(ret: np.ndarray, worst: np.ndarray, p: SimParams = SimParams(), start: float = 500.0) -> str:
    rows = ["| Levier | Median după 1 an | Medie | Lichidat (0) | Pierde ≥50% | ≥2× | ≥5× | ≥10× |",
            "|---|---|---|---|---|---|---|---|"]
    for lev in LEVERAGES:
        m = simulate(ret, worst, lev, p)
        rows.append(f"| {lev}× | {start * np.median(m):,.0f} | {start * m.mean():,.0f} | {np.mean(m == 0):.0%} | "
                    f"{np.mean(m <= 0.5):.0%} | {np.mean(m >= 2):.0%} | {np.mean(m >= 5):.0%} | {np.mean(m >= 10):.0%} |")
    return "\n".join(rows)


def main() -> None:
    from apps.strategy.daily_trend import load_daily
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--short", action="store_true")
    ap.add_argument("--years", type=int, default=6)
    a = ap.parse_args()
    daily = load_daily(a.symbol, years=a.years)
    ret, worst = day_moves(daily, a.short)
    k = kelly_leverage(ret)
    side = "short" if a.short else "long"
    print(f"## {a.symbol} {side} · {daily.index[0]:%Y-%m-%d} → {daily.index[-1]:%Y-%m-%d} · {len(daily)} zile reale\n")
    print(f"Levierul care maximizează creșterea pe termen lung (Kelly) pe istoric: {k:.2f}×  "
          f"(jumătate de Kelly, uzual în practică: {k / 2:.2f}×). Istoricul viitor nu va fi același.\n")
    print(table(ret, worst))
    print("\nMedia e trasă în sus de câteva căi norocoase; mediana e ce pățește un om obișnuit.")


if __name__ == "__main__":
    main()
