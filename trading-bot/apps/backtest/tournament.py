"""Strategy tournament with an out-of-sample holdout.

Testing many strategies and keeping the best one is the fastest way to fool yourself: with enough
candidates, some pass any gate by luck. So every candidate is scored on the first part of the data
(in-sample) and ONLY the ones that pass are re-run on the untouched later part (out-of-sample).
A strategy that does not survive out-of-sample is noise, however good it looked.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from apps.backtest.engine import Report, run_backtest
from apps.strategy.trend_pullback import StrategyParams

BARS_PER_YEAR = 35_040
MIN_TRADES_PER_YEAR = 80


@dataclass
class Result:
    name: str
    is_rep: Report
    oos_rep: Report | None = None

    @property
    def passed_is(self) -> bool: return self.is_rep.passed
    @property
    def passed_oos(self) -> bool: return bool(self.oos_rep and self.oos_rep.passed)


def split(df: pd.DataFrame, is_frac: float = 0.6) -> tuple[pd.DataFrame, pd.DataFrame]:
    cut = int(len(df) * is_frac)
    return df.iloc[:cut], df.iloc[cut:]


Candidate = StrategyParams | pd.DataFrame     # built-in params, or a full-history signal frame


def _run(df: pd.DataFrame, symbol: str, label: str, cand: Candidate, start_equity: float) -> Report:
    if isinstance(cand, pd.DataFrame):
        # Valid only for lookahead-free candidates: a value at bar j depends on data <= j,
        # so slicing a full-history frame equals recomputing it on the slice.
        return run_backtest(df, symbol, label=label, signal_frame=cand.loc[df.index], start_equity=start_equity)
    return run_backtest(df, symbol, label=label, params=cand, start_equity=start_equity)


def run_tournament(df: pd.DataFrame, symbol: str, candidates: dict[str, Candidate],
                   *, is_frac: float = 0.6, start_equity: float = 500.0) -> list[Result]:
    is_df, oos_df = split(df, is_frac)
    min_is = round(MIN_TRADES_PER_YEAR * len(is_df) / BARS_PER_YEAR)
    min_oos = round(MIN_TRADES_PER_YEAR * len(oos_df) / BARS_PER_YEAR)
    results: list[Result] = []
    for name, cand in candidates.items():
        rep = _run(is_df, symbol, f"{name} · in-sample", cand, start_equity)
        rep.min_trades = min_is
        results.append(Result(name, rep))
    for r in results:
        if r.passed_is:
            rep = _run(oos_df, symbol, f"{r.name} · out-of-sample", candidates[r.name], start_equity)
            rep.min_trades = min_oos
            r.oos_rep = rep
    return results


def summary(results: list[Result]) -> str:
    n = len(results)
    passed_is = [r for r in results if r.passed_is]
    passed_oos = [r for r in passed_is if r.passed_oos]
    best = max(results, key=lambda r: r.is_rep.profit_factor if r.is_rep.n else 0)
    lines = [
        f"Candidates tested:            {n}",
        f"Passed in-sample gates:       {len(passed_is)}",
        f"Survived out-of-sample:       {len(passed_oos)}",
        f"Best in-sample:               {best.name}  PF {best.is_rep.profit_factor:.2f}  "
        f"net {best.is_rep.net:+.2f}  trades {best.is_rep.n}",
    ]
    if best.oos_rep:
        lines.append(f"  same strategy out-of-sample: PF {best.oos_rep.profit_factor:.2f}  "
                     f"net {best.oos_rep.net:+.2f}  trades {best.oos_rep.n}  -> {'PASS' if best.oos_rep.passed else 'FAIL'}")
    return "\n".join(lines)


def param_grid() -> dict[str, StrategyParams]:
    out = {}
    for adx_min in (15, 20, 25, 30):
        for mult in (1.0, 1.5, 2.0, 2.5):
            for rr in (1.8, 2.2, 2.6, 3.0):
                for vm in (0.8, 1.0, 1.3):
                    out[f"adx{adx_min}_atr{mult}_rr{rr}_vol{vm}"] = StrategyParams(
                        adx_min=adx_min, stop_atr_mult=mult, target_rr=rr, volume_mult=vm)
    return out
