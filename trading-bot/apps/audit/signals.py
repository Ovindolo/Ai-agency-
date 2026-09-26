"""Signal-group auditor: what would each paid group's calls have actually made, after costs?

It never trades. It replays every signal the operator forwards against real candles:
  - the entry fills only if price reaches it within `entry_hours` (market entries fill at the next open)
  - after a fill, each 15m bar is checked; if stop and a target are both inside one bar, the STOP counts
    (a candle does not say which came first; groups' screenshots always assume the good order)
  - position split equally across the targets; after TP1 the stop moves to entry (the usual convention)
  - leverage multiplies the result on margin; if price reaches the liquidation price before the stop,
    the whole margin is lost
  - futures fees (taker both sides by default), slippage and funding are charged
  - still open after `max_days`: closed at market

Input (CSV, one row per signal):
  group,time,symbol,side,entry,stop,targets,leverage
  VIPGroup,2026-09-01 14:00,BTC/USDT,long,61500,60200,62500|63500|65000,10
`entry` may be "market". `time` is UTC. `targets` separated by "|".

  python -m apps.audit.signals semnale.csv --fetch        # downloads candles (public API, no key)
  python -m apps.audit.signals semnale.csv --fee 50        # monthly subscription, per group, in USD

Results are per signal on margin, and for a fixed 1% of a 500 account at risk per signal.
Signals are only as honest as the log: forward them BEFORE the move, not after.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class Costs:
    fee_pct: float = 0.0005            # Binance USD-M VIP0 taker 0.05% (maker 0.02%)
    slippage_pct: float = 0.0005
    funding_pct_8h: float = 0.0001     # default 0.01% per 8h paid by longs; real history replaces it when given
    mmr: float = 0.005                 # maintenance margin rate (BTC tier 1 ~0.4%, alts higher)
    entry_hours: float = 24.0
    max_days: float = 7.0


@dataclass(frozen=True)
class Signal:
    group: str
    time: datetime
    symbol: str
    side: str
    entry: float | None                # None = market
    stop: float
    targets: tuple[float, ...]
    leverage: float = 1.0


@dataclass
class Outcome:
    signal: Signal
    status: str = "unfilled"           # unfilled | closed | liquidated | invalid | no_data
    fill: float | None = None
    exits: list[tuple[str, float]] = field(default_factory=list)
    move_pct: float = 0.0              # price result of the whole position, before leverage and costs
    margin_pct: float = 0.0            # result on margin after leverage and costs (-1.0 = margin gone)
    r: float = 0.0                     # result in units of the risk the stop implied

    @property
    def filled(self) -> bool:
        return self.status in ("closed", "liquidated")


def parse(path: Path) -> list[Signal]:
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            t = datetime.fromisoformat(row["time"].strip())
            t = t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t
            entry = row["entry"].strip().lower()
            out.append(Signal(row["group"].strip(), t, row["symbol"].strip().upper(), row["side"].strip().lower(),
                              None if entry == "market" else float(entry), float(row["stop"]),
                              tuple(float(x) for x in row["targets"].split("|") if x.strip()),
                              float(row.get("leverage") or 1)))
    return out


def _liq_price(entry: float, lev: float, side: str, mmr: float) -> float:
    """Isolated-margin approximation: margin 1/lev is gone when the adverse move reaches 1/lev - mmr."""
    d = max(1 / lev - mmr, 0.0)
    return entry * (1 - d) if side == "long" else entry * (1 + d)


def evaluate(sig: Signal, candles: pd.DataFrame, costs: Costs = Costs(), funding: pd.Series | None = None) -> Outcome:
    out = Outcome(sig)
    long = sig.side == "long"
    sgn = 1 if long else -1
    if sig.side not in ("long", "short") or not sig.targets or (sig.entry and (sig.stop - sig.entry) * sgn >= 0):
        out.status = "invalid"
        return out
    bars = candles[candles.index >= pd.Timestamp(sig.time)]
    if bars.empty:
        out.status = "no_data"
        return out

    # ---- entry
    i0 = None
    if sig.entry is None:
        i0, fill = 0, float(bars["open"].iloc[0]) * (1 + sgn * costs.slippage_pct)
    else:
        window = bars[bars.index < pd.Timestamp(sig.time + timedelta(hours=costs.entry_hours))]
        hit = (window["low"] <= sig.entry) if long else (window["high"] >= sig.entry)
        if not hit.any():
            return out
        i0, fill = bars.index.get_loc(hit.idxmax()), sig.entry
    out.fill = fill
    liq = _liq_price(fill, sig.leverage, sig.side, costs.mmr)
    stop = sig.stop
    left = list(sig.targets)
    share = 1 / len(sig.targets)
    remaining, move = 1.0, 0.0
    end = bars.index[i0] + pd.Timedelta(days=costs.max_days)

    def adverse(bar) -> float:
        return bar["low"] if long else bar["high"]

    def favorable(bar) -> float:
        return bar["high"] if long else bar["low"]

    for k in range(i0, len(bars)):
        bar = bars.iloc[k]
        t = bars.index[k]
        # the fill bar: only the part after our fill is known, so check only the adverse side
        worst = adverse(bar)
        if (worst <= liq) if long else (worst >= liq):
            if (liq >= stop) if long else (liq <= stop):          # liquidation before the stop
                out.status, out.margin_pct = "liquidated", -1.0
                out.exits.append(("liquidation", liq))
                return _finish(out, sig, costs, fill, move, remaining, t, funding, liquidated=True)
        if (worst <= stop) if long else (worst >= stop):
            px = stop * (1 - sgn * costs.slippage_pct)
            move += remaining * sgn * (px / fill - 1)
            out.exits.append(("stop", px))
            remaining = 0.0
            break
        if k > i0:
            while left and ((favorable(bar) >= left[0]) if long else (favorable(bar) <= left[0])):
                tp = left.pop(0)
                move += share * sgn * (tp / fill - 1)
                remaining -= share
                out.exits.append((f"TP{len(sig.targets) - len(left)}", tp))
                stop = fill                                            # breakeven after the first target
            if not left:
                remaining = 0.0
                break
        if t >= end:
            px = float(bar["close"]) * (1 - sgn * costs.slippage_pct)
            move += remaining * sgn * (px / fill - 1)
            out.exits.append(("timeout", px))
            remaining = 0.0
            break
    else:
        px = float(bars["close"].iloc[-1])
        move += remaining * sgn * (px / fill - 1)
        out.exits.append(("still_open", px))
        remaining = 0.0
    return _finish(out, sig, costs, fill, move, remaining, bars.index[min(k, len(bars) - 1)], funding)


def _finish(out: Outcome, sig: Signal, costs: Costs, fill: float, move: float, remaining: float, t_end,
            funding: pd.Series | None, liquidated: bool = False) -> Outcome:
    hours = max((pd.Timestamp(t_end) - pd.Timestamp(sig.time)).total_seconds() / 3600, 0)
    if funding is not None and len(funding):
        f = funding[(funding.index >= pd.Timestamp(sig.time)) & (funding.index <= pd.Timestamp(t_end))].sum()
    else:
        f = costs.funding_pct_8h * hours / 8
    funding_cost = f if sig.side == "long" else -f             # positive funding: longs pay shorts
    out.move_pct = move
    if not liquidated:
        out.status = "closed"
        out.margin_pct = max(-1.0, sig.leverage * (move - 2 * costs.fee_pct - funding_cost))
    risk = abs(fill - sig.stop) / fill
    out.r = (move - 2 * costs.fee_pct - funding_cost) / risk if risk > 0 else 0.0
    if liquidated:
        out.r = -1 / (risk * sig.leverage) if risk > 0 else -1.0
    return out


@dataclass
class GroupStats:
    group: str
    outcomes: list[Outcome]
    monthly_fee: float = 0.0

    @property
    def filled(self) -> list[Outcome]:
        return [o for o in self.outcomes if o.filled]

    def row(self, account: float = 500.0, risk_pct: float = 0.01) -> dict:
        f = self.filled
        rs = [o.r for o in f]
        wins = [r for r in rs if r > 0]
        gl = -sum(r for r in rs if r <= 0)
        streak = worst = 0
        for r in rs:
            streak = streak + 1 if r <= 0 else 0
            worst = max(worst, streak)
        months = 1.0
        if self.outcomes:
            span = max(o.signal.time for o in self.outcomes) - min(o.signal.time for o in self.outcomes)
            months = max(span.days / 30.4, 1.0)
        usd = sum(rs) * account * risk_pct
        return {"group": self.group, "signals": len(self.outcomes), "filled": len(f),
                "liquidated": sum(o.status == "liquidated" for o in f),
                "win_rate": len(wins) / len(f) if f else 0.0,
                "pf": sum(wins) / gl if gl else float("inf"), "avg_r": sum(rs) / len(rs) if rs else 0.0,
                "worst_streak": worst, "usd_at_1pct": usd, "subscription": self.monthly_fee * months,
                "net_usd": usd - self.monthly_fee * months}


def report(groups: list[GroupStats]) -> str:
    lines = ["| Grup | Semnale | Umplute | Lichidate | Câștigate | PF | Medie R | Cea mai lungă serie de pierderi | "
             "$ la 1% risc | Abonament | Net |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for g in groups:
        r = g.row()
        lines.append(f"| {r['group']} | {r['signals']} | {r['filled']} | {r['liquidated']} | {r['win_rate']:.0%} | "
                     f"{r['pf']:.2f} | {r['avg_r']:+.2f} | {r['worst_streak']} | {r['usd_at_1pct']:+.2f} | "
                     f"{r['subscription']:.2f} | **{r['net_usd']:+.2f}** |")
    lines.append("\nSub 30 de semnale umplute pe grup, rezultatul e încă zgomot.")
    return "\n".join(lines)


def audit(signals: list[Signal], candles: dict[str, pd.DataFrame], costs: Costs = Costs(),
          funding: dict[str, pd.Series] | None = None, monthly_fee: float = 0.0) -> list[GroupStats]:
    by_group: dict[str, list[Outcome]] = {}
    for s in signals:
        o = evaluate(s, candles.get(s.symbol, pd.DataFrame()), costs, (funding or {}).get(s.symbol)) \
            if s.symbol in candles else Outcome(s, status="no_data")
        by_group.setdefault(s.group, []).append(o)
    return [GroupStats(g, os, monthly_fee) for g, os in sorted(by_group.items())]


def fetch(symbol: str, start: datetime, days: float, exchange: str = "binanceusdm") -> tuple[pd.DataFrame, pd.Series]:
    """15m candles and funding history from public futures endpoints (no key)."""
    import ccxt
    ex = getattr(ccxt, exchange)({"enableRateLimit": True})
    since = int(start.timestamp() * 1000)
    until = since + int(days * 86_400_000)
    rows = []
    while since < until:
        batch = ex.fetch_ohlcv(symbol, "15m", since=since, limit=1000)
        if not batch:
            break
        rows += batch
        since = batch[-1][0] + 1
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"]).drop_duplicates("ts")
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("ts"), unit="ms", utc=True))
    fr = ex.fetch_funding_rate_history(symbol, since=int(start.timestamp() * 1000), limit=1000)
    funding = pd.Series({pd.Timestamp(x["timestamp"], unit="ms", tz="UTC"): x["fundingRate"] for x in fr}, dtype=float)
    return df, funding


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--fetch", action="store_true", help="download candles + funding from Binance futures")
    ap.add_argument("--fee", type=float, default=0.0, help="monthly subscription per group, USD")
    a = ap.parse_args()
    sigs = parse(Path(a.csv))
    costs = Costs()
    candles, funding = {}, {}
    if a.fetch:
        for sym in sorted({s.symbol for s in sigs}):
            first = min(s.time for s in sigs if s.symbol == sym)
            last = max(s.time for s in sigs if s.symbol == sym)
            days = (last - first).days + costs.max_days + costs.entry_hours / 24 + 1
            candles[sym], funding[sym] = fetch(sym, first, days)
    print(report(audit(sigs, candles, costs, funding, a.fee)))


if __name__ == "__main__":
    main()
