"""make pa-select -> reports/PA_SELECTOR.md: let the bot pick the best book setup each month, then test that.

Input: every trade the book setups would have taken (reports/price_action_trades.csv from `make pa`).
At the start of each month the selector looks ONLY at trades that closed before that month, scores each
candidate by its average R over the trailing window, and trades next month only the top `k` candidates
whose trailing average is above `min_r`. If none qualifies it stays in cash. A candidate is a
(setup, time frame, side) combination, or the same per coin.

This answers "can choosing the recently best strategy turn losing setups into a winning bot?" The
result is out-of-sample by construction; the variants tried are counted for the Deflated Sharpe.
"""
from __future__ import annotations

import argparse
import itertools
import math
from pathlib import Path

import numpy as np
import pandas as pd

from apps.research.metrics import deflated_sharpe

ROOT = Path(__file__).resolve().parents[2]


def select(tr: pd.DataFrame, keys: list[str], lookback_m: int, k: int, min_r: float, min_n: int) -> pd.DataFrame:
    """Trades taken by the selector. tr needs t (entry time), t_close, R and the key columns."""
    tr = tr.copy()
    tr["month"] = tr["t"].dt.tz_localize(None).dt.to_period("M")
    months = sorted(tr["month"].unique())
    taken = []
    for m in months[lookback_m:]:
        start = (m - lookback_m).to_timestamp().tz_localize("UTC")
        now = m.to_timestamp().tz_localize("UTC")
        past = tr[(tr["t"] >= start) & (tr["t_close"] < now)]          # only trades already closed
        score = past.groupby(keys)["R"].agg(["mean", "count"])
        score = score[(score["count"] >= min_n) & (score["mean"] > min_r)].nlargest(k, "mean")
        if score.empty:
            continue
        chosen = tr[tr["month"] == m].merge(score.reset_index()[keys], on=keys)
        taken.append(chosen)
    return pd.concat(taken) if taken else tr.iloc[0:0]


def summarize(name: str, s: pd.DataFrame, months_total: int, risk: float) -> tuple[str, float]:
    if s.empty:
        return f"| {name} | 0 | 0 of {months_total} | | | | |", 0.0
    r = s.sort_values("t")["R"]
    eq = (1 + risk * r).cumprod()
    dd = float(((eq.cummax() - eq) / eq.cummax()).max())
    t = float(r.mean() / r.std() * math.sqrt(len(r))) if len(r) > 1 and r.std() > 0 else 0.0
    monthly = s.groupby("month")["R"].sum() * risk
    return (f"| {name} | {len(r)} | {s['month'].nunique()} of {months_total} | **{r.mean():+.2f}** | {t:+.1f} | "
            f"{eq.iloc[-1] - 1:+.0%} | {dd:.0%} |"), float(monthly.mean() / monthly.std()) if len(monthly) > 1 and monthly.std() > 0 else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--risk", type=float, default=0.005, help="share of the account risked per trade")
    a = ap.parse_args()
    tr = pd.read_csv(ROOT / "reports" / "price_action_trades.csv", parse_dates=["t"])
    if "t_close" not in tr:
        hold = {"1h": pd.Timedelta("48h"), "4h": pd.Timedelta("120h")}
        tr["t_close"] = tr["t"] + tr["tf"].map(hold)                    # upper bound: max holding period
    months_total = tr["t"].dt.tz_localize(None).dt.to_period("M").nunique()

    rows, trials, best = [], [], None
    grids = {
        "setup·tf·side": (["setup", "tf", "side"], [3, 6, 12], [1, 3], [0.0, 0.1], 30),
        "setup·tf·side·coin": (["setup", "tf", "side", "coin"], [6, 12], [3, 10], [0.0, 0.2], 10),
    }
    for gname, (keys, lbs, ks, mins, min_n) in grids.items():
        for lb, k, mr in itertools.product(lbs, ks, mins):
            s = select(tr, keys, lb, k, mr, min_n)
            line, sharpe = summarize(f"{gname}, last {lb}m, top {k}, avg R > {mr}", s, months_total, a.risk)
            rows.append(line)
            trials.append(sharpe)
            if not s.empty and (best is None or s["R"].mean() > best[1]["R"].mean()):
                best = (f"{gname}, last {lb}m, top {k}, avg R > {mr}", s)
    all_line, _ = summarize("everything, no selection", tr.assign(month=tr["t"].dt.tz_localize(None).dt.to_period("M")),
                            months_total, a.risk)
    dsr = 0.0
    if best is not None:
        monthly = best[1].groupby("month")["R"].sum() * a.risk
        dsr = deflated_sharpe(monthly, trials)
    verdict = ("The selector finds an edge that survives counting its tries: paper trade it."
               if best is not None and best[1]["R"].mean() > 0 and dsr > 0.95 else
               "Picking the recently best setup does not turn the book setups into a winning bot: what worked last "
               "months does not keep working next month. The bot should not trade them.")
    head = ("| Selector | Trades | Months active | **Avg R / trade** | t | Return at "
            f"{a.risk:.1%} risk | Max DD |\n|---|---|---|---|---|---|---|")
    md = f"""# Strategy selector over the book setups

Each month: score every candidate on the trades that CLOSED in the trailing window, trade only the top
ones with a positive score, else stay in cash. {len(trials)} selector variants tried. All results are
out-of-sample by construction (a month's choice never sees that month).

{head}
{all_line}
{chr(10).join(rows)}

Best variant by average R: **{best[0] if best else "none"}**. Deflated Sharpe probability (monthly returns,
{len(trials)} variants): **{dsr:.0%}** (want > 95%).

## Verdict

{verdict}
"""
    out = ROOT / "reports" / "PA_SELECTOR.md"
    out.write_text(md)
    print(md)


if __name__ == "__main__":
    main()
