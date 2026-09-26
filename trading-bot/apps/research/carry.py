"""Funding carry (cash-and-carry): long spot + short the same amount of perpetual. Price moves cancel;
the position collects funding while longs pay shorts. Peer-reviewed: Schmeling, Schrimpf & Todorov,
"Crypto Carry" (BIS WP 1087, 2023; Management Science 2026): mean carry about 8% a year for BTC.

It does NOT multiply money. It is the closest thing crypto has to a yield that does not depend on
guessing direction, and it has shrunk: a public walk-forward (github.com/zwmjj/funding-rate-arb)
stopped trading in Dec 2024 because funding fell below its entry threshold.

Risks the backtest cannot show: exchange failure (both legs on one venue), auto-deleveraging of the
profitable short in a crash (10 Oct 2025: ADL closed winning positions, leaving hedges open),
stablecoin depeg, funding flipping negative for weeks.

Rules: enter when the average of the last `lookback` funding prints > enter_bp, exit when < exit_bp.
Capital = spot notional + short margin (notional / perp_leverage). Four taker fills per round trip.

  python -m apps.research.carry --symbol BTC/USDT:USDT      # needs internet (public endpoint, no key)
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class CarryParams:
    enter_bp: float = 1.0             # per funding interval, basis points
    exit_bp: float = 0.5
    lookback: int = 3
    fee_pct: float = 0.001            # worst leg: spot taker 0.10%; perp taker is 0.05% (conservative)
    perp_leverage: float = 3.0        # short margin = notional / 3; the spot leg is fully paid
    cash_rate: float = 0.04           # what the same dollars earn doing nothing risky (T-bills / savings)


@dataclass
class CarryResult:
    equity: pd.Series
    trades: int
    days_in: float
    fees: float

    @property
    def years(self) -> float:
        return max((self.equity.index[-1] - self.equity.index[0]).days / 365.25, 1e-9)

    @property
    def apr(self) -> float:
        return float((self.equity.iloc[-1] / self.equity.iloc[0]) ** (1 / self.years) - 1)


def run_carry(funding: pd.Series, p: CarryParams = CarryParams(), start: float = 500.0) -> CarryResult:
    """funding: rate per interval (e.g. 0.0001 = 1 bp), indexed by settlement time."""
    f = funding.sort_index().astype(float)
    signal = f.rolling(p.lookback).mean() * 1e4                  # bp, known after each settlement
    capital = start
    notional_share = 1 / (1 + 1 / p.perp_leverage)                 # spot + margin must fit in capital
    inside, trades, fees, t_in = False, 0, 0.0, 0.0
    eq = []
    prev_t = None
    for t, rate in f.items():
        if inside:
            capital += capital * notional_share * rate              # this settlement is paid to the short
            t_in += ((t - prev_t).total_seconds() / 86400) if prev_t is not None else 0
        s = signal.loc[t]
        if not inside and s == s and s > p.enter_bp:
            cost = capital * notional_share * 2 * p.fee_pct         # buy spot + sell perp
            capital -= cost
            fees += cost
            inside, trades = True, trades + 1
        elif inside and s == s and s < p.exit_bp:
            cost = capital * notional_share * 2 * p.fee_pct
            capital -= cost
            fees += cost
            inside = False
        eq.append(capital)
        prev_t = t
    return CarryResult(pd.Series(eq, index=f.index), trades, t_in, fees)


def fetch_funding(symbol: str, years: float = 6, exchange: str = "binanceusdm") -> pd.Series:
    import ccxt
    ex = getattr(ccxt, exchange)({"enableRateLimit": True})
    since = ex.milliseconds() - int(years * 365 * 86_400_000)
    out: dict = {}
    while True:
        batch = ex.fetch_funding_rate_history(symbol, since=since, limit=1000)
        if not batch:
            break
        for x in batch:
            out[pd.Timestamp(x["timestamp"], unit="ms", tz="UTC")] = x["fundingRate"]
        since = batch[-1]["timestamp"] + 1
        if len(batch) < 1000:
            break
    return pd.Series(out, dtype=float).sort_index()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTC/USDT:USDT")
    ap.add_argument("--years", type=float, default=6)
    a = ap.parse_args()
    f = fetch_funding(a.symbol, a.years)
    p = CarryParams()
    print(f"## Funding carry {a.symbol} · {f.index[0]:%Y-%m-%d} → {f.index[-1]:%Y-%m-%d}\n")
    print("| Perioadă | APR carry | APR fără risc (presupus) | Carry peste cash | Tranzacții | Zile în poziție |")
    print("|---|---|---|---|---|---|")
    for label, part in (("tot", f), *((str(y), f[f.index.year == y]) for y in sorted(set(f.index.year)))):
        if len(part) < 30:
            continue
        r = run_carry(part, p)
        print(f"| {label} | {r.apr:+.1%} | {p.cash_rate:.1%} | {r.apr - p.cash_rate:+.1%} | {r.trades} | {r.days_in:.0f} |")


if __name__ == "__main__":
    main()
