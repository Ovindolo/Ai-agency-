"""make model -> reports/MODEL.md: does our own cross-sectional model beat simple rules after costs?

Every prediction is out-of-sample: the model is retrained every `retrain` days on rows whose label was
fully known before that day (purge = horizon), then predicts the following days. Hyperparameters are
fixed in advance, not tuned on the test. The portfolio holds the top-K coins (spot, long only, equal
weight), rebalances every `horizon` days and pays fees on turnover.

The model must beat two baselines on the same days: top-K by 30-day momentum (no model at all) and
buy & hold (BTC, and an equal-weight basket). Variants tried are all counted in the Deflated Sharpe.
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from apps.model.data import UNIVERSE
from apps.model.features import COIN_FEATURES, MARKET_FEATURES, build_panel
from apps.research.metrics import deflated_sharpe, perf

ROOT = Path(__file__).resolve().parents[2]
FEATURES = COIN_FEATURES + MARKET_FEATURES
PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=200, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, random_state=7, deterministic=True,
              force_row_wise=True, verbose=-1, n_jobs=2)


@dataclass
class Book:
    name: str
    daily: pd.Series            # daily net returns
    turnover: float             # average one-way turnover per rebalance
    trades_per_year: float


def walk_forward(panel: pd.DataFrame, horizon: int, warmup_days: int = 365, retrain: int = 30) -> pd.Series:
    import lightgbm as lgb
    days = pd.DatetimeIndex(sorted(panel["day"].unique()))
    start = days[0] + pd.Timedelta(days=warmup_days)
    preds = []
    for t0 in pd.date_range(start, days[-1], freq=f"{retrain}D"):
        train = panel[(panel["day"] <= t0 - pd.Timedelta(days=horizon)) & panel["label"].notna()]
        test = panel[(panel["day"] >= t0) & (panel["day"] < t0 + pd.Timedelta(days=retrain))]
        if test.empty or len(train) < 2000:
            continue
        m = lgb.LGBMRegressor(**PARAMS).fit(train[FEATURES], train["label"] - 0.5)
        preds.append(pd.Series(m.predict(test[FEATURES]), index=test.index))
    return pd.concat(preds) if preds else pd.Series(dtype=float)


def importance(panel: pd.DataFrame, horizon: int) -> pd.Series:
    """Gain importance of a model fit on everything but the last horizon: descriptive, not a test."""
    import lightgbm as lgb
    train = panel[panel["label"].notna()]
    m = lgb.LGBMRegressor(**PARAMS).fit(train[FEATURES], train["label"] - 0.5)
    return pd.Series(m.booster_.feature_importance("gain"), index=FEATURES).sort_values(ascending=False)


def book(panel: pd.DataFrame, score: pd.Series, name: str, horizon: int, k: int, fee: float,
         trend_filter: bool = False) -> Book:
    """Top-k by score at each rebalance day; daily equal-weight returns while held; fees on turnover."""
    p = panel.assign(score=score).dropna(subset=["score"])
    days = pd.DatetimeIndex(sorted(p["day"].unique()))
    rebal = set(days[::horizon])
    held: set[str] = set()
    rets, turns = [], []
    for d in days:
        today = p[p["day"] == d]
        cost = 0.0
        if d in rebal:
            risk_on = not trend_filter or (today["btc_r_84d"].iloc[0] > 0)
            new = set(today.nlargest(k, "score")["coin"]) if risk_on else set()
            changed = len(held ^ new) / (2 * k) if (held or new) else 0.0     # one-way share of the book
            cost = 2 * changed * fee
            turns.append(changed)
            held = new
        r = today[today["coin"].isin(held)]["ret_1d_next"].mean() if held else 0.0
        rets.append((d, (0.0 if np.isnan(r) else r) - cost))
    s = pd.Series(dict(rets)).sort_index()
    years = max((days[-1] - days[0]).days / 365.25, 1e-9)
    return Book(name, s, float(np.mean(turns)) if turns else 0.0, sum(t > 0 for t in turns) / years)


def hold(panel: pd.DataFrame, coins: list[str] | None, name: str, days: pd.DatetimeIndex) -> Book:
    p = panel[panel["day"].isin(days)]
    if coins:
        p = p[p["coin"].isin(coins)]
    s = p.groupby("day")["ret_1d_next"].mean().reindex(days).fillna(0.0)
    return Book(name, s, 0.0, 0.0)


def ic_stats(panel: pd.DataFrame, score: pd.Series) -> tuple[float, float, int]:
    p = panel.assign(score=score).dropna(subset=["score", "fwd_ret"])
    ics = p.groupby("day").apply(lambda g: g["score"].rank().corr(g["fwd_ret"].rank()), include_groups=False).dropna()
    return float(ics.mean()), float(ics.mean() / ics.std() * math.sqrt(len(ics))) if len(ics) > 1 else 0.0, len(ics)


def row(b: Book, since: pd.Timestamp | None = None) -> str:
    s = b.daily if since is None else b.daily[b.daily.index >= since]
    eq = (1 + s).cumprod()
    m = perf(eq)
    return (f"| {b.name} | {m['cagr']:+.1%} | {m['sharpe']:.2f} | {m['max_dd']:.1%} | {m['total']:+.1%} | "
            f"{b.turnover:.0%} | {b.trades_per_year:.0f} |")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default=",".join(UNIVERSE))
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--fee", type=float, default=0.001, help="per side, Binance spot VIP0 taker")
    ap.add_argument("--equity", type=float, default=800.0)
    a = ap.parse_args()
    coins = a.coins.split(",")

    sections, trials, books_all = [], [], {}
    for horizon in (1, 3, 7):
        panel = build_panel(coins, horizon)
        pred = walk_forward(panel, horizon)
        days = pd.DatetimeIndex(sorted(panel.loc[pred.index, "day"].unique()))
        oos = panel[panel["day"].isin(days)]
        mom = oos["r_30d"]                                         # baseline: plain 30-day momentum rank
        books = [
            book(oos, pred, f"model top{a.k} / {horizon}d", horizon, a.k, a.fee),
            book(oos, pred, f"model top{a.k} / {horizon}d + BTC trend", horizon, a.k, a.fee, trend_filter=True),
            book(oos, mom, f"momentum30 top{a.k} / {horizon}d", horizon, a.k, a.fee),
            book(oos, mom, f"momentum30 top{a.k} / {horizon}d + BTC trend", horizon, a.k, a.fee, trend_filter=True),
        ]
        for b in books:
            trials.append(float(b.daily.mean() / b.daily.std()) if b.daily.std() > 0 else 0.0)
            books_all[b.name] = b
        ic, ic_t, n_days = ic_stats(oos, pred)
        mic, mic_t, _ = ic_stats(oos, mom)
        sections.append((horizon, days, books, ic, ic_t, n_days, mic, mic_t, importance(panel, horizon)))

    days = sections[0][1]
    first = sections[0][0]
    base = [hold(build_panel(coins, first), ["BTC"], "BTC buy & hold", days),
            hold(build_panel(coins, first), None, f"equal-weight {len(coins)} coins", days)]
    last_year = days[-1] - pd.Timedelta(days=365)
    best = max(books_all.values(), key=lambda b: perf((1 + b.daily).cumprod())["sharpe"])
    dsr = deflated_sharpe(best.daily, trials)

    head = "| Strategy | CAGR | Sharpe | Max DD | Total | Turnover / rebalance | Rebalances / yr |\n|---|---|---|---|---|---|---|"
    parts = [f"""# Own model vs simple rules — {len(coins)} coins

Out-of-sample walk-forward {days[0]:%Y-%m-%d} → {days[-1]:%Y-%m-%d}: LightGBM retrained every 30 days on the past
only (purged by the horizon), fixed hyperparameters. Spot, long only, top {a.k} coins equal weight, fee
{a.fee:.2%} per side on turnover. Start equity {a.equity:.0f} USDT (results are percentages; scale is linear).

Baselines on the same days:

{head}
{chr(10).join(row(b) for b in base)}
"""]
    for horizon, d, books, ic, ic_t, n_days, mic, mic_t, imp in sections:
        parts.append(f"""## Rebalance every {horizon} day(s)

Ranking skill (Spearman IC of score vs next {horizon}d return, averaged over {n_days} days):
model **{ic:+.3f}** (t = {ic_t:.1f}), plain 30-day momentum {mic:+.3f} (t = {mic_t:.1f}).

{head}
{chr(10).join(row(b) for b in books)}

Last 12 months only:

{head}
{chr(10).join(row(b, last_year) for b in books)}

Top features (gain): {", ".join(f"{k} {v / imp.sum():.0%}" for k, v in imp.head(8).items())}
""")
    model_beats = any(perf((1 + b.daily).cumprod())["sharpe"] >
                      max(perf((1 + x.daily).cumprod())["sharpe"] for x in books_all.values() if x.name.startswith("momentum"))
                      for b in books_all.values() if b.name.startswith("model"))
    parts.append(f"""## Verdict

{len(trials)} strategy variants were tried. Best Sharpe: **{best.name}**; Deflated Sharpe probability that
its true Sharpe is above zero after {len(trials)} tries: **{dsr:.0%}** (want > 95%).

{"The model beats the best momentum rule on Sharpe." if model_beats else "The model does NOT beat plain momentum on Sharpe: the extra data adds nothing a simple rule does not already capture."}
{"Statistically credible: earns paper trading next." if dsr > 0.95 else "Not statistically credible after counting the tries: do not trade it."}
""")
    out = ROOT / "reports" / "MODEL.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(parts))
    print(parts[-1], f"\n-> {out}")


if __name__ == "__main__":
    main()
