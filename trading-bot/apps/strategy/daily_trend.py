"""Daily trend core: hold the coin while its N-day return is positive, stay in cash otherwise.

Why it exists: the best-documented crypto effect is time-series momentum on DAILY data (20-65 day
lookbacks; e.g. Le & Ruthbah, Monash; Man Group "In crypto we trend"). The documented benefit is mostly
LOWER DRAWDOWNS, often with lower total return than buy-and-hold after costs. It trades a few times a
year, so fees barely matter - the opposite of a 15m bot.

Rules (spot, long or cash, no leverage):
  signal at the close of day d  ->  trade at the open of day d+1, taker fee + slippage
  weight = min(1, target_vol / realized_vol_20d) while momentum is up (volatility targeting), else 0
  rebalance only if the weight moves by more than `band` (avoids paying fees for noise)

Compared against buy-and-hold and weekly DCA over the same days. This is research code; the paper
runner does not trade it yet.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DailyTrendParams:
    lookback: int = 20
    target_vol: float = 0.60          # annualized; BTC realized vol is usually 40-80%
    vol_window: int = 20
    band: float = 0.20                # rebalance only if |w_new - w_now| > band, or on a 0 <-> >0 switch
    fee_pct: float = 0.001
    slippage_pct: float = 0.0008


@dataclass
class DailyResult:
    label: str
    equity: pd.Series
    trades: int = 0
    fees: float = 0.0

    @property
    def total_return(self) -> float:
        return float(self.equity.iloc[-1] / self.equity.iloc[0] - 1)

    @property
    def max_dd(self) -> float:
        e = self.equity
        return float(((e.cummax() - e) / e.cummax()).max())

    @property
    def cagr(self) -> float:
        years = (self.equity.index[-1] - self.equity.index[0]).days / 365.25
        return float((self.equity.iloc[-1] / self.equity.iloc[0]) ** (1 / years) - 1) if years > 0 else 0.0

    @property
    def sharpe(self) -> float:
        r = self.equity.pct_change().dropna()
        return float(r.mean() / r.std() * np.sqrt(365)) if r.std() > 0 else 0.0


def target_weights(daily: pd.DataFrame, p: DailyTrendParams) -> pd.Series:
    """Weight decided at the close of each day (uses that day's close and earlier only)."""
    c = daily["close"]
    up = c > c.shift(p.lookback)
    vol = c.pct_change().rolling(p.vol_window).std() * np.sqrt(365)
    w = (p.target_vol / vol).clip(upper=1.0).where(up, 0.0)
    return w.fillna(0.0)


def run_daily_trend(daily: pd.DataFrame, p: DailyTrendParams = DailyTrendParams(), start_equity: float = 500.0) -> DailyResult:
    w_target = target_weights(daily, p).to_numpy()
    o, c = daily["open"].to_numpy(), daily["close"].to_numpy()
    cash, units, w_now = start_equity, 0.0, 0.0
    trades, fees = 0, 0.0
    eq = np.empty(len(daily))
    for d in range(len(daily)):
        if d > 0:                                          # act at today's open on yesterday's decision
            want = w_target[d - 1]
            value = cash + units * o[d]
            switch = (want == 0) != (w_now == 0)
            if switch or abs(want - w_now) > p.band:
                delta_usd = want * value - units * o[d]
                px = o[d] * (1 + p.slippage_pct if delta_usd > 0 else 1 - p.slippage_pct)
                fee = abs(delta_usd) * p.fee_pct
                units += delta_usd / px
                cash -= delta_usd + fee
                fees += fee
                trades += 1
                w_now = want
        eq[d] = cash + units * c[d]
    return DailyResult(f"trend {p.lookback}z", pd.Series(eq, index=daily.index), trades, fees)


def buy_and_hold(daily: pd.DataFrame, start_equity: float = 500.0, fee_pct: float = 0.001) -> DailyResult:
    units = start_equity * (1 - fee_pct) / daily["open"].iloc[0]
    return DailyResult("buy & hold", units * daily["close"], 1, start_equity * fee_pct)


def weekly_dca(daily: pd.DataFrame, start_equity: float = 500.0, fee_pct: float = 0.001) -> DailyResult:
    """Same 500 spread evenly over the period, bought every 7 days. Uninvested cash waits."""
    buys = list(range(0, len(daily), 7))
    per = start_equity / len(buys)
    cash, units, fees = start_equity, 0.0, 0.0
    eq = np.empty(len(daily))
    o, c = daily["open"].to_numpy(), daily["close"].to_numpy()
    for d in range(len(daily)):
        if d in buys:
            fee = per * fee_pct
            units += (per - fee) / o[d]
            cash -= per
            fees += fee
        eq[d] = cash + units * c[d]
    return DailyResult("DCA săptămânal", pd.Series(eq, index=daily.index), len(buys), fees)


def compare(daily: pd.DataFrame, lookbacks=(20, 60), start_equity: float = 500.0) -> list[DailyResult]:
    out = [run_daily_trend(daily, DailyTrendParams(lookback=n), start_equity) for n in lookbacks]
    return out + [buy_and_hold(daily, start_equity), weekly_dca(daily, start_equity)]


def table(results: list[DailyResult]) -> str:
    rows = ["| Strategie | Randament | CAGR | Max drawdown | Sharpe | Tranzacții | Taxe |", "|---|---|---|---|---|---|---|"]
    rows += [f"| {r.label} | {r.total_return:+.1%} | {r.cagr:+.1%} | {r.max_dd:.1%} | {r.sharpe:.2f} | {r.trades} | {r.fees:.2f} |"
             for r in results]
    return "\n".join(rows)


def load_daily(symbol: str, exchange: str = "binance", years: int = 6, refresh: bool = False) -> pd.DataFrame:
    """Daily candles from the exchange's public API (no key), cached in data/."""
    from apps.backtest.data import csv_path, download
    path = csv_path(symbol, "1d")
    if refresh or not path.exists():
        download(symbol, exchange, tf="1d", days=int(years * 365))
    raw = pd.read_csv(path)
    raw.index = pd.DatetimeIndex(pd.to_datetime(raw.pop("ts"), unit="ms", utc=True))
    return raw.sort_index()


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Daily trend core vs buy-and-hold vs weekly DCA")
    ap.add_argument("--symbols", default="BTC/USDT,ETH/USDT")
    ap.add_argument("--exchange", default="binance")
    ap.add_argument("--years", type=int, default=6)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    for sym in a.symbols.split(","):
        daily = load_daily(sym, a.exchange, a.years, a.refresh)
        half = len(daily) // 2
        print(f"\n## {sym} · {daily.index[0]:%Y-%m-%d} → {daily.index[-1]:%Y-%m-%d}\n")
        print(table(compare(daily)))
        print(f"\nPrima jumătate ({daily.index[0]:%Y-%m} → {daily.index[half]:%Y-%m}):\n")
        print(table(compare(daily.iloc[:half])))
        print(f"\nA doua jumătate ({daily.index[half]:%Y-%m} → {daily.index[-1]:%Y-%m}):\n")
        print(table(compare(daily.iloc[half:])))


if __name__ == "__main__":
    main()
