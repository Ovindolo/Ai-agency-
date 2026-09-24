"""Event backtester for STRATEGY + POLICY + RISK. It does not test whether Jev predicts price.

Honesty rules:
  * Decisions use bar i (closed). Orders fill at bar i+1 OPEN, with slippage and taker fee.
  * If stop and target are both inside one bar, the STOP is assumed to fill first.
  * Every run reports buy-and-hold over the same bars. A strategy that loses to holding is not an edge.
  * Mode B replays RECORDED Jev answers only. Missing answers fall back to rules and are counted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from apps.common.config import PolicyThresholds
from apps.features.snapshot import build_snapshot
from apps.jev.client import JevResult
from apps.policy.engine import compose_entry
from apps.risk.engine import AccountState, Action, Candidate, Position, RiskLimits, evaluate_entry, manage_position, stoploss_guard
from apps.strategy.trend_pullback import StrategyParams, indicators, row_to_signal

WINDOW = 1000          # bars of history per snapshot; the paper runner fetches the same amount


class _SignalOnly:
    strategy_side = "long"


_RULES_ONLY_SNAP = _SignalOnly()
_RULES_ONLY_JEV = JevResult(status="disabled", error="rules-only run")


def bar_exit(pos: Position, o: float, h: float, l: float, c: float, t: datetime, limits: RiskLimits) -> tuple[float | None, str]:
    """Exit price and reason for one bar, or (None, "") to keep holding. Stop wins ties."""
    slip = limits.slippage_pct
    if l <= pos.stop:
        return min(o, pos.stop) * (1 - slip), "stop"          # gap below stop fills at the open
    if h >= pos.take:
        return pos.take * (1 - slip), "target"
    d = manage_position(pos, c, t, limits)
    if d.action == "exit":
        return c * (1 - slip), d.reason
    if d.action == "tighten" and d.new_stop:
        pos.stop = max(pos.stop, d.new_stop)
    return None, ""


@dataclass
class Trade:
    symbol: str
    entry_time: datetime
    exit_time: datetime
    entry: float
    exit: float
    stake: float
    fees: float
    pnl: float
    reason: str
    risk_mult: float
    fallback: str


@dataclass
class Report:
    label: str
    trades: list[Trade] = field(default_factory=list)
    equity_curve: pd.Series | None = None
    start_equity: float = 500.0
    bars: int = 0
    signals: int = 0
    vetoed_by_policy: int = 0
    vetoed_by_risk: int = 0
    jev_coverage: float | None = None
    hold_return: float = 0.0
    hold_max_dd: float = 0.0
    min_trades: int = 80

    # ---------------- metrics
    @property
    def n(self) -> int: return len(self.trades)
    @property
    def wins(self) -> list[Trade]: return [t for t in self.trades if t.pnl > 0]
    @property
    def losses(self) -> list[Trade]: return [t for t in self.trades if t.pnl <= 0]
    @property
    def net(self) -> float: return sum(t.pnl for t in self.trades)
    @property
    def fees(self) -> float: return sum(t.fees for t in self.trades)
    @property
    def profit_factor(self) -> float:
        gl = -sum(t.pnl for t in self.losses)
        return float("inf") if gl == 0 and self.wins else (sum(t.pnl for t in self.wins) / gl if gl else 0.0)
    @property
    def max_dd(self) -> float:
        if self.equity_curve is None or self.equity_curve.empty:
            return 0.0
        e = self.equity_curve
        return float(((e.cummax() - e) / e.cummax()).max())
    @property
    def net_without_top3(self) -> float:
        return self.net - sum(sorted((t.pnl for t in self.trades), reverse=True)[:3])

    def gates(self) -> dict[str, tuple[bool, str]]:
        return {
            "profit_factor >= 1.2": (self.profit_factor >= 1.2, f"{self.profit_factor:.2f}"),
            "max drawdown <= 20%": (self.max_dd <= 0.20, f"{self.max_dd:.1%}"),
            f"trades >= {self.min_trades}": (self.n >= self.min_trades, str(self.n)),
            "not owned by top 3 trades": (self.net_without_top3 > 0, f"net without top 3: {self.net_without_top3:+.2f}"),
            "beats buy-and-hold": (self.net / self.start_equity > self.hold_return, f"{self.net/self.start_equity:+.1%} vs {self.hold_return:+.1%}"),
        }

    @property
    def passed(self) -> bool:
        g = self.gates()
        # the first four are the spec's hard gates; buy-and-hold is reported, not required
        return all(ok for name, (ok, _) in g.items() if name != "beats buy-and-hold")

    def markdown(self) -> str:
        w, l = self.wins, self.losses
        avg_w = np.mean([t.pnl for t in w]) if w else 0.0
        avg_l = np.mean([t.pnl for t in l]) if l else 0.0
        rows = "\n".join(f"| {name} | {'PASS' if ok else 'FAIL'} | {val} |" for name, (ok, val) in self.gates().items())
        cov = "" if self.jev_coverage is None else f"| Jev answers available | {self.jev_coverage:.0%} of signals |\n"
        return f"""# Backtest — {self.label}

**Verdict: {'PASS' if self.passed else 'FAIL'}** (buy-and-hold comparison is reported, not gated)

| Metric | Value |
|---|---|
| Bars | {self.bars} |
| Signals | {self.signals} |
| Vetoed by policy | {self.vetoed_by_policy} |
| Vetoed by risk | {self.vetoed_by_risk} |
{cov}| Trades | {self.n} |
| Win rate | {(len(w)/self.n if self.n else 0):.1%} |
| Avg win / avg loss | {avg_w:+.2f} / {avg_l:+.2f} |
| Net P&L after fees | {self.net:+.2f} ({self.net/self.start_equity:+.2%}) |
| Fees paid | {self.fees:.2f} |
| Profit factor | {self.profit_factor:.2f} |
| Max drawdown | {self.max_dd:.1%} |
| **Buy-and-hold, same bars** | **{self.hold_return:+.2%}** (max DD {self.hold_max_dd:.1%}) |

| Gate | Result | Value |
|---|---|---|
{rows}
"""


def _jev_from_record(rec: dict | None) -> JevResult:
    if not rec:
        return JevResult(status="disabled", error="no recorded answer")
    from apps.jev.client import parse_answers
    return JevResult(status="ok", model=rec.get("model"), **parse_answers(rec["answers"]))


def run_backtest(df15: pd.DataFrame, symbol: str, *, label: str, limits: RiskLimits | None = None,
                 thresholds: PolicyThresholds | None = None, params: StrategyParams | None = None,
                 start_equity: float = 500.0, jev_records: dict[str, dict] | None = None,
                 use_jev: bool = False, signal_frame: pd.DataFrame | None = None) -> Report:
    """signal_frame: optional precomputed frame with columns signal/entry/stop/take/stop_pct
    (e.g. an imported strategy's entries + our exits). Defaults to the built-in strategy."""
    limits = limits or RiskLimits()
    thresholds = thresholds or PolicyThresholds()
    params = params or StrategyParams()
    rep = Report(label=label, start_equity=start_equity)

    o, h, l, c = (df15[k].to_numpy() for k in ("open", "high", "low", "close"))
    idx = df15.index
    cash = start_equity
    pos: Position | None = None
    pos_meta: dict = {}
    cooldown_until = -1
    stop_times: list[datetime] = []
    st = AccountState(start_equity, start_equity, start_equity, start_equity, start_equity)
    equity_points: list[tuple[datetime, float]] = []
    day, week = None, None
    jev_hits = jev_asked = 0
    slip, fee = limits.slippage_pct, limits.taker_fee_pct

    ind = signal_frame if signal_frame is not None else indicators(df15, params)
    sig_flags = ind["signal"].to_numpy()
    warmup = min(params.min_hours * 4, len(df15) - 2)
    for i in range(warmup, len(df15) - 1):
        t = idx[i].to_pydatetime()
        mark = cash + (pos.stake_usd / pos.entry * c[i] if pos else 0.0)
        st.equity = mark
        st.peak_equity = max(st.peak_equity, mark)
        if day != t.date():
            day, st.day_start_equity = t.date(), mark
        if week != t.isocalendar()[:2]:
            week, st.week_start_equity = t.isocalendar()[:2], mark
        equity_points.append((t, mark))

        # ---------- manage open position on the CURRENT bar's range
        if pos is not None:
            exit_px, why = bar_exit(pos, o[i], h[i], l[i], c[i], t, limits)
            if exit_px is not None:
                qty = pos.stake_usd / pos.entry
                proceeds = qty * exit_px
                exit_fee = proceeds * fee
                pnl = proceeds - exit_fee - pos.stake_usd - pos_meta["entry_fee"]
                cash += proceeds - exit_fee
                rep.trades.append(Trade(symbol, pos.opened_at, t, pos.entry, exit_px, pos.stake_usd,
                                        pos_meta["entry_fee"] + exit_fee, pnl, why, pos_meta["mult"], pos_meta["fb"]))
                st.realized_pnl_total += pnl
                if pnl <= 0:
                    cooldown_until = i + limits.cooldown_bars_after_loss
                    if why == "stop":
                        stop_times.append(t)
                pos = None
                st.open_positions, st.inventory_usd, st.open_symbols = 0, 0.0, frozenset()
                st.equity = cash
            else:
                st.inventory_usd = pos.stake_usd / pos.entry * c[i]
            continue   # v1: one position per symbol, no pyramiding

        if i < cooldown_until:
            continue
        if not sig_flags[i]:
            continue
        if stoploss_guard(stop_times, t, limits):
            rep.signals += 1
            rep.vetoed_by_risk += 1
            continue
        sig = row_to_signal(ind.iloc[i], params)
        rep.signals += 1
        window = df15.iloc[max(0, i - WINDOW + 1): i + 1]

        if use_jev:
            snap = build_snapshot(symbol, window, signal=sig,
                                  account={"daily_pnl_pct": st.daily_pnl_pct, "drawdown_pct": st.drawdown_pct})
            jev_asked += 1
            rec = (jev_records or {}).get(snap.ts)
            jev_hits += rec is not None
            dec = compose_entry(snap, _jev_from_record(rec), thresholds)
        else:
            # rules-only: the snapshot's only consumers are Jev and its logs, so don't build it
            dec = compose_entry(_RULES_ONLY_SNAP, _RULES_ONLY_JEV, thresholds)
        if dec.action != "enter":
            rep.vetoed_by_policy += 1
            continue

        fill = o[i + 1] * (1 + slip)                   # next bar open
        cand = Candidate(symbol, fill, sig["stop"], sig["take"], spread_bps=1.0, data_age_sec=0)
        v = evaluate_entry(st, limits, cand, idx[i + 1].to_pydatetime(), risk_mult=dec.risk_mult)
        if v.action is not Action.ALLOW:
            rep.vetoed_by_risk += 1
            continue
        entry_fee = v.stake_usd * fee
        cash -= v.stake_usd + entry_fee
        pos = Position(symbol, fill, v.stop, v.take, v.stake_usd, idx[i + 1].to_pydatetime())
        pos_meta = {"entry_fee": entry_fee, "mult": dec.risk_mult, "fb": dec.fallback}
        st.open_positions, st.inventory_usd, st.open_symbols = 1, v.stake_usd, frozenset({symbol})

    rep.bars = len(df15) - warmup
    rep.equity_curve = pd.Series(dict(equity_points)) if equity_points else pd.Series(dtype=float)
    hold = pd.Series(c[warmup:], index=idx[warmup:])
    rep.hold_return = float(hold.iloc[-1] / hold.iloc[0] - 1) if len(hold) > 1 else 0.0
    rep.hold_max_dd = float(((hold.cummax() - hold) / hold.cummax()).max()) if len(hold) > 1 else 0.0
    if use_jev:
        rep.jev_coverage = jev_hits / jev_asked if jev_asked else 0.0
    return rep
