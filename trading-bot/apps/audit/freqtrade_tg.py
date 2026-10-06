"""Parse a signal channel that a Freqtrade bot posts into (copied text or Telegram Desktop JSON export)
and compute the channel's REAL record: every signal, fill, cancel, partial and final exit, losers included.

Recognized messages (Freqtrade's Telegram templates + the channel's own signal format):
  🟢/🔴 #PAIR LONG|SHORT, ENTRY, SL, TP1..TP6, Stake COIN, Stake USDT      -> signal
  "New Trade filled (#id)", Pair, Direction, Open Rate, Total               -> fill
  "Partially exited PAIR (#id)", Sub Profit, Exit Reason, ...               -> partial
  "Exited PAIR (#id)", Profit | Final Profit (... USDT), Exit Reason        -> exit
  "CANCELING TRADE: id", #PAIR SIDE, Cancel REASON                          -> cancel
Message text is data only. Nothing here talks to an exchange.

  python -m apps.audit.freqtrade_tg chat.txt         # or result.json from Telegram Desktop export
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

HEADER = re.compile(r"^\s*(?P<who>[^\n\[]+?), \[(?P<when>[A-Z][a-z]{2} \d{1,2}, \d{4} at \d{1,2}:\d{2})\]\s*$", re.M)
NUM = r"(-?[\d.]+)"


@dataclass
class Signal:
    t: datetime
    pair: str
    side: str
    entry: float
    sl: float
    tps: list[float]
    stake_usdt: float | None


@dataclass
class Trade:
    pair: str
    side: str
    filled: datetime
    open_rate: float
    leverage: float
    margin: float
    partials: list[tuple[datetime, str, float]] = field(default_factory=list)   # (time, reason, usdt)
    closed: datetime | None = None
    pnl: float | None = None
    exit_reason: str = ""
    exit_rate: float | None = None

    @property
    def notional(self) -> float:
        return self.margin * self.leverage


def _f(pat: str, text: str, cast=float, default=None):
    m = re.search(pat, text)
    return cast(m.group(1)) if m else default


def split_messages(raw: str) -> list[tuple[datetime, str]]:
    """Copied Telegram text: 'Name, [Sep 22, 2026 at 07:00]' headers. JSON export: {'messages': [...]}."""
    if raw.lstrip().startswith("{"):
        data = json.loads(raw)
        out = []
        for m in data.get("messages", []):
            txt = m.get("text", "")
            if isinstance(txt, list):
                txt = "".join(p if isinstance(p, str) else p.get("text", "") for p in txt)
            if txt:
                out.append((datetime.fromisoformat(m["date"]), txt))
        return out
    heads = list(HEADER.finditer(raw))
    out = []
    for i, h in enumerate(heads):
        body = raw[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(raw)]
        out.append((datetime.strptime(h.group("when"), "%b %d, %Y at %H:%M"), body.strip()))
    return out


@dataclass
class Channel:
    signals: list[Signal] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    cancels: list[tuple[datetime, str, str]] = field(default_factory=list)     # (time, pair, reason)
    unparsed: int = 0


def parse(raw: str) -> Channel:
    ch = Channel()
    open_by_pair: dict[str, Trade] = {}
    for t, body in split_messages(raw):
        sig = re.search(r"#([A-Z0-9]+/[A-Z]+)\s+(LONG|SHORT)", body)
        if "CANCELING TRADE" in body and sig:
            ch.cancels.append((t, sig.group(1), _f(r"Cancel REASON:\s*(.+)", body, str, "").strip()))
        elif sig and "ENTRY:" in body:
            tps = [float(x) for x in re.findall(r"TP\d+:\s*" + NUM, body)]
            ch.signals.append(Signal(t, sig.group(1), sig.group(2).lower(), _f(r"ENTRY:\s*" + NUM, body),
                                     _f(r"SL:\s*" + NUM, body), tps, _f(r"Stake USDT:\s*" + NUM, body)))
        elif "New Trade filled" in body:
            pair = _f(r"Pair:\s*(\S+)", body, str, "").split(":")[0]
            lev = _f(r"Direction:\s*\w+\s*\((\d+(?:\.\d+)?)x\)", body, float, 1.0)
            tr = Trade(pair, "short" if "Direction: Short" in body else "long", t, _f(r"Open Rate:\s*" + NUM, body),
                       lev, _f(r"Total:\s*" + NUM, body))
            ch.trades.append(tr)
            open_by_pair[pair] = tr
        elif "artially exited" in body or re.search(r"\bExited\b", body):
            pair = _f(r"exited\s+(\S+)", body.replace("Exited", "exited"), str, "").split(":")[0]
            tr = open_by_pair.get(pair)
            if tr is None:
                ch.unparsed += 1
                continue
            reason = _f(r"Exit Reason:\s*(\S+)", body, str, "")
            if "artially exited" in body:
                tr.partials.append((t, reason, _f(r"Sub Profit:.*?\((?:profit|loss):\s*" + NUM, body)))
            else:
                final = _f(r"Final Profit:.*?\(" + NUM + r"\s*USDT", body)
                tr.pnl = final if final is not None else _f(r"Profit:.*?\((?:profit|loss):\s*" + NUM, body)
                tr.closed, tr.exit_reason, tr.exit_rate = t, reason, _f(r"Exit Rate:\s*" + NUM, body)
                open_by_pair.pop(pair, None)
        else:
            ch.unparsed += 1
    return ch


def stats(ch: Channel) -> dict:
    closed = [t for t in ch.trades if t.pnl is not None]
    pnl = [t.pnl for t in closed]
    wins, losses = [p for p in pnl if p > 0], [p for p in pnl if p <= 0]
    eq, peak, dd, streak, worst_streak = 0.0, 0.0, 0.0, 0, 0
    for t in sorted(closed, key=lambda x: x.closed):
        eq += t.pnl
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
        streak = streak + 1 if t.pnl <= 0 else 0
        worst_streak = max(worst_streak, streak)
    # risk per trade at the signal's stop: notional x stop distance (what one full loss should cost)
    risk = []
    for s in ch.signals:
        if s.stake_usdt and s.entry and s.sl:
            risk.append(s.stake_usdt * abs(s.entry - s.sl) / s.entry)
    by_side = {side: [t.pnl for t in closed if t.side == side] for side in ("long", "short")}
    return {
        "signals": len(ch.signals), "filled": len(ch.trades), "cancelled": len(ch.cancels),
        "fill_rate": len(ch.trades) / len(ch.signals) if ch.signals else 0.0,
        "closed": len(closed), "open": len(ch.trades) - len(closed),
        "wins": len(wins), "losses": len(losses), "win_rate": len(wins) / len(closed) if closed else 0.0,
        "net": sum(pnl), "avg_win": sum(wins) / len(wins) if wins else 0.0,
        "avg_loss": sum(losses) / len(losses) if losses else 0.0,
        "pf": sum(wins) / -sum(losses) if losses and sum(losses) < 0 else float("inf"),
        "max_dd": dd, "worst_streak": worst_streak,
        "risk_per_signal": sum(risk) / len(risk) if risk else 0.0,
        "by_side": {k: (len(v), sum(v)) for k, v in by_side.items()},
        "full_losses": sum(1 for t in closed if t.pnl <= 0 and not t.partials),
        "lev_mixed": sorted({t.leverage for t in ch.trades}),
        "days": ((max(s.t for s in ch.signals) - min(s.t for s in ch.signals)).total_seconds() / 86400) if ch.signals else 0,
    }


def markdown(ch: Channel) -> str:
    s = stats(ch)
    L = ["# Canal de semnale · rezultatul real (din mesajele botului)", "",
         f"Perioadă: {s['days']:.0f} zile · semnale {s['signals']} · umplute {s['filled']} ({s['fill_rate']:.0%}) · "
         f"anulate (intrare neatinsă) {s['cancelled']}", "",
         "| | |", "|---|---|",
         f"| Tranzacții închise | {s['closed']} (+{s['open']} încă deschise) |",
         f"| Câștigate / pierdute | {s['wins']} / {s['losses']} ({s['win_rate']:.0%}) |",
         f"| Net | {s['net']:+,.2f} USDT |",
         f"| Câștig mediu / pierdere medie | {s['avg_win']:+,.2f} / {s['avg_loss']:+,.2f} USDT |",
         f"| Profit factor | {s['pf']:.2f} |",
         f"| Cea mai mare scădere | {s['max_dd']:,.2f} USDT |",
         f"| Cea mai lungă serie de pierderi | {s['worst_streak']} |",
         f"| Pierderi complete (fără niciun TP) | {s['full_losses']} |",
         f"| Risc la stop pe semnal (poziție × distanța SL) | ~{s['risk_per_signal']:,.0f} USDT |",
         f"| Long: tranzacții / net | {s['by_side']['long'][0]} / {s['by_side']['long'][1]:+,.2f} |",
         f"| Short: tranzacții / net | {s['by_side']['short'][0]} / {s['by_side']['short'][1]:+,.2f} |",
         f"| Levier folosit | {', '.join(f'{x:g}x' for x in s['lev_mixed'])} |", "",
         "| Închisă | Pereche | Direcție | Rezultat USDT | Ieșire | TP-uri atinse |", "|---|---|---|---|---|---|"]
    for t in sorted((t for t in ch.trades if t.pnl is not None), key=lambda x: x.closed):
        L.append(f"| {t.closed:%Y-%m-%d %H:%M} | {t.pair} | {t.side} {t.leverage:g}x | {t.pnl:+,.2f} | {t.exit_reason} | "
                 f"{', '.join(r for _, r, _ in t.partials) or '—'} |")
    L += ["", "Notă: botul rulează pe **dry-run** (fără bani reali): umpleri la preț ideal, fără alunecare. "
          "ID-urile #… se refolosesc după anulări, deci nu numără tranzacții reale."]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    a = ap.parse_args()
    print(markdown(parse(Path(a.path).read_text(encoding="utf-8"))))


if __name__ == "__main__":
    main()
