"""make m15 -> reports/M15.md: one model that sees every indicator and pattern on the 15m chart and
decides long, short or nothing. Does knowing everything at once beat futures costs?

Walk-forward from 2024-01: every month a LightGBM model is trained on the previous 18 months of all
coins (every 4th bar, purged by the horizon), then predicts every 15m bar of the next month. It goes
long when its prediction is in the top 5% (1%) of what it predicted on the training data, short in the
bottom 5% (1%), else stays out. Entry at the next bar's open, exit at the open `horizon` bars later,
one position per coin. Costs: taker 0.05% + slippage 0.02% per side, funding at each 8h settlement held.
Portfolio: each coin gets 1/N of the account, 1x (no leverage), so results scale linearly with leverage.
"""
from __future__ import annotations

import argparse
import hashlib
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from apps.backtest.data import DATA_DIR
from apps.m15.data import COINS, load_15m
from apps.m15.features import MARKET, coin_features, labels, market
from apps.pa.data import funding as load_funding
from apps.research.metrics import deflated_sharpe, perf

ROOT = Path(__file__).resolve().parents[2]
COST = 2 * (0.0005 + 0.0002)
PARAMS = dict(n_estimators=200, learning_rate=0.05, num_leaves=31, min_child_samples=500, subsample=0.7,
              subsample_freq=1, colsample_bytree=0.7, reg_lambda=1.0, random_state=7, verbose=-1, n_jobs=4)


def build(coins: list[str], since: pd.Timestamp) -> dict[str, pd.DataFrame]:
    btc = load_15m("BTC")
    mk = market(btc)

    def one(coin: str) -> tuple[str, pd.DataFrame]:
        df = load_15m(coin)
        f = coin_features(df, load_funding(coin)).join(mk, how="left")
        for h in (4, 16):
            f[f"fwd{h}"] = labels(df, h)["fwd"]
        f["open"] = df["open"]
        f = f[f.index >= since]
        return coin, f.astype({c: "float32" for c in f.columns if c != "open"})

    with ThreadPoolExecutor(4) as pool:
        return dict(pool.map(one, coins))


def walk_forward(frames: dict[str, pd.DataFrame], horizon: int, start: str, train_months: int = 18,
                 stride: int = 4) -> tuple[pd.DataFrame, dict]:
    import lightgbm as lgb
    feats = [c for c in next(iter(frames.values())).columns if not c.startswith("fwd") and c != "open"]
    target = f"fwd{horizon}"
    allrows = pd.concat([f.assign(coin=c) for c, f in frames.items()])
    allrows["z"] = (allrows[target] / (allrows["vol96"] * math.sqrt(horizon))).clip(-5, 5)
    months = pd.period_range(pd.Timestamp(start), pd.Timestamp.now(), freq="M")
    # finished months are cached, keyed on the feature set, so an interrupted run resumes
    tag = hashlib.sha1(",".join(feats).encode()).hexdigest()[:8]
    cache = DATA_DIR / "m15_cache"
    cache.mkdir(parents=True, exist_ok=True)
    current = pd.Timestamp.now().to_period("M")
    preds, cuts = [], {}
    for m in months:
        f_cache = cache / f"h{horizon}_{m}_{tag}.pkl"
        if m != current and f_cache.exists():
            p_m, c_m = pd.read_pickle(f_cache)
            preds.append(p_m)
            cuts[str(m)] = c_m
            continue
        t0 = m.to_timestamp().tz_localize("UTC")
        t1 = (m + 1).to_timestamp().tz_localize("UTC")
        lo = t0 - pd.DateOffset(months=train_months)
        tr = allrows[(allrows.index >= lo) & (allrows.index < t0 - pd.Timedelta(minutes=15 * (horizon + 1)))]
        tr = tr.iloc[::stride].dropna(subset=["z"])
        te = allrows[(allrows.index >= t0) & (allrows.index < t1)]
        if te.empty or len(tr) < 50_000:
            continue
        model = lgb.LGBMRegressor(**PARAMS).fit(tr[feats], tr["z"])
        p_tr = model.predict(tr[feats])
        cuts[str(m)] = {q: (np.quantile(p_tr, 1 - q), np.quantile(p_tr, q)) for q in (0.95, 0.99)}
        preds.append(pd.DataFrame({"coin": te["coin"], "pred": model.predict(te[feats]), "month": str(m)}, index=te.index))
        if m != current:
            pd.to_pickle((preds[-1], cuts[str(m)]), f_cache)
        print(f"  h={horizon} {m}: trained on {len(tr):,} rows, predicted {len(te):,}", flush=True)
    return pd.concat(preds), cuts


def simulate(frames: dict[str, pd.DataFrame], preds: pd.DataFrame, cuts: dict, horizon: int, q: float) -> pd.DataFrame:
    trades = []
    for coin, p in preds.groupby("coin"):
        f = frames[coin]
        o = f["open"].to_numpy()
        fund = f["funding"].fillna(0).to_numpy()
        pos = {t: i for i, t in enumerate(f.index)}
        busy = -1
        lo = p["month"].map(lambda m: cuts[m][q][0])
        hi = p["month"].map(lambda m: cuts[m][q][1])
        sides = np.where(p["pred"] > hi, 1, np.where(p["pred"] < lo, -1, 0))
        for t, side in zip(p.index[sides != 0], sides[sides != 0]):
            i = pos[t]
            if i <= busy or i + 1 + horizon >= len(f):
                continue
            e, x = o[i + 1], o[i + 1 + horizon]
            t_in, t_out = f.index[i + 1], f.index[i + 1 + horizon]
            settlements = sum(1 for k in pd.date_range(t_in.ceil("8h"), t_out, freq="8h") if t_in < k <= t_out)
            gross = side * (x / e - 1)
            trades.append({"t": t_in, "coin": coin, "side": side, "gross": gross,
                           "net": gross - COST - side * fund[i] * settlements})
            busy = i + horizon
    return pd.DataFrame(trades)


def portfolio(tr: pd.DataFrame, n_coins: int) -> pd.Series:
    """Daily returns: each coin's book is 1/n of the account at 1x; a trade's net return lands on its entry day."""
    day = tr.groupby(tr["t"].dt.floor("D"))["net"].sum() / n_coins
    idx = pd.date_range(day.index.min(), day.index.max(), freq="D")
    return day.reindex(idx, fill_value=0.0)


def ic(frames: dict[str, pd.DataFrame], preds: pd.DataFrame, horizon: int) -> float:
    vals = []
    for coin, p in preds.groupby("coin"):
        y = frames[coin][f"fwd{horizon}"].reindex(p.index)
        ok = y.notna()
        if ok.sum() > 100:
            vals.append(p["pred"][ok].rank().corr(y[ok].rank()))
    return float(np.nanmean(vals))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default=",".join(COINS))
    ap.add_argument("--start", default="2024-01")
    a = ap.parse_args()
    coins = a.coins.split(",")
    frames = build(coins, pd.Timestamp(a.start, tz="UTC") - pd.DateOffset(months=19))
    print("features built", flush=True)
    sections, trials, results = [], [], []
    for h in (4, 16):
        preds, cuts = walk_forward(frames, h, a.start)
        rank_ic = ic(frames, preds, h)
        rows = []
        for q in (0.95, 0.99):
            tr = simulate(frames, preds, cuts, h, q)
            if tr.empty:
                rows.append(f"| top/bottom {1 - q:.0%} | 0 | | | | | | | | |")
                continue
            d = portfolio(tr, len(coins))
            m = perf((1 + d).cumprod())
            trials.append(float(d.mean() / d.std()) if d.std() > 0 else 0.0)
            results.append((f"{h * 15} min, top/bottom {1 - q:.0%}", d, tr))
            t = tr["net"].mean() / tr["net"].std() * math.sqrt(len(tr))
            last = tr[tr["t"] >= tr["t"].max() - pd.Timedelta(days=182)]
            rows.append(f"| top/bottom {1 - q:.0%} | {len(tr):,} | {(tr['gross'] > 0).mean():.1%} | {tr['gross'].mean() * 1e4:+.1f} | "
                        f"**{tr['net'].mean() * 1e4:+.1f}** | {t:+.1f} | {m['total']:+.0%} | {m['max_dd']:.0%} | "
                        f"{last['net'].mean() * 1e4:+.1f} |")
            by_coin = tr.groupby("coin")["net"].mean().mul(1e4).round(1).sort_values()
            rows.append(f"| ↳ coins with positive net | {(by_coin > 0).sum()} of {len(by_coin)} | best: "
                        f"{', '.join(f'{k} {v:+.0f}' for k, v in by_coin.tail(3).items())} | worst: "
                        f"{', '.join(f'{k} {v:+.0f}' for k, v in by_coin.head(3).items())} | | | | | | |")
        sections.append(f"""## Hold {h * 15} minutes

Ranking skill (Spearman IC, prediction vs the next {h * 15} min, all bars): **{rank_ic:+.3f}**.

| Signal | Trades | Direction right | Avg before costs (bp) | **Avg after costs (bp)** | t | Return, 1x | Max DD | Last 6 months (bp) |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(rows)}
""")
    best = max(results, key=lambda r: r[1].mean()) if results else None
    dsr = deflated_sharpe(best[1], trials) if best else 0.0
    ok = best is not None and best[2]["net"].mean() > 0 and dsr > 0.95
    md = f"""# One model, every indicator and pattern, 15m futures — {len(coins)} coins

Coins: {", ".join(coins)}. Out-of-sample walk-forward from {a.start} (monthly retraining on the previous
18 months only). Costs per round trip: {COST:.2%} (taker + slippage) plus funding. 1 bp = 0.01%.
A trade needs to be right by more than ~{COST * 1e4:.0f} bp on average just to break even.

{"".join(sections)}
## Verdict

Best: **{best[0] if best else "none"}**; Deflated Sharpe over {len(trials)} variants: **{dsr:.0%}** (want > 95%).

{"Survives costs and the count of tries: paper trade it next." if ok else "Seeing every indicator and pattern at once does not beat futures costs on 15m: the model reads the chart, but what it reads is not enough to pay ~14 bp per round trip."}
"""
    out = ROOT / "reports" / "M15.md"
    out.write_text(md)
    print(md)


if __name__ == "__main__":
    main()
