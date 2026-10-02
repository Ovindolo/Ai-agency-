"""Insider alert bot on Telegram. Research and alerts only: it never places a trade.

Alerts: a company reaches N+ distinct open-market insider buyers within W days (default 3 in 30).
Commands from the operator's phone (only TELEGRAM_ADMIN_ID is answered; anything else is ignored):
  /clusters [days]   ranked clusters
  /ticker XYZ        insider buys for one ticker (+ Congress/lobbying/contracts if QUIVER_API_KEY is set)
  /rising            early signals
  /help
Messages and filing text are treated as data: no command is built from them, nothing is executed.

  python -m apps.insiders.bot              # loop: refresh EDGAR every 30 min, answer commands
  python -m apps.insiders.bot --report     # one-off markdown report -> reports/INSIDERS.md
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from apps.insiders.screen import buys, clusters, early_signals, report

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "data" / "insider_alerts.json"


def cluster_alerts(txns, end: date, sent: dict, min_buyers: int = 3, days: int = 30) -> list[str]:
    msgs = []
    for c in clusters(txns, end, days, min_buyers):
        key, n = c.ticker, len(c.buyers)
        if sent.get(key, 0) >= n:
            continue
        sent[key] = n
        who = ", ".join(f"{b.owner} ({b.title}) {b.value:,.0f}$" for b in c.buyers[:5])
        batch = "\n⚠️ Arată a batch: " + "; ".join(c.batch_reasons) if c.batch else ""
        out = ("\n⭐ " + "; ".join(c.outliers[:2])) if c.outliers else ""
        last = max(c.buyers, key=lambda b: b.filed)
        msgs.append(f"🔔 {c.ticker} · {n} insideri au cumpărat în {days} zile · {c.total:,.0f}$\n{who}{batch}{out}\n"
                    f"Ultima declarație: {last.filed} (tranzacție {last.first_trade}) · {last.url}")
    return msgs


def answer(text: str, txns, end: date) -> str:
    parts = text.strip().split()
    if not parts:
        return ""
    cmd, args = parts[0].lower().split("@")[0], parts[1:]
    if cmd == "/clusters":
        days = int(args[0]) if args and args[0].isdigit() else 60
        cl = clusters(txns, end, days)
        if not cl:
            return f"Niciun cluster de 3+ cumpărători în {days} zile."
        return "\n".join(f"{i}. {c.ticker}: {len(c.buyers)} cumpărători, {c.total:,.0f}$" + (" (batch?)" if c.batch else "")
                         for i, c in enumerate(cl[:15], 1))
    if cmd == "/ticker" and args:
        tk = "".join(ch for ch in args[0].upper() if ch.isalnum() or ch in ".-")[:10]
        rows = [t for t in buys(txns, end, 90) if t.ticker == tk]
        lines = [f"{t.trade_date} (declarat {t.filed}) {t.owner}, {t.title}: {t.value:,.0f}$" for t in rows[:15]]
        msg = f"{tk}: {len(rows)} cumpărări de insideri în 90 zile\n" + "\n".join(lines)
        if os.getenv("QUIVER_API_KEY"):
            from apps.insiders import quiver
            data = quiver.fetch(quiver.client(), tk)
            for label in ("Congressional trades", "Lobbying", "Federal contracts"):
                d = data[label]
                msg += f"\n{label}: " + (d if isinstance(d, str) else f"{len(d)} rânduri")
        return msg
    if cmd == "/rising":
        tr = [t for t in early_signals(txns, end) if t.state == "rising"][:15]
        return "\n".join(f"{t.ticker}: {t.recent} în ultimele 30z vs {t.prior} înainte" for t in tr) or "Nimic în creștere."
    return "Comenzi: /clusters [zile] · /ticker XYZ · /rising"


class Telegram:
    def __init__(self, token: str | None = None, admin: str | None = None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.admin = str(admin or os.getenv("TELEGRAM_ADMIN_ID", ""))
        self.offset = 0

    def _call(self, method: str, **params):
        url = f"https://api.telegram.org/bot{self.token}/{method}?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=40) as r:
            return json.loads(r.read())

    def send(self, text: str) -> None:
        if self.token and self.admin:
            self._call("sendMessage", chat_id=self.admin, text=text[:4000], disable_web_page_preview="true")
        else:
            print(text)

    def commands(self) -> list[str]:
        """New messages from the admin only; everyone else is ignored."""
        if not self.token:
            return []
        upd = self._call("getUpdates", offset=self.offset, timeout=25).get("result", [])
        out = []
        for u in upd:
            self.offset = u["update_id"] + 1
            m = u.get("message") or {}
            if str((m.get("from") or {}).get("id")) == self.admin and m.get("text", "").startswith("/"):
                out.append(m["text"])
        return out


def main() -> None:
    from apps.insiders.edgar import Edgar
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--refresh-minutes", type=int, default=30)
    a = ap.parse_args()
    edgar = Edgar()
    txns = edgar.load(max(a.days, 90))
    if a.report:
        md = report(clusters(txns, date.today(), a.days), early_signals(txns, date.today()), date.today(), a.days)
        out = ROOT / "reports" / "INSIDERS.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(md)
        return
    tg = Telegram()
    sent = json.loads(STATE.read_text()) if STATE.exists() else {}
    tg.send("🟢 Bot insideri pornit. Doar alerte și cercetare, niciodată tranzacții. /help")
    last = 0.0
    while True:
        if time.time() - last > a.refresh_minutes * 60:
            fresh = [t for t in txns if (date.today() - t.trade_date).days <= 120] + edgar.load(2)
            txns = list({(t.accession, t.owner_cik, t.trade_date, t.code, t.shares, t.price): t for t in fresh}.values())
            for m in cluster_alerts(txns, date.today(), sent):
                tg.send(m)
            STATE.parent.mkdir(exist_ok=True)
            STATE.write_text(json.dumps(sent))
            last = time.time()
        for c in tg.commands():
            tg.send(answer(c, txns, date.today()))


if __name__ == "__main__":
    main()
