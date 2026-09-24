"""Paper runner. Every 15m candle, for each symbol:

  1. read control file (pause / kill / risk override set from Telegram)
  2. manage open positions: stops, targets, time stop, trailing, Jev exit advice (tighten/flatten only)
  3. if flat: strategy signal -> snapshot -> words -> Jev -> policy -> hard risk -> simulated fill
  4. log decision triple + fill in the outcome of the previous decision (price 15m later)
  5. persist state, write ledger, notify Telegram

Paper only. There is no live order path in this file; see docs/LIVE_CHECKLIST.md.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from apps.backtest.engine import bar_exit
from apps.common.config import PolicyThresholds
from apps.features.snapshot import build_snapshot
from apps.features.words import state_text
from apps.jev.client import JevClient
from apps.policy.engine import compose_entry, compose_exit
from apps.risk.engine import (AccountState, Action, Candidate, Position, RiskLimits, circuit_breakers,
                              correlation_mult, evaluate_entry, manual_kill, stoploss_guard, tighten_only)
from apps.strategy.trend_pullback import StrategyParams, indicators, row_to_signal
from apps.trader.notify import Notifier

ROOT = Path(__file__).resolve().parents[2]
BAR = pd.Timedelta("15min")
JEV_KIND = {"regime": "choice", "setup_quality": "score"}   # the rest are noul
STRATEGY_ID = "trend_pullback"


def _version(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:8]


def config_version() -> str:
    """Hash of the three config files: every logged decision says which rules produced it."""
    cfg = ROOT / "config"
    return _version([(cfg / n).read_text() for n in ("risk.yaml", "policy.yaml", "buckets.yaml")])


def hourly_corr(a, b, hours: int = 168) -> float | None:
    ra = a["close"].resample("1h").last().pct_change().iloc[-hours:]
    rb = b["close"].resample("1h").last().pct_change().iloc[-hours:]
    j = pd.concat([ra, rb], axis=1).dropna()
    return float(j.iloc[:, 0].corr(j.iloc[:, 1])) if len(j) >= 24 else None


class Runner:
    def __init__(self, source, symbols: list[str], *, jev: JevClient, notifier: Notifier,
                 base: Path = ROOT, starting_equity: float = 500.0, now: datetime | None = None):
        self.src, self.symbols, self.jev, self.tg = source, symbols, jev, notifier
        self.limits, self.policy, self.params = RiskLimits.load(), PolicyThresholds.load(), StrategyParams()
        self.data, self.logs, self.ctx = base / "data", base / "logs", base / "context"
        for d in (self.data, self.logs, self.ctx):
            d.mkdir(parents=True, exist_ok=True)
        self.state_path, self.control_path = self.data / "state.json", self.data / "control.json"
        self.versions = {"strategy_id": STRATEGY_ID, "strategy_version": _version(asdict(self.params)),
                         "config_version": config_version()}
        self._load(starting_equity, now or datetime.now(timezone.utc))

    # ------------------------------------------------------------------ persistence
    def _load(self, eq: float, now: datetime) -> None:
        if self.state_path.exists():
            s = json.loads(self.state_path.read_text())
            self.cash = s["cash"]
            self.acct = AccountState(**{k: v for k, v in s["acct"].items() if k not in ("paused_until", "open_symbols")},
                                     paused_until=datetime.fromisoformat(s["acct"]["paused_until"]) if s["acct"]["paused_until"] else None)
            self.positions = {k: Position(**{**p, "opened_at": datetime.fromisoformat(p["opened_at"])})
                              for k, p in s["positions"].items()}
            self.meta, self.cooldown = s["meta"], {k: datetime.fromisoformat(v) for k, v in s["cooldown"].items()}
            self.day, self.week, self.trades = s["day"], s["week"], s["trades"]
            self.pending = s.get("pending", [])
            self.stop_times = [datetime.fromisoformat(t) for t in s.get("stop_times", [])]
        else:
            self.cash = eq
            self.acct = AccountState(eq, eq, eq, eq, eq)
            self.positions, self.meta, self.cooldown, self.trades, self.pending = {}, {}, {}, 0, []
            self.stop_times = []
            self.day, self.week = now.date().isoformat(), list(now.isocalendar()[:2])
            self.tg.send(f"🟢 Bot pornit în PAPER. Capital virtual: {eq:.2f} USDT. Simboluri: {', '.join(self.symbols)}")

    def _save(self) -> None:
        a = asdict(self.acct)
        a["paused_until"] = self.acct.paused_until.isoformat() if self.acct.paused_until else None
        a["open_symbols"] = sorted(self.acct.open_symbols)
        self.state_path.write_text(json.dumps({
            "mode": "paper", "cash": self.cash, "acct": a, "day": self.day, "week": self.week, "trades": self.trades,
            "positions": {k: {**asdict(p), "opened_at": p.opened_at.isoformat()} for k, p in self.positions.items()},
            "meta": self.meta, "cooldown": {k: v.isoformat() for k, v in self.cooldown.items()},
            "pending": self.pending, "stop_times": [t.isoformat() for t in self.stop_times[-20:]],
            "jev_last": self.jev.last.as_log() if self.jev.last else None,
        }, indent=1, default=str))

    def _control(self) -> dict:
        try:
            return json.loads(self.control_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _log(self, rec: dict) -> None:
        with open(self.logs / "decisions.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")

    # ------------------------------------------------------------------ one tick
    def step(self, now: datetime) -> None:
        ctl = self._control()
        if ctl.get("kill") and not self.acct.killed:
            manual_kill(self.acct, "Telegram /kill")
            self.tg.send("🛑 KILL. Nicio intrare nouă. Botul trebuie repornit manual.")
        self.acct.risk_per_trade_pct = ctl.get("risk_per_trade_pct")

        frames = {s: self.src.candles(s, now) for s in self.symbols}
        prices = {s: float(f["close"].iloc[-1]) for s, f in frames.items()}
        self._roll_periods(now)
        self._resolve_pending(prices)
        self._mark(prices)

        for sym in self.symbols:
            df = frames[sym]
            bar = df.iloc[-1]
            if sym in self.positions:
                self._manage(sym, df, bar, now)

        breaker = circuit_breakers(self.acct, self.limits, now)
        if breaker and breaker.action is Action.KILL and not ctl.get("kill_notified"):
            self.tg.send(f"🛑 KILL automat: {breaker.reasons[0]}")
            ctl["kill_notified"] = True
            self.control_path.write_text(json.dumps(ctl))
        paused = bool(ctl.get("paused")) or (breaker is not None)
        guard = stoploss_guard(self.stop_times, now, self.limits)
        if guard and ctl.get("guard_notified") != guard.isoformat():
            self.tg.send(f"⚠️ {self.limits.stoploss_guard_trades} stopuri în "
                         f"{self.limits.stoploss_guard_lookback_min // 60}h → fără intrări noi până la {guard:%H:%M} UTC")
            ctl["guard_notified"] = guard.isoformat()
            self.control_path.write_text(json.dumps(ctl))
        paused = paused or guard is not None

        for sym in self.symbols:
            if sym in self.positions or paused:
                continue
            if sym in self.cooldown and now < self.cooldown[sym]:
                continue
            self._consider_entry(sym, frames, now)

        self._mark(prices)
        self._save()

    # ------------------------------------------------------------------ pieces
    def _roll_periods(self, now: datetime) -> None:
        eq = self.acct.equity
        if now.date().isoformat() != self.day:
            if self.trades:
                self.tg.send(f"📅 Ziua {self.day}: P&L {eq - self.acct.day_start_equity:+.2f} USDT · capital {eq:.2f}")
            self.day, self.acct.day_start_equity = now.date().isoformat(), eq
        if list(now.isocalendar()[:2]) != self.week:
            self.week, self.acct.week_start_equity = list(now.isocalendar()[:2]), eq

    def _mark(self, prices: dict[str, float]) -> None:
        inv = sum(p.stake_usd / p.entry * prices[s] for s, p in self.positions.items())
        self.acct.inventory_usd = inv
        self.acct.equity = self.cash + inv
        self.acct.peak_equity = max(self.acct.peak_equity, self.acct.equity)
        self.acct.open_positions = len(self.positions)
        self.acct.open_symbols = frozenset(self.positions)

    def _resolve_pending(self, prices: dict[str, float]) -> None:
        """Calibration data: what the price did 15m after each logged decision."""
        for p in self.pending:
            px = prices.get(p["symbol"])
            if px:
                self._log({"type": "outcome", "decision_id": p["id"], "symbol": p["symbol"],
                           "ret_15m": px / p["px"] - 1})
        self.pending = []

    def _manage(self, sym: str, df, bar, now: datetime) -> None:
        pos = self.positions[sym]
        stop_before = pos.stop
        px, why = bar_exit(pos, bar["open"], bar["high"], bar["low"], bar["close"], now, self.limits)
        if px is None and stop_before < pos.entry <= pos.stop:      # announce once, not every trailing tick
            self.tg.send(f"🔒 {sym}: trailing stop la {pos.stop:.2f}, peste intrare → tranzacția nu mai poate pierde")
        if px is None:
            snap = build_snapshot(sym, df, position={"inventory_usd": pos.stake_usd,
                                  "unrealized_pnl_pct": bar["close"] / pos.entry - 1,
                                  "age_min": (now - pos.opened_at).total_seconds() / 60})
            advice = compose_exit(self.jev.ask(state_text(snap), candidate_signal=False, in_position=True), self.policy)
            if advice.action == "flatten":
                px, why = bar["close"] * (1 - self.limits.slippage_pct), f"Jev flatten ({advice.reason})"
            elif advice.action in ("tighten", "reduce"):      # paper has no partial exits: reduce == tighten
                new = tighten_only(pos, max(pos.stop, bar["close"] - 0.5 * pos.r_value))
                if new.stop > pos.stop:
                    self.positions[sym] = new
                    self.tg.send(f"🔒 {sym}: stop ridicat la {new.stop:.2f} (Jev: {advice.action})")
        if px is None:
            return
        qty = pos.stake_usd / pos.entry
        proceeds = qty * px
        fee_out = proceeds * self.limits.taker_fee_pct
        pnl = proceeds - fee_out - pos.stake_usd - self.meta[sym]["fee_in"]
        self.cash += proceeds - fee_out
        self.acct.realized_pnl_total += pnl
        self.trades += 1
        if pnl <= 0:
            self.cooldown[sym] = now + timedelta(minutes=15 * self.limits.cooldown_bars_after_loss)
            if why == "stop":
                self.stop_times.append(now)
        del self.positions[sym]
        m = self.meta.pop(sym)
        emoji = "✅" if pnl > 0 else "❌"
        self.tg.send(f"{emoji} IEȘIRE {sym} @ {px:.2f} · {why} · P&L {pnl:+.2f} USDT ({pnl / pos.stake_usd:+.2%})")
        with open(self.ctx / "Trade_Ledger.md", "a", encoding="utf-8") as fh:
            if fh.tell() == 0:
                fh.write("# Trade Ledger (paper)\n\n| # | Simbol | Intrare | Ieșire | Preț in | Preț out | Mărime | Stop | Target | Motiv ieșire | Jev | P&L |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n")
            fh.write(f"| {self.trades} | {sym} | {pos.opened_at:%Y-%m-%d %H:%M} | {now:%Y-%m-%d %H:%M} | {pos.entry:.2f} | {px:.2f} | "
                     f"{pos.stake_usd:.2f} | {pos.initial_stop:.2f} | {pos.take:.2f} | {why} | {m['fallback']} | {pnl:+.2f} |\n")
        level = {"stop": pos.stop, "target": pos.take}.get(why, float(bar["close"]))
        self._log({"type": "exit", "t": now, "symbol": sym, "decision_id": m.get("decision_id"), "price": px,
                   "expected_price": level, "slippage_bps": (level / px - 1) * 1e4 if px else None,
                   "reason": why, "pnl": pnl, **self.versions})

    def _consider_entry(self, sym: str, frames: dict, now: datetime) -> None:
        df = frames[sym]
        row = indicators(df, self.params).iloc[-1]
        if not bool(row["signal"]):
            return
        sig = row_to_signal(row, self.params)
        book = self.src.book(sym, now)
        data_age = max(0.0, (now - (df.index[-1] + BAR).to_pydatetime()).total_seconds())
        snap = build_snapshot(sym, df, book=book, signal=sig, data_age_sec=data_age,
                              account={"daily_pnl_pct": self.acct.daily_pnl_pct, "drawdown_pct": self.acct.drawdown_pct})
        words = state_text(snap)
        jev = self.jev.ask(words, candidate_signal=True, in_position=False)
        dec = compose_entry(snap, jev, self.policy)
        rec = {"type": "decision", "id": f"{sym}-{snap.ts}", "t": now, "symbol": sym, "snapshot_ts": snap.ts,
               "words": words, "jev_status": jev.status, "jev_model": jev.model, "jev_latency_ms": jev.latency_ms,
               "jev_answers": None, "policy": dec.action, "policy_fallback": dec.fallback,
               "policy_reasons": dec.reasons, "risk_mult": dec.risk_mult, **self.versions}
        if jev.ok:
            # typed dicts, readable by parse_answers -> backtest mode B replays exactly these answers
            rec["jev_answers"] = {k: {**asdict(getattr(jev, k)), "type": JEV_KIND.get(k, "noul")} for k in
                                  ("regime", "setup_quality", "aligned_with_signal", "toxic_or_unstable") if getattr(jev, k)}
        if jev.status == "timeout":
            self.tg.send(f"⏱️ {sym}: Jev a răspuns prea târziu ({jev.latency_ms}ms) → HOLD")

        if dec.action != "enter":
            rec["action"] = "skip"
            self._log(rec)
            self.pending.append({"id": rec["id"], "symbol": sym, "px": book["mid"]})
            return
        corr = max((c for c in (hourly_corr(df, frames[o]) for o in self.positions) if c is not None), default=None)
        mult = dec.risk_mult * correlation_mult(corr, self.limits)
        fill = book["ask"] * (1 + self.limits.slippage_pct)
        v = evaluate_entry(self.acct, self.limits, Candidate(sym, fill, sig["stop"], sig["take"], book["spread_bps"],
                                                             data_age), now, risk_mult=mult)
        rec.update(risk=v.action.value, risk_reasons=v.reasons, stake=v.stake_usd, corr_with_open=corr,
                   risk_mult=mult, expected_price=book["mid"], fill=fill, slippage_bps=(fill / book["mid"] - 1) * 1e4)
        if not v.allowed:
            rec["action"] = "skip"
            self._log(rec)
            return
        fee_in = v.stake_usd * self.limits.taker_fee_pct
        self.cash -= v.stake_usd + fee_in
        self.positions[sym] = Position(sym, fill, v.stop, v.take, v.stake_usd, now)
        self.meta[sym] = {"fee_in": fee_in, "fallback": dec.fallback, "decision_id": rec["id"]}
        rec["action"] = "enter"
        self._log(rec)
        self.pending.append({"id": rec["id"], "symbol": sym, "px": fill})
        size_note = ""
        if mult < 1:
            why_small = dec.fallback if dec.risk_mult < 1 else f"corelat {corr:.2f} cu o poziție deschisă"
            size_note = f" · mărime ×{mult:g} ({why_small})"
        self.tg.send(f"🟦 INTRARE {sym} @ {fill:.2f} · {v.stake_usd:.2f} USDT · stop {v.stop:.2f} (−{v.stop_pct:.1%}) · "
                     f"target {v.take:.2f} · R:R {v.reward_risk}{size_note} · Jev: {jev.status}")

