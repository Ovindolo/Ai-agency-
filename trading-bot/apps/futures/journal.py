"""Futures journal from the exchange's own ledger (/fapi/v1/income). Answers, with numbers:
how much of the balance is trading profit and how much is deposits; what fees and funding cost;
win rate, profit factor, average win vs loss, worst loss, drawdown; which coins make and lose money;
and whether the result is distinguishable from luck (t-statistic of the per-exit result).

  python -m apps.futures.journal --days 90       # writes context/Futures_Journal.md

REALIZED_PNL on Binance excludes fees; COMMISSION and FUNDING_FEE are separate lines, all included here.
Exits = REALIZED_PNL lines of one symbol within 60 seconds of each other (one close, several fills).
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
TRADING = ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE")


@dataclass
class Journal:
    ledger: pd.DataFrame        # time, symbol, type, amount
    exits: pd.DataFrame         # time, symbol, pnl (realized, before fees)

    def total(self, kind: str) -> float:
        return float(self.ledger.loc[self.ledger["type"] == kind, "amount"].sum())

    @property
    def net_trading(self) -> float:
        return float(self.ledger.loc[self.ledger["type"].isin(TRADING), "amount"].sum())

    @property
    def net_transfers(self) -> float:
        return self.total("TRANSFER")

    def stats(self) -> dict:
        x = self.exits["pnl"]
        wins, losses = x[x > 0], x[x <= 0]
        n = len(x)
        curve = self.ledger.loc[self.ledger["type"].isin(TRADING)].set_index("time")["amount"].cumsum()
        dd = float((curve.cummax() - curve).max()) if len(curve) else 0.0
        t = float(x.mean() / (x.std(ddof=1) / math.sqrt(n))) if n > 2 and x.std(ddof=1) > 0 else 0.0
        return {"exits": n, "win_rate": len(wins) / n if n else 0.0,
                "pf": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else float("inf"),
                "avg_win": float(wins.mean()) if len(wins) else 0.0, "avg_loss": float(losses.mean()) if len(losses) else 0.0,
                "worst": float(x.min()) if n else 0.0, "max_dd": dd, "t_stat": t}


def build_journal(income: list[dict]) -> Journal:
    rows = [{"time": pd.Timestamp(int(r["time"]), unit="ms", tz="UTC"), "symbol": r.get("symbol") or "",
             "type": r["incomeType"], "amount": float(r["income"])} for r in income]
    ledger = pd.DataFrame(rows, columns=["time", "symbol", "type", "amount"]).sort_values("time")
    rp = ledger[ledger["type"] == "REALIZED_PNL"]
    exits = []
    for sym, g in rp.groupby("symbol"):
        cluster_t, cluster_sum, last = None, 0.0, None
        for t, amt in zip(g["time"], g["amount"]):
            if last is not None and t - last > pd.Timedelta("60s"):
                exits.append({"time": cluster_t, "symbol": sym, "pnl": cluster_sum})
                cluster_t, cluster_sum = None, 0.0
            cluster_t = cluster_t or t
            cluster_sum += amt
            last = t
        if cluster_t is not None:
            exits.append({"time": cluster_t, "symbol": sym, "pnl": cluster_sum})
    ex = pd.DataFrame(exits, columns=["time", "symbol", "pnl"]).sort_values("time").reset_index(drop=True)
    return Journal(ledger.reset_index(drop=True), ex)


def verdict(s: dict) -> str:
    if s["exits"] < 30:
        return f"Doar {s['exits']} închideri: prea puține ca să separi metoda de noroc. Revino după 30+."
    if s["t_stat"] >= 2:
        return f"t = {s['t_stat']:.1f}: rezultatul mediu pe tranzacție e greu de explicat doar prin noroc (nu e o garanție)."
    if s["t_stat"] > 0:
        return f"t = {s['t_stat']:.1f}: pe plus, dar încă în zona în care norocul explică rezultatul."
    return f"t = {s['t_stat']:.1f}: rezultatul mediu pe tranzacție e negativ."


def markdown(j: Journal, days: int, balance: float | None = None) -> str:
    s = j.stats()
    gross, fees, funding = j.total("REALIZED_PNL"), j.total("COMMISSION"), j.total("FUNDING_FEE")
    lines = [f"# Jurnal futures · ultimele {days} zile · generat {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", "",
             "## De unde vin banii", "",
             "| | USDT |", "|---|---|",
             f"| Profit realizat din tranzacții (înainte de taxe) | {gross:+,.2f} |",
             f"| Taxe (commission) | {fees:+,.2f} |",
             f"| Funding | {funding:+,.2f} |",
             f"| **Net din trading** | **{j.net_trading:+,.2f}** |",
             f"| Transferuri nete (depuneri − retrageri pe contul futures) | {j.net_transfers:+,.2f} |"]
    if balance is not None:
        lines.append(f"| Sold actual (margin balance) | {balance:,.2f} |")
    if gross > 0:
        lines.append(f"\nTaxele și funding-ul au mâncat {-(fees + funding) / gross:.0%} din profitul brut.")
    lines += ["", "## Cum tranzacționezi", "",
              f"- Închideri: {s['exits']} · câștigătoare {s['win_rate']:.0%} · profit factor {s['pf']:.2f}",
              f"- Câștig mediu {s['avg_win']:+,.2f} · pierdere medie {s['avg_loss']:+,.2f} · cea mai mare pierdere {s['worst']:+,.2f}",
              f"- Cea mai mare scădere a profitului cumulat: {s['max_dd']:,.2f} USDT",
              f"- **Noroc sau metodă?** {verdict(s)}", "", "## Pe monede", "",
              "| Monedă | Închideri | Câștigate | Net realizat |", "|---|---|---|---|"]
    by = j.exits.groupby("symbol")["pnl"]
    for sym, g in sorted(by, key=lambda kv: kv[1].sum()):
        lines.append(f"| {sym} | {len(g)} | {(g > 0).mean():.0%} | {g.sum():+,.2f} |")
    lines += ["", "## Pe luni", "", "| Lună | Net din trading |", "|---|---|"]
    tr = j.ledger[j.ledger["type"].isin(TRADING)]
    for m, g in tr.groupby(tr["time"].dt.strftime("%Y-%m")):
        lines.append(f"| {m} | {g['amount'].sum():+,.2f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    from apps.futures.exchange import BinanceFuturesReader
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--allow-trading-key", action="store_true")
    a = ap.parse_args()
    r = BinanceFuturesReader(allow_trading_key=a.allow_trading_key)
    print("cheie:", r.check_key())
    since = datetime.now(timezone.utc) - timedelta(days=a.days)
    j = build_journal(r.income(int(since.timestamp() * 1000)))
    md = markdown(j, a.days, r.equity())
    out = ROOT / "context" / "Futures_Journal.md"
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"salvat: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
