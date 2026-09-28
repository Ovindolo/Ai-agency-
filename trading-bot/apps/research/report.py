"""make research -> reports/RESEARCH_REPORT.md (+ one SVG equity chart per symbol)

One command, the whole research process: 6 fundamentally different 15m strategies and 2 daily ones,
same costs and risk engine, on several coins; full-period, in-sample / out-of-sample and walk-forward
results; parameter sensitivity; Deflated Sharpe for the number of things tried; performance by market
regime; and a pass/fail checklist per strategy. Nothing is recommended that fails the checklist.

  python -m apps.research.report --symbols BTC/USDT,ETH/USDT,SOL/USDT --download
  python -m apps.research.report --simulated          # plumbing demo on SIMULATED markets
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from apps.backtest.engine import run_backtest
from apps.features.snapshot import resample_1d
from apps.research.metrics import by_regime, daily, deflated_sharpe, perf, regimes
from apps.strategy.classic import CLASSIC, entries
from apps.strategy.daily_trend import DailyTrendParams, buy_and_hold, run_daily_trend, weekly_dca
from apps.strategy.freqtrade_adapter import signal_frame
from apps.strategy.trend_pullback import StrategyParams

ROOT = Path(__file__).resolve().parents[2]
EQUITY = 500.0

THESIS = {
    "trend_pullback": "Buy a pullback to the 15m EMA inside a 1h uptrend with ADX: trends persist, dips inside them get bought.",
    "trend_pullback+mom20d": "Same, only while the coin's 20-day return is positive (time-series momentum filter).",
    "trend_pullback+mom60d": "Same, with a 60-day momentum filter: slower, fewer trades in bear markets.",
    "ichimoku_breakout": "Close breaks above the Ichimoku cloud with Tenkan>Kijun and a future-safe Chikou check.",
    "fib_618_pullback": "Retracement into the 0.5-0.618 zone of the last day's up-leg, above EMA200: buy the dip in a leg.",
    "supertrend_flip": "Supertrend(10,3) flips up: classic volatility-band trend entry.",
    "daily_trend20": "Hold the coin while its 20-day return is positive, else cash; volatility-targeted, few trades.",
    "daily_trend60": "Same with 60 days.",
}


@dataclass
class Row:
    symbol: str
    name: str
    family: str                                   # 15m | daily
    eq: pd.Series                                 # daily equity
    trades: int = 0
    win_rate: float = 0.0
    pf: float = 0.0
    fees: float = 0.0
    p: dict = field(default_factory=dict)
    p_oos: dict = field(default_factory=dict)
    dsr: float = 0.0
    regimes: dict = field(default_factory=dict)
    checks: dict = field(default_factory=dict)

    @property
    def score(self) -> int:
        return sum(self.checks.values())


def family_15m(df: pd.DataFrame) -> dict:
    fam = {"trend_pullback": StrategyParams(), "trend_pullback+mom20d": StrategyParams(daily_mom_days=20),
           "trend_pullback+mom60d": StrategyParams(daily_mom_days=60)}
    fam.update({n: signal_frame(entries(n, df), df) for n in CLASSIC})
    return fam


def sensitivity_grid() -> dict[str, StrategyParams]:
    return {f"adx{a}_rr{rr}_atr{m}": StrategyParams(adx_min=a, target_rr=rr, stop_atr_mult=m)
            for a, rr, m in product((15, 20, 25), (1.8, 2.0, 2.5), (1.2, 1.5, 2.0))}


def run_15m(df: pd.DataFrame, sym: str, name: str, cand) -> Row:
    kw = {"signal_frame": cand} if isinstance(cand, pd.DataFrame) else {"params": cand}
    rep = run_backtest(df, sym, label=name, start_equity=EQUITY, **kw)
    eq = daily(rep.equity_curve) if rep.equity_curve is not None and len(rep.equity_curve) else pd.Series(dtype=float)
    return Row(sym, name, "15m", eq, rep.n, len(rep.wins) / rep.n if rep.n else 0.0, rep.profit_factor, rep.fees)


def oos_slice(eq: pd.Series, frac: float = 0.6) -> pd.Series:
    return eq.iloc[int(len(eq) * frac):]


def walk_forward(eqs: dict[str, pd.Series], folds: int = 5) -> tuple[pd.Series, list[str]]:
    """Pick, at the start of each fold, the candidate with the best Sharpe on everything BEFORE the fold;
    hold it for the fold. Stitched returns = what choosing-by-the-past would really have earned."""
    rets = pd.DataFrame({k: v.pct_change() for k, v in eqs.items()}).dropna(how="all").fillna(0.0)
    edges = np.linspace(0, len(rets), folds + 1).astype(int)
    out, picks = [], []
    for k in range(1, folds):
        past = rets.iloc[:edges[k]]
        sharpe = past.mean() / past.std().replace(0, np.nan)
        pick = sharpe.fillna(-np.inf).idxmax()
        picks.append(pick)
        out.append(rets[pick].iloc[edges[k]:edges[k + 1]])
    r = pd.concat(out) if out else pd.Series(dtype=float)
    return EQUITY * (1 + r).cumprod(), picks


def svg_chart(series: dict[str, pd.Series], path: Path, title: str) -> None:
    w, h, pad = 760, 300, 40
    colors = ["#2563eb", "#16a34a", "#dc2626", "#9333ea", "#ea580c", "#0891b2", "#64748b"]
    norm = {k: v / v.iloc[0] for k, v in series.items() if len(v) > 1}
    if not norm:
        return
    lo = min(v.min() for v in norm.values())
    hi = max(v.max() for v in norm.values())
    t0 = min(v.index[0] for v in norm.values())
    t1 = max(v.index[-1] for v in norm.values())
    span = max((t1 - t0).total_seconds(), 1)

    def xy(t, y):
        return pad + (t - t0).total_seconds() / span * (w - 2 * pad), h - pad - (y - lo) / max(hi - lo, 1e-9) * (h - 2 * pad)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" font-family="sans-serif" font-size="11">',
             f'<rect width="{w}" height="{h}" fill="white"/><text x="{pad}" y="20" font-size="13">{title}</text>']
    y1 = xy(t0, 1.0)[1]
    parts.append(f'<line x1="{pad}" y1="{y1:.1f}" x2="{w - pad}" y2="{y1:.1f}" stroke="#ccc" stroke-dasharray="4"/>')
    for i, (k, v) in enumerate(norm.items()):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (xy(t, val) for t, val in v.items()))
        c = colors[i % len(colors)]
        parts.append(f'<polyline fill="none" stroke="{c}" stroke-width="1.5" points="{pts}"/>')
        parts.append(f'<text x="{w - pad - 200}" y="{40 + 14 * i}" fill="{c}">{k} ({v.iloc[-1] - 1:+.0%})</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts))


def evaluate_symbol(sym: str, df: pd.DataFrame, daily_long: pd.DataFrame) -> dict:
    fam = family_15m(df)
    rows = [run_15m(df, sym, n, c) for n, c in fam.items()]
    sens = [run_15m(df, sym, n, c) for n, c in sensitivity_grid().items()]
    px = resample_1d(df)["close"]
    bh_eq = EQUITY * px / px.iloc[0]
    bh = Row(sym, "buy & hold", "benchmark", bh_eq, 1)
    labels = regimes(px)

    long_px = daily_long
    for n, lb in (("daily_trend20", 20), ("daily_trend60", 60)):
        res = run_daily_trend(long_px, DailyTrendParams(lookback=lb), EQUITY)
        rows.append(Row(sym, n, "daily", res.equity, res.trades, fees=res.fees))
    bh_long = buy_and_hold(long_px, EQUITY)
    dca_long = weekly_dca(long_px, EQUITY)

    trials = [r.eq.pct_change().dropna() for r in rows + sens if len(r.eq) > 30]
    trial_sr = [float(t.mean() / t.std()) for t in trials if t.std() > 0]
    long_labels = regimes(long_px["close"])
    for r in rows + [bh]:
        r.p = perf(r.eq) if len(r.eq) > 2 else {}
        r.p_oos = perf(oos_slice(r.eq)) if len(r.eq) > 10 else {}
        r.dsr = deflated_sharpe(r.eq.pct_change(), trial_sr) if r.family != "benchmark" else 0.0
        r.regimes = by_regime(r.eq, long_labels if r.family == "daily" else labels)
    wf_eq, picks = walk_forward({r.name: r.eq for r in rows if r.family == "15m" and len(r.eq) > 30})
    wf_start = wf_eq.index[0] if len(wf_eq) else px.index[0]
    bh_wf = perf(bh_eq[bh_eq.index >= wf_start]) if len(wf_eq) else {}
    sens_oos = [perf(oos_slice(s.eq))["sharpe"] for s in sens if len(s.eq) > 10]
    return {"symbol": sym, "rows": rows, "bh": bh, "bh_long": bh_long, "dca_long": dca_long, "labels": labels,
            "wf": (perf(wf_eq) if len(wf_eq) > 2 else {}, picks, bh_wf), "sens": sens_oos, "trials": len(trial_sr),
            "long_period": (long_px.index[0], long_px.index[-1])}


def apply_checks(results: list[dict]) -> None:
    for res in results:
        bh_15 = res["bh"].p.get("total", 0.0)
        bh_long = perf(res["bh_long"].equity)["total"]
        for r in res["rows"]:
            bench = bh_long if r.family == "daily" else bh_15
            good_regimes = sum(1 for d, ann in r.regimes.values() if d >= 20 and ann > 0)
            r.checks = {"bate buy&hold după costuri": r.p.get("total", -1) > bench,
                        "Sharpe > 1": r.p.get("sharpe", 0) > 1.0,
                        "max drawdown < 30%": r.p.get("max_dd", 1) < 0.30,
                        "Sharpe pe date nevăzute > 0": r.p_oos.get("sharpe", 0) > 0,
                        "pe plus în ≥2 regimuri": good_regimes >= 2,
                        "Deflated Sharpe > 0.95": r.dsr > 0.95}
    names = {r.name for res in results for r in res["rows"]}
    for n in names:
        core = ("bate buy&hold după costuri", "Sharpe pe date nevăzute > 0")
        ok = sum(1 for res in results for r in res["rows"] if r.name == n and all(r.checks[c] for c in core))
        for res in results:
            for r in res["rows"]:
                if r.name == n:
                    r.checks["merge pe ≥2 monede"] = ok >= 2 or len(results) == 1


def _p(x, pct=True):
    return "—" if x is None else (f"{x:+.1%}" if pct else f"{x:.2f}")


def markdown(results: list[dict], simulated: bool) -> str:
    now = datetime.now(timezone.utc)
    ranked = sorted((r for res in results for r in res["rows"]), key=lambda r: (r.score, r.p_oos.get("sharpe", -9)), reverse=True)
    max_score = len(ranked[0].checks) if ranked else 7
    winners = [r for r in ranked if r.score == max_score]
    L = [f"# Raport de cercetare · {now:%Y-%m-%d %H:%M} UTC", ""]
    if simulated:
        L += ["> **DATE SIMULATE.** Raportul arată doar că mecanismul funcționează. Nicio concluzie despre piața reală.", ""]
    L += ["## 1. Rezumat", "",
          f"- Strategii testate: {len({r.name for r in ranked})} pe {len(results)} monede, plus "
          f"{len(sensitivity_grid())} variante de parametri pe monedă (toate intră în Deflated Sharpe).",
          f"- Strategii care trec **toate** cele {max_score} verificări: **{len(winners)}**"
          + (": " + ", ".join(sorted({f'{r.name} ({r.symbol})' for r in winners})) if winners else "."),
          "- Regula: nu se recomandă nimic care pică verificările. Dacă nu trece nimic, răspunsul corect e "
          "cumpărat-și-ținut sau DCA, nu o strategie.", ""]
    L += ["## 2. Piața (pe perioada testată)", "", "| Monedă | Perioadă 15m | Buy & hold | Max DD | Zile bull / lateral / bear | Regim acum |",
          "|---|---|---|---|---|---|"]
    for res in results:
        lab, bh = res["labels"], res["bh"]
        cnt = lab.value_counts()
        L.append(f"| {res['symbol']} | {bh.eq.index[0]:%Y-%m-%d} → {bh.eq.index[-1]:%Y-%m-%d} | {_p(bh.p.get('total'))} | "
                 f"{bh.p.get('max_dd', 0):.0%} | {cnt.get('bull', 0)} / {cnt.get('sideways', 0)} / {cnt.get('bear', 0)} | {lab.iloc[-1]} |")
    L += ["", "Regim = randamentul ultimelor 90 de zile: bull > +20%, bear < −20%, altfel lateral.", "",
          "## 3. Strategiile", "", "| Strategie | Teza |", "|---|---|"]
    L += [f"| {k} | {v} |" for k, v in THESIS.items()]
    L += ["", "Toate strategiile de 15m folosesc aceleași stopuri, targeturi, taxe (0.10% + 0.08% alunecare pe parte) și "
          "motor de risc. Cele zilnice plătesc aceleași taxe la fiecare rebalansare.", ""]
    for res in results:
        sym = res["symbol"]
        L += [f"## 4. Rezultate · {sym}", "", f"![equity](equity_{sym.replace('/', '')}.svg)", "",
              "| Strategie | Tranz. | Randament | CAGR | Sharpe | Sortino | Max DD | Câștig% | PF | Taxe | OOS Sharpe | DSR |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in res["rows"] + [res["bh"]]:
            p, po = r.p, r.p_oos
            L.append(f"| {r.name} | {r.trades} | {_p(p.get('total'))} | {_p(p.get('cagr'))} | {p.get('sharpe', 0):.2f} | "
                     f"{p.get('sortino', 0):.2f} | {p.get('max_dd', 0):.0%} | "
                     f"{f'{r.win_rate:.0%}' if r.family == '15m' else '—'} | {f'{r.pf:.2f}' if r.family == '15m' else '—'} | {r.fees:.1f} | "
                     f"{po.get('sharpe', 0):.2f} | {r.dsr:.2f} |")
        lp = res["long_period"]
        bhl, dca = perf(res["bh_long"].equity), perf(res["dca_long"].equity)
        daily_rows = [r for r in res["rows"] if r.family == "daily"]
        yrs = max((lp_ := res["long_period"])[1] - lp_[0], pd.Timedelta(days=1)).days / 365.25
        turn = ", ".join(f"{r.name} {r.trades / yrs:.0f} rebalansări/an, taxe {r.fees / EQUITY:.0%} din capital" for r in daily_rows)
        L += ["", f"Strategiile zilnice rulează pe {lp[0]:%Y-%m-%d} → {lp[1]:%Y-%m-%d}; pe aceeași perioadă buy & hold "
              f"{bhl['total']:+.0%} (max DD {bhl['max_dd']:.0%}), DCA săptămânal {dca['total']:+.0%} (max DD {dca['max_dd']:.0%}). "
              f"Cost: {turn}.", ""]
        wf, picks, bh_wf = res["wf"]
        if wf:
            L += [f"**Walk-forward** (la începutul fiecărui sfert aleg strategia cu cel mai bun Sharpe pe tot ce a fost înainte): "
                  f"randament {wf['total']:+.1%}, Sharpe {wf['sharpe']:.2f}, max DD {wf['max_dd']:.0%} · buy & hold pe aceleași zile "
                  f"{bh_wf.get('total', 0):+.1%} · alegeri: {' → '.join(picks)}", ""]
        s = res["sens"]
        if s:
            L += [f"**Sensibilitate** ({len(s)} variante trend_pullback: ADX × R:R × stop): Sharpe pe date nevăzute pozitiv în "
                  f"{np.mean(np.array(s) > 0):.0%} din variante, median {np.median(s):.2f}. Un avantaj real nu dispare când "
                  "muți un parametru cu un pas.", ""]
        L += ["**Pe regimuri** (randament anualizat al strategiei în zilele din fiecare regim):", "",
              "| Strategie | Bull | Lateral | Bear |", "|---|---|---|---|"]
        for r in res["rows"] + [res["bh"]]:
            g = r.regimes
            L.append(f"| {r.name} | " + " | ".join(
                f"{g[k][1]:+.0%} ({g[k][0]}z)" if k in g else "—" for k in ("bull", "sideways", "bear")) + " |")
        L.append("")
    L += ["## 5. Clasament", "", "| # | Strategie | Monedă | Scor | " + " | ".join(ranked[0].checks) + " |" if ranked else "",
          "|---|---|---|---|" + "---|" * (len(ranked[0].checks) if ranked else 0)]
    for i, r in enumerate(ranked[:20], 1):
        L.append(f"| {i} | {r.name} | {r.symbol} | {r.score}/{max_score} | " + " | ".join("✅" if v else "❌" for v in r.checks.values()) + " |")
    L += ["", "## 6. Recomandare", ""]
    if winners:
        L += [f"- **{r.name}** pe {r.symbol}: intră pe paper trading 2–4 săptămâni pe prețuri reale, nu pe bani." for r in winners[:5]]
    else:
        L += ["- **Nicio strategie nu trece toate verificările.** Nu tranzacționa niciuna cu bani reali. Alternativa care nu cere "
              "niciun avantaj: DCA sau cumpărat-și-ținut, cu mărime pe care o suporți la −70%."]
    L += ["", "## 7. Punere în practică", "",
          "- Paper întâi, cu `make paper`; bani reali doar după paritate paper ↔ backtest și 40+ tranzacții.",
          "- Risc pe tranzacție ≤1%, max 2 poziții, 30% cash, pauză la −3% pe zi, stop total la −12% de la vârf (config/risk.yaml).",
          "- Analiză la fiecare 10 tranzacții (Learnings.md); nicio schimbare fără testul din raportul ăsta.", "",
          "## 8. Ce poate merge prost", "",
          "- Perioada testată conține un singur tip de piață; alt regim poate inversa clasamentul.",
          "- Deflated Sharpe presupune că variantele testate sunt toate cele încercate; orice încercare nescrisă aici îl umflă.",
          "- Execuția reală: spread-uri mai mari în crash-uri, ordine neumplute, exchange-ul oprit exact când ai nevoie.",
          "- Invalidare: Sharpe pe paper sub 0 după 40 de tranzacții, sau drawdown peste cel mai rău din backtest."]
    return "\n".join(L) + "\n"


def main() -> None:
    import warnings
    warnings.filterwarnings("ignore")
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTC/USDT,ETH/USDT,SOL/USDT")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--simulated", action="store_true")
    ap.add_argument("--days", type=int, default=365)
    a = ap.parse_args()
    out = ROOT / "reports"
    out.mkdir(exist_ok=True)
    results = []
    for k, sym in enumerate(a.symbols.split(",")):
        if a.simulated:
            from apps.trader.paper import simulated_market
            df = simulated_market(a.days, 31 + k, start=[60_000.0, 3_000.0, 150.0][k % 3])
            daily_long = resample_1d(simulated_market(365 * 4, 71 + k, start=[60_000.0, 3_000.0, 150.0][k % 3]))
        else:
            from apps.backtest.data import download, load
            from apps.strategy.daily_trend import load_daily
            if a.download:
                download(sym, days=a.days + 60)
            df = load(sym)
            daily_long = load_daily(sym, refresh=a.download)
        print(f"{sym}: {len(df)} lumânări 15m, {len(daily_long)} zile")
        res = evaluate_symbol(sym, df, daily_long)
        results.append(res)
        top = sorted(res["rows"], key=lambda r: r.p.get("total", -9), reverse=True)[:3]
        svg_chart({**{r.name: r.eq for r in top if r.family == "15m"}, "buy & hold": res["bh"].eq},
                  out / f"equity_{sym.replace('/', '')}.svg", f"{sym} · capital normalizat (1 = start)")
    apply_checks(results)
    md = markdown(results, a.simulated)
    path = out / "RESEARCH_REPORT.md"
    path.write_text(md, encoding="utf-8")
    print(md)
    print(f"salvat: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
