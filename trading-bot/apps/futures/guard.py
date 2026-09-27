"""Futures guard: watches the operator's MANUAL futures positions and warns on Telegram. Never trades.

Alerts:
  no_stop      a position without a protective stop (trigger on the losing side of the mark price)
  partial_stop the stops cover only part of the position
  risk         loss at the stop > max_risk_per_trade_pct of equity
  leverage     position leverage > max_leverage
  liq          mark price within min_liq_distance_pct of liquidation
  exposure     total notional > max_exposure_x times equity
  daily_loss   realized today + unrealized < -max_daily_loss_pct of the day's starting equity

  python -m apps.futures.guard            # every poll_seconds
  python -m apps.futures.guard --once     # one check (cron)
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apps.common.config import build, load_yaml
from apps.futures.models import FPosition, StopOrder, protective_stops

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class GuardConfig:
    max_leverage: float = 5
    max_exposure_x: float = 3.0
    max_risk_per_trade_pct: float = 0.02
    max_daily_loss_pct: float = 0.03
    min_liq_distance_pct: float = 0.10
    repeat_minutes: int = 60
    poll_seconds: int = 60

    @classmethod
    def load(cls) -> "GuardConfig":
        return build(cls, load_yaml("guard.yaml"))


@dataclass(frozen=True)
class Alert:
    key: str                    # stable id for de-duplication, e.g. "no_stop:BTCUSDT:long"
    text: str
    severity: str = "warn"      # warn | danger


def _usd(x: float) -> str:
    return f"{x:,.2f}$"


def check(positions: list[FPosition], stops: list[StopOrder], equity: float, day_pnl: float,
          cfg: GuardConfig) -> list[Alert]:
    alerts: list[Alert] = []
    eq = max(equity, 1e-9)
    for p in positions:
        tag = f"{p.symbol} {p.side.upper()}"
        k = f"{p.symbol}:{p.side}"
        mine = protective_stops(p, stops)
        if not mine:
            if p.liq:
                loss = p.qty * abs(p.entry - p.liq)
                alerts.append(Alert(f"no_stop:{k}", f"🚨 {tag}: FĂRĂ STOP-LOSS. Până la lichidare ({p.liq:,.4g}) poți "
                                    f"pierde ~{_usd(loss)} ({loss / eq:.0%} din cont).", "danger"))
            else:
                alerts.append(Alert(f"no_stop:{k}", f"🚨 {tag}: FĂRĂ STOP-LOSS.", "danger"))
        else:
            covered = sum(p.qty if o.qty is None else o.qty for o in mine)
            if covered < p.qty * 0.99:
                alerts.append(Alert(f"partial_stop:{k}", f"⚠️ {tag}: stopul acoperă doar {covered / p.qty:.0%} din poziție."))
            worst = min(mine, key=lambda o: o.trigger) if p.side == "long" else max(mine, key=lambda o: o.trigger)
            loss = max(0.0, (p.entry - worst.trigger) * p.qty if p.side == "long" else (worst.trigger - p.entry) * p.qty)
            if loss / eq > cfg.max_risk_per_trade_pct:
                alerts.append(Alert(f"risk:{k}", f"⚠️ {tag}: la stop ({worst.trigger:,.4g}) pierzi {_usd(loss)} = "
                                    f"{loss / eq:.1%} din cont (limita ta: {cfg.max_risk_per_trade_pct:.0%})."))
        if p.leverage and p.leverage > cfg.max_leverage:
            alerts.append(Alert(f"leverage:{k}", f"⚠️ {tag}: levier {p.leverage:g}× (limita ta: {cfg.max_leverage:g}×)."))
        if p.liq and p.mark:
            dist = abs(p.mark - p.liq) / p.mark
            if dist < cfg.min_liq_distance_pct:
                alerts.append(Alert(f"liq:{k}", f"🚨 {tag}: lichidarea e la {dist:.1%} de prețul actual "
                                    f"({p.mark:,.4g} → {p.liq:,.4g}).", "danger"))
    exposure = sum(p.notional for p in positions)
    if exposure > cfg.max_exposure_x * eq:
        alerts.append(Alert("exposure", f"⚠️ Expunere totală {_usd(exposure)} = {exposure / eq:.1f}× contul "
                            f"(limita ta: {cfg.max_exposure_x:g}×)."))
    start_eq = equity - day_pnl
    if start_eq > 0 and day_pnl < -cfg.max_daily_loss_pct * start_eq:
        alerts.append(Alert(f"daily_loss:{datetime.now(timezone.utc):%Y-%m-%d}",
                            f"🛑 Azi: {_usd(day_pnl)} ({day_pnl / start_eq:.1%}). Ai atins limita zilnică de "
                            f"{cfg.max_daily_loss_pct:.0%}. Ia o pauză până mâine.", "danger"))
    return alerts


class Dedup:
    """Send each alert once, repeat while unresolved at most every repeat_minutes, announce when resolved."""

    def __init__(self, path: Path, repeat_minutes: int):
        self.path, self.repeat = path, timedelta(minutes=repeat_minutes)
        try:
            self.sent = {k: datetime.fromisoformat(v) for k, v in json.loads(path.read_text()).items()}
        except (FileNotFoundError, json.JSONDecodeError):
            self.sent = {}

    def filter(self, alerts: list[Alert], now: datetime) -> tuple[list[Alert], list[str]]:
        active = {a.key for a in alerts}
        due = [a for a in alerts if a.key not in self.sent or now - self.sent[a.key] >= self.repeat]
        for a in due:
            self.sent[a.key] = now
        resolved = [k for k in self.sent if k not in active]
        for k in resolved:
            del self.sent[k]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({k: v.isoformat() for k, v in self.sent.items()}))
        return due, [k for k in resolved if not k.startswith("daily_loss")]


RESOLVED = {"no_stop": "✅ {s}: are stop acum.", "liq": "✅ {s}: s-a depărtat de lichidare.",
            "risk": "✅ {s}: riscul la stop e în limită.", "leverage": "✅ {s}: levierul e în limită.",
            "partial_stop": "✅ {s}: stopul acoperă toată poziția.", "exposure": "✅ Expunerea e în limită."}


def resolved_text(key: str) -> str | None:
    kind, _, rest = key.partition(":")
    sym = rest.replace(":", " ").upper()
    tpl = RESOLVED.get(kind)
    return tpl.format(s=sym) if tpl else None


def day_pnl(income: list[dict], positions: list[FPosition]) -> float:
    realized = sum(float(r["income"]) for r in income if r.get("incomeType") in ("REALIZED_PNL", "COMMISSION", "FUNDING_FEE"))
    return realized + sum(p.unrealized for p in positions)


def tick(reader, notifier, cfg: GuardConfig, dedup: Dedup, now: datetime | None = None) -> list[Alert]:
    now = now or datetime.now(timezone.utc)
    positions, stops, equity = reader.positions(), reader.stops(), reader.equity()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    pnl = day_pnl(reader.income(int(midnight.timestamp() * 1000), int(now.timestamp() * 1000)), positions)
    alerts = check(positions, stops, equity, pnl, cfg)
    due, resolved = dedup.filter(alerts, now)
    for a in due:
        notifier.send(a.text)
    for k in resolved:
        t = resolved_text(k)
        if t:
            notifier.send(t)
    return alerts


def main() -> None:
    from apps.futures.exchange import BinanceFuturesReader
    from apps.trader.notify import Notifier
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--allow-trading-key", action="store_true", help="accept a key that can trade (not recommended)")
    a = ap.parse_args()
    cfg = GuardConfig.load()
    reader = BinanceFuturesReader(allow_trading_key=a.allow_trading_key)
    print("cheie:", reader.check_key())
    tg = Notifier()
    dedup = Dedup(ROOT / "data" / "guard_state.json", cfg.repeat_minutes)
    tg.send(f"🛡️ Gardian futures pornit. Limite: levier {cfg.max_leverage:g}×, risc/tranzacție "
            f"{cfg.max_risk_per_trade_pct:.0%}, pierdere zilnică {cfg.max_daily_loss_pct:.0%}. Doar citire.")
    while True:
        try:
            tick(reader, tg, cfg, dedup)
        except Exception as exc:  # noqa: BLE001 - a network error must not stop the guard
            print(f"[guard] check failed: {type(exc).__name__}")
        if a.once:
            return
        time.sleep(cfg.poll_seconds)


if __name__ == "__main__":
    main()
