"""make pa -> reports/PRICE_ACTION.md: the book's setups on Binance USDT-M futures, 1h and 4h, 20 coins.

Per coin, one position at a time, long and short. Results are in R (multiples of the risk taken), net of
taker 0.05% / maker 0.02% per side, 0.02% slippage on market and stop fills, and the funding actually
settled while the position was open. A bar that touches both stop and target counts as a stop.
In-sample 2022-2024, out-of-sample 2025 onward: a setup is credible only if it is positive in both.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

from apps.pa.data import UNIVERSE, funding, load_1h, to_4h
from apps.pa.setups import SETUPS

ROOT = Path(__file__).resolve().parents[2]
TAKER, MAKER, SLIP = 0.0005, 0.0002, 0.0002
MAX_HOLD = {"1h": 48, "4h": 30}                 # time stop: 2 days on 1h, 5 days on 4h
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def simulate(df: pd.DataFrame, sig: pd.DataFrame, fund: pd.Series, tf: str) -> list[dict]:
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    idx = df.index
    pos_of = {t: i for i, t in enumerate(idx)}
    fund = fund.sort_index()
    trades, busy_until = [], -1
    for t, s in sig.sort_index().iterrows():
        i = pos_of.get(t)
        if i is None or i <= busy_until or i + 1 >= len(df):
            continue
        side, kind = int(s["side"]), s["entry_kind"]
        f, entry, fee_in = None, None, TAKER
        if kind == "open":
            f, entry = i + 1, o[i + 1] * (1 + side * SLIP)
        elif kind == "stop":
            for j in range(i + 1, min(i + 4, len(df))):
                if (side == 1 and h[j] >= s["entry"]) or (side == -1 and l[j] <= s["entry"]):
                    base = max(o[j], s["entry"]) if side == 1 else min(o[j], s["entry"])
                    f, entry = j, base * (1 + side * SLIP)
                    break
        else:                                                   # limitN: resting order at the zone
            wait = int(kind[5:])
            for j in range(i + 1, min(i + 1 + wait, len(df))):
                if (side == 1 and l[j] <= s["entry"]) or (side == -1 and h[j] >= s["entry"]):
                    f, entry, fee_in = j, (min(o[j], s["entry"]) if side == 1 else max(o[j], s["entry"])), MAKER
                    break
        if f is None:
            continue
        stop = s["stop"]
        risk = (entry - stop) * side
        if not risk > 0:
            continue
        target = s["target"] if not np.isnan(s["target"]) else entry + side * s.get("rr", 2.0) * risk
        exit_px, reason, fee_out, k = None, "time", TAKER, f
        for k in range(f, min(f + MAX_HOLD[tf], len(df))):
            stop_hit = l[k] <= stop if side == 1 else h[k] >= stop
            tgt_hit = h[k] >= target if side == 1 else l[k] <= target
            if stop_hit:
                gap = min(o[k], stop) if side == 1 else max(o[k], stop)
                exit_px, reason, fee_out = gap * (1 - side * SLIP), "stop", TAKER
                break
            if tgt_hit and not (k == f and kind != "open"):
                # on the bar a resting order fills, its high may have come before the fill: no target there
                exit_px, reason, fee_out = target, "target", MAKER
                break
        if exit_px is None:
            exit_px = c[k] * (1 - side * SLIP)
        t_in, t_out = idx[f], idx[k] + (idx[1] - idx[0])
        fr = fund[(fund.index > t_in) & (fund.index <= t_out)].sum() if len(fund) else 0.0
        gross = side * (exit_px / entry - 1)
        net = gross - fee_in - fee_out - side * fr
        stop_pct = risk / entry
        trades.append({"t": t_in, "side": side, "R": net / stop_pct, "gross_R": side * (exit_px - entry) / risk,
                       "reason": reason, "stop_pct": stop_pct})
        busy_until = k
    return trades


def stats(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"n": 0}
    r = tr["R"]
    losses = (r <= 0).astype(int).to_numpy()
    streak = run = 0
    for x in losses:
        run = run + 1 if x else 0
        streak = max(streak, run)
    eq = (1 + 0.01 * r).cumprod()                               # 1% risk per trade, in time order
    years = max((tr["t"].max() - tr["t"].min()).days / 365.25, 1 / 12)
    return {"n": len(r), "win": float((r > 0).mean()), "avg_R": float(r.mean()), "gross_R": float(tr["gross_R"].mean()),
            "t": float(r.mean() / r.std() * math.sqrt(len(r))) if len(r) > 1 and r.std() > 0 else 0.0,
            "pf": float(r[r > 0].sum() / -r[r <= 0].sum()) if (r <= 0).any() and r[r <= 0].sum() < 0 else float("inf"),
            "dd": float(((eq.cummax() - eq) / eq.cummax()).max()), "streak": streak,
            "ret": float(eq.iloc[-1] - 1), "per_year": len(r) / years,
            "lev": float(np.median(0.01 / tr["stop_pct"]))}


def fmt(name: str, s: dict) -> str:
    if s["n"] == 0:
        return f"| {name} | 0 | | | | | | | | | |"
    return (f"| {name} | {s['n']} | {s['win']:.0%} | {s['gross_R']:+.2f} | **{s['avg_R']:+.2f}** | {s['t']:+.1f} | "
            f"{s['pf']:.2f} | {s['ret']:+.0%} | {s['dd']:.0%} | {s['streak']} | {s['lev']:.1f}x |")


HEAD = ("| | Trades | Win % | R before costs | **R after costs** | t | PF | Return at 1% risk | Max DD | "
        "Losing streak | Median leverage |\n|---|---|---|---|---|---|---|---|---|---|---|")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default=",".join(UNIVERSE))
    a = ap.parse_args()
    coins = a.coins.split(",")
    rows = []
    for coin in coins:
        d1 = load_1h(coin)
        fr = funding(coin)
        for tf, df in (("1h", d1), ("4h", to_4h(d1))):
            for name, fn in SETUPS.items():
                for t in simulate(df, fn(df), fr, tf):
                    rows.append({**t, "coin": coin, "tf": tf, "setup": name})
        print(f"{coin}: done", flush=True)
    tr = pd.DataFrame(rows).sort_values("t")
    out_csv = ROOT / "reports" / "price_action_trades.csv"
    out_csv.parent.mkdir(exist_ok=True)
    tr.to_csv(out_csv, index=False)

    parts = [f"""# Price action from the book, tested — {len(coins)} coins, Binance USDT-M futures

Setups from *The Ultimate Price Action Trading Guide* (Matov) as exact rules (`apps/pa/setups.py`), on
{tr['t'].min():%Y-%m-%d} → {tr['t'].max():%Y-%m-%d}. Long and short, one position per coin, stop and target
from the book. Costs: taker {TAKER:.2%} / maker {MAKER:.2%} per side, slippage {SLIP:.2%}, real funding.
**R** = result in multiples of the risk; +0.10 R per trade at 1% risk ≈ +0.1% of the account per trade.
"Median leverage" = position size / account needed to risk 1% with that setup's stops.
"""]
    verdict = []
    for tf in ("1h", "4h"):
        lines = []
        for name in SETUPS:
            sub = tr[(tr["tf"] == tf) & (tr["setup"] == name)]
            isd, oos = stats(sub[sub["t"] < SPLIT]), stats(sub[sub["t"] >= SPLIT])
            lines += [fmt(f"{name} · 2022-24", isd), fmt(f"{name} · 2025-26 (unseen)", oos)]
            if isd.get("n") and oos.get("n") and isd["avg_R"] > 0 and oos["avg_R"] > 0 and oos["t"] > 2:
                verdict.append(f"{name} on {tf}")
        parts.append(f"## {tf} candles\n\n{HEAD}\n" + "\n".join(lines) + "\n")
    by = tr[tr["t"] >= SPLIT].groupby(["tf", "setup", "side"])["R"].agg(["count", "mean"]).round(3)
    parts.append("## Out-of-sample by side (+1 long, -1 short)\n\n```\n" + by.to_string() + "\n```\n")
    yr = tr.assign(year=tr["t"].dt.year).groupby(["tf", "setup", "year"])["R"].mean().unstack().round(2)
    parts.append("## Average R after costs, by year\n\n```\n" + yr.to_string() + "\n```\n")
    n_tests = 2 * len(SETUPS)
    parts.append(f"""## Verdict

{n_tests} setup × timeframe combinations were tested; at 5% significance about {0.05 * n_tests:.1f} could pass by luck.
Positive in-sample AND out-of-sample with t > 2: **{", ".join(verdict) if verdict else "none"}**.

{"Those earn paper trading on futures, at 1% risk per trade, before any money." if verdict else "No setup from the book has an edge after costs on these coins. Trading them on futures loses money on average."}
""")
    out = ROOT / "reports" / "PRICE_ACTION.md"
    out.write_text("\n".join(parts))
    print(parts[-1], f"\n-> {out}")


if __name__ == "__main__":
    main()
