"""make kronos -> reports/KRONOS_<SYMBOL>.md

Does Kronos earn a place in the tournament? Two questions, answered only on data after `--since`:
  1. Skill: does the predicted direction beat "always up" (hit rate) and rank moves (IC > 0)?
  2. Money: do its entries, through our exits, fees and risk engine, survive out-of-sample?
A pass earns paper trading, not money. The first run is slow on CPU (cached, resumable).

  python -m apps.research.kronos_eval --symbol BTC/USDT --download
"""
from __future__ import annotations

import argparse
import logging
import warnings
from dataclasses import replace
from pathlib import Path

import pandas as pd

from apps.backtest.data import DATA_DIR, csv_path, download, load
from apps.backtest.tournament import run_tournament, split
from apps.strategy.freqtrade_adapter import signal_frame
from apps.strategy.kronos import KronosParams, entries, forecast_frame, kronos_forecaster, skill
from apps.strategy.trend_pullback import StrategyParams

ROOT = Path(__file__).resolve().parents[2]
THRESHOLDS = (0.002, 0.004, 0.008)


def evaluate(df: pd.DataFrame, fc: pd.DataFrame, symbol: str, p: KronosParams, since: pd.Timestamp,
             equity: float, model: str) -> str:
    ev = df.loc[since:]
    cands = {"built_in_trend_pullback": StrategyParams()}
    for r in THRESHOLDS:
        cands[f"kronos ret>{r:.1%}"] = signal_frame(entries(fc, replace(p, min_ret=r)), df)
    results = run_tournament(ev, symbol, cands, start_equity=equity)
    is_df, oos_df = split(ev)
    sk = {"in-sample": skill(fc.loc[is_df.index], df, p.horizon),
          "out-of-sample": skill(fc.loc[oos_df.index], df, p.horizon)}
    skill_rows = "\n".join(f"| {k} | {v['n']} | {v['hit_rate']:.1%} | {v['base_up']:.1%} | {v['ic']:+.3f} |"
                           for k, v in sk.items())
    rows = []
    for r in results:
        o = r.oos_rep
        rows.append(f"| {r.name} | {r.is_rep.n} | {r.is_rep.profit_factor:.2f} | {r.is_rep.net:+.2f} | "
                    f"{'PASS' if r.passed_is else '—'} | "
                    f"{(f'{o.n} / PF {o.profit_factor:.2f} / {o.net:+.2f}') if o else '—'} | "
                    f"{'**SURVIVOR**' if r.passed_oos else ''} |")
    oos = sk["out-of-sample"]
    has_skill = oos["n"] > 0 and oos["hit_rate"] > oos["base_up"] and oos["ic"] > 0.02
    kronos_survived = any(r.passed_oos for r in results if r.name.startswith("kronos"))
    verdict = ("Kronos survived out-of-sample: it earns PAPER trading next to the other candidates, not money."
               if kronos_survived else
               "Kronos did not survive out-of-sample after costs. Do not trade it.")
    return f"""# Kronos — {symbol}

Model: `{model}`. Data: {ev.index[0]:%Y-%m-%d} → {ev.index[-1]:%Y-%m-%d} (only after {since:%Y-%m-%d}, so
the model cannot have been pre-trained on it). Forecast {p.horizon} bars (15m) ahead from the last
{p.lookback}, {p.paths} sampled paths, one decision every {p.every} bars. Start equity {equity:.0f} USDT.

## 1. Forecast skill (before any trading rule)

| Period | Forecasts | Hit rate | "Always up" | IC (Spearman) |
|---|---|---|---|---|
{skill_rows}

Skill out-of-sample: **{'yes' if has_skill else 'no'}** (hit rate above "always up" and IC > 0.02).

## 2. Tournament (same exits, fees and risk engine; first 60% in-sample, last 40% out-of-sample)

| Strategy | IS trades | IS PF | IS net | IS | OOS trades / PF / net | Result |
|---|---|---|---|---|---|---|
{chr(10).join(rows)}

{len(THRESHOLDS)} Kronos thresholds were tried; with several tries, one passing by luck is plausible.

## Verdict

{verdict}
"""


def main() -> None:
    warnings.filterwarnings("ignore")
    logging.disable(logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTC/USDT")
    ap.add_argument("--since", default="2025-09-01", help="first test day; must be after Kronos' training data")
    ap.add_argument("--model", default="NeoQuasar/Kronos-small")
    ap.add_argument("--tokenizer", default="NeoQuasar/Kronos-Tokenizer-base")
    ap.add_argument("--equity", type=float, default=800.0)
    ap.add_argument("--every", type=int, default=KronosParams.every)
    ap.add_argument("--download", action="store_true")
    a = ap.parse_args()

    since = pd.Timestamp(a.since, tz="UTC")
    p = KronosParams(every=a.every)
    if a.download or not csv_path(a.symbol).exists():
        days = (pd.Timestamp.now(tz="UTC") - since).days + 30          # + warm-up for lookback and exits
        download(a.symbol, days=max(days, 400))
    df = load(a.symbol)
    cache = DATA_DIR / f"kronos_{a.symbol.replace('/', '')}_{a.model.split('/')[-1]}_{p.key()}.csv"
    fc = forecast_frame(df, kronos_forecaster(a.model, a.tokenizer), p, cache=cache, since=since, progress=True)
    md = evaluate(df, fc, a.symbol, p, since, a.equity, a.model)
    out = ROOT / "reports" / f"KRONOS_{a.symbol.replace('/', '')}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(md)
    print(md.split("## Verdict")[1].strip(), f"\n-> {out}")


if __name__ == "__main__":
    main()
