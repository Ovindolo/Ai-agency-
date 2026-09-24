"""make tournament -> reports/TOURNAMENT_<SYMBOL>.md

Imports every strategy from a cloned freqtrade-strategies repo, rejects anything with lookahead,
adds the built-in strategy, and runs an in-sample / out-of-sample tournament. Only candidates that
pass on data they were never selected on are reported as survivors.
"""
from __future__ import annotations

import argparse
import logging
import warnings
from pathlib import Path

from apps.backtest.data import load
from apps.backtest.tournament import run_tournament
from apps.strategy.freqtrade_adapter import import_strategy, signal_frame
from apps.strategy.trend_pullback import StrategyParams

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    warnings.filterwarnings("ignore")
    logging.disable(logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT / "vendor" / "freqtrade-strategies" / "user_data" / "strategies"))
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--equity", type=float, default=500.0)
    a = ap.parse_args()

    df = load(a.symbol)
    census, candidates = [], {"built_in_trend_pullback": StrategyParams()}
    for f in sorted(Path(a.repo).rglob("*.py")):
        if "futures" in f.parts:
            continue
        for imp in import_strategy(f, df):
            census.append(imp)
            if imp.usable:
                candidates[imp.name] = signal_frame(imp.entries, df)

    results = run_tournament(df, a.symbol, candidates, start_equity=a.equity)
    n = len(results)
    passed_is = [r for r in results if r.passed_is]
    survivors = [r for r in passed_is if r.passed_oos]
    rows = []
    # Rank by sample size first: a 1-trade "PF inf" is the purest selection-bias fluke there is.
    def rank(r):
        enough = r.is_rep.n >= r.is_rep.min_trades
        pf = r.is_rep.profit_factor if r.is_rep.n else 0.0
        return (enough, min(pf, 99.0))
    for r in sorted(results, key=rank, reverse=True):
        o = r.oos_rep
        rows.append(f"| {r.name} | {r.is_rep.n} | {r.is_rep.profit_factor:.2f} | {r.is_rep.net:+.2f} | "
                    f"{'PASS' if r.passed_is else '—'} | "
                    f"{(f'{o.n} / PF {o.profit_factor:.2f} / {o.net:+.2f}') if o else '—'} | "
                    f"{'**SURVIVOR**' if r.passed_oos else ''} |")
    rejected = "\\n".join(f"| {c.name} | {c.status} | {c.detail[:80]} |" for c in census if not c.usable)
    expected_lucky = 0.05 * n
    md = f"""# Tournament — {a.symbol}

Data: {df.index[0]:%Y-%m-%d} → {df.index[-1]:%Y-%m-%d}, {len(df)} candles (15m).
In-sample: first 60%. Out-of-sample: last 40%, never used for selection.
Every candidate exits through the same stops, targets, fees and risk engine.

| | |
|---|---|
| Candidates tested | {n} |
| Passed in-sample | {len(passed_is)} |
| **Survived out-of-sample** | **{len(survivors)}** |
| Expected lucky passes at 5% | ~{expected_lucky:.1f} |

> If survivors are no more numerous than lucky passes, treat every survivor as unproven. A survivor
> earns paper trading, not money.

| Strategy | IS trades | IS PF | IS net | IS | OOS trades / PF / net | Result |
|---|---|---|---|---|---|---|
{chr(10).join(rows)}

## Not admitted

| Strategy | Reason | Detail |
|---|---|---|
{rejected}
"""
    out = ROOT / "reports" / f"TOURNAMENT_{a.symbol.replace('/', '')}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(md)
    print(f"{n} tested, {len(passed_is)} passed in-sample, {len(survivors)} survived out-of-sample -> {out}")


if __name__ == "__main__":
    main()
